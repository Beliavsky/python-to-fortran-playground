"""Shared-memory backing files must fit actual worker limits."""
import os
from pathlib import Path
import signal
import sys
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import xrun
from xsandbox_worker import file_size_limit


class SandboxLimitTests(unittest.TestCase):
    def test_shared_memory_budget_is_bounded_and_requires_coarray_options(self):
        self.assertEqual(file_size_limit({}), 16 * 1024 * 1024)
        for compiler in ('gfortran', 'gfortran17', 'ifx', 'flang', 'lfortran'):
            self.assertEqual(file_size_limit({'compiler': compiler, 'compiler_options': {'images': 2}}),
                             64 * 1024 * 1024)
        for images in (None, True, '2', 8):
            self.assertEqual(file_size_limit({'compiler_options': {'images': images}}), 16 * 1024 * 1024)

    def test_silent_nonzero_exit_gets_a_diagnostic(self):
        result = xrun.run_command([sys.executable, '-c', 'raise SystemExit(7)'],
                                 xrun.ROOT, threading.Event(), 5)
        self.assertFalse(result['ok'])
        self.assertEqual(result['exit_code'], 7)
        self.assertIn('exited with code 7', result['stderr'])

    @unittest.skipUnless(os.name == 'posix', 'Unix resource limits required')
    def test_actual_worker_limits_and_signal_reporting(self):
        for coarrays in (False, True):
            payload = {'compiler': 'gfortran17', 'compiler_options': {'images': 2}} if coarrays else {}
            script = ('import tempfile, signal; from xsandbox_worker import apply_sandbox_limits; '
                      f'apply_sandbox_limits({payload!r}); '
                      'signal.signal(signal.SIGXFSZ, signal.SIG_DFL); '
                      'stream=tempfile.TemporaryFile(); stream.truncate(20*1024*1024); print("created")')
            result = xrun.run_command([sys.executable, '-c', script], xrun.ROOT, threading.Event(), 5)
            self.assertEqual(result['ok'], coarrays, result)
            if coarrays:
                self.assertEqual(result['stdout'].strip(), 'created')
            else:
                self.assertEqual(result['exit_code'], -signal.SIGXFSZ)
                self.assertIn('SIGXFSZ', result['stderr'])
                self.assertIn('File-size limit exceeded', result['stderr'])


if __name__ == '__main__':
    unittest.main()
