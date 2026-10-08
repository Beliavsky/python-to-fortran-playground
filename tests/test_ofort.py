"""Interpreter jobs use standalone source, not compiler/linker workflows."""
from pathlib import Path
import shutil
import sys
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import xrun
from compiler_options import user_flags


SOURCE = 'program main\nimplicit none\ninteger :: i\ni=42\nprint*,i\nend program main\n'


class OfortTests(unittest.TestCase):
    def execute(self, mode='fortran-edit', **kwargs):
        return xrun.execute(Path('/unused'), '', mode, threading.Event(),
                            compiler_name='ofort', fortran_source=SOURCE, **kwargs)

    def test_selection_has_no_compiler_flags(self):
        self.assertEqual(xrun.compiler_command('ofort'), 'ofort')
        self.assertEqual(user_flags('ofort'), [])
        for options in ({'preset': 'debug'}, {'warnings': True}, {'fast_math': True}, {'standard': '2008'}):
            with self.assertRaises(ValueError):
                user_flags('ofort', options)

    def test_check_does_not_execute_or_link_helpers(self):
        stage = {'ok': True, 'stdout': 'ofort check passed', 'stderr': '', 'seconds': 0.1}
        with patch('xrun.shutil.which', return_value='ofort'), \
             patch('xrun.detect_compiler_version', return_value='ofort test'), \
             patch('xrun.seed_helper_cache') as seed, patch('xrun.run_command', return_value=stage) as run:
            result = self.execute('fortran-compile')
        self.assertTrue(result['ok'])
        self.assertTrue(result['interpreter'])
        self.assertNotIn('execution', result)
        self.assertEqual(run.call_args.args[0], ['ofort', '--check', 'input.f90'])
        seed.assert_not_called()

    def test_invalid_modes_and_unavailable_never_fall_back(self):
        with patch('xrun.run_command') as run:
            for mode in ('fortran', 'both-edit', 'compare-edit', 'fortran-run'):
                self.assertFalse(self.execute(mode)['ok'])
            with patch('xrun.shutil.which', return_value=None):
                self.assertIn('unavailable', self.execute()['error'])
            run.assert_not_called()

    @unittest.skipUnless(shutil.which('ofort'), 'ofort required')
    def test_execution_and_uninitialized_read(self):
        result = self.execute()
        self.assertTrue(result['ok'], result)
        self.assertEqual(result['execution']['stdout'].strip(), '42')
        self.assertNotIn('_artifact', result)
        source = SOURCE.replace('i=42\n', '')
        result = xrun.execute(Path('/unused'), '', 'fortran-edit', threading.Event(),
                             compiler_name='ofort', fortran_source=source)
        self.assertFalse(result['ok'], result)
        self.assertIn('before it is set', result['execution']['stdout'] + result['execution']['stderr'])

    def test_syntax_failure_stops_before_execution(self):
        with patch('xrun.shutil.which', return_value='ofort'), \
             patch('xrun.detect_compiler_version', return_value='ofort test'), \
             patch('xrun.run_command', return_value={'ok': False}) as run:
            self.assertFalse(self.execute()['ok'])
            self.assertEqual(run.call_count, 1)


if __name__ == '__main__':
    unittest.main()
