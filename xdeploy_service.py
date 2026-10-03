"""Build the pinned sandbox image locally, publish it, and deploy the Modal API."""
import subprocess
import sys

import modal
from xmodal import ROOT, RUNTIME_IMAGE_NAME, job_image


def main():
    build_app = modal.App.lookup('p2f-playground-execution', create_if_missing=True)
    with modal.enable_output():
        job_image.build(build_app).publish(RUNTIME_IMAGE_NAME)
    subprocess.run([sys.executable, '-X', 'utf8', '-m', 'modal', 'deploy',
                    str(ROOT / 'xmodal.py')], cwd=ROOT, check=True)


if __name__ == '__main__':
    main()
