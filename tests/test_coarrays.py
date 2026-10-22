"""Coarrays require bounded, verified capabilities and retain their execution settings."""
import base64
import os
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from compiler_options import OPTIONS, user_flags, coarray_environment, coarray_command
import xrun
from xverify_coarrays import probe, probe_output_matches


class CoarrayTests(unittest.TestCase):
    def test_probe_recognizes_lfortran_normal_stop_messages_without_hiding_failures(self):
        self.assertTrue(probe_output_matches('lfortran', 'STOP\n2\nSTOP\n', 2))
        self.assertTrue(probe_output_matches('lfortran', '2\n', 2))
        for output in ('STOP\n1\nSTOP\n', 'STOP\n2\nerror\n', 'STOP\nSTOP\n', '2\n2\nSTOP\n'):
            self.assertFalse(probe_output_matches('lfortran', output, 2))
        self.assertFalse(probe_output_matches('flang', '2\nSTOP\n', 2))

    def test_execution_environment_does_not_leak_between_jobs(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'GFORTRAN_NUM_IMAGES': '99'}):
            result = xrun.run_command([sys.executable, '-c', 'import os; print(os.environ["GFORTRAN_NUM_IMAGES"])'],
                Path(directory), threading.Event(), 5, env={'GFORTRAN_NUM_IMAGES': '2'})
            self.assertTrue(result['ok'], result)
            self.assertEqual(result['stdout'].strip(), '2')
            self.assertEqual(os.environ['GFORTRAN_NUM_IMAGES'], '99')

    def test_structured_image_counts_and_flags(self):
        for compiler in ('gfortran', 'gfortran17'):
            for count in (1, 2, 4):
                self.assertEqual(user_flags(compiler, {'images': count}),
                                 ['-fcoarray=single' if count == 1 else '-fcoarray=lib'])
            for invalid in (0, 3, 8, True, '2', None, []):
                with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                    user_flags(compiler, {'images': invalid})
            with self.assertRaises(ValueError):
                user_flags(compiler, {'images': 2}, coarrays={})
            with self.assertRaises(ValueError):
                user_flags(compiler, {'additional': ['-fcoarray=lib']})
        for count in (1, 2, 4):
            self.assertEqual(user_flags('ifx', {'images': count}), OPTIONS['ifx']['coarray_images'][str(count)])
        for invalid in (0, 3, 8, True, '2', None, []):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                user_flags('ifx', {'images': invalid})
        with self.assertRaises(ValueError):
            user_flags('ifx', {'images': 2}, coarrays={})
        for flag in ('-coarray=shared', '-coarray=single', '-coarray-num-images=8'):
            with self.assertRaises(ValueError):
                user_flags('ifx', {'additional': [flag]})
        for compiler, flag in [('flang', '-fcoarray'), ('lfortran', '--coarray=true')]:
            for count in (1, 2, 4):
                self.assertEqual(user_flags(compiler, {'images': count}), [flag])
            with self.assertRaises(ValueError):
                user_flags(compiler, {'images': 1}, coarrays={})
            with self.assertRaises(ValueError):
                user_flags(compiler, {'additional': [flag]})
        for compiler in ('ofort',):
            with self.assertRaises(ValueError):
                user_flags(compiler, {'images': 1})

    def test_execution_and_retained_rerun_get_bounded_environment(self):
        stage = {'ok': True, 'stdout': '2\n', 'stderr': '', 'seconds': 0.01}
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(xrun, 'compiler_version', return_value='GNU test'), \
                patch.object(xrun.shutil, 'which', return_value='/compiler'), \
                patch.object(xrun, 'seed_helper_cache', return_value=False), \
                patch.object(xrun, 'run_command', return_value=stage) as run:
            runtime = Path(directory)
            xrun.execute(runtime, '', 'fortran-edit', threading.Event(), fortran_source='print *, 42\nend\n',
                         compiler_options={'images': 2})
            self.assertEqual(run.call_args.kwargs['env'], {'GFORTRAN_NUM_IMAGES': '2',
                'GFORTRAN_SHARED_MEMORY_SIZE': '64M', 'GFORTRAN_IMAGE_RESTARTS_LIMIT': '8'})
            self.assertNotIn('env', run.call_args_list[0].kwargs)  # Compiler environment is unchanged.
            xrun.execute(runtime, '', 'fortran-run', threading.Event(), compiler_options={'images': 4},
                         executable=base64.b64encode(b'fake-binary').decode())
            self.assertEqual(run.call_args.kwargs['env']['GFORTRAN_NUM_IMAGES'], '4')

    def test_failed_multi_image_probes_are_not_advertised(self):
        success = {'ok': True, 'stdout': '1\n'}
        failure = {'ok': False, 'stdout': '', 'stderr': 'Timed out'}
        with patch('xverify_coarrays.run_command', side_effect=[success, success, success, failure, failure]):
            self.assertEqual(probe('gfortran'), {'1': ['-fcoarray=single']})

    def test_intel_execution_and_retained_rerun_use_same_mpi_environment(self):
        stage = {'ok': True, 'stdout': '2\n', 'stderr': '', 'seconds': 0.01}
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(xrun, 'compiler_version', return_value='Intel test'), \
                patch.object(xrun.shutil, 'which', return_value='/compiler'), \
                patch.object(xrun, 'seed_helper_cache', return_value=False), \
                patch.object(xrun, 'run_command', return_value=stage) as run:
            for mode in ('fortran-edit', 'fortran-run'):
                xrun.execute(Path(directory), '', mode, threading.Event(), compiler_name='ifx',
                             fortran_source='print *, num_images()\nend\n',
                             compiler_options={'images': 2},
                             executable=base64.b64encode(b'fake-binary').decode())
                self.assertEqual(run.call_args.args[0][0], 'p2f-ifx-run')
                self.assertEqual(run.call_args.kwargs['env'], {
                    'FOR_COARRAY_NUM_IMAGES': '2', 'I_MPI_FABRICS': 'shm',
                    'I_MPI_PIN': '0', 'I_MPI_WAIT_MODE': '1'})
        self.assertIsNone(coarray_environment('ifx', None))
        self.assertEqual(coarray_command('ifx', '/program', None), ['/program'])

    def test_intel_probe_uses_runtime_launcher_and_rejects_wrong_image_count(self):
        success = {'ok': True, 'stdout': '1\n'}
        # Successful exit alone is insufficient: two images report the wrong count.
        with patch('xverify_coarrays.run_command', side_effect=[
                success, success, success, success, success, {'ok': False, 'stdout': ''}]) as run:
            self.assertEqual(probe('ifx'), {'1': ['-coarray=single']})
        build = run.call_args_list[2].args[0]
        self.assertIn('-coarray=shared', build)
        self.assertIn('-coarray-num-images=2', build)
        ran = run.call_args_list[3]
        self.assertEqual(ran.args[0][0], 'p2f-ifx-run')
        self.assertEqual(ran.kwargs['env'], coarray_environment('ifx', 2))

    def test_caffeine_probes_use_matching_libraries_runtime_and_image_counts(self):
        for compiler in ('flang', 'lfortran'):
            responses = []
            for count in (1, 2, 4):
                responses += [{'ok': True, 'stdout': ''}, {'ok': True, 'stdout': str(count)}]
            libraries = ['-L/runtime/' + compiler, '-lcaffeine-smp-seq', '-lgasnet-smp-seq']
            with patch('xverify_coarrays.coarray_link_flags', return_value=libraries), \
                    patch('xverify_coarrays.run_command', side_effect=responses) as run:
                self.assertEqual(probe(compiler), OPTIONS[compiler]['coarray_images'])
            for index, count in enumerate((1, 2, 4)):
                built, ran = run.call_args_list[index * 2:index * 2 + 2]
                self.assertEqual(built.args[0][-3:], libraries)
                self.assertTrue(ran.args[0][0].endswith('probe.exe'))
                self.assertEqual(ran.kwargs['env']['GASNET_PSHM_NODES'], str(count))
                self.assertEqual(ran.kwargs['env']['GASNET_MAX_SEGSIZE'], '64M')

    def test_caffeine_execution_and_rerun_preserve_runtime_selection(self):
        stage = {'ok': True, 'stdout': '2\n', 'stderr': '', 'seconds': 0.01}
        for compiler in ('flang', 'lfortran'):
            with tempfile.TemporaryDirectory() as directory, \
                    patch.object(xrun, 'compiler_version', return_value='Compiler test'), \
                    patch.object(xrun.shutil, 'which', return_value='/compiler'), \
                    patch.object(xrun, 'seed_helper_cache', return_value=False), \
                    patch.object(xrun, 'run_command', return_value=stage) as run:
                xrun.execute(Path(directory), '', 'fortran-edit', threading.Event(), compiler_name=compiler,
                             fortran_source='print *, num_images()\nend\n', compiler_options={'images': 2})
                build = run.call_args_list[0].args[0]
                self.assertEqual(build[-4:], ['--coarray-runtime', compiler, '--coarray-images', '2'])
                self.assertEqual(run.call_args.kwargs['env']['GASNET_PSHM_NODES'], '2')
                xrun.execute(Path(directory), '', 'fortran-run', threading.Event(), compiler_name=compiler,
                             compiler_options={'images': 2}, executable=base64.b64encode(b'fake').decode())
                self.assertEqual(run.call_args.kwargs['env']['GASNET_PSHM_NODES'], '2')
                self.assertEqual(run.call_args.kwargs['env'], coarray_environment(compiler, 2))

    @unittest.skipUnless(shutil.which('gfortran'), 'GNU compiler required')
    def test_local_probe_verifies_at_least_single_image_exchange(self):
        result = probe('gfortran')
        self.assertIn('1', result)
        self.assertTrue(set(result) <= {'1', '2', '4'})
