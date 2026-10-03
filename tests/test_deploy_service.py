"""Deployment orchestration without real Modal calls or account credentials."""
from contextlib import nullcontext
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import xdeploy_service


class DeploymentTests(unittest.TestCase):
    def deploy(self, args=(), intel_error=None, gnu_error=None, flang_error=None, lfortran_error=None):
        gnu, intel, flang, lfortran = Mock(), Mock(), Mock(), Mock()
        gnu.build.return_value = gnu
        intel.build.return_value = intel
        flang.build.return_value = flang
        lfortran.build.return_value = lfortran
        gnu.build.side_effect = gnu_error
        intel.build.side_effect = intel_error
        flang.build.side_effect = flang_error
        lfortran.build.side_effect = lfortran_error
        definitions = SimpleNamespace(ROOT=Path('/repo'), RUNTIME_IMAGE_NAME='gnu-image',
            INTEL_IMAGE_NAME='intel-image', FLANG_IMAGE_NAME='flang-image',
            LFORTRAN_IMAGE_NAME='lfortran-image', job_image=gnu, intel_job_image=intel,
            flang_job_image=flang, lfortran_job_image=lfortran)
        with patch.dict(sys.modules, {'xmodal': definitions}), \
                patch.object(sys, 'argv', ['xdeploy_service.py', *args]), \
                patch.object(xdeploy_service.modal.App, 'lookup'), \
                patch.object(xdeploy_service.modal, 'enable_output', return_value=nullcontext()), \
                patch.object(xdeploy_service.subprocess, 'run') as deploy, \
                patch.dict(os.environ, {'P2F_INTEL_ENABLED': 'unexpected', 'P2F_FLANG_ENABLED': 'unexpected',
                                       'P2F_LFORTRAN_ENABLED': 'unexpected'}):
            xdeploy_service.main()
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

    def test_intel_failure_keeps_gnu_available(self):
        gnu, intel, flang, _, deploy = self.deploy(intel_error=RuntimeError('Intel installation failed'))
        gnu.publish.assert_called_once_with('gnu-image')
        intel.publish.assert_not_called()
        self.assertEqual(deploy.call_args.kwargs['env']['P2F_INTEL_ENABLED'], '0')
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
