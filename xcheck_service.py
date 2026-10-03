"""Run small end-to-end checks against the configured hosted API (uses job quota)."""
import argparse
import json
from pathlib import Path
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--require-intel', action='store_true', help='Fail unless Intel is advertised and passes')
    args = parser.parse_args()
    url = json.loads((ROOT / 'site/run/service.json').read_text())['url']
    token = ''

    def request(path, payload=None):
        headers = {'Origin': 'https://beliavsky.github.io', 'X-P2F-Token': token}
        if payload is not None:
            headers['Content-Type'] = 'application/json'
        req = urllib.request.Request(url + '/api/' + path,
            data=json.dumps(payload).encode() if payload is not None else None, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=120) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            raise RuntimeError(error.read().decode()) from None

    health = request('health')
    session = request('session')
    token = session['token']
    pin = json.loads((ROOT / 'upstream.json').read_text(encoding='utf-8'))
    if health.get('commit') != pin['commit'] or session.get('commit') != pin['commit']:
        raise RuntimeError('Hosted service does not match upstream.json')
    intel = 'ifx' in session.get('compilers', ['gfortran'])
    if args.require_intel and not intel:
        raise RuntimeError('Intel is unavailable; deploy an Intel-verified image first')
    cases = [
        ('unprivileged Python', 'python', 'import os\nprint(os.geteuid())\n', '65534'),
        ('sum of squares', 'compare', 'total = 0\nfor i in range(1, 11):\n    total += i*i\nprint(total)\n', '385'),
        # mean requires compiling python.f90; sum alone is a Fortran intrinsic.
        ('NumPy helpers', 'compare', 'import numpy as np\nx = np.array([1.0, 2.0, 3.0])\nprint(np.sum(x*x))\nprint(np.mean(x))\n', '14.0\n2.0'),
    ]
    cases = [(name, mode, source, expected, 'gfortran') for name, mode, source, expected in cases]
    if intel:
        cases += [
            ('Intel sum of squares', 'compare', 'total = 0\nfor i in range(1, 11):\n    total += i*i\nprint(total)\n', '385', 'ifx'),
            ('Intel NumPy helpers', 'compare', 'import numpy as np\nx = np.array([1.0, 2.0, 3.0])\nprint(np.mean(x))\n', '2.0', 'ifx'),
            ('Intel LAPACK', 'compare', 'import numpy as np\na = np.array([[2.0, 0.0], [0.0, 4.0]])\nb = np.array([2.0, 8.0])\nx = np.linalg.solve(a,b)\nprint(x[0], x[1])\n', '1.0 2.0', 'ifx'),
        ]
    for name, mode, source, expected, compiler in cases:
        identifier = request('jobs', {'source': source, 'mode': mode, 'compiler': compiler})['id']
        deadline = time.monotonic() + 270
        try:
            while time.monotonic() < deadline:
                result = request('jobs/' + identifier)
                if result['state'] == 'done':
                    result = result['result']
                    if not result.get('ok') or result.get('python', {}).get('stdout', '').strip() != expected:
                        raise RuntimeError(json.dumps(result, indent=2))
                    if mode == 'compare' and result.get('compiler') != compiler:
                        raise RuntimeError('Service used a different compiler than requested')
                    print(f'{name}: PASS ({result["seconds"]:.2f} s)', flush=True)
                    break
                time.sleep(0.5)
            else:
                raise TimeoutError('Hosted test timed out')
        except BaseException:
            request('jobs/' + identifier + '/cancel', {})
            raise


if __name__ == '__main__':
    main()
