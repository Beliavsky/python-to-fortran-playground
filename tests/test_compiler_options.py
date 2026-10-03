"""Validate the public option vocabulary and real GNU compilation paths."""
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch, Mock
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from compiler_options import OPTIONS, user_flags
import xrun
import xcompile_fortran
from xprecompile import precompile


class OptionTests(unittest.TestCase):
    def test_cold_helpers_receive_only_baseline_flags(self):
        helper = Mock(return_value=(['python.o', 'lapack_d.o'], None, None))
        fake = SimpleNamespace(_prepare_helper_link_inputs=helper,
            _modules_defined_in_source=Mock(return_value=set()),
            resolve_helper_files_for_build=Mock(return_value=(['python.f90', 'lapack_d.f90'], [], [])))
        command = ['xcompile_fortran.py', '--runtime', '.', '--compiler',
                   'gfortran -ffree-line-length-none', '--user-flags', '["-O3", "-Wall"]']
        # Avoid importing an unrelated local transpiler or actually compiling.
        original_path = list(sys.path)
        try:
            with patch.object(sys, 'argv', command), patch.dict(sys.modules, {'xp2f': fake}), \
                 patch.object(Path, 'read_text', return_value='use python_mod'), \
                 patch.object(xcompile_fortran.subprocess, 'run', return_value=SimpleNamespace(returncode=0)) as run:
                self.assertEqual(xcompile_fortran.main(), 0)
                self.assertEqual(helper.call_args.args[1], ['gfortran', '-ffree-line-length-none'])
                self.assertEqual(run.call_args.args[0], ['gfortran', '-ffree-line-length-none',
                    '-O3', '-Wall', 'python.o', 'lapack_d.o', 'input_p.f90', '-o', 'input_p.exe'])
        finally:
            sys.path[:] = original_path

    def test_allowlist(self):
        for compiler in OPTIONS:
            self.assertEqual(user_flags(compiler), [])
            for invalid in ([], '-O3', {'preset': []}, {'preset': '-O3'},
                            {'flags': ['-fdefault-real-8']}, {'warnings': 'yes'},
                            {'fast_math': 1}, {'include': '/tmp'}):
                with self.subTest(compiler=compiler, selection=invalid):
                    with self.assertRaises(ValueError):
                        user_flags(compiler, invalid)
        with self.assertRaises(ValueError):
            user_flags('flang', {'warnings': True})
        with self.assertRaises(ValueError):
            user_flags('lfortran', {'preset': 'optimized'})
        self.assertEqual(user_flags('lfortran', {'fast_math': True}), ['--fast'])

    @unittest.skipUnless(shutil.which('gfortran'), 'GNU compiler required')
    def test_all_gnu_presets_in_translated_and_edited_code(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory)
            xrun.unpack_runtime(runtime)
            ft = 'program demo\nprint *, 42\nend program demo\n'
            selections = [{'preset': preset} for preset in OPTIONS['gfortran']['presets']]
            selections.append({'preset': 'optimized', 'warnings': True, 'fast_math': True})
            for selection in selections:
                for mode in ('compare', 'compare-edit'):
                    with self.subTest(selection=selection, mode=mode):
                        result = xrun.execute(runtime, 'print(42)', mode, threading.Event(),
                            fortran_source=ft, compiler_options=selection)
                        self.assertTrue(result['ok'], result)
                        for flag in user_flags('gfortran', selection):
                            self.assertIn(flag, result['build']['stdout'])

    @unittest.skipUnless(shutil.which('gfortran'), 'GNU compiler required')
    def test_user_options_do_not_invalidate_or_rebuild_helpers(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory)
            xrun.unpack_runtime(runtime)
            precompile(runtime, 'gfortran')
            cache = runtime / 'precompiled' / 'gfortran'
            originals = {path.name: path.read_bytes() for path in cache.iterdir()}
            for preset in ('debug', 'optimized', 'strict'):
                result = xrun.execute(runtime,
                    'import numpy as np\nx = np.array([1., 2., 3.])\nprint(np.mean(x))\n',
                    'compare', threading.Event(), compiler_options={'preset': preset})
                self.assertTrue(result['ok'], result)
                self.assertTrue(result['precompiled_helpers'])
                self.assertNotIn('Build helper:', result['build']['stdout'])
            self.assertEqual(originals, {path.name: path.read_bytes() for path in cache.iterdir()})


if __name__ == '__main__':
    unittest.main()
