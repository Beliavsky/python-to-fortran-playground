"""Run one submitted job INSIDE a disposable, network-blocked Modal sandbox."""
import json
import os
from pathlib import Path
import sys
import threading

from xrun import execute


def main():
    # Modal ignores Dockerfile USER. Drop privileges explicitly and fail closed.
    if os.geteuid() == 0:
        os.setgroups([])
        os.setgid(65534)
        os.setuid(65534)
    if os.geteuid() == 0:
        raise RuntimeError('Refusing to execute submitted code as root')
    # These extra Unix limits complement the enclosing sandbox's hard CPU,
    # memory, network, filesystem isolation, and wall-clock limits.
    import resource
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_FSIZE, (16 * 1024 * 1024,) * 2)
    resource.setrlimit(resource.RLIMIT_NPROC, (128, 128))
    resource.setrlimit(resource.RLIMIT_NOFILE, (128, 128))
    # Public requests remain small; the API may attach a private retained binary.
    payload = json.loads(sys.stdin.readline(8_000_001))
    try:
        result = execute(Path('/opt/p2f/runtime'), payload['source'], payload['mode'],
                         threading.Event(), timeout=30, automatic=payload.get('automatic', False),
                         compiler_name=payload.get('compiler', 'gfortran'),
                         fortran_source=payload.get('fortran_source'),
                         compiler_options=payload.get('compiler_options'),
                         translation_options=payload.get('translation_options'),
                         retain_executable=payload.get('retain_executable', False),
                         executable=payload.get('executable'))
    except Exception as error:
        result = {'ok': False, 'error': str(error)}
    # Return results only; do not separately log submitted input. Annotation
    # results necessarily contain the suggested Python source, like Fortran results.
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
