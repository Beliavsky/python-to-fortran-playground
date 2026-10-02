"""A translation-only entry point shared by browser and smoke tests."""
import contextlib
import io
import copy
import json
from pathlib import Path
import sys
import tempfile

_modules = {}
_containers = (dict, list, set, tuple, bytearray)
# These two lazy caches describe only the pinned, read-only vendored runtime.
# They are not derived from submitted Python. Keep them warm across requests.
_runtime_caches = {'_vendored_purity_registry_cache', '_vendored_dp_returning_registry_cache'}


def _snapshot(namespace):
    memo = {}
    seen = set()
    def preserve_metadata(value):
        if id(value) in seen:
            return
        seen.add(id(value))
        if isinstance(value, dict):
            for key, item in value.items():
                preserve_metadata(key)
                preserve_metadata(item)
        elif isinstance(value, (list, set, tuple)):
            for item in value:
                preserve_metadata(item)
        elif not isinstance(value, bytearray):
            # Functions, classes, regexes and dataclass Field descriptors
            # are code/metadata, not mutable per-translation containers.
            # In particular Field objects cannot safely be deep-copied.
            memo[id(value)] = value
    containers = {key: value for key, value in namespace.items()
                  if isinstance(value, _containers) and key != '__builtins__'}
    preserve_metadata(containers)
    return {**namespace, **copy.deepcopy(containers, memo)}


def initialize(vendor_dir='/upstream'):
    """Load once and record clean module/class state without copying code."""
    # Pyodide disables bytecode writes by default. Cache in its in-memory
    # filesystem for any later imports of dependencies.
    sys.dont_write_bytecode = False
    import xp2f
    vendor = Path(vendor_dir).resolve()
    for name, module in list(sys.modules.items()):
        filename = getattr(module, '__file__', None)
        if filename and Path(filename).resolve().parent == vendor and name not in _modules:
            classes = [(value, _snapshot(vars(value))) for value in vars(module).values()
                       if isinstance(value, type) and value.__module__ == name]
            _modules[name] = (module, _snapshot(vars(module)), classes)


def reset_transpiler(vendor_dir):
    initialize(vendor_dir)
    # Function objects retain their original module dictionary, which we
    # restore in place. Clone mutable state, but retain compiled functions.
    for name, (module, original, classes) in _modules.items():
        caches = {key: vars(module)[key] for key in _runtime_caches
                  if name == 'xp2f' and key in vars(module)}
        vars(module).clear()
        vars(module).update(_snapshot(original))
        vars(module).update(caches)
        for cls, attributes in classes:
            for added in set(vars(cls)) - set(attributes):
                delattr(cls, added)
            for key, value in _snapshot(attributes).items():
                if key not in {'__dict__', '__weakref__'}:
                    setattr(cls, key, value)


def prepare():
    """Pay lazy runtime-registry setup costs before enabling Translate."""
    initialize()
    result = json.loads(translate('print(0)'))
    if not result['ok']:
        raise RuntimeError('Warm-up translation failed: ' + result['diagnostics'])


def translate(source, vendor_dir='/upstream', work_dir='/work'):
    diagnostics = io.StringIO()
    if len(source.encode('utf-8')) > 100_000:
        return json.dumps({'ok': False, 'diagnostics': 'Input exceeds the 100 KB prototype limit.'})
    try:
        work = Path(work_dir)
        work.mkdir(parents=True, exist_ok=True)
        with contextlib.redirect_stdout(diagnostics), contextlib.redirect_stderr(diagnostics), \
                tempfile.TemporaryDirectory(prefix='translation_', dir=work) as job:
            reset_transpiler(vendor_dir)
            import xp2f
            output = Path(job) / 'input_p.f90'
            # Only parse and translate. Never call main(), compile, run, eval,
            # or exec on the submission. Each job has fresh upstream state
            # and its own temporary filesystem directory.
            result = xp2f.transpile_file(
                Path(job) / 'input.py', [Path(vendor_dir) / 'python.f90'], flat=True,
                src_override=source, out_path=output,
            )
            if output.exists():
                fortran = output.read_text(encoding='utf-8')
            elif isinstance(result, str):
                fortran = result
            else:
                raise RuntimeError('Upstream returned no generated Fortran file')
        return json.dumps({'ok': True, 'fortran': fortran, 'diagnostics': diagnostics.getvalue()})
    except Exception as exc:
        return json.dumps({'ok': False, 'diagnostics': diagnostics.getvalue() + f'{type(exc).__name__}: {exc}'})
