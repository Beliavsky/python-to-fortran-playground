"""Verify unchanged helpers and translations in LLVM Flang or LFortran images."""
import argparse
from pathlib import Path
import threading

from xrun import execute


def verify(runtime, compiler='flang'):
    cases = [
        ('arithmetic', 'compare', 'total = 0\nfor i in range(1, 11):\n    total += i*i\nprint(total)\n'),
        ('NumPy helpers', 'compare', 'import numpy as np\nx = np.array([1.0, 2.0, 3.0])\nprint(np.mean(x), np.std(x))\n'),
        ('LAPACK', 'compare', 'import numpy as np\na = np.array([[2.0, 0.0], [0.0, 4.0]])\nb = np.array([2.0, 8.0])\nx = np.linalg.solve(a,b)\nprint(x[0], x[1])\n'),
        ('formatting', 'compare', 'import numpy as np\nx = np.array([1.0, 2.0, 3.0])\nprint("%.6g" % np.mean(x))\n'),
        # Genuine random draws need not match Python; exercise helper execution.
        ('random numbers', 'fortran', 'import numpy as np\nx = np.random.normal(size=1000)\nprint(x.size)\n'),
    ]
    for name, mode, source in cases:
        result = execute(runtime, source, mode, threading.Event(), compiler_name=compiler)
        if not result['ok']:
            raise RuntimeError(str(result))
        if not result.get('precompiled_helpers') or 'Build helper:' in result['build']['stdout']:
            raise RuntimeError(f'{compiler} image did not reuse its own precompiled helpers')
        if name == 'random numbers' and result['execution']['stdout'].strip() != '1000':
            raise RuntimeError(f'{compiler} random-number helper returned the wrong array size')
        print(f'{compiler} {name}: PASS ({result["seconds"]:.2f} s)', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compiler', choices=('flang', 'lfortran'), default='flang')
    verify(Path('/opt/p2f/runtime'), parser.parse_args().compiler)
