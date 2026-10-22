"""Check optional runtime installation and linking without downloading or building."""
from contextlib import redirect_stdout
from io import BytesIO, StringIO
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest.mock import patch

import compiler_options
import xcompile_fortran
import xinstall_caffeine as installer


class CaffeineTests(unittest.TestCase):
    def test_gnu_shared_library_is_linked_after_source_only_for_multiple_images(self):
        for compiler in ('gfortran', 'gfortran17'):
            self.assertEqual(compiler_options.coarray_link_flags(compiler, 1), [])
            self.assertEqual(compiler_options.coarray_link_flags(compiler, 2), ['-lcaf_shmem'])
            self.assertEqual(compiler_options.coarray_link_flags(compiler, 4), ['-lcaf_shmem'])
        arguments = ['compile', '--runtime', '.', '--compiler', 'gfortran',
                     '--user-flags', '["-fcoarray=lib"]', '--coarray-runtime', 'gfortran',
                     '--coarray-images', '2']
        with patch.object(Path, 'read_text', return_value='program main\nend\n'), \
                patch.object(sys, 'argv', arguments), \
                patch.object(xcompile_fortran.subprocess, 'run', return_value=SimpleNamespace(returncode=0)) as run, \
                redirect_stdout(StringIO()):
            self.assertEqual(xcompile_fortran.main(), 0)
        command = run.call_args.args[0]
        self.assertEqual(command[-1], '-lcaf_shmem')
        self.assertLess(command.index('input_p.f90'), command.index('-lcaf_shmem'))

    def test_installer_uses_verified_archive_and_rejects_changed_layout(self):
        source = ('GASNET_VERSION="stable"\nGASNET_SOURCE_URL="https://moving.example/archive"\n'
                  '  APPEND_CFLAGS+=-I$($FC --print-c-include-dir)\n')
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / 'gasnet.tar.gz'
            pinned = installer.pinned_installer(source, archive)
            self.assertNotIn('stable', pinned)
            self.assertIn(archive.as_uri(), pinned)
            self.assertIn('APPEND_CFLAGS+=" -I', pinned)
            with self.assertRaises(RuntimeError):
                installer.pinned_installer(source + 'GASNET_VERSION="other"\n', archive)
            with patch.object(installer.urllib.request, 'urlopen', return_value=BytesIO(b'tampered')):
                with self.assertRaisesRegex(RuntimeError, 'checksum'):
                    installer.download_gasnet(archive)
            self.assertFalse(archive.exists())

    def test_failed_install_clears_readiness_without_disabling_compiler(self):
        with tempfile.TemporaryDirectory() as directory:
            prefix = Path(directory) / 'flang'
            prefix.mkdir()
            marker = prefix / 'link-flags.json'
            marker.write_text('{"flags": ["stale"]}')
            with patch.object(installer, 'RUNTIME_ROOT', Path(directory)), \
                    patch.object(installer, 'build', side_effect=RuntimeError('build failed')), \
                    patch.object(sys, 'argv', ['installer', '--compiler', 'flang']), \
                    redirect_stdout(StringIO()) as output:
                installer.main()
            self.assertFalse(marker.exists())
            self.assertIn('ordinary compilation remains enabled', output.getvalue())

    def test_caffeine_libraries_follow_user_objects_and_are_absent_when_off(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for compiler in ('flang', 'lfortran'):
                prefix = root / compiler
                prefix.mkdir()
                libraries = ['-L' + str(prefix), '-lcaffeine-smp-seq', '-lgasnet-smp-seq', '-lpthread']
                (prefix / 'link-flags.json').write_text(json.dumps({'flags': libraries}))
                # Use real metadata reads, with only the submitted source mocked.
                original_read = Path.read_text
                def read(path, *args, **kwargs):
                    return 'program main\nend\n' if path.name == 'input_p.f90' else original_read(path, *args, **kwargs)
                for enabled in (False, True):
                    arguments = ['compile', '--runtime', '.', '--compiler', compiler]
                    if enabled:
                        arguments += ['--coarray-runtime', compiler]
                    with patch.object(compiler_options, 'COARRAY_RUNTIME_ROOT', root), \
                            patch.object(Path, 'read_text', read), patch.object(sys, 'argv', arguments), \
                            patch.object(xcompile_fortran.subprocess, 'run', return_value=SimpleNamespace(returncode=0)) as run, \
                            redirect_stdout(StringIO()):
                        self.assertEqual(xcompile_fortran.main(), 0)
                    command = run.call_args.args[0]
                    if enabled:
                        self.assertEqual(command[-len(libraries):], libraries)
                        self.assertLess(command.index('input_p.f90'), command.index('-lcaffeine-smp-seq'))
                    else:
                        self.assertNotIn('-lcaffeine-smp-seq', command)
            with patch.object(compiler_options, 'COARRAY_RUNTIME_ROOT', root / 'missing'):
                with self.assertRaisesRegex(RuntimeError, 'unavailable'):
                    compiler_options.coarray_link_flags('flang')


if __name__ == '__main__':
    unittest.main()
