import { createEditor, enableColoring } from '../editors.mjs';
import {sourceTools, translationSettings, saveText} from '../source_tools.mjs';
import {pythonExamples, populateExamples, describeExample} from '../examples.mjs';

const get = id => document.getElementById(id);
const actions = ['translate', 'run-python', 'run-fortran', 'run-both', 'compare'];
populateExamples(get('example')); describeExample(get);
get('example').onchange = () => describeExample(get);
const fortranExamples = {
  sum: 'program main\n   implicit none\n   integer :: i, total\n   total = 0\n   do i = 1, 10\n      total = total + i*i\n   end do\n   print *, total\nend program main\n',
  helper: 'program main\n   use, intrinsic :: iso_fortran_env, only: real64\n   use python_mod, only: mean\n   implicit none\n   real(real64) :: x(3) = [1.0_real64, 2.0_real64, 3.0_real64]\n   print *, mean(x)\nend program main\n',
};
let fortranOnly = false, previousEditMode = false;
let token = '', commit = '', revision = 0, active = null, debounce = null, pending = false;
let downloading = false, connecting = false;
let serviceURL = '';
let sourceToolsAvailable = false;
let optionCatalog = {};
function selectedOptions() {
  return { preset: get('compiler-preset').value || 'default',
    warnings: Boolean(get('compiler-warnings').checked), fast_math: Boolean(get('compiler-fast-math').checked) };
}
function optionControls() {
  const spec = optionCatalog[get('compiler').value];
  const locked = !token || Boolean(active) || !spec;
  for (const preset of ['default', 'debug', 'optimized', 'strict']) get(`preset-${preset}`).disabled = !spec?.presets[preset];
  if (!spec?.presets[get('compiler-preset').value]) get('compiler-preset').value = 'default';
  get('compiler-preset').disabled = locked;
  for (const [id, key] of [['compiler-warnings', 'warnings'], ['compiler-fast-math', 'fast_math']]) {
    if (!spec?.extras[key]) get(id).checked = false;
    get(id).disabled = locked || !spec?.extras[key];
  }
  const selection = selectedOptions();
  const flags = spec ? [...spec.presets[selection.preset],
    ...(selection.warnings ? spec.extras.warnings : []), ...(selection.fast_math ? spec.extras.fast_math : [])] : [];
  get('compiler-options-note').textContent = `${spec?.note || 'Option controls require an updated execution service.'} User-code flags: ${flags.join(' ') || '(compiler default)'}. Helpers keep fixed build options; checks do not instrument helpers.${selection.fast_math ? ' Fast math can change numerical results, including comparisons.' : ''}`;
}
let lastTranslation = '', settingOutput = false;
const editing = () => Boolean(get('edit-fortran').checked);
const modified = () => output.getValue() !== lastTranslation;
function setOutput(value) {
  settingOutput = true;
  try { output.setValue(value); } finally { settingOutput = false; }
  downloading = Boolean(value.trim());
}
const output = createEditor(get('fortran'), get('fortran-lines'), () => {
  if (settingOutput) return;
  revision++;
  downloading = Boolean(output.getValue().trim());
  get('freshness').textContent = 'Fortran changed; previous results are retained.';
  buttons();
});
const input = createEditor(get('python'), get('python-lines'), () => {
  revision++;
  downloading = (editing() || modified()) && Boolean(output.getValue().trim());
  get('download').disabled = !downloading;
  get('freshness').textContent = 'Input changed; previous results are retained.';
  schedule();
});
input.setValue(pythonExamples.sum.source);
const tools = sourceTools({get, input, output,
  pause: () => { get('live').checked = false; clearTimeout(debounce); debounce = null; pending = false; },
  pythonChanged: () => {},
  fortranChanged: source => {
    get('edit-fortran').checked = true; output.setReadOnly(false);
    revision++; setOutput(source); buttons();
    get('freshness').textContent = 'Fortran file loaded; compilation results are stale.';
  }, requestAnnotations: () => submit('annotate')});
