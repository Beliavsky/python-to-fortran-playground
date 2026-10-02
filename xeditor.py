"""Bundle the pinned editor assets and MIT notice for static hosting."""
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / 'node_modules/codemirror'
DEST = ROOT / 'site/editor-vendor'

if __name__ == '__main__':
    DEST.mkdir(parents=True, exist_ok=True)
    for source, dest in [('lib/codemirror.js', 'codemirror.js'),
                         ('lib/codemirror.css', 'codemirror.css'),
                         ('mode/python/python.js', 'python.js'),
                         ('mode/fortran/fortran.js', 'fortran.js'),
                         ('LICENSE', 'LICENSE')]:
        shutil.copyfile(SOURCE / source, DEST / dest)
    print('Bundled CodeMirror editor assets and license')
