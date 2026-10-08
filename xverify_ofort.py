"""Smoke-test ofort before advertising it in the hosted playground."""
from pathlib import Path
import subprocess
import tempfile


def verify():
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / 'main.f90'
        path.write_text('program main\nimplicit none\ninteger :: i\ni=42\nprint*,i\nend program main\n', encoding='utf-8')
        subprocess.run(['ofort', '--check', str(path)], check=True, timeout=15)
        result = subprocess.run(['ofort', str(path)], capture_output=True, text=True, timeout=15)
        if result.returncode or result.stdout.strip() != '42':
            raise RuntimeError('ofort arithmetic smoke test failed: ' + result.stdout + result.stderr)
        path.write_text('program main\nimplicit none\ninteger :: i\nprint*,i\nend program main\n', encoding='utf-8')
        result = subprocess.run(['ofort', str(path)], capture_output=True, text=True, timeout=15)
        if not result.returncode or 'before it is set' not in result.stdout + result.stderr:
            raise RuntimeError('ofort did not detect the uninitialized-variable test')


if __name__ == '__main__':
    verify()
