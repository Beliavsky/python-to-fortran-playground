import ast
import importlib.util
from pathlib import Path
import sys
import shutil
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location('playground_annotations', ROOT / 'site' / 'annotations.py')
annotations = importlib.util.module_from_spec(spec)
spec.loader.exec_module(annotations)
from translation_options import validate_options, cli_options, strip_fortran_comments
import xrun


class SourceTests(unittest.TestCase):
    def test_annotation_headers_are_preserved(self):
        sources = [
            'def f(x): return x + 1\nf(3)\n',
            'def f(x, /, *, y=2):\n    return x+y\nf(1, y=4)\n',
            'def f(\n    x, # retained\n    y=3,\n):\n    return x+y\nf(1, 2)\n',
            'def f(café): return café\nf(2.0)\n',
            'def f(x: float, y): return x+y\nf(1.0, 2.0)\n',
            'def f(x): return x\r\nf(2)\r\n',
        ]
        for source in sources:
            with self.subTest(source=source):
                result = annotations.annotate(source)
                self.assertGreater(result['count'], 0)
                self.assertIn('return ', result['annotated'])
                ast.parse(result['annotated'])
                if '# retained' in source:
                    self.assertIn('# retained', result['annotated'])
                if '\r\n' in source:
                    self.assertEqual(result['annotated'].count('\r\n'), source.count('\r\n'))

    def test_arrays_conflicts_and_unsupported_cases(self):
        source = 'import numpy as np\ndef f(a): return a\nf(np.zeros((2,3)))\n'
        self.assertIn("a: 'float[:,:]'", annotations.annotate(source)['annotated'])
        for source in (
            'def f(x): return x\nf(1)\nf(1.0)\n',
            'def f(x): return x\nf(1)\nf(unknown)\n',
            'def f(x): return x\n',
            'async def f(x): return x\nf(2)\n',
            '@decorate\ndef f(x): return x\nf(2)\n',
            'def f(*args): return args\nf(1)\n',
            'def f(x): return x\ndef g(x): return f(x)\ng(1)\n',
            'import numpy as np\ndef f(x): return x\nf(np.array(2.0))\nf(np.zeros(3))\n',
        ):
            result = annotations.annotate(source)
            # The nested caller example may annotate g, but must not guess f.
            self.assertNotIn('def f(x:', result['annotated'])
        explicit = 'def f(x: "float[:]"): return x\nf(1)\n'
        self.assertEqual(annotations.annotate(explicit)['annotated'], explicit)

    def test_never_executes_source_and_errors_are_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / 'wrong.txt'
            source = f"open({str(marker)!r}, 'w').write('wrong')\ndef f(x): return x\nf(2)\n"
            annotations.annotate(source)
            self.assertFalse(marker.exists())
            result = xrun.execute(Path(directory), source, 'annotate', threading.Event())
            self.assertTrue(result['ok'], result)
            self.assertIn('x: int', result['annotated'])
            self.assertFalse(marker.exists())
        self.assertIn('false', annotations.annotate_json('def f(:'))

    def test_translation_option_allowlist(self):
        self.assertEqual(cli_options({'int_kind': 'int64', 'preserve_comments': False}), ['--int-kind', 'int64'])
        for invalid in ([], '-O3', {'int_kind': []}, {'int_kind': 'real64'}, {'preserve_comments': 1}, {'flags': '--compile'}):
            with self.assertRaises(ValueError):
                validate_options(invalid)

    def test_fortran_comment_removal_preserves_strings_and_directives(self):
        ft = "! comment\nprint *, 'hello! ''quoted!''' ! trailing\n!$omp parallel\n!dir$ something\n"
        self.assertEqual(strip_fortran_comments(ft), "print *, 'hello! ''quoted!'''\n!$omp parallel\n!dir$ something\n")
        ft = "print *, 'hello &\n & !world' ! remove\n"
        self.assertEqual(strip_fortran_comments(ft), "print *, 'hello &\n & !world'\n")

    @unittest.skipUnless(shutil.which('gfortran'), 'GNU compiler required')
    def test_hosted_style_translation_flags_compile_and_reset(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory)
            xrun.unpack_runtime(runtime)
            source = '# KEEP_THIS_COMMENT\nn = 3\nprint(n)\n'
            result = xrun.execute(runtime, source, 'compare', threading.Event(),
                translation_options={'int_kind': 'int64', 'preserve_comments': False})
            self.assertTrue(result['ok'], result)
            self.assertIn('int64', result['fortran'])
            self.assertNotIn('KEEP_THIS_COMMENT', result['fortran'])
            result = xrun.execute(runtime, source, 'translate', threading.Event())
            self.assertTrue(result['ok'], result)
            self.assertIn('KEEP_THIS_COMMENT', result['fortran'])
            self.assertNotIn('ikind', result['fortran'])



if __name__ == '__main__':
    unittest.main()
