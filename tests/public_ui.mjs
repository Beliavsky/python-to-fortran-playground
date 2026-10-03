import assert from 'node:assert/strict';
const elements = new Map();
globalThis.document = { getElementById(id) {
  if (!elements.has(id)) elements.set(id, { value: '', textContent: '', disabled: false,
    addEventListener() {}, focus() {} });
  return elements.get(id);
} };
globalThis.location = { hostname: 'beliavsky.github.io' };
const requests = [];
let config = { url: 'https://workspace--p2f-api.modal.run/' };
let serverCommit = 'abc1234';
globalThis.fetch = async (url, options = {}) => {
  requests.push({ url, options });
  let payload;
  if (url === './service.json') payload = config;
  else if (url === '../vendor/manifest.json') payload = { commit: 'abc1234' };
  else if (url.endsWith('/api/session')) payload = { token: 'session-token', commit: serverCommit, compiler: 'gfortran', timeout: 30 };
  else if (url.endsWith('/api/jobs')) payload = { id: 'job1' };
  else payload = { state: 'done', result: { ok: true, seconds: 0.1, python: { seconds: 0.1, stdout: '385', stderr: '' } } };
  return { ok: true, json: async () => payload };
};
await import('../site/run/run.mjs');
const get = id => elements.get(id);
assert.equal(get('run-python').disabled, false);
await get('run-python').onclick();
const submission = requests.find(r => r.url.endsWith('/api/jobs'));
assert.equal(submission.url, 'https://workspace--p2f-api.modal.run/api/jobs');
assert.equal(submission.options.headers['X-P2F-Token'], 'session-token');
assert.equal(get('python-output').textContent, '385');

serverCommit = 'different';
await get('connect').onclick();
assert.equal(get('run-python').disabled, true);
assert.match(get('diagnostics').textContent, /different transpiler revisions/);
serverCommit = 'abc1234';
config = { url: 'http://workspace--p2f-api.modal.run' };
const before = requests.filter(r => r.url.endsWith('/api/session')).length;
await get('connect').onclick();
assert.match(get('diagnostics').textContent, /HTTPS/);
assert.equal(requests.filter(r => r.url.endsWith('/api/session')).length, before);
globalThis.location.hostname = '127.0.0.1';
await get('connect').onclick();
assert.ok(requests.some(r => r.url === '/api/session'));
assert.equal(get('run-python').disabled, false);
console.log('Hosted connection: endpoint routing, revision checks, HTTPS validation, and local override passed');
