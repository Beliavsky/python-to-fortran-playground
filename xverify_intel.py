"""Build-image smoke checks for Intel; no public job quota or deployment needed."""
from pathlib import Path
import threading

from xrun import execute


def main():
    runtime = Path('/opt/p2f/runtime')
    cases = [
        'total = 0\nfor i in range(1, 11):\n    total += i*i\nprint(total)\n',
        'import numpy as np\nx = np.array([1.0, 2.0, 3.0])\nprint(np.mean(x), np.std(x))\n',
        'import numpy as np\na = np.array([[2.0, 0.0], [0.0, 4.0]])\nb = np.array([2.0, 8.0])\nx = np.linalg.solve(a, b)\nprint(x[0], x[1])\n',
    ]
    for source in cases:
        result = execute(runtime, source, 'compare', threading.Event(), compiler_name='ifx')
        if not result['ok']:
            raise RuntimeError(str(result))
        if not result.get('precompiled_helpers') or 'Build helper:' in result['build']['stdout']:
            raise RuntimeError('Intel image did not reuse its precompiled helpers')
        print('Intel compare: PASS', flush=True)


if __name__ == '__main__':
    main()
