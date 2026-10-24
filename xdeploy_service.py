"""Build the pinned sandbox image locally, publish it, and deploy the Modal API."""
import argparse
import json
import os
import subprocess
import sys

import modal


def read_image_metadata(build_app, image_name, compiler):
    """Read build metadata once at deployment, not on sessions or user jobs."""
    from xrun import version_banner
    script = ("import json; from pathlib import Path; "
              f"data=json.loads(Path('/opt/p2f/runtime/precompiled/{compiler}/manifest.json').read_text()); "
              "print(json.dumps({'version':data['identity']['version'],'standards':data.get('standards',{})}))")
    if compiler == 'ofort':
        script = ("import json, subprocess; "
                  "version=subprocess.check_output(['ofort','--version'],text=True); "
                  "print(json.dumps({'version':version,'standards':{}}))")
    sandbox = modal.Sandbox.create('python', '-c', script, app=build_app,
        image=modal.Image.from_name(image_name), timeout=30, cpu=0.125, memory=256,
        block_network=True, secrets=[], volumes={}, include_oidc_identity_token=False)
    try:
        sandbox.wait()
        if sandbox.returncode != 0:
            raise RuntimeError('Compiler-version metadata reader failed')
        metadata = json.loads(sandbox.stdout.read())
        if not isinstance(metadata, dict) or not isinstance(metadata.get('version'), str) or not isinstance(metadata.get('standards'), dict):
            raise ValueError('Invalid compiler-version metadata')
        return {**metadata, 'version': version_banner(metadata['version'])}
    finally:
        sandbox.terminate()


