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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--without-intel', action='store_true', help='Skip the optional Intel image')
    parser.add_argument('--without-flang', action='store_true', help='Skip the optional LLVM Flang image')
    parser.add_argument('--without-lfortran', action='store_true', help='Skip the optional LFortran image')
    args = parser.parse_args()
    from xmodal import (ROOT, RUNTIME_IMAGE_NAME, INTEL_IMAGE_NAME, FLANG_IMAGE_NAME,
                        LFORTRAN_IMAGE_NAME, job_image, intel_job_image, flang_job_image,
                        lfortran_job_image)
    build_app = modal.App.lookup('p2f-playground-execution', create_if_missing=True)
    intel_enabled = False
    flang_enabled = False
    lfortran_enabled = False
    with modal.enable_output():
        job_image.build(build_app).publish(RUNTIME_IMAGE_NAME)
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
    versions, standards = {}, {}
    for compiler, image_name, enabled in [('gfortran', RUNTIME_IMAGE_NAME, True),
            ('ifx', INTEL_IMAGE_NAME, intel_enabled), ('flang', FLANG_IMAGE_NAME, flang_enabled),
            ('lfortran', LFORTRAN_IMAGE_NAME, lfortran_enabled)]:
        if enabled:
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
    subprocess.run([sys.executable, '-X', 'utf8', '-m', 'modal', 'deploy',
                    str(ROOT / 'xmodal.py')], cwd=ROOT, env=env, check=True)


if __name__ == '__main__':
    main()
