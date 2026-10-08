"""Check standard automatic allocation without building the large helpers."""
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import xrun


class AllocationTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('lfortran') and
                         (os.name != 'nt' or shutil.which('cl')),
                         'LFortran required; initialize MSVC on Windows')
    def test_initial_allocation_and_resize(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'input.f90'
            source.write_text('''implicit none
integer, allocatable :: v(:)
v = [10, 20, 30]
print *, v
print *, size(v)
v = [40, 50]
print *, v
print *, size(v)
end
''', encoding='utf-8')
            executable = root / ('input.exe' if os.name == 'nt' else 'input')
            build = subprocess.run(shlex.split(xrun.DEFAULT_LFORTRAN) +
                                   [str(source), '-o', str(executable)],
                                   cwd=root, capture_output=True, text=True, timeout=60)
            self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
            for _ in range(3):
                run = subprocess.run([str(executable)], cwd=root,
                                     capture_output=True, text=True, timeout=10)
                self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
                self.assertEqual([int(x) for x in re.findall(r'-?\d+', run.stdout)],
                                 [10, 20, 30, 3, 40, 50, 2])


if __name__ == '__main__':
    unittest.main()
