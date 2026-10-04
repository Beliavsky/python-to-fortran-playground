import { createEditor, enableColoring } from './editors.mjs';
import {sourceTools, translationSettings, saveText} from './source_tools.mjs';
import {pythonExamples, populateExamples, describeExample} from './examples.mjs';
const get = id => document.getElementById(id);
populateExamples(get('example')); describeExample(get);
get('example').onchange = () => describeExample(get);
let worker = null, timer = null, liveTimer = null, ready = false, deploymentLoaded = false;
let initializationSeconds = 0, requestId = 0, revision = 0, active = null, livePending = false;
const output = createEditor(get('fortran'), get('fortran-lines'));
const input = createEditor(get('python'), get('python-lines'), () => {
  revision++; markStale();
  if (ready) get('status').textContent = active ? 'Translating previous input…' : 'Input changed';
  scheduleLive();
});
input.setValue(pythonExamples.sum.source);
const tools = sourceTools({get, input, output, pause: () => { get('live').checked = false; cancelLiveTimer(); },
  pythonChanged: () => { markStale(); get('status').textContent = 'Python loaded or annotations applied; translate explicitly.'; },
  fortranChanged: () => {}, requestAnnotations: source => new Promise(resolve => {
    if (!ready || active) { resolve({ok: false, diagnostics: 'Wait for initialization or the current operation.'}); return; }
    active = {id: ++requestId, revision, annotationResolve: resolve};
    get('translate').disabled = get('suggest-annotations').disabled = true; get('cancel').disabled = false;
    timer = setTimeout(() => fail('Annotation suggestions timed out.', true), 180000);
    worker.postMessage({type: 'annotate', id: active.id, source});
  })});
for (const id of ['translation-int-kind', 'translation-comments']) get(id).onchange = () => {
  revision++; markStale(); scheduleLive();
};
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
  get('suggest-annotations').disabled = !ready;
}
function fail(message, destroy = false) {
  const annotationResolve = active?.annotationResolve;
  if (destroy) {
    worker?.terminate(); worker = null; ready = false;
    cancelLiveTimer(); get('live').checked = false;
    get('translate').textContent = 'Initialize';
    get('initialization').textContent = 'Initialization: worker stopped';
  }
  finish(); markStale(); get('status').textContent = 'Not translated';
  get('diagnostics').textContent = message;
  annotationResolve?.({ok: false, diagnostics: message});
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
    if (job.annotationResolve) { job.annotationResolve(data); return; }
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
      const completion = `Translation completed. Time elapsed: ${data.translationSeconds.toFixed(2)} s (translation only). Initialization: ${initializationSeconds.toFixed(2)} s (reused). Compilation was not checked.\nTranslation settings: ${JSON.stringify(job.options)}`;
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
  active = { id: ++requestId, revision, options: translationSettings(get) };
  get('suggest-annotations').disabled = true;
  timer = setTimeout(() => fail('Translation exceeded 180 seconds. Live mode is paused. Click Initialize to restart; try a smaller example.', true), 180000);
  worker.postMessage({ type: 'translate', id: active.id, source, automatic, translation_options: active.options });
}
get('live').onchange = () => {
  if (get('live').checked) {
    scheduleLive();
    if (!worker && deploymentLoaded) startWorker();
  } else { cancelLiveTimer(); }
};
get('load').onclick = () => {
  const example = pythonExamples[get('example').value];
  if (!example) return;
  if (input.getValue().trim() && !confirm('Replace the Python input with this example?')) return;
  get('live').checked = false; cancelLiveTimer();
  input.setValue(example.source, true); input.focus();
  get('diagnostics').textContent = 'Example loaded; live translation paused. Click Translate when ready.';
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
  saveText(output.getValue(), tools.fortranFilename());
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
