import assert from 'node:assert/strict';
import {pythonExamples, populateExamples, describeExample} from '../site/examples.mjs';
const entries = Object.entries(pythonExamples);
assert.equal(entries.length, 20);
assert.equal(new Set(entries.map(([id]) => id)).size, 20);
assert.equal(entries.filter(([, item]) => item.random).length, 2);
for (const [id, item] of entries) {
  assert.match(id, /^[a-z_]+$/);
  assert.equal(typeof item.source, 'string');
  assert.ok(item.source.endsWith('\n'));
  assert.ok(item.source.length < 3000);
  if (!['sum', 'function', 'numpy'].includes(id)) assert.match(item.upstream, /^x\w+\.py$/);
}
const elements = new Map(['example', 'example-description', 'example-source'].map(id => [id, {}]));
const get = id => elements.get(id);
populateExamples(get('example'));
assert.equal(get('example').value, 'sum');
assert.equal((get('example').innerHTML.match(/<option /g) || []).length, 20);
assert.equal((get('example').innerHTML.match(/<optgroup /g) || []).length, 6);
describeExample(get);
assert.equal(get('example-source').hidden, true);
get('example').value = 'normal'; describeExample(get);
assert.match(get('example-description').textContent, /Compare can report DIFF/);
assert.match(get('example-source').href, /examples\/xrandom_normal.py$/);
get('example').value = 'solve'; describeExample(get);
assert.doesNotMatch(get('example-description').textContent, /draws differ/);
assert.equal(get('example-source').hidden, false);
console.log('PASS shared 20-example catalog, six categories, provenance and random warnings');
