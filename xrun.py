"""Serve the execution playground for trusted local use (never a public sandbox)."""
import argparse
import codeop
from dataclasses import dataclass, field
import hashlib
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import zipfile

ROOT = Path(__file__).resolve().parent
MAX_SOURCE = 100_000
MAX_OUTPUT = 200_000
EDIT_MODES = {'fortran-edit', 'both-edit', 'compare-edit'}
COMPILE_MODES = {'fortran', 'both', 'compare'} | EDIT_MODES
MODES = {"translate", "python", "fortran", "both", "compare"} | EDIT_MODES
# Apply to helper compilation as well as generated source via upstream --compiler.
DEFAULT_COMPILER = "gfortran -ffree-line-length-none"
DEFAULT_LFORTRAN = ('lfortran --no-style-suggestions --no-color --implicit-interface '
                    '--separate-compilation --legacy-array-sections')
COMPILERS = {"gfortran", "ifx", "flang", "lfortran"}


def helper_identity(runtime, command):
    """Fingerprint sources and the exact compiler/options used for helpers."""
    version = subprocess.run(shlex.split(command) + ['--version'], capture_output=True,
                             text=True, check=True, timeout=15)
    return {'command': command, 'version': version.stdout + version.stderr,
            'sources': {name: hashlib.sha256((runtime / name).read_bytes()).hexdigest()
                        for name in ('python.f90', 'lapack_d.f90')}}


def seed_helper_cache(runtime, job, name, command):
    """Copy verified image artifacts into a private job; otherwise compile normally."""
    cache = runtime / 'precompiled' / name
    try:
        manifest = json.loads((cache / 'manifest.json').read_text(encoding='utf-8'))
        if manifest['identity'] != helper_identity(runtime, command):
            return False
        artifacts = manifest['artifacts']
        if not {'python.o', 'lapack_d.o', 'python.o.flags', 'lapack_d.o.flags'} <= artifacts.keys():
            return False
        for filename, digest in artifacts.items():
            if Path(filename).name != filename or '\\' in filename:
                return False
            if hashlib.sha256((cache / filename).read_bytes()).hexdigest() != digest:
                return False
        for filename in artifacts:
            # copyfile gives objects current timestamps for upstream's source-mtime check.
            shutil.copyfile(cache / filename, job / filename)
        return True
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        # Remove only cache artifacts we may have copied, not submitted source.
        for path in job.iterdir():
            if path.suffix in {'.o', '.mod', '.smod', '.flags'}:
                path.unlink(missing_ok=True)
        return False


def compiler_command(name, default=DEFAULT_COMPILER):
    """Map a browser choice to a trusted command, never accept browser flags."""
    if name == "gfortran":
        return default
    if name == "ifx":
        # Hosted wrapper initializes Intel's library/tool environment.
        return "p2f-ifx" if shutil.which("p2f-ifx") else "ifx"
    if name == "flang":
        # Hosted image pins LLVM 21; allow normal local LLVM installations too.
        return next((exe for exe in ('flang-21', 'flang', 'flang-new') if shutil.which(exe)), 'flang-21')
    if name == "lfortran":
        return DEFAULT_LFORTRAN
    raise ValueError("Choose GNU Fortran, Intel Fortran, LLVM Flang, or LFortran.")


def available_compilers(default=DEFAULT_COMPILER):
    available = []
    for name in ("gfortran", "ifx", "flang", "lfortran"):
        if shutil.which(shlex.split(compiler_command(name, default))[0]):
            available.append(name)
    return available


def unpack_runtime(destination):
    """Use exactly the same verified upstream bundle as the browser playground."""
    vendor = ROOT / "site" / "vendor"
    manifest = json.loads((vendor / "manifest.json").read_text(encoding="utf-8"))
    pin = json.loads((ROOT / "upstream.json").read_text(encoding="utf-8"))
    if any(manifest[key] != pin[key] for key in ("repository", "commit", "pyodide")):
        raise ValueError("Vendor bundle differs from upstream.json; run python xvendor.py.")
    archive = (vendor / "upstream.zip").read_bytes()
    if hashlib.sha256(archive).hexdigest() != manifest["bundle_sha256"]:
        raise ValueError("Upstream bundle checksum mismatch")
    import io
    with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
        for name in bundle.namelist():
            if Path(name).name != name or "\\" in name:
                raise ValueError("Unexpected bundled path")
            (destination / name).write_bytes(bundle.read(name))
    return manifest


