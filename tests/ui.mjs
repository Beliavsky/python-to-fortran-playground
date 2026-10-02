// Unit-test UI state transitions without a browser or network.
import assert from 'node:assert/strict';
const elements = new Map();
globalThis.document = { getElementById(id) {
  if (!elements.has(id)) elements.set(id, { value: '', textContent: '', disabled: false,
    listeners: {}, addEventListener(name, fn) { this.listeners[name] = fn; },
    focus() { this.focused = true; } });
  return elements.get(id);
} };
globalThis.fetch = async () => ({ ok: true, json: async () => ({
  commit: 'abcdef123', source_url: 'https://example.invalid/commit/abcdef123'
}) });
globalThis.confirm = () => true;
const timers = new Map();
let timerId = 0;
globalThis.setTimeout = fn => { timers.set(++timerId, fn); return timerId; };
globalThis.clearTimeout = id => timers.delete(id);
const workers = [];
globalThis.Worker = class {
  constructor() { this.sent = []; this.terminated = false; workers.push(this); }
  postMessage(data) { this.sent.push(data); }
  terminate() { this.terminated = true; }
  receive(data) { this.onmessage({ data }); }
};
await import('../site/app.mjs');
const get = id => elements.get(id);
assert.equal(workers.length, 1);
assert.equal(workers[0].sent[0].type, 'init');
assert.equal(get('translate').disabled, true);
assert.equal(get('python-lines').textContent, '4 lines');
assert.equal(get('fortran-lines').textContent, '0 lines');
workers[0].receive({ type: 'ready', initializationSeconds: 37 });
assert.equal(get('translate').disabled, false);
assert.match(get('initialization').textContent, /37.00 s/);
for (let id = 1; id <= 2; id++) {
  get('translate').onclick();
  assert.equal(get('clear').disabled, true);
  assert.equal(workers.length, 1);
  assert.equal(workers[0].sent.at(-1).id, id);
  workers[0].receive({ type: 'result', id, ok: true, fortran: 'program input',
    translationSeconds: 0.42, commit: 'abcdef123' });
  assert.equal(workers[0].terminated, false);
  assert.equal(get('download').disabled, false);
  assert.equal(get('fortran-lines').textContent, '1 line');
  assert.match(get('diagnostics').textContent, /0.42 s \(translation only\)/);
}
const priorInput = get('python').value;
globalThis.confirm = () => false;
get('clear').onclick();
assert.equal(get('python').value, priorInput);
globalThis.confirm = () => true;
get('clear').onclick();
assert.equal(get('python-lines').textContent, '0 lines');
assert.equal(get('fortran-lines').textContent, '0 lines');
assert.equal(get('diagnostics').textContent, '');
assert.equal(get('download').disabled, true);
assert.equal(get('python').focused, true);
assert.equal(workers.length, 1);
assert.equal(workers[0].terminated, false);
assert.equal(get('translate').disabled, false);
get('python').value = 'print(42)\n';
get('python').listeners.input();
assert.equal(get('python-lines').textContent, '1 line');
get('translate').onclick();
workers[0].receive({ type: 'result', id: 3, ok: false, diagnostics: 'SyntaxError' });
assert.equal(workers[0].terminated, false);
assert.equal(get('fortran').value, '');
assert.equal(get('translate').disabled, false);
get('translate').onclick();
get('cancel').onclick();
assert.equal(workers[0].terminated, true);
assert.equal(get('translate').textContent, 'Initialize');
get('translate').onclick();
assert.equal(workers.length, 2);
workers[0].receive({ type: 'ready', initializationSeconds: 1 });
assert.equal(get('translate').disabled, true);
workers[1].receive({ type: 'ready', initializationSeconds: 2 });
get('translate').onclick();
[...timers.values()][0]();
assert.equal(workers[1].terminated, true);
assert.match(get('diagnostics').textContent, /exceeded 180/);
get('translate').onclick();
workers[2].receive({ type: 'fatal', diagnostics: 'runtime failed' });
assert.equal(workers[2].terminated, true);
assert.equal(get('translate').textContent, 'Initialize');
console.log('PASS UI preload, reuse, timing, error recovery, cancellation, stale messages, timeout, fatal restart');
