"""Version reporting uses image metadata, with cached local probes as fallback."""
import base64
import json
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

import xrun


class CompilerVersionTests(unittest.TestCase):
    def setUp(self):
        xrun.detect_compiler_version.cache_clear()
        xrun.probe_standards.cache_clear()

    def tearDown(self):
        xrun.detect_compiler_version.cache_clear()
        xrun.probe_standards.cache_clear()

    def test_probe_is_cached_by_full_command_and_accepts_stderr(self):
        result = Mock(stdout='', stderr='\nIntel Fortran 2026.0\nCopyright details\n')
        with patch.object(xrun.subprocess, 'run', return_value=result) as probe:
            for _ in range(2):
                self.assertEqual(xrun.detect_compiler_version('ifx'), 'Intel Fortran 2026.0')
            probe.assert_called_once()
            self.assertEqual(probe.call_args.args[0], ['ifx', '--version'])
            xrun.detect_compiler_version('gfortran -ffree-line-length-none')
            self.assertEqual(probe.call_count, 2)

    def test_missing_or_failing_probe_is_optional_and_cached(self):
        for error in (OSError('missing'), subprocess.TimeoutExpired('compiler', 15),
                      subprocess.CalledProcessError(1, 'compiler')):
            xrun.detect_compiler_version.cache_clear()
            with patch.object(xrun.subprocess, 'run', side_effect=error) as probe:
                self.assertIsNone(xrun.detect_compiler_version('missing'))
                self.assertIsNone(xrun.detect_compiler_version('missing'))
                probe.assert_called_once()

    def test_image_metadata_avoids_probes_and_wrong_command_falls_back(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory)
            cache = runtime / 'precompiled' / 'gfortran'
            cache.mkdir(parents=True)
            manifest = cache / 'manifest.json'
            manifest.write_text(json.dumps({'identity': {'command': xrun.DEFAULT_COMPILER,
                'version': '\nGNU Fortran (GCC) 15.2.0\nCopyright\n'}}), encoding='utf-8')
            with patch.object(xrun, 'detect_compiler_version', return_value='different version') as probe:
                self.assertEqual(xrun.compiler_version(runtime, 'gfortran', xrun.DEFAULT_COMPILER),
                                 'GNU Fortran (GCC) 15.2.0')
                probe.assert_not_called()
                self.assertEqual(xrun.compiler_version(runtime, 'gfortran', 'gfortran -O2'),
                                 'different version')
                probe.assert_called_once_with('gfortran -O2')
                manifest.write_text('invalid json', encoding='utf-8')
                self.assertEqual(xrun.compiler_version(runtime, 'gfortran', xrun.DEFAULT_COMPILER),
                                 'different version')

    def test_compile_and_rerun_results_record_version_but_python_does_not_probe(self):
        stage = {'ok': True, 'stdout': '', 'stderr': '', 'seconds': 0.01}
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(xrun, 'compiler_version', return_value='GNU Fortran test') as version, \
                patch.object(xrun.shutil, 'which', return_value='/compiler'), \
                patch.object(xrun, 'seed_helper_cache', return_value=False), \
                patch.object(xrun, 'run_command', return_value=stage):
            runtime = Path(directory)
            compiled = xrun.execute(runtime, '', 'fortran-compile', threading.Event(),
                                    fortran_source='program main\nend program main\n')
            self.assertTrue(compiled['ok'])
            self.assertEqual(compiled['compiler_version'], 'GNU Fortran test')
            rerun = xrun.execute(runtime, '', 'fortran-run', threading.Event(),
                                executable=base64.b64encode(b'fake-test-binary').decode())
            self.assertEqual(rerun['compiler_version'], 'GNU Fortran test')
            version.reset_mock()
            result = xrun.execute(runtime, 'print(7)', 'python', threading.Event())
            self.assertNotIn('compiler_version', result)
            version.assert_not_called()

    def test_standard_probe_is_cached_and_refuses_ignored_flags(self):
        def compile(command, **kwargs):
            ignored = '-std=f2023' in command
            return Mock(returncode=0, stdout='', stderr='Warning: ignoring unknown option' if ignored else '')
        with patch.object(xrun.subprocess, 'run', side_effect=compile) as probe:
            first = xrun.probe_standards('gfortran', 'gfortran')
            self.assertIn('2008', first)
            self.assertNotIn('2023', first)
            self.assertEqual(xrun.probe_standards('gfortran', 'gfortran'), first)
            self.assertEqual(probe.call_count, 5)

    def test_recorded_standard_capabilities_do_not_launch_probes(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory)
            cache = runtime / 'precompiled' / 'gfortran'
            cache.mkdir(parents=True)
            (cache / 'manifest.json').write_text(json.dumps({'identity': {'command': xrun.DEFAULT_COMPILER},
                'standards': {'2008': ['-std=f2008'], '2023': ['forged-flag']}}), encoding='utf-8')
            with patch.object(xrun, 'probe_standards', side_effect=AssertionError('no hosted probes')):
                self.assertEqual(xrun.runtime_standards(runtime, 'gfortran', xrun.DEFAULT_COMPILER),
                                 {'2008': ['-std=f2008']})
