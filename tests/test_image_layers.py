"""Verify cache boundaries without building images or using Modal credentials."""
import hashlib
from pathlib import Path
import runpy
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class Image:
    def __init__(self, events=()):
        self.events = events

    def __getattr__(self, method):
        def layer(*args, **kwargs):
            if method == 'add_local_file':
                args = (str(args[1]), hashlib.sha256(Path(args[0]).read_bytes()).hexdigest())
            return Image(self.events + ((method, args, kwargs),))
        return layer


def definitions(changed=None):
    original_read = Path.read_bytes
    def read(path):
        data = original_read(path)
        if changed and path == ROOT / changed:
            return data + b'\n# application update\n'
        return data

    # Decorators are inert; none of the API or sandbox code is called.
    decorator = lambda *args, **kwargs: lambda fn: fn
    fake = SimpleNamespace(
        App=lambda name: SimpleNamespace(function=decorator),
        Dict=SimpleNamespace(from_name=lambda *args, **kwargs: None),
        Image=SimpleNamespace(debian_slim=lambda **kwargs: Image((('debian', (), kwargs),)),
                              micromamba=lambda **kwargs: Image((('conda', (), kwargs),))),
        is_local=lambda: True, concurrent=decorator, asgi_app=decorator)
    with patch.dict(sys.modules, {'modal': fake}), patch.object(Path, 'read_bytes', read):
        return runpy.run_path(str(ROOT / 'xmodal.py'))


class LayerTests(unittest.TestCase):
    def test_ofort_has_no_compiled_helper_dependency(self):
        images = definitions()
        events = str(images['ofort_job_image'].events)
        self.assertNotIn('xbuild_helpers.py', events)
        self.assertNotIn('upstream.zip', events)
        self.assertNotIn('xprecompile.py ofort', events)
        self.assertIn('xverify_ofort.py', events)
        for mode in ('fortran-edit', 'fortran-compile'):
            self.assertEqual(images['job_image_name']({'mode': mode, 'compiler': 'ofort'}), images['OFORT_IMAGE_NAME'])
        self.assertEqual(images['ofort_installed_image'].events,
                         definitions('xrun.py')['ofort_installed_image'].events)
    def test_lfortran_helpers_use_the_execution_defaults(self):
        import xrun
        events = definitions()['lfortran_job_image'].events
        build = next(event for event in events
                     if event[0] == 'run_commands' and 'xbuild_helpers.py' in str(event[1]))
        self.assertIn(xrun.DEFAULT_LFORTRAN, str(build[1]))

    def test_application_edits_do_not_invalidate_toolchains_or_helper_builds(self):
        original = definitions()
        changed = definitions('xrun.py')
        for name in ('gnu_toolchain_image', 'intel_installed_image', 'flang_installed_image', 'lfortran_installed_image'):
            self.assertEqual(original[name].events, changed[name].events, name)
        for name in ('job_image', 'intel_job_image', 'flang_job_image', 'lfortran_job_image'):
            first, second = original[name].events, changed[name].events
            boundary = next(i for i, event in enumerate(first)
                            if event[0] == 'run_commands' and 'xbuild_helpers.py' in str(event[1]))
            self.assertEqual(first[:boundary + 1], second[:boundary + 1], name)
            self.assertNotEqual(first, second, name)
            self.assertIn('--verify-only', str(first))

    def test_formatting_worker_edits_do_not_invalidate_helper_layers(self):
        original, changed = definitions(), definitions('xformat_fortran.py')
        for name in ('job_image', 'intel_job_image', 'flang_job_image', 'lfortran_job_image'):
            first, second = original[name].events, changed[name].events
            boundary = next(i for i, event in enumerate(first)
                            if event[0] == 'run_commands' and 'xbuild_helpers.py' in str(event[1]))
            self.assertEqual(first[:boundary + 1], second[:boundary + 1])
            self.assertEqual(first, second, 'Formatter-only edits must not rebuild compiler images')
        self.assertNotEqual(original['tools_job_image'].events, changed['tools_job_image'].events)

    def test_tools_have_no_compiler_or_bundle(self):
        images = definitions()
        events = images['tools_job_image'].events
        self.assertNotIn('apt_install', [event[0] for event in events])
        self.assertNotIn('micromamba_install', [event[0] for event in events])
        self.assertNotIn('upstream.zip', str(events))
        self.assertNotIn('xbuild_helpers.py', str(events))
        self.assertIn('fortitude-lint==0.9.2', str(events))
        self.assertIn('fprettify==0.3.7', str(events))
        for name in ('job_image', 'intel_job_image', 'flang_job_image', 'lfortran_job_image'):
            self.assertNotIn('fortitude-lint', str(images[name].events))
            self.assertNotIn('fprettify==', str(images[name].events))

    def test_source_tools_always_use_compiler_free_image(self):
        images = definitions()
        route = images['job_image_name']
        for mode in ('format', 'check'):
            for compiler in ('gfortran', 'ifx', 'flang', 'lfortran'):
                self.assertEqual(route({'mode': mode, 'compiler': compiler}), images['TOOLS_IMAGE_NAME'])
        for compiler, image in [('gfortran', 'RUNTIME_IMAGE_NAME'), ('ifx', 'INTEL_IMAGE_NAME'),
                                ('flang', 'FLANG_IMAGE_NAME'), ('lfortran', 'LFORTRAN_IMAGE_NAME')]:
            for mode in ('fortran-edit', 'fortran-compile', 'fortran-run'):
                self.assertEqual(route({'mode': mode, 'compiler': compiler}), images[image])


if __name__ == '__main__':
    unittest.main()
