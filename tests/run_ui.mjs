// Exercise asynchronous execution controls without a compiler or browser.
import assert from 'node:assert/strict';
const elements = new Map();
globalThis.document = { getElementById(id) {
  if (!elements.has(id)) elements.set(id, { value: '', textContent: '', disabled: false,
    listeners: {}, addEventListener(name, fn) { this.listeners[name] = fn; }, focus() {} });
  return elements.get(id);
} };
globalThis.confirm = () => true;
const get = id => elements.get(id);
let state, created, cancellation = 0, jobNumber = 0;
let stoppedBeforeCreated = false;
const sleep = setTimeout;
globalThis.fetch = async (url, options = {}) => {
  let payload;
  if (url === '/api/session') payload = { token: 'test-token', commit: '123abcdef', compiler: 'gfortran', timeout: 30 };
  else if (url === '../vendor/manifest.json') payload = { commit: '123abcdef' };
  else if (url === '/api/jobs') {
    created = JSON.parse(options.body); jobNumber++;
    assert.equal(options.headers['X-P2F-Token'], 'test-token');
    if (stoppedBeforeCreated) await new Promise(resolve => sleep(resolve, 10));
    payload = { id: String(jobNumber) };
  } else if (url.endsWith('/cancel')) { cancellation++; payload = { cancelled: true }; }
  else payload = state;
  return { ok: true, json: async () => payload };
};
await import('../site/run/run.mjs');
assert.equal(get('run-both').disabled, false);
assert.match(get('connection').textContent, /123abcd/);

const result = { ok: true, mode: 'compare', seconds: 1.2, fortran: 'program input\nend program input\n', matches: true,
  build: { seconds: 0.8, stdout: 'Build: PASS', stderr: '' },
  python: { seconds: 0.2, stdout: '385\n', stderr: '' },
  execution: { seconds: 0.2, stdout: '385\n', stderr: '' } };
state = { state: 'done', result };
await get('compare').onclick();
assert.equal(created.mode, 'compare');
assert.match(get('status').textContent, /outputs match/);
assert.equal(get('python-output').textContent, '385\n');
assert.equal(get('fortran-output').textContent, '385\n');
assert.equal(get('python-time').textContent, '0.20 s');
assert.equal(get('download').disabled, false);
assert.equal(get('fortran-lines').textContent, '2 lines');

state = { state: 'running' };
const stale = get('run-both').onclick();
await new Promise(resolve => sleep(resolve, 10));
assert.equal(get('run-python').disabled, true);
assert.equal(get('stop').disabled, false);
get('python').value = 'print(2)'; get('python').listeners.input();
assert.equal(get('download').disabled, true);
state = { state: 'done', result: { ...result, fortran: 'wrong stale output' } };
await stale;
assert.match(get('status').textContent, /discarded/);
assert.doesNotMatch(get('fortran').value, /wrong/);

state = { state: 'running' };
stoppedBeforeCreated = true;
const cancelled = get('run-python').onclick();
await get('stop').onclick();
state = { state: 'done', result };
await cancelled;
assert.equal(cancellation, 1);
assert.equal(get('status').textContent, 'Stopped');
assert.equal(get('stop').disabled, true);
assert.equal(get('run-python').disabled, false);
get('clear').onclick();
assert.equal(get('python-lines').textContent, '0 lines');
assert.equal(get('fortran-lines').textContent, '0 lines');
console.log('Execution UI: outputs, timings, stale results, early Stop, and Clear passed');
