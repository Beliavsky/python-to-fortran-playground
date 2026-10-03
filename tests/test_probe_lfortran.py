"""Probe/report behavior without LFortran, Modal calls, or account credentials."""
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import xprobe_lfortran


class ProbeTests(unittest.TestCase):
    def exercise(self, fail_helper=False, wrong_output=False):
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory)
            for name in ('python.f90', 'lapack_d.f90'):
                (runtime / name).write_text('! unchanged source\n', encoding='utf-8')

            def command(args, cwd, cancel, timeout):
                result = {'ok': True, 'stdout': '385\n', 'stderr': '', 'seconds': 0.1, 'exit_code': 0}
                if args[0] == 'lfortran' and '-c' in args and args[args.index('-c') + 1].endswith('python.f90') and fail_helper:
                    result.update(ok=False, stderr='unsupported feature', exit_code=1)
                if '--compile' in args:
                    (cwd / 'input_p.f90').write_text('! generated\n', encoding='utf-8')
                if wrong_output and args[0].endswith('input_p.exe'):
                    result['stdout'] = '999\n'
                return result

            with patch('xprobe_lfortran.run_command', side_effect=command):
                report = xprobe_lfortran.probe(runtime)
            for name in ('python.f90', 'lapack_d.f90'):
                self.assertEqual((runtime / name).read_text(encoding='utf-8'), '! unchanged source\n')
                self.assertEqual(report['helpers'][name]['sha256'],
                                 hashlib.sha256((runtime / name).read_bytes()).hexdigest())
            self.assertEqual(set(report['translations']), {'arithmetic', 'NumPy helpers', 'LAPACK'})
            return report

    def test_success_includes_unchanged_source_hashes_and_output_checks(self):
        self.assertTrue(self.exercise()['ready'])

    def test_helper_failure_retains_diagnostics_and_does_not_skip_other_checks(self):
        report = self.exercise(fail_helper=True)
        self.assertFalse(report['ready'])
        self.assertIn('unsupported feature', report['helpers']['python.f90']['stderr'])
        self.assertTrue(report['helpers']['lapack_d.f90']['ok'])

    def test_compilation_alone_is_not_sufficient(self):
        self.assertFalse(self.exercise(wrong_output=True)['ready'])


if __name__ == '__main__':
    unittest.main()
