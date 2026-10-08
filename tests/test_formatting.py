"""Formatting-only jobs must never compile, translate, or execute source."""
import importlib.util
from pathlib import Path
import threading
import unittest
from unittest.mock import patch

from xrun import execute, MAX_SOURCE


class FormattingTests(unittest.TestCase):
    def test_worker_failure_preserves_source(self):
        with patch('xrun.run_command', return_value={'ok': False, 'stdout': 'partial', 'stderr': 'Failed'}), patch('xrun.compiler_command', side_effect=AssertionError('Compiler used')):
            result = execute(Path('.'), 'program main\nend', 'format', threading.Event())
        self.assertFalse(result['ok'])
        self.assertNotIn('formatted_source', result)

    def test_warnings_and_oversized_output_are_not_applied(self):
        for output, diagnostics in [('partial', 'warning'), ('x' * (MAX_SOURCE + 1), '')]:
            with patch('xrun.run_command', return_value={'ok': True, 'stdout': output, 'stderr': diagnostics}):
                result = execute(Path('.'), 'program main\nend', 'format', threading.Event())
            self.assertFalse(result['ok'])
            self.assertNotIn('formatted_source', result)

    def test_rejects_automatic_empty_and_large_input(self):
        for source, automatic in [('', False), ('x' * (MAX_SOURCE + 1), False), ('program main\nend', True)]:
            with patch('xrun.run_command', side_effect=AssertionError('Worker launched')):
                self.assertFalse(execute(Path('.'), source, 'format', threading.Event(), automatic=automatic)['ok'])

    @unittest.skipUnless(importlib.util.find_spec('fprettify'), 'Install fprettify==0.3.7')
    def test_real_formatter_is_idempotent_and_preserves_case_and_strings(self):
        source = 'PROGRAM main\ninteger::i\ni=2\nprint *, "a=b",i\nEND PROGRAM main\n'
        with patch('xrun.compiler_command', side_effect=AssertionError('Compiler used')):
            first = execute(Path('.'), source, 'format', threading.Event())
            self.assertTrue(first['ok'], first)
            output = first['formatted_source']
            self.assertIn('PROGRAM main', output)
            self.assertIn('   integer::i', output)
            self.assertIn('"a=b"', output)
            second = execute(Path('.'), output, 'format', threading.Event())
        self.assertEqual(output, second['formatted_source'])
        self.assertNotIn('build', first)
        self.assertNotIn('execution', first)

    @unittest.skipUnless(importlib.util.find_spec('fprettify'), 'Install fprettify==0.3.7')
    def test_cancelled_input_returns_no_replacement(self):
        cancel = threading.Event()
        cancel.set()
        result = execute(Path('.'), 'program main\nend', 'format', cancel)
        self.assertFalse(result['ok'])
        self.assertNotIn('formatted_source', result)

    @unittest.skipUnless(importlib.util.find_spec('fprettify'), 'Install fprettify==0.3.7')
    def test_annotations_cannot_override_settings_or_trigger_execution(self):
        source = '! fprettify: --indent 9\nprogram main\nprint *, "hello"\nend program main\n'
        result = execute(Path('.'), source, 'format', threading.Event())
        self.assertTrue(result['ok'], result)
        self.assertIn('   print', result['formatted_source'])


if __name__ == '__main__':
    unittest.main()