for (const id of ['translation-int-kind', 'translation-comments']) get(id).onchange = () => {
  revision++; get('freshness').textContent = 'Translation options changed; previous results are retained.'; schedule();
};

function buttons() {
  for (const id of actions) get(id).disabled = !token || Boolean(active) || (fortranOnly && id !== 'run-fortran');
  get('stop').disabled = !active || active.stopping;
  get('connect').disabled = connecting || Boolean(active);
  get('download').disabled = !downloading;
  get('compiler').disabled = !token || Boolean(active);
  get('reset-fortran').disabled = !lastTranslation || !modified() || Boolean(active);
  get('live').disabled = editing();
  get('fortran-title').textContent = fortranOnly ? 'Fortran input' : modified() ? 'Edited Fortran' : 'Generated Fortran';
  get('run-fortran').textContent = editing() ? 'Compile and Run Fortran' : 'Run Fortran';
  get('fortran-only').disabled = Boolean(active);
  get('suggest-annotations').disabled = !sourceToolsAvailable || !token || Boolean(active) || fortranOnly;
  for (const id of ['translation-int-kind', 'translation-comments']) get(id).disabled = !sourceToolsAvailable || Boolean(active);
  optionControls();
}
function changeLayout() {
  if (active) { get('fortran-only').checked = fortranOnly; return; }
  const enabled = Boolean(get('fortran-only').checked);
  if (enabled !== fortranOnly) {
    if (enabled) {
      previousEditMode = editing();
      get('edit-fortran').checked = true;
      get('live').checked = false;
      clearTimeout(debounce); debounce = null; pending = false;
    } else get('edit-fortran').checked = previousEditMode;
  }
  fortranOnly = enabled;
  get('run-layout').classList.toggle('fortran-only', enabled);
  for (const id of ['python-panel', 'python-output-panel', 'python-example-label', 'example',
    'translate', 'live-label', 'edit-fortran-label', 'reset-fortran', 'run-python', 'run-both', 'compare', 'comparison-note',
    'translation-tools', 'example-note']) get(id).hidden = enabled;
  if (enabled) get('annotation-preview-panel').hidden = true;
  get('fortran-example-label').hidden = get('fortran-example').hidden = !enabled;
  get('page-heading').textContent = enabled ? 'Fortran playground' : 'Python → Fortran';
  get('eyebrow').textContent = enabled ? 'EDIT · COMPILE · RUN' : 'TRANSLATE · RUN · COMPARE';
  get('page-intro').textContent = enabled ? 'Write and run a single-file Fortran program with your chosen compiler.' : 'Run a single-file program in Python and its Fortran translation.';
  get('execution-note').textContent = enabled ? 'Code runs only when you click Compile and Run Fortran.' : 'Programs run only when you click a Run or Compare button. Live mode only translates.';
  get('build-heading').textContent = enabled ? 'Compilation' : 'Translation and compilation';
  get('mode-help').textContent = enabled ? 'Compile the Fortran pane directly. Existing python_mod helpers are available automatically; additional libraries are not provided. Switch Fortran only off to return to Python without losing its code or output.' : 'Edit Fortran pauses live translation. Run Both and Compare use edited Fortran. Existing python_mod helpers are available automatically; additional libraries are not provided.';
  document.title = enabled ? 'Fortran playground' : 'p2f — Run Python and Fortran';
  output.setReadOnly(!editing());
  if (enabled && !output.getValue().trim()) { revision++; setOutput(fortranExamples.sum); }
  if (typeof location !== 'undefined' && typeof history !== 'undefined') {
    const url = new URL(location.href);
    if (enabled) url.searchParams.set('mode', 'fortran'); else url.searchParams.delete('mode');
    history.replaceState(null, '', url);
  }
  buttons(); input.refresh(); output.refresh();
}
async function api(path, method = 'GET', payload) {
  const response = await fetch(`${serviceURL}/api/${path}`, {
    method, cache: 'no-store',
    headers: { 'X-P2F-Token': token, ...(payload === undefined ? {} : { 'Content-Type': 'application/json' }) },
    ...(payload === undefined ? {} : { body: JSON.stringify(payload) }),
  });
  let result;
  try { result = await response.json(); }
  catch { throw new Error('Execution service returned an invalid response. Try Reconnect.'); }
  if (!response.ok) {
    const error = new Error(result.error || `Service returned ${response.status}`);
    error.status = response.status;
    throw error;
  }
  return result;
}
async function connect() {
  if (active || connecting) return;
  connecting = true; token = ''; buttons();
  try {
    const configResponse = await fetch('./service.json', { cache: 'no-store' });
    if (!configResponse.ok) throw new Error('Execution service configuration is unavailable.');
    const config = await configResponse.json();
    // A localhost preview always uses its own trusted local service.
    const local = typeof location !== 'undefined' && ['127.0.0.1', 'localhost'].includes(location.hostname);
    serviceURL = local ? '' : (config.url || '').replace(/\/$/, '');
    if (serviceURL) {
      const url = new URL(serviceURL);
      if (url.protocol !== 'https:' || !url.hostname.endsWith('.modal.run') || url.username || url.password || url.search || url.hash || url.pathname !== '/') {
        throw new Error('Expected the HTTPS origin of the deployed Modal service.');
      }
    }
    const session = await api('session');
    const response = await fetch('../vendor/manifest.json', { cache: 'no-store' });
    if (!response.ok) throw new Error('Published transpiler manifest is unavailable.');
    const manifest = await response.json();
    if (manifest.commit !== session.commit) throw new Error('Service and page use different transpiler revisions.');
    token = session.token; commit = session.commit;
    sourceToolsAvailable = session.source_tools === true;
    optionCatalog = session.compiler_options || {};
    const compilers = session.compilers || ['gfortran'];
    get('compiler-intel').disabled = !compilers.includes('ifx');
    get('compiler-intel').textContent = compilers.includes('ifx') ? 'Intel Fortran (experimental)' : 'Intel Fortran (unavailable)';
    get('compiler-flang').disabled = !compilers.includes('flang');
    get('compiler-flang').textContent = compilers.includes('flang') ? 'LLVM Flang (experimental)' : 'LLVM Flang (unavailable)';
    get('compiler-lfortran').disabled = !compilers.includes('lfortran');
    get('compiler-lfortran').textContent = compilers.includes('lfortran') ? 'LFortran (experimental)' : 'LFortran (unavailable)';
    if (!compilers.includes(get('compiler').value)) get('compiler').value = 'gfortran';
    get('connection').textContent = `Connected · p2f ${commit.slice(0, 7)} · ${compilers.join(' / ')} · ${session.timeout} s run limit`;
    get('status').textContent = 'Ready';
    if (get('live').checked) schedule();
  } catch (error) {
    get('connection').textContent = serviceURL ? 'Execution service unavailable. Try Reconnect; a hosted service may take a moment to start.' : 'A hosted execution service has not been configured. For the local preview, run python xrun.py and open http://127.0.0.1:8766/run/.';
    get('diagnostics').textContent = String(error);
    get('status').textContent = 'Not connected';
  } finally { connecting = false; buttons(); }
}
function schedule() {
  clearTimeout(debounce); debounce = null; pending = false;
  if (editing() || modified() || !get('live').checked || !token || !input.getValue().trim()) return;
  debounce = setTimeout(() => {
    debounce = null;
    if (active) pending = true;
    else submit('translate', true);
  }, 750);
}
function show(result) {
  if (result.syntaxStatus) {
    get('status').textContent = 'Waiting for complete, valid Python…';
    return;
  }
  if (result.fortran && !result.mode?.endsWith('-edit')) {
    lastTranslation = result.fortran;
    setOutput(result.fortran);
  }
  function stage(key, outputId, timeId) {
    const value = result[key];
    get(timeId).textContent = value ? `${value.seconds.toFixed(2)} s` : '';
    get(outputId).textContent = value ? `${value.stdout}${value.stderr ? '\n' + value.stderr : ''}` || '(No output)' : 'Not run for this operation.';
  }
  if (!fortranOnly) stage('python', 'python-output', 'python-time');
  stage('execution', 'fortran-output', 'fortran-time');
  stage('build', 'diagnostics', 'build-time');
  if (result.error) get('diagnostics').textContent = result.error;
  if (result.translation_options) get('diagnostics').textContent += `\nTranslation settings: ${JSON.stringify(result.translation_options)}`;
  const comparison = result.matches === undefined ? '' : result.matches ? ' · outputs match' : ' · outputs differ';
  const engine = result.execution || ['fortran', 'both', 'compare'].includes(result.mode) ? ` · ${result.compiler || 'gfortran'}` : '';
  get('status').textContent = `${result.ok ? 'Completed' : 'Failed'}${comparison}${engine} · ${(result.seconds || 0).toFixed(2)} s total`;
  get('freshness').textContent = `Results for current input · p2f ${commit.slice(0, 7)}.${result.fortran ? '' : ' Generated Fortran was not updated.'} Program times include process startup; compilation is shown separately.`;
}
async function submit(mode, automatic = false) {
  if (!token || active) return;
  if (fortranOnly && mode !== 'fortran') return;
  if (editing() && ['fortran', 'both', 'compare'].includes(mode)) mode += '-edit';
  const editJob = mode.endsWith('-edit');
  if (!editJob && mode !== 'python' && modified()) {
    if (automatic || !confirm('Replace your edited Fortran with a new translation?')) return;
  }
  const source = fortranOnly ? '' : input.getValue();
  const fortranSource = output.getValue();
  clearTimeout(debounce); debounce = null; pending = false;
  if ((mode !== 'fortran-edit' && !source.trim()) || new TextEncoder().encode(source).length > 100000) {
    get('status').textContent = 'Enter between 1 byte and 100 KB of Python.'; return;
  }
  if (editJob && (!fortranSource.trim() || new TextEncoder().encode(fortranSource).length > 100000)) {
    get('status').textContent = 'Enter between 1 byte and 100 KB of Fortran.'; return;
  }
  const job = active = { id: null, revision, stopping: false };
  downloading = (editing() || modified()) && Boolean(fortranSource.trim()); buttons();
  get('freshness').textContent = 'Operation in progress; previous results are retained.';
  get('status').textContent = mode === 'translate' ? 'Translating…' : 'Running…';
  try {
    const created = await api('jobs', 'POST', { source, mode, automatic, compiler: get('compiler').value || 'gfortran',
      ...(editJob ? { fortran_source: fortranSource } : {}),
      ...(sourceToolsAvailable ? {translation_options: translationSettings(get)} : {}),
      ...(optionCatalog[get('compiler').value] ? { compiler_options: selectedOptions() } : {}) });
    job.id = created.id;
    if (job.stopping) await api(`jobs/${job.id}/cancel`, 'POST', {});
    while (active === job) {
      const state = await api(`jobs/${job.id}`);
      if (state.state === 'done') {
        if (mode === 'annotate') return job.stopping ? {ok: false, diagnostics: 'Stopped'} : state.result;
        if (job.stopping) get('status').textContent = 'Stopped';
        else if (job.revision === revision) show(state.result);
        else get('status').textContent = 'Previous result discarded — input changed';
        break;
      }
      await new Promise(resolve => setTimeout(resolve, 250));
    }
  } catch (error) {
    // Try to cancel a submitted job when polling loses its connection.
    if (job.id) api(`jobs/${job.id}/cancel`, 'POST', {}).catch(() => {});
    get('status').textContent = 'Execution request failed';
    get('diagnostics').textContent = String(error);
    // A failed job does not invalidate a healthy session. Require Reconnect
    // only for an authentication failure or an unreadable/network response.
    if (!error.status || error.status === 401 || error.status === 403) token = '';
    pending = false;
    clearTimeout(debounce); debounce = null;
    get('live').checked = false;
  } finally {
    if (active === job) active = null;
    buttons();
    if (pending && !editing() && !modified() && get('live').checked && token) { pending = false; submit('translate', true); }
  }
}
get('translate').onclick = () => submit('translate');
get('run-python').onclick = () => submit('python');
get('run-fortran').onclick = () => submit('fortran');
get('run-both').onclick = () => submit('both');
get('compare').onclick = () => submit('compare');
get('connect').onclick = connect;
get('live').onchange = schedule;
get('fortran-only').onchange = changeLayout;
get('edit-fortran').onchange = () => {
  revision++;
  output.setReadOnly(!editing());
  if (editing()) get('live').checked = false;
  schedule(); buttons();
  get('freshness').textContent = editing() ? 'Edit mode: run commands use the Fortran pane directly.' : 'Translation mode: manual edits are retained until explicitly replaced.';
};
get('reset-fortran').onclick = () => {
  if (!lastTranslation || !modified() || !confirm('Discard Fortran edits and restore the last translation?')) return;
  revision++; setOutput(lastTranslation); buttons();
  get('freshness').textContent = 'Last translation restored; run again to refresh results.';
};
get('compiler').onchange = () => {
  revision++;
  optionControls();
  get('freshness').textContent = 'Compiler changed; previous results are retained.';
};
for (const id of ['compiler-preset', 'compiler-warnings', 'compiler-fast-math']) get(id).onchange = () => {
  revision++; optionControls();
  get('freshness').textContent = 'Compiler options changed; previous results are retained.';
};
get('stop').onclick = async () => {
  if (!active) return;
  active.stopping = true; pending = false;
  clearTimeout(debounce); debounce = null;
  get('live').checked = false; buttons();
  get('status').textContent = 'Stopping…';
  try { if (active.id) await api(`jobs/${active.id}/cancel`, 'POST', {}); }
  catch (error) { get('diagnostics').textContent = String(error); }
};
get('load').onclick = () => {
  if (fortranOnly) {
    if (output.getValue().trim() && !confirm('Replace the Fortran input with this example?')) return;
    revision++; setOutput(fortranExamples[get('fortran-example').value || 'sum']); buttons(); output.focus();
    get('freshness').textContent = 'Fortran example loaded; run to refresh results.';
    return;
  }
  if (input.getValue().trim() && !confirm('Replace the Python input with this example?')) return;
  const example = pythonExamples[get('example').value];
  if (!example) return;
  get('live').checked = false; clearTimeout(debounce); debounce = null; pending = false;
  input.setValue(example.source, true); input.focus();
  get('freshness').textContent = 'Example loaded; live translation paused. Use Translate or a Run button when ready.';
};
get('clear').onclick = () => {
  if (fortranOnly) {
    if (output.getValue() && !confirm('Clear the Fortran input?')) return;
    revision++; setOutput(''); buttons();
    for (const id of ['fortran-output', 'diagnostics', 'fortran-time', 'build-time']) get(id).textContent = '';
    get('freshness').textContent = 'Fortran cleared; Python code and output are retained.';
    output.focus(); return;
  }
  if (input.getValue() && !input.undoableClear && !confirm('Clear the Python input?')) return;
  input.setValue('', true);
  if (!editing() && !modified()) { lastTranslation = ''; setOutput(''); }
  buttons();
  for (const id of ['python-output', 'fortran-output', 'diagnostics', 'python-time', 'fortran-time', 'build-time']) get(id).textContent = '';
  input.focus();
};
get('download').onclick = () => {
  if (!downloading) return;
  saveText(output.getValue(), tools.fortranFilename());
};
if (typeof window !== 'undefined') enableColoring(input, output, 'Fortran source').then(() => {
  input.refresh(); output.refresh();
  get('editor-note').textContent = 'Syntax coloring enabled · Tab: indentation · Ctrl+Z: undo · Esc: leave editor.';
}).catch(() => { get('editor-note').textContent = 'Plain-text editors are available.'; });
if (typeof location !== 'undefined' && new URLSearchParams(location.search || '').get('mode') === 'fortran') {
  get('fortran-only').checked = true; changeLayout();
}
await connect();
