"""Public execution API; build and deploy using python xdeploy_service.py.

User code runs only in fresh, network-blocked gVisor sandboxes. The API
container owns the Modal client and persistent limits; neither is in a job.
"""
import json
import hashlib
import os
from pathlib import Path

import modal

ROOT = Path(__file__).resolve().parent
app = modal.App('p2f-playground-execution')
state = modal.Dict.from_name('p2f-playground-execution-state', create_if_missing=True)


def runtime_image_name():
    if not modal.is_local():
        return os.environ['P2F_RUNTIME_IMAGE_NAME']
    digest = hashlib.sha256()
    # Changing an execution dependency selects a new immutable named image.
    for filename in ('xmodal.py', 'xrun.py', 'compiler_options.py', 'translation_options.py',
                     'site/annotations.py', 'site/translation_settings.py', 'xcompile_fortran.py', 'xformat_fortran.py', 'xbuild_helpers.py', 'xsandbox_worker.py', 'xinstall_intel.sh',
                     'xverify_intel.py', 'xprecompile.py', 'xinstall_flang.sh',
                     'xverify_flang.py', 'xinstall_ofort.sh', 'xverify_ofort.py', 'upstream.json',
                     'site/vendor/manifest.json', 'site/vendor/upstream.zip'):
        digest.update((ROOT / filename).read_bytes())
    return 'p2f-runtime-' + digest.hexdigest()[:20]


RUNTIME_IMAGE_NAME = runtime_image_name()
INTEL_IMAGE_NAME = RUNTIME_IMAGE_NAME + '-ifx'
INTEL_ENABLED = os.environ.get('P2F_INTEL_ENABLED') == '1'
FLANG_IMAGE_NAME = RUNTIME_IMAGE_NAME + '-flang'
FLANG_ENABLED = os.environ.get('P2F_FLANG_ENABLED') == '1'
LFORTRAN_IMAGE_NAME = RUNTIME_IMAGE_NAME + '-lfortran'
LFORTRAN_ENABLED = os.environ.get('P2F_LFORTRAN_ENABLED') == '1'
OFORT_IMAGE_NAME = RUNTIME_IMAGE_NAME + '-ofort'
OFORT_ENABLED = os.environ.get('P2F_OFORT_ENABLED') == '1'
TOOLS_IMAGE_NAME = RUNTIME_IMAGE_NAME + '-tools'

# Nothing from the application, formatter, linter, or upstream bundle belongs
# ahead of a compiler installation. Modal can reuse these stable parent layers.
gnu_toolchain_image = (
    modal.Image.debian_slim(python_version='3.12')
    .apt_install('gfortran')
)

# Separate optional image: GNU jobs do not pull Intel's toolchain.
intel_installed_image = (
    gnu_toolchain_image
    .apt_install('curl', 'gnupg', 'build-essential', 'ca-certificates')
    .pip_install('certifi==2026.2.25')
    .add_local_file(ROOT / 'xinstall_intel.sh', '/opt/p2f/xinstall_intel.sh', copy=True)
    .run_commands('bash /opt/p2f/xinstall_intel.sh')
)

# Independent optional image; no Intel installation or cross-compiler modules.
flang_installed_image = (
    gnu_toolchain_image
    .apt_install('curl', 'gnupg', 'build-essential', 'ca-certificates')
    .pip_install('certifi==2026.2.25')
    .add_local_file(ROOT / 'xinstall_flang.sh', '/opt/p2f/xinstall_flang.sh', copy=True)
    .run_commands('bash /opt/p2f/xinstall_flang.sh')
)

# Conda is LFortran's recommended binary installation. Keep its libraries
# independent of GNU/Intel/Flang and use exactly the compiler tested by the probe.
lfortran_installed_image = (
    modal.Image.micromamba(python_version='3.12')
    .micromamba_install('lfortran=0.66.0=hd7e4fe6_4', channels=['conda-forge'])
)


def helper_image(base, name, command):
    image = base.pip_install('numpy==2.2.6', 'scipy==1.15.3', 'pandas==2.2.3')
    for filename in ('xbuild_helpers.py', 'upstream.json', 'site/vendor/manifest.json', 'site/vendor/upstream.zip'):
        image = image.add_local_file(ROOT / filename, '/opt/p2f/' + filename, copy=True)
    return image.run_commands(
        f'python /opt/p2f/xbuild_helpers.py {name} --command "{command}"')


def application_image(base, source_tools=False):
    image = base
    for filename in ('xrun.py', 'compiler_options.py', 'translation_options.py',
                     'site/translation_settings.py', 'site/annotations.py', 'xcompile_fortran.py',
                     'xprecompile.py', 'xsandbox_worker.py', 'xverify_intel.py', 'xverify_flang.py'):
        image = image.add_local_file(ROOT / filename, '/opt/p2f/' + filename, copy=True)
    if source_tools:
        image = image.add_local_file(ROOT / 'xformat_fortran.py', '/opt/p2f/xformat_fortran.py', copy=True)
    return image.run_commands('mkdir -p /work', 'chmod 1777 /work').env(
        {'OPENBLAS_NUM_THREADS': '1', 'OMP_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1'})


# Reverify application changes against cached helpers; do not rebuild artifacts.
job_image = application_image(helper_image(gnu_toolchain_image, 'gfortran',
    'gfortran -ffree-line-length-none')).run_commands(
    'PYTHONPATH=/opt/p2f python /opt/p2f/xprecompile.py gfortran --verify-only')
