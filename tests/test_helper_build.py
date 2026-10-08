"""Check independent helper construction and application-only verification."""
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

import xbuild_helpers
import xprecompile
import xrun

ROOT = Path(__file__).resolve().parents[1]


class HelperBuildTests(unittest.TestCase):
    def test_verify_only_does_not_recompile_objects(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory)
            cache = runtime / 'precompiled/gfortran'
            cache.mkdir(parents=True)
            manifest = cache / 'manifest.json'
            manifest.write_text(json.dumps({'identity': {'command': 'gfortran'}, 'artifacts': {'python.o': 'digest'}}))
            with patch.object(sys, 'argv', ['xprecompile.py', 'gfortran', '--runtime', str(runtime), '--verify-only']), \
                    patch.object(xprecompile, 'precompile', side_effect=AssertionError('Helpers recompiled')), \
                    patch.object(xprecompile, 'probe_standards', return_value={'2008': ['-std=f2008']}), \
                    patch.object(xprecompile, 'verify_options') as verify:
                xprecompile.main()
            verify.assert_called_once_with(runtime.resolve(), 'gfortran')
            self.assertEqual(json.loads(manifest.read_text())['artifacts'], {'python.o': 'digest'})

    @unittest.skipUnless(shutil.which('gfortran'), 'GNU Fortran unavailable')
    def test_standalone_builder_produces_reusable_helpers(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for filename in ('upstream.json', 'site/vendor/manifest.json', 'site/vendor/upstream.zip'):
                destination = root / filename
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / filename, destination)
            xbuild_helpers.build(root, 'gfortran', xrun.DEFAULT_COMPILER)
            runtime = root / 'runtime'
            cache = runtime / 'precompiled/gfortran'
            metadata = json.loads((cache / 'manifest.json').read_text())
            self.assertEqual(metadata['identity'], xrun.helper_identity(runtime, xrun.DEFAULT_COMPILER))
            before = {filename: hashlib.sha256((cache / filename).read_bytes()).hexdigest()
                      for filename in metadata['artifacts']}
            result = xrun.execute(runtime, '', 'fortran-edit', threading.Event(), fortran_source=
                'program main\nuse python_mod, only: mean\nimplicit none\n'
                'real(kind(1.0d0)) :: a(3) = [1.0d0, 2.0d0, 3.0d0]\nprint *, mean(a)\nend program main\n')
            self.assertTrue(result['ok'], result)
            self.assertTrue(result['precompiled_helpers'], result)
            self.assertNotIn('Build helper:', result['build']['stdout'])
            self.assertEqual(float(result['execution']['stdout']), 2.0)
            self.assertEqual(before, {filename: hashlib.sha256((cache / filename).read_bytes()).hexdigest()
                                      for filename in metadata['artifacts']})


if __name__ == '__main__':
    unittest.main()
