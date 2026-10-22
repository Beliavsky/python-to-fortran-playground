"""GNU compiler selection and build gates; no hosted jobs or credentials."""
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import xrun
import xverify_gnu


class GnuToolchainTests(unittest.TestCase):
    def test_snapshot_command_never_uses_stable_fallback(self):
        self.assertEqual(xrun.compiler_command('gfortran17', 'custom-stable'),
                         'p2f-gfortran17 -ffree-line-length-none')
        with patch.object(xrun.shutil, 'which', side_effect=lambda command: command if command == 'gfortran' else None):
            self.assertIn('gfortran', xrun.available_compilers())
            self.assertNotIn('gfortran17', xrun.available_compilers())

    def test_wrong_compiler_versions_fail_before_execution(self):
        for compiler, responses in [('gfortran', ['12.2.0', 'GNU Fortran 12.2.0']),
                                    ('gfortran17', ['17.0.0', 'GNU Fortran 17.0.0 20261011'])]:
            with self.subTest(compiler=compiler), \
                    patch.object(xverify_gnu.subprocess, 'check_output', side_effect=responses), \
                    patch.object(xverify_gnu, 'execute') as execute:
                with self.assertRaisesRegex(RuntimeError, 'Expected GNU'):
                    xverify_gnu.verify(Path('/unused'), compiler)
                execute.assert_not_called()

    @unittest.skipUnless(shutil.which('gfortran'), 'GNU Fortran required')
    def test_source_options_diagnostics_and_retained_execution_with_local_gnu(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(xverify_gnu, 'verify_helpers') as helpers:
            # Exact hosted compiler identities are checked when building their Linux images.
            xverify_gnu.verify(Path(directory), 'gfortran', check_version=False)
            helpers.assert_called_once()
