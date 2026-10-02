import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { countLines, createEditor } from '../site/editors.mjs';

for (const [text, expected] of [['', 0], ['x', 1], ['x\n', 1], ['x\n\n', 2],
  ['\n', 1], ['# comment\n\nprint(1)\n', 3], ['x\r\ny\r\n', 2], ['x\ry', 2]]) {
  assert.equal(countLines(text), expected);
}
const textarea = { value: 'old input\n', readOnly: false, addEventListener() {}, focus() {} };
const counter = {};
const editor = createEditor(textarea, counter);
let value = textarea.value, previous, changed, options;
const cm = {
  getValue: () => value,
  getDoc: () => ({ changeGeneration() {} }),
  posFromIndex: index => ({ line: 1, ch: index - 10 }),
  replaceRange(text, start, end, origin) {
    assert.deepEqual(start, { line: 0, ch: 0 });
    assert.equal(origin, '+clear');
    previous = value; value = text; changed();
  },
  getInputField: () => ({ setAttribute() {} }),
  on: (event, callback) => { changed = callback; },
  setOption(name, v) { options[name] = v; },
};
editor.enhance({ fromTextArea: (el, config) => { options = config; return cm; } }, 'python', 'Python input');
assert.equal(editor.undoableClear, true);
assert.equal(options.lineNumbers, true);
editor.setValue('', true);
assert.equal(counter.textContent, '0 lines');
value = previous; changed(); // Simulate the editor's undo change notification.
assert.equal(editor.getValue(), 'old input\n');
assert.equal(counter.textContent, '1 line');
editor.setReadOnly(true);
assert.equal(options.readOnly, true);
console.log('PASS line counts, undoable-clear integration, and read-only state');

// Test the actual bundled language tokenizers with CodeMirror's Node runner.
const require = createRequire(import.meta.url);
const CodeMirror = require('codemirror/addon/runmode/runmode.node.js');
require('codemirror/mode/python/python.js');
require('codemirror/mode/fortran/fortran.js');
for (const [mode, source] of [
  [{ name: 'python', version: 3 }, 'for i in range(3):\n    print("hello") # note'],
  ['text/x-fortran', 'program demo\nprint *, "hello" ! note\nend program demo'],
]) {
  const styles = [];
  CodeMirror.runMode(source, mode, (text, style) => { if (style) styles.push(style); });
  for (const token of ['keyword', 'string', 'comment']) assert.ok(styles.includes(token), `${mode}: ${token}`);
}
console.log('PASS Python and Fortran syntax coloring modes');