intel_job_image = application_image(helper_image(intel_installed_image, 'ifx', 'p2f-ifx')).run_commands(
    'PYTHONPATH=/opt/p2f python /opt/p2f/xprecompile.py ifx --verify-only',
    'PYTHONPATH=/opt/p2f python /opt/p2f/xverify_intel.py')
flang_job_image = application_image(helper_image(flang_installed_image, 'flang', 'flang-21')).run_commands(
    'PYTHONPATH=/opt/p2f python /opt/p2f/xprecompile.py flang --verify-only',
    'PYTHONPATH=/opt/p2f python /opt/p2f/xverify_flang.py')
lfortran_job_image = application_image(helper_image(lfortran_installed_image, 'lfortran',
    'lfortran --no-style-suggestions --no-color --implicit-interface --separate-compilation --legacy-array-sections --realloc-lhs-arrays')).run_commands(
    'PYTHONPATH=/opt/p2f python /opt/p2f/xprecompile.py lfortran --verify-only',
    'PYTHONPATH=/opt/p2f python /opt/p2f/xverify_flang.py --compiler lfortran')

# Formatting and linting have no compiler or helper dependency.
tools_job_image = application_image(modal.Image.debian_slim(python_version='3.12')
    .pip_install('fprettify==0.3.7', 'fortitude-lint==0.9.2'), source_tools=True)

# Independent interpreter installation: no Fortran toolchain or helper objects.
ofort_installed_image = (modal.Image.debian_slim(python_version='3.12')
    .apt_install('gcc', 'git', 'ca-certificates')
    .add_local_file(ROOT / 'xinstall_ofort.sh', '/opt/p2f/xinstall_ofort.sh', copy=True)
    .run_commands('bash /opt/p2f/xinstall_ofort.sh'))
ofort_job_image = (application_image(ofort_installed_image)
    .add_local_file(ROOT / 'xverify_ofort.py', '/opt/p2f/xverify_ofort.py', copy=True)
    .run_commands('python /opt/p2f/xverify_ofort.py'))

api_image = (
    modal.Image.debian_slim(python_version='3.12')
    .pip_install('fastapi==0.142.2')
    .env({'P2F_RUNTIME_IMAGE_NAME': RUNTIME_IMAGE_NAME,
          'P2F_INTEL_ENABLED': '1' if INTEL_ENABLED else '0',
          'P2F_FLANG_ENABLED': '1' if FLANG_ENABLED else '0',
          'P2F_LFORTRAN_ENABLED': '1' if LFORTRAN_ENABLED else '0',
          'P2F_OFORT_ENABLED': '1' if OFORT_ENABLED else '0',
          'P2F_COMPILER_VERSIONS': os.environ.get('P2F_COMPILER_VERSIONS', '{}'),
          'P2F_COMPILER_STANDARDS': os.environ.get('P2F_COMPILER_STANDARDS', '{}')})
    .add_local_file(ROOT / 'xpublic_api.py', '/root/xpublic_api.py', copy=True)
    .add_local_file(ROOT / 'compiler_options.py', '/root/compiler_options.py', copy=True)
    .add_local_file(ROOT / 'translation_options.py', '/root/translation_options.py', copy=True)
    .add_local_file(ROOT / 'site/translation_settings.py', '/root/site/translation_settings.py', copy=True)
    .add_local_file(ROOT / 'site/vendor/manifest.json', '/opt/p2f/manifest.json', copy=True)
)


class Store:
    async def get(self, key, default):
        return await state.get.aio(key, default)

    async def put(self, key, value):
        await state.put.aio(key, value)

    async def pop(self, key):
        await state.pop.aio(key, None)


def job_image_name(payload):
    if payload.get('mode') in {'format', 'check'}:
        return TOOLS_IMAGE_NAME
    if payload.get('mode') in {'fortran', 'both', 'compare', 'fortran-edit', 'both-edit', 'compare-edit', 'fortran-compile', 'fortran-run'}:
        return {'ifx': INTEL_IMAGE_NAME, 'flang': FLANG_IMAGE_NAME,
                'lfortran': LFORTRAN_IMAGE_NAME, 'ofort': OFORT_IMAGE_NAME}.get(payload.get('compiler'), RUNTIME_IMAGE_NAME)
    return RUNTIME_IMAGE_NAME


class Sandboxes:
    async def start(self, payload):
        image_name = job_image_name(payload)
        sandbox = await modal.Sandbox.create.aio(
            'python', '/opt/p2f/xsandbox_worker.py',
            # Runtime containers cannot upload files from the developer's
            # checkout. Resolve the image built and published before deploy.
            app=app, image=modal.Image.from_name(image_name), runtime='gvisor',
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
    return create_api(PublicService(Store(), Sandboxes(), manifest['commit'], runtime_namespace=RUNTIME_IMAGE_NAME,
                                   compiler_versions=json.loads(os.environ.get('P2F_COMPILER_VERSIONS', '{}')),
                                   compiler_standards=json.loads(os.environ.get('P2F_COMPILER_STANDARDS', '{}')),
                                   compilers=('gfortran',) + (('ifx',) if INTEL_ENABLED else ())
                                   + (('flang',) if FLANG_ENABLED else ())
                                   + (('lfortran',) if LFORTRAN_ENABLED else ())
                                   + (('ofort',) if OFORT_ENABLED else ())))
