import { createEditor, enableColoring } from '../editors.mjs';

const get = id => document.getElementById(id);
const actions = ['translate', 'run-python', 'run-fortran', 'run-both', 'compare'];
const examples = {
  sum: 'total = 0\nfor i in range(1, 11):\n    total += i * i\nprint(total)\n',
  function: 'def square(x: float) -> float:\n    return x * x\n\nprint(square(1.5))\nprint(square(3.0))\n',
  numpy: 'import numpy as np\nx = np.array([1.0, 2.0, 3.0])\nprint(np.sum(x * x))\n',
};
let token = '', commit = '', revision = 0, active = null, debounce = null, pending = false;
let downloading = false, connecting = false;
let serviceURL = '';
const output = createEditor(get('fortran'), get('fortran-lines'));
const input = createEditor(get('python'), get('python-lines'), () => {
  revision++;
  downloading = false;
  get('download').disabled = true;
  get('freshness').textContent = 'Input changed; previous results are retained.';
  schedule();
});
input.setValue(examples.sum);

function buttons() {
  for (const id of actions) get(id).disabled = !token || Boolean(active);
  get('stop').disabled = !active || active.stopping;
  get('connect').disabled = connecting || Boolean(active);
  get('download').disabled = !downloading;
  get('compiler').disabled = !token || Boolean(active);
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
    const compilers = session.compilers || ['gfortran'];
    get('compiler-intel').disabled = !compilers.includes('ifx');
    get('compiler-intel').textContent = compilers.includes('ifx') ? 'Intel Fortran (experimental)' : 'Intel Fortran (unavailable)';
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
  if (!get('live').checked || !token || !input.getValue().trim()) return;
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
  if (result.fortran) {
    output.setValue(result.fortran); downloading = true;
  }
  function stage(key, outputId, timeId) {
    const value = result[key];
    get(timeId).textContent = value ? `${value.seconds.toFixed(2)} s` : '';
    get(outputId).textContent = value ? `${value.stdout}${value.stderr ? '\n' + value.stderr : ''}` || '(No output)' : 'Not run for this operation.';
  }
  stage('python', 'python-output', 'python-time');
  stage('execution', 'fortran-output', 'fortran-time');
  stage('build', 'diagnostics', 'build-time');
  if (result.error) get('diagnostics').textContent = result.error;
  const comparison = result.matches === undefined ? '' : result.matches ? ' · outputs match' : ' · outputs differ';
  const engine = result.execution || ['fortran', 'both', 'compare'].includes(result.mode) ? ` · ${result.compiler || 'gfortran'}` : '';
  get('status').textContent = `${result.ok ? 'Completed' : 'Failed'}${comparison}${engine} · ${(result.seconds || 0).toFixed(2)} s total`;
  get('freshness').textContent = `Results for current input · p2f ${commit.slice(0, 7)}.${result.fortran ? '' : ' Generated Fortran was not updated.'} Program times include process startup; compilation is shown separately.`;
}
async function submit(mode, automatic = false) {
  if (!token || active) return;
  const source = input.getValue();
  clearTimeout(debounce); debounce = null; pending = false;
  if (!source.trim() || new TextEncoder().encode(source).length > 100000) {
    get('status').textContent = 'Enter between 1 byte and 100 KB of Python.'; return;
  }
  const job = active = { id: null, revision, stopping: false };
  downloading = false; buttons();
  get('freshness').textContent = 'Operation in progress; previous results are retained.';
  get('status').textContent = mode === 'translate' ? 'Translating…' : 'Running…';
  try {
    const created = await api('jobs', 'POST', { source, mode, automatic, compiler: get('compiler').value || 'gfortran' });
    job.id = created.id;
    if (job.stopping) await api(`jobs/${job.id}/cancel`, 'POST', {});
    while (active === job) {
      const state = await api(`jobs/${job.id}`);
      if (state.state === 'done') {
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
    if (pending && get('live').checked && token) { pending = false; submit('translate', true); }
  }
}
get('translate').onclick = () => submit('translate');
get('run-python').onclick = () => submit('python');
get('run-fortran').onclick = () => submit('fortran');
get('run-both').onclick = () => submit('both');
get('compare').onclick = () => submit('compare');
get('connect').onclick = connect;
get('live').onchange = schedule;
get('compiler').onchange = () => {
  revision++;
  get('freshness').textContent = 'Compiler changed; previous results are retained.';
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
  if (input.getValue().trim() && !confirm('Replace the Python input with this example?')) return;
  input.setValue(examples[get('example').value]);
};
get('clear').onclick = () => {
  if (input.getValue() && !input.undoableClear && !confirm('Clear the Python input?')) return;
  input.setValue('', true); output.setValue('');
  for (const id of ['python-output', 'fortran-output', 'diagnostics', 'python-time', 'fortran-time', 'build-time']) get(id).textContent = '';
  input.focus();
};
get('download').onclick = () => {
  if (!downloading) return;
  const url = URL.createObjectURL(new Blob([output.getValue()], { type: 'text/plain' }));
  const link = document.createElement('a'); link.href = url; link.download = 'input_p.f90'; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
};
if (typeof window !== 'undefined') enableColoring(input, output).then(() => {
  get('editor-note').textContent = 'Syntax coloring enabled · Tab: indentation · Ctrl+Z: undo · Esc: leave editor.';
}).catch(() => { get('editor-note').textContent = 'Plain-text editors are available.'; });
await connect();
