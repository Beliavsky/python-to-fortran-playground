"""Fetch one published upstream commit; never read a local transpiler checkout."""
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parent


def build():
    pin = json.loads((ROOT / 'upstream.json').read_text())
    if not re.fullmatch(r'[0-9a-f]{40}', pin['commit']):
        raise ValueError('Pin a complete Git commit SHA in upstream.json')
    if pin['repository'] != 'beliavsky/python-to-fortran':
        raise ValueError('Unexpected upstream repository')
    url = f"https://codeload.github.com/{pin['repository']}/zip/{pin['commit']}"
    request = urllib.request.Request(url, headers={'User-Agent': 'xp2f-playground'})
    with urllib.request.urlopen(request, timeout=120) as response:
        archive = response.read()
    files = {}
    with zipfile.ZipFile(io.BytesIO(archive)) as src:
        for item in src.infolist():
            path = PurePosixPath(item.filename)
            # Only repository-root sources and license notices; no archive extraction.
            if len(path.parts) == 2 and not item.is_dir():
                name = path.name
                if path.suffix in {'.py', '.f90'} or name.upper().startswith(('LICENSE', 'COPYING', 'NOTICE')):
                    files[name] = src.read(item)
    for required in ('xp2f.py', 'python.f90', 'fortran_scan.py'):
        if required not in files:
            raise ValueError(f'Missing upstream file: {required}')
    dest = ROOT / 'site/vendor'
    dest.mkdir(parents=True, exist_ok=True)
    for filename, names in [('upstream.zip', sorted(files)),
                            ('helpers.zip', sorted(n for n in files if n.endswith('.f90')))]:
        with zipfile.ZipFile(dest / filename, 'w', compression=zipfile.ZIP_DEFLATED) as out:
            for name in names:
                info = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                out.writestr(info, files[name])
    manifest = {**pin, 'source_url': f"https://github.com/{pin['repository']}/commit/{pin['commit']}",
                'bundle_sha256': hashlib.sha256((dest / 'upstream.zip').read_bytes()).hexdigest(),
                'files': {n: hashlib.sha256(data).hexdigest() for n, data in sorted(files.items())}}
    (dest / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    print(f"Bundled {len(files)} files from {pin['commit']} into {dest}")


if __name__ == '__main__':
    build()
