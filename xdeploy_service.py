"""Build the pinned sandbox image locally, publish it, and deploy the Modal API."""
import argparse
import os
import subprocess
import sys

import modal


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--without-intel', action='store_true', help='Build/deploy only the GNU image')
    args = parser.parse_args()
    from xmodal import ROOT, RUNTIME_IMAGE_NAME, INTEL_IMAGE_NAME, job_image, intel_job_image
    build_app = modal.App.lookup('p2f-playground-execution', create_if_missing=True)
    intel_enabled = False
    with modal.enable_output():
        job_image.build(build_app).publish(RUNTIME_IMAGE_NAME)
        if not args.without_intel:
            try:
                intel_job_image.build(build_app).publish(INTEL_IMAGE_NAME)
                intel_enabled = True
            except Exception as error:
                print(f'WARNING: Intel image could not be built/verified: {error}', flush=True)
                print('Deploying GNU only. Intel will be marked unavailable; GNU jobs are unchanged.', flush=True)
    env = {**os.environ, 'P2F_INTEL_ENABLED': '1' if intel_enabled else '0'}
    subprocess.run([sys.executable, '-X', 'utf8', '-m', 'modal', 'deploy',
                    str(ROOT / 'xmodal.py')], cwd=ROOT, env=env, check=True)


if __name__ == '__main__':
    main()
