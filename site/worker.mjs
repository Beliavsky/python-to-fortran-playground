// One initialized interpreter; bridge.py resets upstream modules between jobs.
let runtime = null, busy = false;
async function initialize() {
    const started = performance.now();
    const manifestResponse = await fetch('./vendor/manifest.json', { cache: 'no-cache' });
    if (!manifestResponse.ok) throw new Error('Published transpiler bundle is missing. Run xvendor.py.');
    const manifest = await manifestResponse.json();
    self.postMessage({ type: 'status', text: 'Loading Python runtime…' });
    const base = `https://cdn.jsdelivr.net/pyodide/v${manifest.pyodide}/full/`;
    const { loadPyodide } = await import(base + 'pyodide.mjs');
    const py = await loadPyodide({ indexURL: base });
    self.postMessage({ type: 'status', text: 'Loading the pinned transpiler…' });
    const response = await fetch('./vendor/upstream.zip');
    if (!response.ok) throw new Error('Could not download upstream bundle');
    const zip = await response.arrayBuffer();
    const digest = [...new Uint8Array(await crypto.subtle.digest('SHA-256', zip))]
      .map(x => x.toString(16).padStart(2, '0')).join('');
    if (digest !== manifest.bundle_sha256) throw new Error('Bundle integrity check failed. Reload the page.');
    py.unpackArchive(zip, 'zip', { extractDir: '/upstream' });
    await py.runPythonAsync("import sys\nsys.path.insert(0, '/upstream')");
    const adapter = await fetch('./bridge.py');
    if (!adapter.ok) throw new Error('Could not load translation adapter');
    await py.runPythonAsync(await adapter.text());
    self.postMessage({ type: 'status', text: 'Initializing the transpiler (first load only)…' });
    await py.runPythonAsync('prepare()');
    return { py, manifest, initializationSeconds: (performance.now() - started) / 1000 };
}
self.onmessage = async ({ data }) => {
  if (busy) return;
  busy = true;
  try {
    runtime ??= initialize();
    const { py, manifest, initializationSeconds } = await runtime;
    if (data.type === 'init') {
      self.postMessage({ type: 'ready', initializationSeconds, commit: manifest.commit });
      return;
    }
    const started = performance.now();
    py.globals.set('submission', data.source);
    const result = JSON.parse(await py.runPythonAsync('translate(submission)'));
    py.globals.delete('submission');
    self.postMessage({ type: 'result', id: data.id, ...result,
      translationSeconds: (performance.now() - started) / 1000, commit: manifest.commit });
  } catch (error) {
    self.postMessage({ type: 'fatal', diagnostics: String(error) });
  } finally {
    busy = false;
  }
};
