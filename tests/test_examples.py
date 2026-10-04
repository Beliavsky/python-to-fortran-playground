"""Every built-in example must run with the actual pinned GNU backend."""
import ast
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import xrun
from xprecompile import precompile


def catalog():
    result = subprocess.run(['node', '--input-type=module', '-e',
                             "import {pythonExamples} from './site/examples.mjs'; console.log(JSON.stringify(pythonExamples));"],
                            cwd=ROOT, capture_output=True, text=True, encoding='utf-8', timeout=30, check=True)
    return json.loads(result.stdout)


class CatalogTests(unittest.TestCase):
    def test_self_contained_small_examples(self):
        examples = catalog()
        self.assertEqual(len(examples), 20)
        for name, item in examples.items():
            with self.subTest(name=name):
                tree = ast.parse(item['source'])
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        self.assertTrue(all(alias.name in {'numpy', 'statistics', 'random'} for alias in node.names))
                    if isinstance(node, ast.ImportFrom):
                        self.fail('Built-in examples should not need user modules')
                    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                        self.assertNotIn(node.func.id, {'open', 'input', 'exec', 'eval', '__import__'})


@unittest.skipUnless(shutil.which('gfortran'), 'gfortran required')
class ExampleExecutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        cls.runtime = Path(cls.temp.name)
        xrun.unpack_runtime(cls.runtime)
        precompile(cls.runtime, 'gfortran')

    def test_pinned_examples_compile_and_run(self):
        for name, item in catalog().items():
            with self.subTest(name=name):
                mode = 'both' if item['random'] else 'compare'
                result = xrun.execute(self.runtime, item['source'], mode, threading.Event())
                self.assertTrue(result['ok'], result)
                for stage in ('build', 'python', 'execution'):
                    self.assertTrue(result[stage]['ok'], result)
                if not item['random']:
                    self.assertTrue(result['matches'], result)
                print(f'PASS example {name}: ' + ('both run (random)' if item['random'] else 'outputs match'), flush=True)


if __name__ == '__main__':
    unittest.main()
