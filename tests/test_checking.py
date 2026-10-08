"""Fortitude findings are successful checks, not failed execution jobs."""
from pathlib import Path
import shutil
import threading
import unittest
from unittest.mock import patch
from xrun import execute, fortitude_command


class CheckingTests(unittest.TestCase):
    def test_status_one_is_findings_and_never_compiles(self):
        stage = {'ok': False, 'exit_code': 1, 'stdout': 'input.f90:1:1: C001 implicit typing', 'stderr': ''}
        with patch('xrun.run_command', return_value=stage) as run, patch('xrun.compiler_command', side_effect=AssertionError('Compiler used')):
            result = execute(Path('.'), 'program main\nend', 'check', threading.Event())
        self.assertTrue(result['ok'])
        self.assertTrue(result['findings'])
        self.assertNotIn('build', result)
        self.assertNotIn('execution', result)
        self.assertNotIn('formatted_source', result)
        command = run.call_args.args[0]
        self.assertIn('--isolated', command)
        self.assertIn('--no-fix', command)
        self.assertNotIn('--fix', command)

    def test_tool_errors_timeouts_and_cancelled_jobs_are_failures(self):
        for status, error in [(2, 'tool failure'), (1, 'Timed out after 15 seconds.'), (None, 'Cancelled.')]:
            with patch('xrun.run_command', return_value={'ok': False, 'exit_code': status, 'stdout': '', 'stderr': error}):
                result = execute(Path('.'), 'program main\nend', 'check', threading.Event())
            self.assertFalse(result['ok'])
            self.assertFalse(result['findings'])

    def test_check_is_explicit_and_bounded(self):
        for source, automatic in [('', False), ('x' * 100001, False), ('program main\nend', True)]:
            with patch('xrun.run_command', side_effect=AssertionError('Tool launched')):
                self.assertFalse(execute(Path('.'), source, 'check', threading.Event(), automatic=automatic)['ok'])

    @unittest.skipUnless(Path(fortitude_command()).is_file() or shutil.which(fortitude_command()), 'Install fortitude-lint==0.9.2')
    def test_real_fortitude_finds_implicit_typing_and_passes_clean_program(self):
        result = execute(Path('.'), 'program main\nprint *, 1\nend program main\n', 'check', threading.Event())
        self.assertTrue(result['ok'], result)
        self.assertTrue(result['findings'], result)
        self.assertIn('C001', result['checking']['stdout'])
        clean = execute(Path('.'), 'program main\n  implicit none(type, external)\n  print *, 1\nend program main\n', 'check', threading.Event())
        self.assertTrue(clean['ok'], clean)
        self.assertFalse(clean['findings'], clean)


if __name__ == '__main__':
    unittest.main()
