import { createEditor, enableColoring } from './editors.mjs';
const get = id => document.getElementById(id);
const examples = {
  sum: 'total = 0\nfor i in range(1, 11):\n    total += i * i\nprint(total)\n',
  function: 'def square(x: float) -> float:\n    return x * x\n\nprint(square(1.5))\nprint(square(3.0))\n',
  numpy: 'import numpy as np\n\nx = np.array([1.0, 2.0, 3.0])\ny = x * x\nprint(np.sum(y))\n'
};
let worker = null, timer = null, liveTimer = null, ready = false, deploymentLoaded = false;
let initializationSeconds = 0, requestId = 0, revision = 0, active = null, livePending = false;
const output = createEditor(get('fortran'), get('fortran-lines'));
const input = createEditor(get('python'), get('python-lines'), () => {
  revision++; markStale();
  if (ready) get('status').textContent = active ? 'Translating previous input…' : 'Input changed';
  scheduleLive();
});
input.setValue(examples.sum);
function markStale() {
  get('download').disabled = true;
  get('fortran-state').textContent = output.getValue() ? 'Previous translation — input changed' : 'No translation yet';
}
function clearResult() {
  output.setValue(''); get('download').disabled = true;
  get('fortran-state').textContent = 'No translation yet';
}
function cancelLiveTimer() {
  clearTimeout(liveTimer); liveTimer = null; livePending = false;
}
function scheduleLive() {
  cancelLiveTimer();
  if (!get('live').checked || !input.getValue().trim()) return;
  liveTimer = setTimeout(() => {
    liveTimer = null;
    if (!ready || active) { livePending = true; return; }
    translate(true);
  }, 750);
}
function runPending() {
  if (livePending && get('live').checked && ready && !active) {
    livePending = false; translate(true);
  }
}
function finish() {
  clearTimeout(timer); timer = null; active = null;
  get('cancel').disabled = true;
  get('translate').disabled = !deploymentLoaded || Boolean(worker && !ready);
}
function fail(message, destroy = false) {
  if (destroy) {
    worker?.terminate(); worker = null; ready = false;
    cancelLiveTimer(); get('live').checked = false;
    get('translate').textContent = 'Initialize';
    get('initialization').textContent = 'Initialization: worker stopped';
  }
  finish(); markStale(); get('status').textContent = 'Not translated';
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
  timer = setTimeout(() => fail('Initialization exceeded 180 seconds. Live mode is paused. Click Initialize to retry.', true), 180000);
  current.onerror = event => {
    if (worker === current) fail(event.message || 'Worker failed. Click Initialize to retry.', true);
  };
  current.onmessage = ({ data }) => {
    if (worker !== current) return;
    if (data.type === 'status') { get('status').textContent = data.text; return; }
    if (data.type === 'fatal') return fail(data.diagnostics, true);
    if (data.type === 'ready') {
      initializationSeconds = data.initializationSeconds;
      ready = true; finish();
      get('translate').textContent = 'Translate'; get('status').textContent = 'Ready';
      get('initialization').textContent = `Initialization: ${initializationSeconds.toFixed(2)} s (once per worker)`;
      if (get('live').checked) scheduleLive();
      return;
    }
    if (data.type !== 'result' || !active || data.id !== active.id) return;
    const job = active; finish();
    if (job.revision !== revision) {
      get('status').textContent = 'Previous result discarded — input changed';
      runPending(); return;
    }
    if (data.syntaxStatus) {
      markStale();
      get('status').textContent = data.syntaxStatus === 'incomplete' ? 'Waiting for complete Python…' : 'Waiting for valid Python…';
      get('diagnostics').textContent = 'Live translation is waiting. Use Translate to see syntax diagnostics.';
    } else if (!data.ok) {
      fail(data.diagnostics);
    } else {
      output.setValue(data.fortran); get('fortran-state').textContent = 'Current translation';
      const completion = `Translation completed. Time elapsed: ${data.translationSeconds.toFixed(2)} s (translation only). Initialization: ${initializationSeconds.toFixed(2)} s (reused). Compilation was not checked.`;
      get('diagnostics').textContent = data.diagnostics ? `${completion}\n\n${data.diagnostics}` : completion;
      get('status').textContent = `Translated · ${data.commit.slice(0, 7)}`;
      get('download').disabled = false;
    }
    runPending();
  };
  current.postMessage({ type: 'init' });
}
function translate(automatic = false) {
  if (!worker) return startWorker();
  if (!ready || active) return;
  const source = input.getValue(); cancelLiveTimer();
  if (!source.trim()) { if (!automatic) fail('Enter some Python code first.'); return; }
  if (new TextEncoder().encode(source).length > 100000) return fail('Input exceeds the 100 KB prototype limit.');
  get('diagnostics').textContent = automatic ? 'Checking syntax and translating…' : 'Translating…';
  get('translate').disabled = true; get('cancel').disabled = false;
  get('status').textContent = 'Translating…';
  active = { id: ++requestId, revision };
  timer = setTimeout(() => fail('Translation exceeded 180 seconds. Live mode is paused. Click Initialize to restart; try a smaller example.', true), 180000);
  worker.postMessage({ type: 'translate', id: active.id, source, automatic });
}
get('live').onchange = () => {
  if (get('live').checked) {
    scheduleLive();
    if (!worker && deploymentLoaded) startWorker();
  } else { cancelLiveTimer(); }
};
get('load').onclick = () => {
  if (input.getValue().trim() && !confirm('Replace the Python input with this example?')) return;
  input.setValue(examples[get('example').value]);
  get('diagnostics').textContent = 'Example loaded; translation is not current yet.';
};
get('clear').onclick = () => {
  if (input.getValue() && !input.undoableClear && !confirm('Clear the Python input?')) return;
  input.setValue('', true); clearResult(); get('diagnostics').textContent = '';
  if (ready && !active) get('status').textContent = 'Ready';
  input.focus();
};
get('cancel').onclick = () => fail('Cancelled. Your input is preserved and live mode is paused. Click Initialize to restart the worker.', true);
get('translate').onclick = () => translate(false);
get('download').onclick = () => {
  if (get('download').disabled) return;
  const url = URL.createObjectURL(new Blob([output.getValue()], { type: 'text/plain' }));
  const link = document.createElement('a'); link.href = url; link.download = 'input_p.f90'; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
};
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
  get('version').textContent = manifest.commit.slice(0, 7); get('version').href = manifest.source_url;
  deploymentLoaded = true; startWorker();
} catch (error) { fail(String(error)); get('version').textContent = 'unavailable'; }
