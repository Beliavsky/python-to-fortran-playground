import assert from 'node:assert/strict';
const elements = new Map();
globalThis.document = { getElementById(id) {
  if (!elements.has(id)) elements.set(id, { value: '', textContent: '', disabled: false,
    listeners: {}, classes: new Set(), classList: { toggle(name, on) {
      if (on) elements.get(id).classes.add(name); else elements.get(id).classes.delete(name);
    } }, addEventListener(name, fn) { this.listeners[name] = fn; }, focus() {} });
  return elements.get(id);
} };
globalThis.location = { hostname: '127.0.0.1', search: '?mode=fortran&keep=1',
  href: 'http://127.0.0.1:8766/run/?mode=fortran&keep=1#editor' };
globalThis.history = { replaceState(_state, _title, url) {
  globalThis.location.href = url.href; globalThis.location.search = url.search;
} };
let confirmAllowed = true;
globalThis.confirm = () => confirmAllowed;
let payload, state = 'done', submissions = 0;
globalThis.fetch = async (url, options = {}) => {
  let result;
  if (url === './service.json') result = {url: ''};
  else if (url === '/api/session') result = {token: 'token', commit: 'abc', timeout: 30};
  else if (url === '../vendor/manifest.json') result = {commit: 'abc'};
  else if (url === '/api/jobs') { payload = JSON.parse(options.body); submissions++; result = {id: 'job'}; }
  else result = {state, result: {ok: true, mode: 'fortran-edit', fortran: payload.fortran_source,
    build: {seconds: 0.1, stdout: 'Build: PASS', stderr: ''},
    execution: {seconds: 0.1, stdout: '385\n', stderr: ''}}};
  return {ok: true, json: async () => result};
};
await import('../site/run/run.mjs');
const get = id => document.getElementById(id);
assert.equal(get('fortran-only').checked, true);
assert.equal(document.title, 'Fortran playground');
assert.equal(get('run-layout').classes.has('fortran-only'), true);
assert.equal(get('fortran').readOnly, false);
assert.match(get('fortran').value, /program main/);
assert.equal(get('fortran-lines').textContent, '9 lines');
assert.equal(get('python-panel').hidden, true);
assert.equal(get('python-output-panel').hidden, true);
assert.equal(get('live-label').hidden, true);
assert.equal(get('translate').disabled, true);
assert.equal(get('compare').disabled, true);
assert.equal(get('fortran-example').hidden, false);
assert.equal(get('build-heading').textContent, 'Compilation');
const initialPython = get('python').value;
get('python-output').textContent = 'saved Python result';
get('python-time').textContent = '2.00 s';
await get('run-fortran').onclick();
assert.equal(payload.mode, 'fortran-edit');
assert.equal(payload.source, ''); // hidden Python is neither submitted nor run
assert.equal(get('python-output').textContent, 'saved Python result');
assert.equal(get('python-time').textContent, '2.00 s');
assert.equal(get('fortran-output').textContent, '385\n');
const count = submissions;
await get('compare').onclick();
assert.equal(submissions, count);
get('fortran-only').checked = false; get('fortran-only').onchange();
assert.equal(get('python').value, initialPython);
assert.equal(get('python-output').textContent, 'saved Python result');
assert.equal(get('python-panel').hidden, false);
assert.equal(get('run-layout').classes.has('fortran-only'), false);
assert.equal(get('fortran').readOnly, true);
assert.equal(new URL(location.href).searchParams.get('mode'), null);
assert.equal(new URL(location.href).searchParams.get('keep'), '1');
assert.equal(new URL(location.href).hash, '#editor');
get('edit-fortran').checked = true; get('edit-fortran').onchange();
get('fortran').value = 'program custom\nend program custom\n'; get('fortran').listeners.input();
get('live').checked = true;
get('fortran-only').checked = true; get('fortran-only').onchange();
assert.match(get('fortran').value, /program custom/); // entering never overwrites nonempty code
assert.equal(get('live').checked, false);
get('fortran-example').value = 'helper';
confirmAllowed = false;
get('load').onclick(); get('clear').onclick();
assert.match(get('fortran').value, /program custom/);
confirmAllowed = true;
get('load').onclick();
assert.match(get('fortran').value, /use python_mod/);
assert.equal(get('python').value, initialPython);
state = 'running';
const running = get('run-fortran').onclick();
await new Promise(resolve => setTimeout(resolve, 10));
assert.equal(get('fortran-only').disabled, true);
get('fortran-only').checked = false; get('fortran-only').onchange();
assert.equal(get('fortran-only').checked, true);
state = 'done'; await running;
get('clear').onclick();
assert.equal(get('fortran').value, '');
assert.equal(get('fortran-lines').textContent, '0 lines');
assert.equal(get('python').value, initialPython);
assert.equal(get('python-output').textContent, 'saved Python result');
get('fortran-only').checked = false; get('fortran-only').onchange();
assert.equal(get('fortran').readOnly, false); // original Edit Fortran setting restored
assert.equal(get('live').checked, false); // don't restart automatic translation
console.log('PASS Fortran-only deep link, layout, preserved buffers/results, examples, Clear and direct execution');
