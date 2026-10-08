"""Build immutable helper artifacts without depending on playground application code."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import zipfile


def build(root, name, command):
    manifest = json.loads((root / 'site/vendor/manifest.json').read_text())
    pin = json.loads((root / 'upstream.json').read_text())
    if any(manifest[key] != pin[key] for key in ('repository', 'commit', 'pyodide')):
        raise ValueError('Vendor bundle differs from upstream.json')
    archive = (root / 'site/vendor/upstream.zip').read_bytes()
    if hashlib.sha256(archive).hexdigest() != manifest['bundle_sha256']:
        raise ValueError('Upstream bundle checksum mismatch')
    runtime = root / 'runtime'
    runtime.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
        for filename in bundle.namelist():
            if Path(filename).name != filename or '\\' in filename:
                raise ValueError('Unexpected bundled path')
            (runtime / filename).write_bytes(bundle.read(filename))
    version = subprocess.run(shlex.split(command) + ['--version'], capture_output=True,
                             text=True, check=True, timeout=15)
    identity = {'command': command, 'version': version.stdout + version.stderr,
                'sources': {filename: hashlib.sha256((runtime / filename).read_bytes()).hexdigest()
                            for filename in ('python.f90', 'lapack_d.f90')}}
    with tempfile.TemporaryDirectory(prefix='p2f_helpers_') as directory:
        job = Path(directory)
        (job / 'input.py').write_text('import numpy as np\nx = np.array([1.0, 2.0, 3.0])\nprint(np.mean(x))\n')
        subprocess.run([sys.executable, str(runtime / 'xp2f.py'), 'input.py', '--flat',
                        '--compile', '--compiler', command], cwd=job, check=True)
        files = sorted(path for path in job.iterdir() if path.suffix in {'.o', '.mod', '.smod', '.flags'})
        if not {'python.o', 'lapack_d.o', 'python.o.flags', 'lapack_d.o.flags'} <= {p.name for p in files}:
            raise RuntimeError('Both helper objects and cache metadata are required')
        cache = runtime / 'precompiled' / name
        cache.mkdir(parents=True, exist_ok=True)
        artifacts = {}
        for path in files:
            shutil.copyfile(path, cache / path.name)
            artifacts[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
        (cache / 'manifest.json').write_text(json.dumps({'identity': identity, 'artifacts': artifacts,
                                                       'standards': {}}, indent=2) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('compiler', choices=('gfortran', 'ifx', 'flang', 'lfortran'))
    parser.add_argument('--command', required=True)
    parser.add_argument('--root', type=Path, default=Path('/opt/p2f'))
    args = parser.parse_args()
    build(args.root.resolve(), args.compiler, args.command)
