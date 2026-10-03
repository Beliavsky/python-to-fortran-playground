"""Deploy the public execution API: python -m modal deploy xmodal.py.

User code runs only in fresh, network-blocked gVisor sandboxes. The API
container owns the Modal client and persistent limits; neither is in a job.
"""
import json
from pathlib import Path

import modal

ROOT = Path(__file__).resolve().parent
app = modal.App('p2f-playground-execution')
state = modal.Dict.from_name('p2f-playground-execution-state', create_if_missing=True)

job_image = (
    modal.Image.debian_slim(python_version='3.12')
    .apt_install('gfortran')
    .pip_install('numpy==2.2.6', 'scipy==1.15.3', 'pandas==2.2.3')
    .add_local_file(ROOT / 'xrun.py', '/opt/p2f/xrun.py', copy=True)
    .add_local_file(ROOT / 'xsandbox_worker.py', '/opt/p2f/xsandbox_worker.py', copy=True)
    .add_local_file(ROOT / 'upstream.json', '/opt/p2f/upstream.json', copy=True)
    .add_local_file(ROOT / 'site/vendor/manifest.json', '/opt/p2f/site/vendor/manifest.json', copy=True)
    .add_local_file(ROOT / 'site/vendor/upstream.zip', '/opt/p2f/site/vendor/upstream.zip', copy=True)
    .run_commands(
        'mkdir -p /opt/p2f/runtime /work',
        "PYTHONPATH=/opt/p2f python -c \"from pathlib import Path; from xrun import unpack_runtime; unpack_runtime(Path('/opt/p2f/runtime'))\"",
        'chmod 1777 /work',
    )
    .env({'OPENBLAS_NUM_THREADS': '1', 'OMP_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1'})
    .dockerfile_commands('USER 65534:65534')
)

api_image = (
    modal.Image.debian_slim(python_version='3.12')
    .pip_install('fastapi==0.142.2')
    .add_local_file(ROOT / 'xpublic_api.py', '/root/xpublic_api.py', copy=True)
    .add_local_file(ROOT / 'site/vendor/manifest.json', '/opt/p2f/manifest.json', copy=True)
)


class Store:
    async def get(self, key, default):
        return await state.get.aio(key, default)

    async def put(self, key, value):
        await state.put.aio(key, value)

    async def pop(self, key):
        await state.pop.aio(key, None)


class Sandboxes:
    async def start(self, payload):
        sandbox = await modal.Sandbox.create.aio(
            'python', '/opt/p2f/xsandbox_worker.py',
            app=app, image=job_image, runtime='gvisor',
            workdir='/work', block_network=True,
            cpu=(0.5, 1.0), memory=(512, 1024), timeout=250,
            secrets=[], volumes={}, include_oidc_identity_token=False,
        )
        try:
            sandbox.stdin.write((json.dumps(payload) + '\n').encode())
            sandbox.stdin.write_eof()
            await sandbox.stdin.drain.aio()
        except BaseException:
            await sandbox.terminate.aio()
            raise
        return sandbox.object_id

    async def poll(self, identifier):
        from xpublic_api import MAX_RESULT
        sandbox = await modal.Sandbox.from_id.aio(identifier)
        if await sandbox.poll.aio() is None:
            return None
        try:
            chunks, size = [], 0
            async for chunk in sandbox.stdout:
                size += len(chunk.encode() if isinstance(chunk, str) else chunk)
                if size > MAX_RESULT:
                    return {'ok': False, 'error': 'Execution result exceeded the output limit.'}
                chunks.append(chunk.decode(errors='replace') if isinstance(chunk, bytes) else chunk)
            try:
                result = json.loads(''.join(chunks))
                if not isinstance(result, dict) or not isinstance(result.get('ok'), bool):
                    raise ValueError()
                return result
            except (ValueError, UnicodeError):
                return {'ok': False, 'error': 'Execution stopped or reached a resource/time limit.'}
        finally:
            await sandbox.terminate.aio()

    async def cancel(self, identifier):
        sandbox = await modal.Sandbox.from_id.aio(identifier)
        await sandbox.terminate.aio()


# One API container serializes durable limits; jobs are separate sandboxes.
@app.function(image=api_image, cpu=(0.125, 0.5), memory=(256, 512), max_containers=1, timeout=150)
@modal.concurrent(max_inputs=16)
@modal.asgi_app()
def api():
    from xpublic_api import PublicService, create_api
    manifest = json.loads(Path('/opt/p2f/manifest.json').read_text())
    return create_api(PublicService(Store(), Sandboxes(), manifest['commit']))
