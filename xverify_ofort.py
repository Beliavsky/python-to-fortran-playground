"""Smoke-test ofort before advertising it in the hosted playground."""
from pathlib import Path
import shlex
import subprocess
import tempfile
from xrun import DEFAULT_OFORT

MILLION_SOURCE = '''program main
implicit none
integer, parameter :: n = 10**6
real :: x(n)
call random_number(x)
print "(i0,*(1x,f0.6))", n, sum(x)/n, sum(x**2)/n, minval(x), maxval(x)
end program main
'''
TWO_MILLION_SOURCE = MILLION_SOURCE.replace('n = 10**6', 'n = 2*10**6')


def verify():
    command = shlex.split(DEFAULT_OFORT)
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / 'main.f90'
        path.write_text('program main\nimplicit none\ninteger :: i\ni=42\nprint*,i\nend program main\n', encoding='utf-8')
        subprocess.run(command + ['--check', str(path)], check=True, timeout=15)
        result = subprocess.run(command + [str(path)], capture_output=True, text=True, timeout=15)
        if result.returncode or result.stdout.strip() != '42':
            raise RuntimeError('ofort arithmetic smoke test failed: ' + result.stdout + result.stderr)
        path.write_text('program main\nimplicit none\ninteger :: i\nprint*,i\nend program main\n', encoding='utf-8')
        result = subprocess.run(command + [str(path)], capture_output=True, text=True, timeout=15)
        if not result.returncode or 'before it is set' not in result.stdout + result.stderr:
            raise RuntimeError('ofort did not detect the uninitialized-variable test')
        path.write_text(TWO_MILLION_SOURCE, encoding='utf-8')
        subprocess.run(command + ['--check', str(path)], check=True, timeout=15)
        result = subprocess.run(command + [str(path)], capture_output=True, text=True, timeout=15)
        values = result.stdout.split()
        if result.returncode or len(values) != 5 or values[0] != '2000000':
            raise RuntimeError('ofort two-million-element array smoke test failed: ' + result.stdout + result.stderr)
        if not all(0 <= float(value) <= 1 for value in values[1:]):
            raise RuntimeError('ofort two-million-element array results are outside their expected range')


if __name__ == '__main__':
    verify()
