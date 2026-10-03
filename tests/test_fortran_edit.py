"""Direct Fortran compilation must not translate Python or alter manual source."""
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import xrun
from xcompile_fortran import uses_python_mod
from xprecompile import precompile


class FortranEditTests(unittest.TestCase):
    def test_helper_import_detection(self):
        for source in ('use python_mod, only: mean', 'USE :: python_mod',
                       'use, non_intrinsic :: python_mod', 'use &\n & python_mod',
                       'program custom; use python_mod, only: mean'):
            self.assertTrue(uses_python_mod(source), source)
        for source in ('! use python_mod', 'use my_python_mod', "print *, 'use python_mod'"):
            self.assertFalse(uses_python_mod(source), source)

    @unittest.skipUnless(shutil.which('gfortran'), 'gfortran required')
    def test_standalone_compare_and_compile_failure(self):
        ft = 'program custom\nprint *, 42\nend program custom\n'
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory)
            xrun.unpack_runtime(runtime)
            result = xrun.execute(runtime, '', 'fortran-edit', threading.Event(), fortran_source=ft)
            self.assertTrue(result['ok'], result)
            self.assertEqual(result['fortran'], ft)
            self.assertEqual(result['execution']['stdout'].strip(), '42')
            self.assertNotIn('python', result)
            self.assertNotIn('wrote input_p.f90', result['build']['stdout'])
            result = xrun.execute(runtime, 'print(42)', 'compare-edit', threading.Event(), fortran_source=ft)
            self.assertTrue(result['matches'], result)
            result = xrun.execute(runtime, 'print(43)', 'compare-edit', threading.Event(), fortran_source=ft)
            self.assertFalse(result['matches'], result)
            result = xrun.execute(runtime, '', 'fortran-edit', threading.Event(), fortran_source='not fortran')
            self.assertFalse(result['build']['ok'], result)
            self.assertNotIn('execution', result)

    @unittest.skipUnless(shutil.which('gfortran'), 'gfortran required')
    def test_existing_helpers_link(self):
        ft = '''program custom
use, intrinsic :: iso_fortran_env, only: real64
use python_mod, only: mean
implicit none
real(real64) :: x(3) = [1.0_real64, 2.0_real64, 3.0_real64]
print *, mean(x)
end program custom
'''
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory)
            xrun.unpack_runtime(runtime)
            precompile(runtime, 'gfortran')
            result = xrun.execute(runtime, '', 'fortran-edit', threading.Event(), fortran_source=ft)
            self.assertTrue(result['ok'], result)
            self.assertEqual(float(result['execution']['stdout']), 2.0)
            self.assertTrue(result['precompiled_helpers'])
            self.assertNotIn('Build helper:', result['build']['stdout'])
            self.assertIn('python.o', result['build']['stdout'])
            self.assertIn('lapack_d.o', result['build']['stdout'])


if __name__ == '__main__':
    unittest.main()
