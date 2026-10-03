"""Run one submitted job INSIDE a disposable, network-blocked Modal sandbox."""
import json
from pathlib import Path
import sys
import threading

from xrun import execute


def main():
    # These extra Unix limits complement the enclosing sandbox's hard CPU,
    # memory, network, filesystem isolation, and wall-clock limits.
    import resource
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_FSIZE, (16 * 1024 * 1024,) * 2)
    resource.setrlimit(resource.RLIMIT_NPROC, (128, 128))
    resource.setrlimit(resource.RLIMIT_NOFILE, (128, 128))
    payload = json.loads(sys.stdin.readline(650_001))
    try:
        result = execute(Path('/opt/p2f/runtime'), payload['source'], payload['mode'],
                         threading.Event(), timeout=30, automatic=payload.get('automatic', False))
    except Exception as error:
        result = {'ok': False, 'error': str(error)}
    # Do not echo submitted source to the control plane or its logs.
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
