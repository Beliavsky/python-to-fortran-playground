"""Deployment orchestration without real Modal calls or account credentials."""
from contextlib import nullcontext
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import xdeploy_service
from compiler_options import OPTIONS


class DeploymentTests(unittest.TestCase):
    def deploy(self, args=(), intel_error=None, gnu_error=None, flang_error=None, lfortran_error=None,
               version_error=None, ofort_error=None, gnu17_error=None, coarray_error=None):
        gnu, intel, flang, lfortran = Mock(), Mock(), Mock(), Mock()
        gnu.build.return_value = gnu
        intel.build.return_value = intel
        flang.build.return_value = flang
        lfortran.build.return_value = lfortran
        gnu.build.side_effect = gnu_error
        intel.build.side_effect = intel_error
        flang.build.side_effect = flang_error
        lfortran.build.side_effect = lfortran_error
        gnu17 = Mock()
        gnu17.build.return_value = gnu17
        gnu17.build.side_effect = gnu17_error
        definitions = SimpleNamespace(ROOT=Path('/repo'), RUNTIME_IMAGE_NAME='gnu-image',
            OFORT_IMAGE_NAME='ofort-image', ofort_job_image=Mock(),
            TOOLS_IMAGE_NAME='tools-image', tools_job_image=Mock(),
            INTEL_IMAGE_NAME='intel-image', FLANG_IMAGE_NAME='flang-image',
            LFORTRAN_IMAGE_NAME='lfortran-image', job_image=gnu, intel_job_image=intel,
            GNU17_IMAGE_NAME='gnu17-image', gnu17_job_image=gnu17,
            flang_job_image=flang, lfortran_job_image=lfortran)
        definitions.tools_job_image.build.return_value = definitions.tools_job_image
        definitions.ofort_job_image.build.return_value = definitions.ofort_job_image
        definitions.ofort_job_image.build.side_effect = ofort_error
        with patch.dict(sys.modules, {'xmodal': definitions}), \
                patch.object(sys, 'argv', ['xdeploy_service.py', *args]), \
                patch.object(xdeploy_service.modal.App, 'lookup'), \
                patch.object(xdeploy_service.modal, 'enable_output', return_value=nullcontext()), \
                patch.object(xdeploy_service.subprocess, 'run') as deploy, \
                patch.object(xdeploy_service, 'read_image_metadata', side_effect=version_error or (lambda app, image, compiler:
                    {'version': compiler + ' version 1', 'standards': {'2008': ['verified-flag']}})), \
                patch.object(xdeploy_service, 'read_coarray_support', side_effect=coarray_error or
                             (lambda app, image, compiler: {
                                 count: flags for count, flags in OPTIONS[compiler]['coarray_images'].items()
                                 if count in ('1', '2')})), \
                patch.dict(os.environ, {'P2F_INTEL_ENABLED': 'unexpected', 'P2F_FLANG_ENABLED': 'unexpected',
                                       'P2F_LFORTRAN_ENABLED': 'unexpected'}):
            xdeploy_service.main()
        definitions.tools_job_image.publish.assert_called_once_with('tools-image')
        deploy.gnu17_image = gnu17
        if '--without-ofort' in args:
            definitions.ofort_job_image.build.assert_not_called()
        elif not ofort_error and not gnu_error:
            definitions.ofort_job_image.publish.assert_called_once_with('ofort-image')
        return gnu, intel, flang, lfortran, deploy

    def test_success_enables_intel_only_after_build_and_publish(self):
        gnu, intel, flang, lfortran, deploy = self.deploy()
        gnu.publish.assert_called_once_with('gnu-image')
        intel.publish.assert_called_once_with('intel-image')
        flang.publish.assert_called_once_with('flang-image')
        lfortran.publish.assert_called_once_with('lfortran-image')
        self.assertEqual(deploy.call_args.kwargs['env']['P2F_INTEL_ENABLED'], '1')
        self.assertEqual(deploy.call_args.kwargs['env']['P2F_FLANG_ENABLED'], '1')
        self.assertEqual(deploy.call_args.kwargs['env']['P2F_LFORTRAN_ENABLED'], '1')
        self.assertEqual(json.loads(deploy.call_args.kwargs['env']['P2F_COMPILER_VERSIONS']),
                         {name: name + ' version 1' for name in ('gfortran', 'gfortran17', 'ifx', 'flang', 'lfortran', 'ofort')})
        self.assertEqual(json.loads(deploy.call_args.kwargs['env']['P2F_COMPILER_STANDARDS']),
                         {name: {'2008': ['verified-flag']} for name in ('gfortran', 'gfortran17', 'ifx', 'flang', 'lfortran', 'ofort')})
        self.assertEqual(deploy.call_args.kwargs['env']['P2F_GNU17_ENABLED'], '1')
        deploy.gnu17_image.publish.assert_called_once_with('gnu17-image')
        self.assertEqual(deploy.call_args.kwargs['env']['P2F_OFORT_ENABLED'], '1')
        self.assertEqual(json.loads(deploy.call_args.kwargs['env']['P2F_COMPILER_COARRAYS'])['ifx'],
                         {'1': ['-coarray=single'], '2': ['-coarray=shared', '-coarray-num-images=2']})
        for name, flag in [('flang', '-fcoarray'), ('lfortran', '--coarray=true')]:
            self.assertEqual(json.loads(deploy.call_args.kwargs['env']['P2F_COMPILER_COARRAYS'])[name],
                             {'1': [flag], '2': [flag]})

    def test_ofort_failure_does_not_disable_compilers(self):
        _, _, _, _, deploy = self.deploy(ofort_error=RuntimeError('ofort failed'))
        self.assertEqual(deploy.call_args.kwargs['env']['P2F_OFORT_ENABLED'], '0')
        self.assertEqual(deploy.call_args.kwargs['env']['P2F_LFORTRAN_ENABLED'], '1')
        self.assertNotIn('ofort', json.loads(deploy.call_args.kwargs['env']['P2F_COMPILER_VERSIONS']))

    def test_without_ofort_skips_interpreter_only(self):
        _, _, _, _, deploy = self.deploy(('--without-ofort',))
        self.assertEqual(deploy.call_args.kwargs['env']['P2F_OFORT_ENABLED'], '0')
        self.assertEqual(deploy.call_args.kwargs['env']['P2F_LFORTRAN_ENABLED'], '1')

    def test_ofort_metadata_uses_interpreter_not_helper_manifest(self):
        sandbox = Mock(returncode=0)
        sandbox.stdout.read.return_value = json.dumps({'version': 'ofort 0.1.0 (commit abc)', 'standards': {}})
        with patch.object(xdeploy_service.modal.Sandbox, 'create', return_value=sandbox) as create, \
                patch.object(xdeploy_service.modal.Image, 'from_name'):
            result = xdeploy_service.read_image_metadata(Mock(), 'ofort-image', 'ofort')
        self.assertEqual(result['version'], 'ofort 0.1.0 (commit abc)')
        self.assertNotIn('manifest.json', create.call_args.args[2])
        self.assertIn('--version', create.call_args.args[2])
        sandbox.terminate.assert_called_once()

    def test_intel_failure_keeps_gnu_available(self):
        gnu, intel, flang, _, deploy = self.deploy(intel_error=RuntimeError('Intel installation failed'))
        gnu.publish.assert_called_once_with('gnu-image')
        intel.publish.assert_not_called()
        self.assertEqual(deploy.call_args.kwargs['env']['P2F_INTEL_ENABLED'], '0')
        self.assertNotIn('ifx', json.loads(deploy.call_args.kwargs['env']['P2F_COMPILER_VERSIONS']))
        flang.publish.assert_called_once_with('flang-image')
        self.assertEqual(deploy.call_args.kwargs['env']['P2F_FLANG_ENABLED'], '1')

    def test_gnu_only_skips_intel_build(self):
        _, intel, flang, lfortran, deploy = self.deploy(('--without-intel', '--without-flang', '--without-lfortran'))
        intel.build.assert_not_called()
        flang.build.assert_not_called()
        lfortran.build.assert_not_called()
        self.assertEqual(deploy.call_args.kwargs['env']['P2F_INTEL_ENABLED'], '0')
        self.assertEqual(deploy.call_args.kwargs['env']['P2F_FLANG_ENABLED'], '0')
        self.assertEqual(deploy.call_args.kwargs['env']['P2F_LFORTRAN_ENABLED'], '0')

    def test_flang_failure_does_not_disable_intel(self):
        gnu, intel, flang, _, deploy = self.deploy(flang_error=RuntimeError('Flang verification failed'))
        flang.publish.assert_not_called()
        gnu.publish.assert_called_once_with('gnu-image')
        intel.publish.assert_called_once_with('intel-image')
        self.assertEqual(deploy.call_args.kwargs['env']['P2F_FLANG_ENABLED'], '0')
        self.assertEqual(deploy.call_args.kwargs['env']['P2F_INTEL_ENABLED'], '1')

    def test_without_flang_still_builds_intel(self):
        _, intel, flang, _, deploy = self.deploy(('--without-flang',))
        intel.publish.assert_called_once_with('intel-image')
        flang.build.assert_not_called()
        self.assertEqual(deploy.call_args.kwargs['env']['P2F_FLANG_ENABLED'], '0')

    def test_lfortran_failure_keeps_other_compilers_available(self):
        gnu, intel, flang, lfortran, deploy = self.deploy(lfortran_error=RuntimeError('LFortran failed'))
        lfortran.publish.assert_not_called()
        for compiler in (gnu, intel, flang):
            compiler.publish.assert_called_once()
        self.assertEqual(deploy.call_args.kwargs['env']['P2F_LFORTRAN_ENABLED'], '0')
        self.assertEqual(deploy.call_args.kwargs['env']['P2F_INTEL_ENABLED'], '1')
        self.assertEqual(deploy.call_args.kwargs['env']['P2F_FLANG_ENABLED'], '1')

    def test_without_lfortran_skips_only_lfortran(self):
        _, intel, flang, lfortran, deploy = self.deploy(('--without-lfortran',))
        lfortran.build.assert_not_called()
        intel.publish.assert_called_once()
        flang.publish.assert_called_once()
        self.assertEqual(deploy.call_args.kwargs['env']['P2F_LFORTRAN_ENABLED'], '0')

    def test_gnu_failure_does_not_deploy(self):
        with self.assertRaisesRegex(RuntimeError, 'GNU build failed'):
            self.deploy(gnu_error=RuntimeError('GNU build failed'))

    def test_gnu17_failure_keeps_stable_and_other_compilers(self):
        gnu, intel, _, _, deploy = self.deploy(gnu17_error=RuntimeError('snapshot failed'))
        gnu.publish.assert_called_once()
        intel.publish.assert_called_once()
        deploy.gnu17_image.publish.assert_not_called()
        self.assertEqual(deploy.call_args.kwargs['env']['P2F_GNU17_ENABLED'], '0')
        self.assertNotIn('gfortran17', json.loads(deploy.call_args.kwargs['env']['P2F_COMPILER_VERSIONS']))

    def test_without_gnu17_skips_snapshot(self):
        gnu, _, _, _, deploy = self.deploy(('--without-gnu17',))
        gnu.publish.assert_called_once()
        deploy.gnu17_image.build.assert_not_called()
        self.assertEqual(deploy.call_args.kwargs['env']['P2F_GNU17_ENABLED'], '0')

    def test_version_reader_uses_metadata_not_compiler_and_cleans_up(self):
        sandbox = Mock(returncode=0)
        sandbox.stdout.read.return_value = json.dumps({'version': '\nGNU Fortran (GCC) 15.2.0\nCopyright details\n',
                                                       'standards': {'2008': ['-std=f2008']}})
        with patch.object(xdeploy_service.modal.Sandbox, 'create', return_value=sandbox) as create, \
                patch.object(xdeploy_service.modal.Image, 'from_name'):
            self.assertEqual(xdeploy_service.read_image_metadata(Mock(), 'image', 'gfortran'),
                             {'version': 'GNU Fortran (GCC) 15.2.0', 'standards': {'2008': ['-std=f2008']}})
        self.assertIn('manifest.json', create.call_args.args[2])
        self.assertNotIn('--version', create.call_args.args[2])
        sandbox.terminate.assert_called_once()

    def test_coarray_probe_uses_job_isolation_and_filters_untrusted_flags(self):
        sandbox = Mock(returncode=0)
        sandbox.stdout.read.return_value = '{"1":["-fcoarray=single"],"2":["-fcoarray=lib"],"4":["untrusted"]}'
        with patch.object(xdeploy_service.modal.Sandbox, 'create', return_value=sandbox) as create, \
                patch.object(xdeploy_service.modal.Image, 'from_name'):
            self.assertEqual(xdeploy_service.read_coarray_support(Mock(), 'image', 'gfortran'),
                             {'1': ['-fcoarray=single'], '2': ['-fcoarray=lib']})
        self.assertEqual(create.call_args.kwargs['runtime'], 'gvisor')
        self.assertTrue(create.call_args.kwargs['block_network'])
        self.assertEqual(create.call_args.kwargs['secrets'], [])
        self.assertEqual(create.call_args.kwargs['cpu'], (0.5, 1.0))
        sandbox.terminate.assert_called_once()

    def test_coarray_probe_failure_does_not_disable_normal_compilation(self):
        gnu, _, _, _, deploy = self.deploy(coarray_error=RuntimeError('Shared memory unavailable'))
        gnu.publish.assert_called_once()
        self.assertEqual(json.loads(deploy.call_args.kwargs['env']['P2F_COMPILER_COARRAYS']), {})
        self.assertIn('gfortran', json.loads(deploy.call_args.kwargs['env']['P2F_COMPILER_VERSIONS']))

    def test_intel_probe_uses_network_blocked_vm(self):
        sandbox = Mock(returncode=0)
        sandbox.stdout.read.return_value = '{"2":["-coarray=shared","-coarray-num-images=2"]}'
        with patch.object(xdeploy_service.modal.Sandbox, 'create', return_value=sandbox) as create, \
                patch.object(xdeploy_service.modal.Image, 'from_name'):
            result = xdeploy_service.read_coarray_support(Mock(), 'image', 'ifx')
        self.assertIn('2', result)
        self.assertEqual(create.call_args.kwargs['runtime'], 'vm')
        self.assertTrue(create.call_args.kwargs['block_network'])
        self.assertEqual(create.call_args.kwargs['secrets'], [])
        self.assertEqual(create.call_args.kwargs['volumes'], {})
        sandbox.terminate.assert_called_once()

    def test_version_reader_failure_still_cleans_up(self):
        sandbox = Mock(returncode=1)
        with patch.object(xdeploy_service.modal.Sandbox, 'create', return_value=sandbox), \
                patch.object(xdeploy_service.modal.Image, 'from_name'):
            with self.assertRaisesRegex(RuntimeError, 'metadata reader failed'):
                xdeploy_service.read_image_metadata(Mock(), 'image', 'gfortran')
        sandbox.terminate.assert_called_once()

    def test_missing_versions_do_not_disable_compilers_or_preserve_stale_metadata(self):
        with patch.dict(os.environ, {'P2F_COMPILER_VERSIONS': '{"gfortran":"old"}'}):
            _, _, _, _, deploy = self.deploy(version_error=RuntimeError('metadata unavailable'))
        env = deploy.call_args.kwargs['env']
        self.assertEqual(json.loads(env['P2F_COMPILER_VERSIONS']), {})
        self.assertEqual(json.loads(env['P2F_COMPILER_STANDARDS']), {})
        self.assertEqual(env['P2F_INTEL_ENABLED'], '1')
        self.assertEqual(env['P2F_FLANG_ENABLED'], '1')
        self.assertEqual(env['P2F_LFORTRAN_ENABLED'], '1')