def read_coarray_support(build_app, image_name, compiler):
    """Use the real job runtime/isolation/resource settings, never a build-container guess."""
    from compiler_options import OPTIONS, coarray_sandbox_runtime
    sandbox = modal.Sandbox.create('python', '/opt/p2f/xverify_coarrays.py', '--compiler', compiler,
        app=build_app, image=modal.Image.from_name(image_name), runtime=coarray_sandbox_runtime(compiler, 4),
        workdir='/work', timeout=60, cpu=(0.5, 1.0), memory=(512, 1024),
        block_network=True, secrets=[], volumes={}, include_oidc_identity_token=False)
    try:
        sandbox.wait()
        diagnostics = sandbox.stderr.read()
        if isinstance(diagnostics, str) and diagnostics.strip():
            print(diagnostics, flush=True)
        if sandbox.returncode != 0:
            raise RuntimeError('Coarray sandbox probe failed')
        result = json.loads(sandbox.stdout.read())
        if not isinstance(result, dict):
            raise ValueError('Invalid coarray capability response')
        return {count: flags for count, flags in OPTIONS[compiler].get('coarray_images', {}).items()
                if result.get(count) == flags}
    finally:
        sandbox.terminate()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--without-intel', action='store_true', help='Skip the optional Intel image')
    parser.add_argument('--without-flang', action='store_true', help='Skip the optional LLVM Flang image')
    parser.add_argument('--without-lfortran', action='store_true', help='Skip the optional LFortran image')
    parser.add_argument('--without-ofort', action='store_true', help='Skip the optional ofort interpreter image')
    parser.add_argument('--without-gnu17', action='store_true', help='Skip the optional GNU 17 snapshot image')
    parser.add_argument('--owner-secret', help='Modal secret name containing P2F_OWNER_KEY (API only)')
    args = parser.parse_args()
    if args.owner_secret:
        os.environ['P2F_OWNER_SECRET_NAME'] = args.owner_secret
    from xmodal import (ROOT, RUNTIME_IMAGE_NAME, INTEL_IMAGE_NAME, FLANG_IMAGE_NAME,
                        LFORTRAN_IMAGE_NAME, job_image, intel_job_image, flang_job_image,
                        lfortran_job_image, TOOLS_IMAGE_NAME, tools_job_image, OFORT_IMAGE_NAME, ofort_job_image,
                        GNU17_IMAGE_NAME, gnu17_job_image)
    build_app = modal.App.lookup('p2f-playground-execution', create_if_missing=True)
    intel_enabled = False
    flang_enabled = False
    lfortran_enabled = False
    ofort_enabled = False
    gnu17_enabled = False
    with modal.enable_output():
        tools_job_image.build(build_app).publish(TOOLS_IMAGE_NAME)
        job_image.build(build_app).publish(RUNTIME_IMAGE_NAME)
        if not args.without_gnu17:
            try:
                gnu17_job_image.build(build_app).publish(GNU17_IMAGE_NAME)
                gnu17_enabled = True
            except Exception as error:
                print(f'WARNING: GNU 17 snapshot could not be built/verified: {error}', flush=True)
                print('GNU 17 will be unavailable; stable GNU remains the default.', flush=True)
        if not args.without_intel:
            try:
                intel_job_image.build(build_app).publish(INTEL_IMAGE_NAME)
                intel_enabled = True
            except Exception as error:
                print(f'WARNING: Intel image could not be built/verified: {error}', flush=True)
                print('Intel will be marked unavailable; other compilers are unchanged.', flush=True)
        if not args.without_flang:
            try:
                flang_job_image.build(build_app).publish(FLANG_IMAGE_NAME)
                flang_enabled = True
            except Exception as error:
                print(f'WARNING: Flang image could not be built/verified: {error}', flush=True)
                print('Flang will be marked unavailable; other compilers are unchanged.', flush=True)
        if not args.without_lfortran:
            try:
                lfortran_job_image.build(build_app).publish(LFORTRAN_IMAGE_NAME)
                lfortran_enabled = True
            except Exception as error:
                print(f'WARNING: LFortran image could not be built/verified: {error}', flush=True)
                print('LFortran will be marked unavailable; other compilers are unchanged.', flush=True)
        if not args.without_ofort:
            try:
                ofort_job_image.build(build_app).publish(OFORT_IMAGE_NAME)
                ofort_enabled = True
            except Exception as error:
                print(f'WARNING: ofort image could not be built/verified: {error}', flush=True)
                print('ofort will be marked unavailable; compilers are unchanged.', flush=True)
    versions, standards, coarrays = {}, {}, {}
    for compiler, image_name, enabled in [('gfortran', RUNTIME_IMAGE_NAME, True),
            ('gfortran17', GNU17_IMAGE_NAME, gnu17_enabled),
            ('ifx', INTEL_IMAGE_NAME, intel_enabled), ('flang', FLANG_IMAGE_NAME, flang_enabled),
            ('lfortran', LFORTRAN_IMAGE_NAME, lfortran_enabled), ('ofort', OFORT_IMAGE_NAME, ofort_enabled)]:
        if enabled:
            if compiler in ('gfortran', 'gfortran17', 'ifx', 'flang', 'lfortran'):
                try:
                    coarrays[compiler] = read_coarray_support(build_app, image_name, compiler)
                    print(f'{compiler} verified coarray image counts: {", ".join(coarrays[compiler]) or "none"}', flush=True)
                except Exception as error:
                    print(f'WARNING: {compiler} coarrays unavailable: {error}', flush=True)
            try:
                metadata = read_image_metadata(build_app, image_name, compiler)
                versions[compiler] = metadata['version']
                standards[compiler] = metadata['standards']
            except Exception as error:
                print(f'WARNING: {compiler} version unavailable: {error}', flush=True)
    env = {**os.environ, 'P2F_COMPILER_VERSIONS': json.dumps(versions),
           'P2F_COMPILER_STANDARDS': json.dumps(standards),
           'P2F_INTEL_ENABLED': '1' if intel_enabled else '0',
           'P2F_FLANG_ENABLED': '1' if flang_enabled else '0',
           'P2F_LFORTRAN_ENABLED': '1' if lfortran_enabled else '0'}
    env['P2F_OFORT_ENABLED'] = '1' if ofort_enabled else '0'
    env['P2F_GNU17_ENABLED'] = '1' if gnu17_enabled else '0'
    env['P2F_COMPILER_COARRAYS'] = json.dumps(coarrays)
    subprocess.run([sys.executable, '-X', 'utf8', '-m', 'modal', 'deploy',
                    str(ROOT / 'xmodal.py')], cwd=ROOT, env=env, check=True)


if __name__ == '__main__':
    main()
