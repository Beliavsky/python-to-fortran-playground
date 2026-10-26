"""Plotting keeps working when a compiled executable is run in a fresh directory."""
import base64
import importlib.util
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fortran_plot import valid_png
from xrun import execute, unpack_runtime

SOURCE = '''program p
use iso_fortran_env, only: dp => real64
use pyplot_module, only: pyplot
implicit none
type(pyplot) :: plt
integer status
call plt%initialize(use_oo_api=.true.)
call plt%add_plot([0.0_dp,1.0_dp], [0.0_dp,1.0_dp], label='line', linestyle='b-')
call plt%savefig('line.png', istat=status)
if(status/=0) error stop 'Plot failed'
end program
'''


class PlottingTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('gfortran') and importlib.util.find_spec('matplotlib'), 'GNU and Matplotlib required')
    def test_compile_and_run_again_return_png(self):
        with tempfile.TemporaryDirectory() as temporary:
            runtime = Path(temporary)
            unpack_runtime(runtime)
            compiled = execute(runtime, '', 'fortran-compile', threading.Event(), compiler_name='gfortran',
                               fortran_source=SOURCE, retain_executable=True)
            self.assertTrue(compiled['ok'], compiled)
            self.assertNotIn('plots', compiled)
            result = execute(runtime, '', 'fortran-run', threading.Event(), compiler_name='gfortran',
                             executable=compiled['_artifact'])
            self.assertTrue(result['ok'], result)
            self.assertEqual([p['name'] for p in result['plots']], ['line.png'])
            self.assertTrue(valid_png(base64.b64decode(result['plots'][0]['data'])))


if __name__ == '__main__': unittest.main()
