"""Real pinned-transpiler, compiler, cancellation, and HTTP boundary checks."""
import json
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import xrun


class ExecutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.runtime = Path(cls.tmp.name)
        cls.manifest = xrun.unpack_runtime(cls.runtime)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    @unittest.skipUnless(shutil.which("gfortran"), "gfortran required")
    def test_pinned_python_and_fortran_match(self):
        for source in ("total = 0\nfor i in range(1, 11):\n    total += i * i\nprint(total)\n",
                       # mean/std require python.f90: np.sum alone is intrinsic
                       # and missed helper compilation failures (long lines).
                       "import numpy as np\nx = np.array([1.0, 2.0, 3.0])\nprint(np.sum(x*x), np.mean(x), np.std(x))\n"):
            with self.subTest(source=source):
                result = xrun.execute(self.runtime, source, "compare", threading.Event())
                self.assertTrue(result["ok"], result)
                self.assertTrue(result["matches"])
                self.assertIn("program input", result["fortran"])
                for stage in ("build", "python", "execution"):
                    self.assertGreater(result[stage]["seconds"], 0)
                self.assertIn("-ffree-line-length-none", result["build"]["stdout"])

    def test_failures_incomplete_input_and_translation_never_execute(self):
        result = xrun.execute(self.runtime, "raise RuntimeError('test error')", "python", threading.Event())
        self.assertFalse(result["ok"])
        self.assertIn("test error", result["python"]["stderr"])
        result = xrun.execute(self.runtime, "def f():", "translate", threading.Event(), automatic=True)
        self.assertEqual(result["syntaxStatus"], "incomplete")
        marker = self.runtime / "must_not_exist.txt"
        source = f"open({str(marker)!r}, 'w').write('wrong')"
        xrun.execute(self.runtime, source, "translate", threading.Event())
        self.assertFalse(marker.exists())

    def test_timeout_cancel_output_limits_and_no_stdin(self):
        for command, timeout, expected in [
            ([sys.executable, "-c", "while True: pass"], 0.2, "Timed out"),
            ([sys.executable, "-c", "print('x' * 500000)"], 5, "Output limit"),
            ([sys.executable, "-c", "input()"], 5, "EOFError"),
        ]:
            result = xrun.run_command(command, self.runtime, threading.Event(), timeout)
            self.assertFalse(result["ok"], result)
            self.assertIn(expected, result["stderr"])
            self.assertLessEqual(len(result["stdout"]), xrun.MAX_OUTPUT)
        cancel = threading.Event()
        timer = threading.Timer(0.2, cancel.set)
        timer.start()
        try:
            result = xrun.run_command([sys.executable, "-c", "while True: pass"], self.runtime, cancel, 10)
            self.assertIn("Cancelled", result["stderr"])
            self.assertLess(result["seconds"], 5)
        finally:
            timer.cancel()

    def test_numeric_comparison(self):
        self.assertTrue(xrun.compare_outputs("14.0\n", "  14.00000000001"))
        self.assertFalse(xrun.compare_outputs("14", "15"))
        self.assertFalse(xrun.compare_outputs("1 2", "1"))
        self.assertFalse(xrun.compare_outputs("hello", "goodbye"))

    def test_compiler_selection_and_unavailable_intel(self):
        self.assertEqual(xrun.compiler_command('gfortran'), xrun.DEFAULT_COMPILER)
        with self.assertRaises(ValueError):
            xrun.compiler_command('ifx -O3')
        with patch('xrun.shutil.which', return_value=None), patch('xrun.run_command') as run:
            result = xrun.execute(self.runtime, 'print(1)', 'fortran', threading.Event(), compiler_name='ifx')
            self.assertFalse(result['ok'])
            self.assertEqual(result['compiler'], 'ifx')
            self.assertIn('unavailable', result['error'])
            run.assert_not_called()

    @unittest.skipUnless(shutil.which('ifx') or shutil.which('p2f-ifx'), 'Intel compiler required')
    def test_intel_compiles_helpers_and_matches_python(self):
        source = 'import numpy as np\nx = np.array([1.0, 2.0, 3.0])\nprint(np.mean(x), np.std(x))\n'
        result = xrun.execute(self.runtime, source, 'compare', threading.Event(), compiler_name='ifx')
        self.assertTrue(result['ok'], result)
        self.assertTrue(result['matches'])
        self.assertEqual(result['compiler'], 'ifx')

    def test_http_requires_local_origin_and_token(self):
        server = xrun.ExecutionServer(("127.0.0.1", 0), self.runtime, self.manifest, "gfortran", 5)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"

        def request(path, data=None, headers=None):
            return urllib.request.urlopen(urllib.request.Request(base + path,
                data=json.dumps(data).encode() if data is not None else None,
                headers=headers or {}), timeout=10)
        try:
            with request("/run/") as response:
                self.assertIn(b"Run Both", response.read())
            with request("/api/session") as response:
                session = json.load(response)
            for headers in ({"Origin": "https://evil.invalid"}, {"Host": "evil.invalid"}):
                with self.assertRaises(urllib.error.HTTPError) as error:
                    request("/api/session", headers=headers)
                self.assertEqual(error.exception.code, 403)
            with self.assertRaises(urllib.error.HTTPError) as error:
                request("/api/jobs", {"source": "print(1)", "mode": "python"}, {"Content-Type": "application/json"})
            self.assertEqual(error.exception.code, 403)
            headers = {"Content-Type": "application/json", "X-P2F-Token": session["token"]}
            for payload in ([], {"source": "print(1)", "mode": []}, {"source": "x" * 100001, "mode": "python"},
                            {"source": "print(1)", "mode": "fortran", "compiler": "ifx -O3"}):
                with self.assertRaises(urllib.error.HTTPError) as error:
                    request("/api/jobs", payload, headers)
                self.assertEqual(error.exception.code, 400)
            with request("/api/jobs", {"source": "while True: pass", "mode": "python"}, headers) as response:
                identifier = json.load(response)["id"]
            with request(f"/api/jobs/{identifier}/cancel", {}, headers) as response:
                self.assertTrue(json.load(response)["cancelled"])
            with request(f"/api/jobs/{identifier}", headers=headers) as response:
                self.assertIn(json.load(response)["state"], ("running", "done"))
        finally:
            for job in server.jobs.values():
                job.cancel.set()
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == "__main__":
    unittest.main()
