// Source-only actions: no loading/applying action executes or auto-translates.
export function translationSettings(get) {
  return {int_kind: get('translation-int-kind').value || 'default',
    preserve_comments: get('translation-comments').checked !== false};
}
export function saveText(text, filename) {
  const url = URL.createObjectURL(new Blob([text], {type: 'text/plain;charset=utf-8'}));
  const link = document.createElement('a'); link.href = url; link.download = filename; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
export function sourceTools({get, input, output, pause, pythonChanged, fortranChanged, requestAnnotations}) {
  let preview = null, pythonName = 'input.py', fortranName = 'input_p.f90', loading = false;
  const report = text => { get('source-tools-status').textContent = text; };
  async function readFile(language) {
    const chooser = get(`file-${language}`), file = chooser.files?.[0];
    chooser.value = '';
    if (!file || loading) return;
    loading = true;
    try {
      if (file.size > 100000) throw new Error('Source file exceeds 100 KB.');
      const bytes = await file.arrayBuffer();
      if (bytes.byteLength > 100000) throw new Error('Source file exceeds 100 KB.');
      const source = new TextDecoder('utf-8', {fatal: true}).decode(bytes);
      if (source.includes('\0')) throw new Error('Expected a UTF-8 text source file, not binary data.');
      const editor = language === 'python' ? input : output;
      if (editor.getValue() && !confirm(`Replace the ${language === 'python' ? 'Python' : 'Fortran'} input with ${file.name}?`)) return;
      pause();
      if (language === 'python') {
        pythonName = file.name; fortranName = pythonName.replace(/\.[^.]*$/, '') + '_p.f90';
        input.setValue(source, true); pythonChanged();
      } else {
        fortranName = file.name; fortranChanged(source);
      }
      preview = null; get('annotation-preview-panel').hidden = true;
      report(`Loaded ${file.name} locally. Nothing was translated or executed.`);
      editor.focus();
    } catch (error) { report(`Could not load file: ${error.message}`); }
    finally { loading = false; }
  }
  for (const language of ['python', 'fortran']) {
    if (get(`load-${language}-file`)) {
      get(`load-${language}-file`).onclick = () => get(`file-${language}`).click();
      get(`file-${language}`).onchange = () => readFile(language);
    }
  }
  get('suggest-annotations').onclick = async () => {
    const source = input.getValue();
    if (!source.trim()) { report('Enter Python code first.'); return; }
    pause(); preview = null;
    get('annotation-preview-panel').hidden = true;
    get('annotation-apply').disabled = get('annotation-download').disabled = true;
    get('source-tools-status').textContent = 'Inferring annotation suggestions without executing code…';
    try {
      const result = await requestAnnotations(source);
      if (!result?.ok) throw new Error(result?.diagnostics || result?.error || 'Annotation request could not complete.');
      preview = {source, text: result.annotated};
      get('annotation-preview').value = result.annotated;
      get('annotation-diagnostics').textContent = result.diagnostics;
      get('annotation-preview-panel').hidden = false;
      get('annotation-apply').disabled = input.getValue() !== source || result.annotated === source;
      get('annotation-download').disabled = false;
      report(`${result.count} annotation suggestion(s). Review the preview before applying.`);
    } catch (error) { report(`Annotation suggestions failed: ${error.message}`); }
  };
  get('annotation-apply').onclick = () => {
    if (!preview) return;
    if (input.getValue() !== preview.source) { report('Python changed after this preview. Generate new suggestions first.'); return; }
    if (!confirm('Apply these annotation suggestions to the Python input?')) return;
    pause(); input.setValue(preview.text, true); pythonChanged();
    get('annotation-apply').disabled = true;
    report('Annotations applied. Nothing was translated or executed; review before running.');
  };
  get('annotation-download').onclick = () => {
    if (preview) saveText(preview.text, pythonName.replace(/\.[^.]*$/, '') + '_annotated.py');
  };
  return {fortranFilename: () => fortranName};
}