def stop_process(process):
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       creationflags=subprocess.CREATE_NO_WINDOW, check=False)
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def run_command(command, cwd, cancel, timeout):
    """Bound captured output while draining both pipes; stop the entire process tree."""
    started = time.perf_counter()
    options = {"creationflags": subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
    result = {"ok": False, "stdout": "", "stderr": "", "seconds": 0.0}
    if cancel.is_set():
        return {**result, "stderr": "Cancelled.\n"}
    try:
        process = subprocess.Popen(command, cwd=cwd, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"}, **options)
    except OSError as error:
        return {**result, "stderr": str(error), "seconds": time.perf_counter() - started}
    buffers = [bytearray(), bytearray()]
    overflow = threading.Event()

    def read(pipe, buffer):
        with pipe:
            while chunk := pipe.read1(4096):
                available = MAX_OUTPUT - len(buffer)
                buffer.extend(chunk[:max(0, available)])
                if len(chunk) > available:
                    overflow.set()

    readers = [threading.Thread(target=read, args=(pipe, buffer), daemon=True)
               for pipe, buffer in zip((process.stdout, process.stderr), buffers)]
    for reader in readers:
        reader.start()
    reason = ""
    # Continue watching inherited pipes even if the immediate parent exits.
    while process.poll() is None or any(reader.is_alive() for reader in readers):
        if cancel.is_set():
            reason = "Cancelled."
        elif overflow.is_set():
            reason = "Output limit exceeded."
        elif time.perf_counter() - started >= timeout:
            reason = f"Timed out after {timeout:g} seconds."
        if reason:
            stop_process(process)
            break
        time.sleep(0.03)
    process.wait()
    for reader in readers:
        reader.join(timeout=2)
    if not reason and overflow.is_set():
        reason = "Output limit exceeded."
    result.update(ok=process.returncode == 0 and not reason, exit_code=process.returncode,
                  stdout=buffers[0].decode("utf-8", errors="replace"),
                  stderr=buffers[1].decode("utf-8", errors="replace") + ("\n" + reason if reason else ""),
                  seconds=time.perf_counter() - started)
    return result


def compare_outputs(left, right, tolerance=1e-10):
    """Compare whitespace-separated output, allowing small numerical differences."""
    import math
    a, b = left.split(), right.split()
    if len(a) != len(b):
        return False
    for x, y in zip(a, b):
        if x == y:
            continue
        try:
            nx, ny = float(x.replace("D", "e").replace("d", "e")), float(y.replace("D", "e").replace("d", "e"))
            if not (math.isclose(nx, ny, rel_tol=tolerance, abs_tol=tolerance) or math.isnan(nx) and math.isnan(ny)):
                return False
        except ValueError:
            return False
    return True


def execute(runtime, source, mode, cancel, compiler=DEFAULT_COMPILER, timeout=30, automatic=False,
            compiler_name="gfortran", fortran_source=None):
    started = time.perf_counter()
    result = {"ok": False, "fortran": "", "mode": mode, "seconds": 0.0,
              "compiler": compiler_name}
    command_text = compiler_command(compiler_name, compiler)
    if mode in COMPILE_MODES and not shutil.which(shlex.split(command_text)[0]):
        return {**result, "error": f"{compiler_name} is unavailable in this execution environment. "
                "Choose GNU Fortran or ask the service owner to install the selected compiler."}
    if mode in EDIT_MODES and (not isinstance(fortran_source, str) or not fortran_source.strip()):
        return {**result, 'error': 'Enter Fortran code to compile.'}
    if automatic and mode not in EDIT_MODES:
        try:
            if codeop.compile_command(source, symbol="exec") is None:
                return {**result, "syntaxStatus": "incomplete"}
        except (SyntaxError, ValueError, OverflowError):
            return {**result, "syntaxStatus": "invalid"}
    with tempfile.TemporaryDirectory(prefix="p2f_execution_") as directory:
        job = Path(directory)
        ft = job / "fortran"
        py = job / "python"
        ft.mkdir()
        py.mkdir()
        (ft / "input.py").write_text(source, encoding="utf-8")
        (py / "input.py").write_text(source, encoding="utf-8")
        if mode in EDIT_MODES:
            (ft / 'input_p.f90').write_text(fortran_source, encoding='utf-8')
            result['fortran'] = fortran_source
            result['precompiled_helpers'] = seed_helper_cache(runtime, ft, compiler_name, command_text)
            command = [sys.executable, str(ROOT / 'xcompile_fortran.py'), '--runtime', str(runtime),
                       '--compiler', command_text]
            result['build'] = run_command(command, ft, cancel, 180)
        elif mode != "python":
            command = [sys.executable, str(runtime / "xp2f.py"), "input.py", "--flat", "--out", "input_p.f90"]
            if mode != "translate":
                result['precompiled_helpers'] = seed_helper_cache(runtime, ft, compiler_name, command_text)
                command += ["--compile", "--compiler", command_text]
            result["build"] = run_command(command, ft, cancel, 180)
            output = ft / "input_p.f90"
            if output.exists():
                result["fortran"] = output.read_text(encoding="utf-8")
        if mode in {"python", "both", "compare", 'both-edit', 'compare-edit'}:
            result["python"] = run_command([sys.executable, "input.py"], py, cancel, timeout)
        if mode in COMPILE_MODES and result["build"]["ok"]:
            # The pinned upstream CLI uses .exe on every platform.
            exe = ft / "input_p.exe"
            result["execution"] = run_command([str(exe)], ft, cancel, timeout)
        stages = [result[key]["ok"] for key in ("build", "python", "execution") if key in result]
        result["ok"] = bool(stages) and all(stages) and not cancel.is_set()
        if mode in {'compare', 'compare-edit'} and result["ok"]:
            result["matches"] = compare_outputs(result["python"]["stdout"], result["execution"]["stdout"])
            result["ok"] = result["matches"]
    result["seconds"] = time.perf_counter() - started
    return result


@dataclass
class Job:
    cancel: threading.Event = field(default_factory=threading.Event)
    result: dict | None = None
    finished: float | None = None


class ExecutionServer(ThreadingHTTPServer):
    def __init__(self, address, runtime, manifest, compiler, timeout):
        super().__init__(address, Handler)
        self.runtime, self.manifest = runtime, manifest
        self.compiler, self.timeout = compiler, timeout
        self.token = secrets.token_urlsafe(32)
        self.jobs = {}
        self.lock = threading.Lock()

    def submit(self, payload):
        with self.lock:
            self.jobs = {key: job for key, job in self.jobs.items()
                         if job.finished is None or time.monotonic() - job.finished < 300}
            if sum(job.result is None for job in self.jobs.values()) >= 2:
                return None
            identifier = secrets.token_urlsafe(24)
            job = self.jobs[identifier] = Job()

        def work():
            try:
                result = execute(self.runtime, payload["source"], payload["mode"], job.cancel,
                                 self.compiler, self.timeout, payload.get("automatic", False),
                                 compiler_name=payload.get("compiler", "gfortran"),
                                 fortran_source=payload.get('fortran_source'))
            except Exception as error:
                result = {"ok": False, "error": str(error)}
            with self.lock:
                job.result = {**result, "commit": self.manifest["commit"]}
                job.finished = time.monotonic()
        threading.Thread(target=work, daemon=True).start()
        return identifier


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT / "site"), **kwargs)

    def allowed(self, token=False):
        host = self.headers.get("Host", "")
        hosts = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
        origin = self.headers.get("Origin")
        if host not in hosts or origin is not None and origin != f"http://{host}":
            self.reply(403, {"error": "Only the local playground origin is allowed."})
            return False
        if token and not secrets.compare_digest(self.headers.get("X-P2F-Token", ""), self.server.token):
            self.reply(403, {"error": "Reconnect to the execution service."})
            return False
        return True

    def reply(self, status, payload):
        content = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self):
        if not self.allowed():
            return
        if self.path == "/api/session":
            self.reply(200, {"token": self.server.token, "commit": self.server.manifest["commit"],
                             "timeout": self.server.timeout, "compiler": self.server.compiler,
                             "compilers": available_compilers(self.server.compiler)})
        elif self.path.startswith("/api/jobs/"):
            if not self.allowed(token=True):
                return
            with self.server.lock:
                job = self.server.jobs.get(self.path.removeprefix("/api/jobs/"))
                payload = {"state": "done", "result": job.result} if job and job.result is not None else {"state": "running"}
            self.reply(200 if job else 404, payload if job else {"error": "Job expired or not found."})
        elif self.path.startswith("/api/"):
            self.reply(404, {"error": "Unknown endpoint"})
        else:
            super().do_GET()

    def do_POST(self):
        if not self.allowed(token=True):
            return
        if self.headers.get("Content-Type") != "application/json":
            self.reply(415, {"error": "Expected application/json"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 1_300_000:
                raise ValueError("Request exceeds the input limit")
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError("Expected a JSON object")
        except (ValueError, json.JSONDecodeError) as error:
            self.reply(400, {"error": str(error)})
            return
        if self.path == "/api/jobs":
            source, mode = payload.get("source", ''), payload.get("mode")
            choice = payload.get("compiler", "gfortran")
            ft_source = payload.get('fortran_source')
            try:
                valid_source = isinstance(source, str) and len(source.encode()) <= MAX_SOURCE
                valid_ft = isinstance(ft_source, str) and bool(ft_source.strip()) and len(ft_source.encode()) <= MAX_SOURCE
            except UnicodeError:
                valid_source = valid_ft = False
            if (not valid_source or (not source.strip() and mode != 'fortran-edit')
                    or not isinstance(mode, str) or mode not in MODES
                    or (mode in EDIT_MODES and (not valid_ft or payload.get('automatic', False)))
                    or not isinstance(choice, str) or choice not in COMPILERS
                    or not isinstance(payload.get("automatic", False), bool)):
                self.reply(400, {"error": "Enter valid source (up to 100 KB per language) and a valid operation."})
                return
            payload['source'] = source
            identifier = self.server.submit(payload)
            self.reply(202 if identifier else 429, {"id": identifier} if identifier else {"error": "Two jobs are already active; stop one or wait."})
        elif self.path.startswith("/api/jobs/") and self.path.endswith("/cancel"):
            identifier = self.path[len("/api/jobs/"):-len("/cancel")]
            with self.server.lock:
                job = self.server.jobs.get(identifier)
                if job:
                    job.cancel.set()
            self.reply(200 if job else 404, {"cancelled": bool(job)})
        else:
            self.reply(404, {"error": "Unknown endpoint"})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--compiler", default=DEFAULT_COMPILER,
                        help="Compiler command including flags (default: %(default)s)")
    parser.add_argument("--timeout", type=float, default=30, help="Maximum seconds per program run")
    options = parser.parse_args()
    if not 0 < options.timeout <= 300:
        parser.error("--timeout must be greater than zero and at most 300")
    with tempfile.TemporaryDirectory(prefix="p2f_pinned_runtime_") as directory:
        runtime = Path(directory)
        try:
            manifest = unpack_runtime(runtime)
        except (OSError, ValueError) as error:
            parser.exit(1, f"{error}\nRun python xvendor.py to build the pinned bundle.\n")
        server = ExecutionServer(("127.0.0.1", options.port), runtime, manifest, options.compiler, options.timeout)
        print(f"Open http://127.0.0.1:{server.server_port}/run/ (Ctrl+C to stop).", flush=True)
        print("Trusted local use only: submitted programs run with your account's permissions.", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            with server.lock:
                for job in server.jobs.values():
                    job.cancel.set()
            # Let jobs kill their processes and remove their temporary files.
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                with server.lock:
                    if all(job.result is not None for job in server.jobs.values()):
                        break
                time.sleep(0.05)
            server.server_close()


if __name__ == "__main__":
    main()
