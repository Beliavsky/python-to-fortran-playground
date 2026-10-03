"""Run small end-to-end checks against the configured hosted API (uses job quota)."""
import json
from pathlib import Path
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parent


def main():
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

    token = request('session')['token']
    cases = [
        ('unprivileged Python', 'python', 'import os\nprint(os.geteuid())\n', '65534'),
        ('sum of squares', 'compare', 'total = 0\nfor i in range(1, 11):\n    total += i*i\nprint(total)\n', '385'),
        ('NumPy', 'compare', 'import numpy as np\nx = np.array([1.0, 2.0, 3.0])\nprint(np.sum(x*x))\n', '14.0'),
    ]
    for name, mode, source, expected in cases:
        identifier = request('jobs', {'source': source, 'mode': mode})['id']
        deadline = time.monotonic() + 270
        try:
            while time.monotonic() < deadline:
                result = request('jobs/' + identifier)
                if result['state'] == 'done':
                    result = result['result']
                    if not result.get('ok') or result.get('python', {}).get('stdout', '').strip() != expected:
                        raise RuntimeError(json.dumps(result, indent=2))
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
