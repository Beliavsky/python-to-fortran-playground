"""Finite program input, EOF, cancellation, and retained Fortran execution."""
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import xrun


class StdinTests(unittest.TestCase):
    def test_utf8_input_and_eof(self):
        with tempfile.TemporaryDirectory() as directory:
            result = xrun.run_command([sys.executable, '-c',
                'import sys; print(sys.stdin.buffer.read().decode("utf-8"))'],
                Path(directory), threading.Event(), 5, stdin='café\n42')
        self.assertTrue(result['ok'], result)
        self.assertEqual(result['stdout'].replace('\r\n', '\n'), 'café\n42\n')

    def test_unread_large_input_cannot_block_timeout_or_cancellation(self):
        for cancel_request in (False, True):
            cancel = threading.Event()
            timer = threading.Timer(0.2, cancel.set)
            if cancel_request:
                timer.start()
            try:
                result = xrun.run_command([sys.executable, '-c', 'while True: pass'],
                    xrun.ROOT, cancel, 0.5 if not cancel_request else 5, stdin='x' * 100000)
                self.assertFalse(result['ok'], result)
                self.assertIn('Cancelled' if cancel_request else 'Timed out', result['stderr'])
                self.assertLess(result['seconds'], 4)
            finally:
                timer.cancel()

    def test_worker_rejects_invalid_input_before_execution(self):
        for value in (None, [], 'é' * 50001):
            result = xrun.execute(xrun.ROOT, '', 'fortran-edit', threading.Event(), stdin=value)
            self.assertFalse(result['ok'])
            self.assertIn('Program input', result['error'])

    @unittest.skipUnless(shutil.which('gfortran'), 'gfortran required')
    def test_fortran_input_and_changed_input_for_retained_build(self):
        source = ('program main\nimplicit none\ninteger :: a, b, status\n'
                  'read(*,*) a,b\nprint *, a+b\n'
                  'read(*,*,iostat=status) a\nif (status >= 0) stop 1\nend program\n')
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory)
            xrun.unpack_runtime(runtime)
            result = xrun.execute(runtime, '', 'fortran-edit', threading.Event(),
                fortran_source=source, stdin='2 3\n', retain_executable=True)
            self.assertTrue(result['ok'], result)
            self.assertEqual(result['execution']['stdout'].strip(), '5')
            rerun = xrun.execute(runtime, '', 'fortran-run', threading.Event(),
                executable=result['_artifact'], stdin='7 8\n')
            self.assertTrue(rerun['ok'], rerun)
            self.assertTrue(rerun['reused_executable'])
            self.assertNotIn('build', rerun)
            self.assertEqual(rerun['execution']['stdout'].strip(), '15')


if __name__ == '__main__':
    unittest.main()
