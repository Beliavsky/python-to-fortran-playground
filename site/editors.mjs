export function countLines(text) {
  if (!text) return 0;
  const normalized = text.replace(/\r\n?/g, '\n');
  return normalized.split('\n').length - (normalized.endsWith('\n') ? 1 : 0);
}

// Keep a working textarea until the optional editor finishes loading.
export function createEditor(textarea, counter, onChange = () => {}) {
  let cm = null;
  function changed() {
    if (cm) textarea.value = cm.getValue();
    const count = countLines(textarea.value);
    counter.textContent = `${count} ${count === 1 ? 'line' : 'lines'}`;
    onChange();
  }
  textarea.addEventListener('input', changed);
  const api = {
    getValue: () => cm ? cm.getValue() : textarea.value,
    setValue(value, undoable = false) {
      if (cm && undoable) {
        cm.getDoc().changeGeneration(true);
        cm.replaceRange(value, { line: 0, ch: 0 }, cm.posFromIndex(cm.getValue().length), '+clear');
        cm.getDoc().changeGeneration(true);
      } else if (cm) {
        cm.setValue(value);
      } else {
        textarea.value = value;
        changed();
      }
    },
    setReadOnly(value) {
      textarea.readOnly = value;
      cm?.setOption('readOnly', value);
    },
    focus() { if (cm) cm.focus(); else textarea.focus(); },
    get undoableClear() { return cm !== null; },
    enhance(CodeMirror, mode, label) {
      cm = CodeMirror.fromTextArea(textarea, {
        mode, lineNumbers: true, indentUnit: 4, tabSize: 4,
        indentWithTabs: false, readOnly: textarea.readOnly,
        viewportMargin: 10,
        extraKeys: {
          Tab(editor) {
            if (editor.getOption('readOnly')) return CodeMirror.Pass;
            if (editor.somethingSelected()) editor.indentSelection('add');
            else editor.replaceSelection(' '.repeat(4 - editor.getCursor().ch % 4), 'end', '+input');
          },
          'Shift-Tab': 'indentLess',
          Esc(editor) { editor.getInputField().blur(); },
        },
      });
      cm.getInputField().setAttribute('aria-label', label);
      textarea.labels?.[0]?.addEventListener('click', event => { event.preventDefault(); cm.focus(); });
      cm.on('change', changed);
    },
  };
  const n = countLines(textarea.value);
  counter.textContent = `${n} ${n === 1 ? 'line' : 'lines'}`;
  return api;
}

export async function enableColoring(python, fortran, fortranLabel = 'Generated Fortran (read only)') {
  await import('./editor-vendor/codemirror.js');
  await import('./editor-vendor/python.js');
  await import('./editor-vendor/fortran.js');
  python.enhance(globalThis.CodeMirror, { name: 'python', version: 3 }, 'Python input');
  fortran.enhance(globalThis.CodeMirror, 'text/x-fortran', fortranLabel);
}
