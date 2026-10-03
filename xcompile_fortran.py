"""Compile a submitted single-file Fortran program with trusted compiler options."""
import argparse
from pathlib import Path
import re
import shlex
import subprocess
import sys


def uses_python_mod(source):
    # Normalize only for detecting USE, never rewrite the submitted program.
    lines = '\n'.join(line.split('!', 1)[0] for line in source.splitlines())
    lines = re.sub(r'&\s*\n\s*&?', ' ', lines)
    return bool(re.search(r'(?:^|;)\s*use\b\s*(?:,\s*non_intrinsic\s*)?(?:::\s*)?python_mod\b',
                          lines, re.I | re.M))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--compiler', required=True)
    options = parser.parse_args()
    parts = shlex.split(options.compiler)
    helpers = []
    if uses_python_mod(Path('input_p.f90').read_text(encoding='utf-8')):
        sys.path.insert(0, str(options.runtime.resolve()))
        # Reuse the pinned upstream's ordering and cache checks, not its transpiler.
        import xp2f
        helpers, failure, _ = xp2f._prepare_helper_link_inputs(
            [str(options.runtime / name) for name in ('python.f90', 'lapack_d.f90')], parts)
        if failure is not None:
            print('Build: FAIL (helper compile)', flush=True)
            print(failure.stdout, end='')
            print(failure.stderr, end='', file=sys.stderr)
            return failure.returncode or 1
    command = parts + helpers + ['input_p.f90', '-o', 'input_p.exe']
    print('Build:', ' '.join(command), flush=True)
    result = subprocess.run(command, check=False)
    print('Build: PASS' if result.returncode == 0 else 'Build: FAIL', flush=True)
    return result.returncode


if __name__ == '__main__':
    sys.exit(main())
