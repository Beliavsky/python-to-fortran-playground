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
    const annotations = await fetch('./annotations.py');
    if (!annotations.ok) throw new Error('Could not load annotation helper');
    py.FS.writeFile('/annotations.py', await annotations.text());
    const settings = await fetch('./translation_settings.py');
    if (!settings.ok) throw new Error('Could not load translation settings');
    py.FS.writeFile('/translation_settings.py', await settings.text());
    await py.runPythonAsync("sys.path.insert(0, '/')\nfrom annotations import annotate_json");
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
    py.globals.set('translation_options_json', JSON.stringify(data.translation_options || {}));
    let result;
    try {
      const syntaxStatus = data.automatic ? py.runPython('syntax_status(submission)') : 'complete';
      result = data.type === 'annotate' ? JSON.parse(await py.runPythonAsync('annotate_json(submission)'))
        : syntaxStatus === 'complete' ? JSON.parse(await py.runPythonAsync('translate(submission, options=json.loads(translation_options_json))'))
        : { ok: false, syntaxStatus };
    } finally {
      py.globals.delete('submission');
      py.globals.delete('translation_options_json');
    }
    self.postMessage({ type: 'result', id: data.id, ...result,
      translationSeconds: (performance.now() - started) / 1000, commit: manifest.commit });
  } catch (error) {
    self.postMessage({ type: 'fatal', diagnostics: String(error) });
  } finally {
    busy = false;
  }
};
