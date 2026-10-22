"""Validate the public option vocabulary and real GNU compilation paths."""
from pathlib import Path
import shutil
import subprocess
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
from xprecompile import precompile, verify_options


class OptionTests(unittest.TestCase):
    def test_portable_mappings_are_allowlisted(self):
        for compiler, spec in OPTIONS.items():
            for feature, values in spec['portable_options'].items():
                for choice, flags in values.items():
                    with self.subTest(compiler=compiler, feature=feature, choice=choice):
                        self.assertEqual(user_flags(compiler, {'additional': flags}), flags)
        self.assertEqual(OPTIONS['gfortran']['portable_options']['bounds_check']['true'], ['-fcheck=bounds'])
        self.assertEqual(OPTIONS['ifx']['portable_options']['bounds_check']['true'], ['-check', 'bounds'])
        self.assertEqual(OPTIONS['flang']['portable_options']['optimization']['3'], ['-O3'])
        self.assertNotIn('bounds_check', OPTIONS['flang']['portable_options'])
        for level in range(4):
            self.assertEqual(OPTIONS['ofort']['portable_options']['optimization'][str(level)], [])
            self.assertEqual(OPTIONS['lfortran']['portable_options']['optimization'][str(level)],
                             ['--fast'] if level else [])
            self.assertIn('ignored', OPTIONS['ofort']['portable_option_notes']['optimization'][str(level)])
        self.assertIn('compliance is relaxed', OPTIONS['lfortran']['portable_option_notes']['optimization']['3'])

    def test_additional_options_allowlists_and_conflicts(self):
        self.assertEqual(user_flags('gfortran', {'additional': ['-O2', '-Wall', '-fcheck=all']}),
                         ['-O2', '-Wall', '-fcheck=all'])
        self.assertEqual(user_flags('ifx', {'additional': ['-O2', '-warn', 'all']}),
                         ['-O2', '-warn', 'all'])
        self.assertEqual(user_flags('gfortran', {'warnings': True, 'additional': ['-Wall']}),
                         ['-Wall', '-Wextra', '-Wall'])
        for compiler in OPTIONS:
            for invalid in ['-O2', None, [None], ['-o', 'anything'], ['@response'], ['-I/tmp'],
                            ['-fdefault-real-8'], ['-O2;echo bad'], ['-O2'] * 33, ['x' * 129]]:
                with self.subTest(compiler=compiler, invalid=invalid), self.assertRaises(ValueError):
                    user_flags(compiler, {'additional': invalid})
        for compiler, selection in [
                ('gfortran', {'preset': 'debug', 'additional': ['-O2']}),
                ('gfortran', {'additional': ['-O2', '-O3']}),
                ('ifx', {'preset': 'optimized', 'additional': ['-fp-model', 'fast']}),
                ('ifx', {'additional': ['-warn']}), ('ofort', {'additional': ['-O2']})]:
            with self.subTest(compiler=compiler, selection=selection), self.assertRaises(ValueError):
                user_flags(compiler, selection)

    @unittest.skipUnless(shutil.which('gfortran'), 'GNU compiler required')
    def test_additional_gnu_options_compile_and_run(self):
        with tempfile.TemporaryDirectory() as directory:
            result = xrun.execute(Path(directory), '', 'fortran-edit', threading.Event(),
                fortran_source='program demo\nimplicit none\nprint *, 42\nend program demo\n',
                compiler_options={'additional': ['-O2', '-Wall', '-fcheck=all']})
            self.assertTrue(result['ok'], result)
            self.assertEqual(result['execution']['stdout'].strip(), '42')
            self.assertIn('-O2 -Wall -fcheck=all', result['build']['stdout'])

    def test_cold_helpers_receive_only_baseline_flags(self):
        helper = Mock(return_value=(['python.o', 'lapack_d.o'], None, None))
        fake = SimpleNamespace(_prepare_helper_link_inputs=helper,
            _modules_defined_in_source=Mock(return_value=set()),
            resolve_helper_files_for_build=Mock(return_value=(['python.f90', 'lapack_d.f90'], [], [])))
        command = ['xcompile_fortran.py', '--runtime', '.', '--compiler',
                   'gfortran -ffree-line-length-none', '--user-flags', '["-O3", "-Wall", "-std=f2008", "-cpp"]']
        # Avoid importing an unrelated local transpiler or actually compiling.
        original_path = list(sys.path)
        try:
            with patch.object(sys, 'argv', command), patch.dict(sys.modules, {'xp2f': fake}), \
                 patch.object(Path, 'read_text', return_value='use python_mod'), \
                 patch.object(xcompile_fortran.subprocess, 'run', return_value=SimpleNamespace(returncode=0)) as run:
                self.assertEqual(xcompile_fortran.main(), 0)
                self.assertEqual(helper.call_args.args[1], ['gfortran', '-ffree-line-length-none'])
                self.assertEqual(run.call_args.args[0], ['gfortran', '-ffree-line-length-none',
                    '-O3', '-Wall', '-std=f2008', '-cpp', 'python.o', 'lapack_d.o', 'input_p.f90', '-o', 'input_p.exe'])
        finally:
            sys.path[:] = original_path

    def test_allowlist(self):
        for compiler in OPTIONS:
            self.assertEqual(user_flags(compiler), [])
            for invalid in ([], '-O3', {'preset': []}, {'preset': '-O3'},
                            {'flags': ['-fdefault-real-8']}, {'warnings': 'yes'},
                            {'fast_math': 1}, {'preprocess': 'yes'}, {'preprocess': 1}, {'include': '/tmp'}):
                with self.subTest(compiler=compiler, selection=invalid):
                    with self.assertRaises(ValueError):
                        user_flags(compiler, invalid)
        with self.assertRaises(ValueError):
            user_flags('flang', {'warnings': True})
        with self.assertRaises(ValueError):
            user_flags('lfortran', {'preset': 'optimized'})
        self.assertEqual(user_flags('lfortran', {'fast_math': True}), ['--fast'])

    def test_preprocessing_flags_are_allowlisted_and_optional(self):
        for name, expected in [('gfortran', '-cpp'), ('ifx', '-fpp'), ('flang', '-cpp'), ('lfortran', '--cpp')]:
            self.assertEqual(user_flags(name, {'preprocess': True}), [expected])
            self.assertEqual(user_flags(name, {'preprocess': False}), [])
        with self.assertRaises(ValueError):
            user_flags('ofort', {'preprocess': True})

    @unittest.skipUnless(shutil.which('lfortran'), 'LFortran compiler required')
    def test_lfortran_preprocessing_compiles_macro_and_conditional(self):
        source = '''#define VALUE 42
#if VALUE == 42
program pp
implicit none
print *, VALUE
end program pp
#else
this is deliberately invalid Fortran
#endif
'''
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / 'input_p.f90').write_text(source, encoding='utf-8')
            for enabled in (False, True):
                result = subprocess.run(['lfortran', *user_flags('lfortran', {'preprocess': enabled}),
                    '-c', 'input_p.f90', '-o', 'probe.o'], cwd=path, capture_output=True, text=True, timeout=60)
                self.assertEqual(result.returncode == 0, enabled, result.stdout + result.stderr)

    @unittest.skipUnless(shutil.which('gfortran'), 'GNU compiler required')
    def test_gnu_preprocessing_changes_macro_and_conditional_behavior(self):
        source = '''#define VALUE 42
#if VALUE == 42
program preprocess_test
implicit none
print *, VALUE
end program preprocess_test
#else
this is deliberately invalid Fortran
#endif
'''
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory)
            off = xrun.execute(runtime, '', 'fortran-edit', threading.Event(),
                fortran_source=source, compiler_options={'preprocess': False})
            self.assertFalse(off['ok'], off)
            on = xrun.execute(runtime, '', 'fortran-edit', threading.Event(),
                fortran_source=source, compiler_options={'preprocess': True})
            self.assertTrue(on['ok'], on)
            self.assertEqual(on['execution']['stdout'].strip(), '42')
            self.assertIn('-cpp', on['build']['stdout'])

    def test_standard_selection_is_independent_of_presets_and_allowlisted(self):
        for compiler in OPTIONS:
            self.assertEqual(user_flags(compiler, {'standard': 'default'}), [])
            for invalid in (2008, [], None, 'f2008', '2008 -O3', '2099'):
                with self.assertRaises(ValueError):
                    user_flags(compiler, {'standard': invalid})
        self.assertEqual(user_flags('gfortran', {'preset': 'strict', 'standard': '2008'}),
                         ['-pedantic', '-Wall', '-Wextra', '-std=f2008'])
        self.assertEqual(user_flags('ifx', {'preset': 'debug', 'standard': '2008'})[-2:], ['-stand', 'f08'])
        with self.assertRaises(ValueError):
            user_flags('gfortran', {'standard': '2023'}, standards={'2008': ['-std=f2008']})
        for compiler in ('flang', 'lfortran'):
            with self.assertRaises(ValueError):
                user_flags(compiler, {'standard': '2008'})

    @unittest.skipUnless(shutil.which('gfortran'), 'GNU compiler required')
    def test_gnu_standard_flags_and_newer_language_features(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory)
            supported = xrun.runtime_standards(runtime, 'gfortran', xrun.DEFAULT_COMPILER)
            self.assertIn('2008', supported)
            for year in supported:
                result = xrun.execute(runtime, '', 'fortran-compile', threading.Event(),
                    fortran_source='program demo\nimplicit none\nprint *, 42\nend program demo\n',
                    compiler_options={'standard': year, 'preset': 'strict'})
                self.assertTrue(result['ok'], result)
                self.assertIn(supported[year][0], result['build']['stdout'])
            source = 'program demo\nimplicit none (type, external)\nprint *, 42\nend program demo\n'
            for year, expected in [('2008', False), ('2018', True)]:
                result = xrun.execute(runtime, '', 'fortran-compile', threading.Event(),
                    fortran_source=source, compiler_options={'standard': year})
                self.assertEqual(result['ok'], expected, result)

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
            verify_options(runtime, 'gfortran')
            cache = runtime / 'precompiled' / 'gfortran'
            originals = {path.name: path.read_bytes() for path in cache.iterdir()}
            for preset in ('debug', 'optimized', 'strict'):
                result = xrun.execute(runtime,
                    'import numpy as np\nx = np.array([1., 2., 3.])\nprint(np.mean(x))\n',
                    'compare', threading.Event(), compiler_options={'preset': preset})
                self.assertTrue(result['ok'], result)
                self.assertTrue(result['precompiled_helpers'])
                self.assertNotIn('Build helper:', result['build']['stdout'])
            for year in xrun.runtime_standards(runtime, 'gfortran', xrun.DEFAULT_COMPILER):
                result = xrun.execute(runtime, '', 'fortran-edit', threading.Event(),
                    fortran_source='program demo\nuse python_mod, only: mean\nimplicit none\n'
                                   'real(kind(1.0d0)) :: x(3) = (/ 1.0d0, 2.0d0, 3.0d0 /)\n'
                                   'print *, mean(x)\nend program demo\n', compiler_options={'standard': year})
                self.assertTrue(result['ok'], result)
                self.assertTrue(result['precompiled_helpers'])
                self.assertNotIn('Build helper:', result['build']['stdout'])
            self.assertEqual(originals, {path.name: path.read_bytes() for path in cache.iterdir()})


if __name__ == '__main__':
    unittest.main()
