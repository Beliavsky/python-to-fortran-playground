import assert from 'node:assert/strict';
const elements = new Map();
globalThis.document = { getElementById(id) {
  if (!elements.has(id)) elements.set(id, { value: '', textContent: '', checked: false, disabled: false,
    listeners: {}, addEventListener(name, fn) { this.listeners[name] = fn; }, focus() {} });
  return elements.get(id);
} };
globalThis.fetch = async () => ({ ok: true, json: async () => ({ commit: 'abcdef123', source_url: 'https://example.invalid/' }) });
globalThis.confirm = () => true;
let now = 0, nextTimer = 0;
const timers = new Map();
globalThis.setTimeout = (fn, delay) => { timers.set(++nextTimer, { fn, due: now + delay }); return nextTimer; };
globalThis.clearTimeout = id => timers.delete(id);
function advance(ms) {
  now += ms;
  for (const [id, timer] of [...timers]) {
    if (timer.due <= now && timers.has(id)) { timers.delete(id); timer.fn(); }
  }
}
const workers = [];
globalThis.Worker = class {
  constructor() { this.sent = []; workers.push(this); }
  postMessage(data) { this.sent.push(data); }
  terminate() { this.terminated = true; }
  receive(data) { this.onmessage({ data }); }
};
await import('../site/app.mjs');
const get = id => elements.get(id);
const edit = source => { get('python').value = source; get('python').listeners.input(); };
const toggle = checked => { get('live').checked = checked; get('live').onchange(); };
const result = (worker, text, extra = {}) => worker.receive({ type: 'result', id: worker.sent.at(-1).id,
  ok: true, fortran: text, translationSeconds: 0.4, commit: 'abcdef123', ...extra });
const first = workers[0];
first.receive({ type: 'ready', initializationSeconds: 12 });
advance(1000);
assert.equal(first.sent.length, 1, 'live defaults off');
get('translate').onclick(); result(first, 'program initial');
edit('print(1)\n');
assert.equal(get('fortran').value, 'program initial');
assert.equal(get('download').disabled, true);
assert.match(get('fortran-state').textContent, /Previous/);
toggle(true); advance(500); edit('print(2)\n'); advance(500);
assert.equal(first.sent.length, 2, 'typing resets debounce');
advance(250);
assert.equal(first.sent.at(-1).automatic, true);
assert.equal(first.sent.at(-1).source, 'print(2)\n');
const obsolete = first.sent.at(-1).id;
assert.notEqual(get('python').readOnly, true);
assert.equal(get('clear').disabled, false);
edit('print(3)\n'); advance(750); edit('print(4)\n'); advance(750);
assert.equal(first.sent.length, 3, 'only one request in flight');
result(first, 'OBSOLETE');
assert.equal(get('fortran').value, 'program initial');
assert.equal(first.sent.length, 4);
assert.equal(first.sent.at(-1).source, 'print(4)\n', 'coalesce to latest input');
first.receive({ type: 'result', id: obsolete, ok: false, diagnostics: 'OLD ERROR' });
assert.equal(get('translate').disabled, true, 'obsolete message cannot finish active job');
result(first, 'program latest');
assert.equal(get('fortran').value, 'program latest');
assert.equal(get('download').disabled, false);
assert.equal(get('fortran-state').textContent, 'Current translation');
edit('print(5)\n'); advance(750); edit('print(6)\n');
result(first, 'EARLY OBSOLETE');
assert.equal(first.sent.at(-1).source, 'print(5)\n');
advance(749); assert.equal(first.sent.at(-1).source, 'print(5)\n');
advance(1); assert.equal(first.sent.at(-1).source, 'print(6)\n');
result(first, 'program six');
edit('def f():\n'); advance(750);
result(first, '', { ok: false, syntaxStatus: 'incomplete' });
assert.match(get('status').textContent, /Waiting for complete/);
assert.equal(get('fortran').value, 'program six');
assert.equal(get('download').disabled, true);
assert.ok(!get('diagnostics').textContent.includes('SyntaxError'));
edit('def f(:\n'); advance(750);
result(first, '', { ok: false, syntaxStatus: 'invalid' });
assert.match(get('status').textContent, /Waiting for valid/);
get('translate').onclick();
assert.equal(first.sent.at(-1).automatic, false);
result(first, '', { ok: false, diagnostics: 'SyntaxError: invalid syntax' });
assert.match(get('diagnostics').textContent, /SyntaxError/);
edit('print(7)\n'); toggle(false); advance(750);
assert.equal(first.sent.at(-1).automatic, false, 'disabling live cancels pending work');
toggle(true); advance(750); get('clear').onclick();
result(first, 'CLEARED OBSOLETE');
assert.equal(get('fortran').value, '');
assert.equal(get('python').value, '');
const count = first.sent.length; advance(1000); assert.equal(first.sent.length, count);
edit('print(8)\n'); advance(750); get('cancel').onclick();
assert.equal(first.terminated, true); assert.equal(get('live').checked, false);
advance(1000); assert.equal(workers.length, 1);
toggle(true); const second = workers[1];
advance(750); assert.equal(second.sent.length, 1, 'wait for initialization');
first.receive({ type: 'ready', initializationSeconds: 1 });
assert.equal(get('translate').disabled, true);
second.receive({ type: 'ready', initializationSeconds: 2 });
advance(750); assert.equal(second.sent.at(-1).automatic, true);
result(second, 'program restarted');
edit('print(9)\n'); advance(750); advance(180000);
assert.equal(second.terminated, true); assert.equal(get('live').checked, false);
assert.equal(timers.size, 0);
console.log('PASS live debounce, queue coalescing, stale results, syntax waiting, editable jobs, clear, cancellation, restart and timeout');
