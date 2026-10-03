// Exercise the same WebAssembly Python distribution and bridge as the page.
import { loadPyodide } from 'pyodide';
import { readFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import assert from 'node:assert/strict';
const root = new URL('../', import.meta.url);
process.on('uncaughtException', error => { console.error(String(error)); process.exit(1); });
const manifest = JSON.parse(await readFile(new URL('site/vendor/manifest.json', root), 'utf8'));
const zip = await readFile(new URL('site/vendor/upstream.zip', root));
assert.equal(createHash('sha256').update(zip).digest('hex'), manifest.bundle_sha256);
console.time('Runtime startup');
const py = await loadPyodide();
py.unpackArchive(new Uint8Array(zip), 'zip', { extractDir: '/upstream' });
await py.runPythonAsync("import sys\nsys.path.insert(0, '/upstream')");
py.FS.writeFile('/annotations.py', await readFile(new URL('site/annotations.py', root), 'utf8'));
py.FS.writeFile('/translation_settings.py', await readFile(new URL('site/translation_settings.py', root), 'utf8'));
await py.runPythonAsync("sys.path.insert(0, '/')\nfrom annotations import annotate_json");
await py.runPythonAsync(await readFile(new URL('site/bridge.py', root), 'utf8'));
console.timeEnd('Runtime startup');
for (const [source, expected] of [
  ['def f():\n', 'incomplete'], ['x = [1,\n', 'incomplete'],
  ['def f(:\n', 'invalid'], ['print(1)\n', 'complete'],
  ['def f():\n    return 1\n', 'complete'], ['raise RuntimeError("NOT_EXECUTED")\n', 'complete'],
]) {
  py.globals.set('submission', source);
  assert.equal(py.runPython('syntax_status(submission)'), expected);
}
assert.equal(py.runPython("'f' in globals()"), false);
console.log('PASS live syntax checks without execution');
console.time('Transpiler initialization');
await py.runPythonAsync('prepare()');
console.timeEnd('Transpiler initialization');
const cases = [
  ['sum', 'total = 0\nfor i in range(1, 11):\n    total += i*i\nprint(total)\n'],
  ['function', 'def square(x: float) -> float:\n    return x*x\nprint(square(1.5))\n'],
  ['numpy', 'import numpy as np\nx = np.array([1.0, 2.0, 3.0])\ny = x*x\nprint(np.sum(y))\n'],
  ['not executed', 'raise RuntimeError("SUBMISSION_EXECUTED")\n'],
];
const baseline = new Map();
const normalized = text => text.replace(/^! transpiled by.*\n/, '');
for (const [name, source] of cases) {
  console.time(name);
  py.globals.set('submission', source);
  const result = JSON.parse(await py.runPythonAsync('translate(submission)'));
  assert.equal(result.ok, true, `${name}: ${result.diagnostics}`);
  assert.match(result.fortran, /program /i);
  baseline.set(name, normalized(result.fortran));
  console.log(`PASS ${name}`);
  console.timeEnd(name);
}
py.globals.set('submission', 'def broken(:\n');
let result = JSON.parse(await py.runPythonAsync('translate(submission)'));
assert.equal(result.ok, false);
assert.match(result.diagnostics, /SyntaxError/);
console.log('PASS syntax diagnostic');
py.globals.set('submission', '#'.repeat(100001));
result = JSON.parse(await py.runPythonAsync('translate(submission)'));
assert.equal(result.ok, false);
assert.match(result.diagnostics, /100 KB/);
console.log('PASS size limit');
py.globals.set('submission', '# KEEP_THIS_COMMENT\nn = 2\nprint(n)\n');
result = JSON.parse(await py.runPythonAsync("translate(submission, options={'int_kind': 'int64', 'preserve_comments': False})"));
assert.equal(result.ok, true, result.diagnostics);
assert.match(result.fortran, /int64/);
assert.doesNotMatch(result.fortran, /KEEP_THIS_COMMENT/);
result = JSON.parse(await py.runPythonAsync('translate(submission)'));
assert.equal(result.ok, true, result.diagnostics);
assert.match(result.fortran, /KEEP_THIS_COMMENT/);
assert.doesNotMatch(result.fortran, /ikind/);
py.globals.set('submission', 'def f(x): return x\nf(2)\n');
result = JSON.parse(await py.runPythonAsync('annotate_json(submission)'));
assert.equal(result.ok, true, result.diagnostics);
assert.match(result.annotated, /x: int/);
assert.equal(py.runPython("'f' in globals()"), false);
console.log('PASS integer/comment settings, option reset, and non-executing annotation preview');
// Reverse-order repetition after failures must produce the same source.
for (const [name, source] of [...cases].reverse()) {
  py.globals.set('submission', source);
  result = JSON.parse(await py.runPythonAsync('translate(submission)'));
  assert.equal(result.ok, true, result.diagnostics);
  assert.equal(normalized(result.fortran), baseline.get(name));
  console.log(`PASS repeated ${name}`);
}
await py.runPythonAsync("import xp2f\nxp2f.PERCENT_FLOAT_INT_FORMAT = True\nxp2f.NAN_SAFE_COMPARISONS = False\nxp2f.playground_test_added_global = 42");
await py.runPythonAsync("xp2f.NUMPY_DIRECT_IMPORT_SUPPORTED.add('playground_leak')\nxp2f.translator.playground_test_added_attribute = 42");
py.globals.set('submission', cases[0][1]);
result = JSON.parse(await py.runPythonAsync('translate(submission)'));
assert.equal(normalized(result.fortran), baseline.get('sum'));
assert.equal(py.runPython('xp2f.PERCENT_FLOAT_INT_FORMAT'), false);
assert.equal(py.runPython('xp2f.NAN_SAFE_COMPARISONS'), true);
assert.equal(py.runPython("hasattr(xp2f, 'playground_test_added_global')"), false);
assert.equal(py.runPython("'playground_leak' in xp2f.NUMPY_DIRECT_IMPORT_SUPPORTED"), false);
assert.equal(py.runPython("hasattr(xp2f.translator, 'playground_test_added_attribute')"), false);
assert.equal(py.runPython("len(list(Path('/work').iterdir()))"), 0);
console.log('PASS upstream state reset and temporary-file cleanup');
assert.equal(manifest.pyodide, '0.27.7');
console.log(`Pinned upstream ${manifest.commit}`);
