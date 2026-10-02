import { createEditor, enableColoring } from './editors.mjs';
const get = id => document.getElementById(id);
const examples = {
  sum: 'total = 0\nfor i in range(1, 11):\n    total += i * i\nprint(total)\n',
  function: 'def square(x: float) -> float:\n    return x * x\n\nprint(square(1.5))\nprint(square(3.0))\n',
  numpy: 'import numpy as np\n\nx = np.array([1.0, 2.0, 3.0])\ny = x * x\nprint(np.sum(y))\n'
};
let worker = null, timer = null, ready = false, deploymentLoaded = false;
let initializationSeconds = 0, requestId = 0;
const output = createEditor(get('fortran'), get('fortran-lines'));
const input = createEditor(get('python'), get('python-lines'), () => {
  clearResult(); if (ready) get('status').textContent = 'Input changed';
});
input.setValue(examples.sum);
function clearResult() { output.setValue(''); get('download').disabled = true; }
function finish() {
  clearTimeout(timer);
  get('cancel').disabled = true;
  get('translate').disabled = !deploymentLoaded;
  get('load').disabled = false;
  get('clear').disabled = false;
  input.setReadOnly(false);
}
function fail(message, destroy = false) {
  if (destroy) {
    worker?.terminate(); worker = null; ready = false;
    get('translate').textContent = 'Initialize';
  }
  finish(); clearResult(); get('status').textContent = 'Not translated';
  get('diagnostics').textContent = message;
}
function startWorker() {
  ready = false;
  get('translate').disabled = true;
  get('translate').textContent = 'Initializing…';
  get('cancel').disabled = false;
  get('status').textContent = 'Initializing…';
  get('initialization').textContent = 'Initialization: in progress';
  const current = new Worker('./worker.mjs', { type: 'module' });
  worker = current;
  timer = setTimeout(() => fail('Initialization exceeded 180 seconds. Click Initialize to retry.', true), 180000);
  current.onerror = event => {
    if (worker === current) fail(event.message || 'Worker failed. Click Initialize to retry.', true);
  };
  current.onmessage = ({ data }) => {
    if (worker !== current) return; // Discard messages from cancelled workers.
    if (data.type === 'status') { get('status').textContent = data.text; return; }
    if (data.type === 'fatal') return fail(data.diagnostics, true);
    if (data.type === 'ready') {
      initializationSeconds = data.initializationSeconds;
      ready = true; finish();
      get('translate').textContent = 'Translate';
      get('status').textContent = 'Ready';
      get('initialization').textContent = `Initialization: ${initializationSeconds.toFixed(2)} s (once per worker)`;
      return;
    }
    if (data.type !== 'result' || data.id !== requestId) return;
    finish();
    if (!data.ok) return fail(data.diagnostics);
    output.setValue(data.fortran);
    const completion = `Translation completed. Time elapsed: ${data.translationSeconds.toFixed(2)} s (translation only). Initialization: ${initializationSeconds.toFixed(2)} s (reused). Compilation was not checked.`;
    get('diagnostics').textContent = data.diagnostics ? `${completion}\n\n${data.diagnostics}` : completion;
    get('status').textContent = `Translated · ${data.commit.slice(0, 7)}`;
    get('download').disabled = false;
  };
  current.postMessage({ type: 'init' });
}
get('load').onclick = () => {
  if (input.getValue().trim() && !confirm('Replace the Python input with this example?')) return;
  input.setValue(examples[get('example').value]); clearResult();
  if (ready) get('status').textContent = 'Ready';
  get('diagnostics').textContent = 'No translation yet.';
};
get('clear').onclick = () => {
  if (get('clear').disabled) return;
  if (input.getValue() && !input.undoableClear && !confirm('Clear the Python input?')) return;
  input.setValue('', true);
  clearResult();
  get('diagnostics').textContent = '';
  if (ready) get('status').textContent = 'Ready';
  input.focus();
};
get('cancel').onclick = () => fail('Cancelled. Your input is preserved. Click Initialize to restart the worker.', true);
get('translate').onclick = () => {
  if (!worker) return startWorker();
  if (!ready) return;
  const source = input.getValue();
  if (!source.trim()) return fail('Enter some Python code first.');
  if (new TextEncoder().encode(source).length > 100000) return fail('Input exceeds the 100 KB prototype limit.');
  clearResult(); get('diagnostics').textContent = 'Translating…';
  get('translate').disabled = true; get('cancel').disabled = false;
  get('load').disabled = true; get('clear').disabled = true; input.setReadOnly(true);
  get('status').textContent = 'Translating…';
  timer = setTimeout(() => fail('Translation exceeded 180 seconds. Click Initialize to restart; try a smaller example.', true), 180000);
  worker.postMessage({ type: 'translate', id: ++requestId, source });
};
get('download').onclick = () => {
  const url = URL.createObjectURL(new Blob([output.getValue()], { type: 'text/plain' }));
  const link = document.createElement('a'); link.href = url; link.download = 'input_p.f90'; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
};
// Load editing features independently; never delay translator initialization.
if (typeof window !== 'undefined') {
  enableColoring(input, output).then(() => {
    get('editor-note').textContent = 'Syntax coloring enabled · Tab: four-space indentation · Ctrl+Z: undo (including Clear) · Esc: leave editor. Line counts include comments and blank lines.';
  }).catch(() => {
    get('editor-note').textContent = 'Syntax coloring could not load. Plain-text editing is still available; Clear asks for confirmation.';
  });
}
try {
  const response = await fetch('./vendor/manifest.json', { cache: 'no-cache' });
  if (!response.ok) throw new Error('Run python xvendor.py before serving this site.');
  const manifest = await response.json();
  get('version').textContent = manifest.commit.slice(0, 7);
  get('version').href = manifest.source_url;
  deploymentLoaded = true;
  startWorker();
} catch (error) { fail(String(error)); get('version').textContent = 'unavailable'; }
