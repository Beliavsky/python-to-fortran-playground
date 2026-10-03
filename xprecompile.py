"""Build compiler-specific helper caches while constructing execution images."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from xrun import compiler_command, helper_identity


def precompile(runtime, name):
    command = compiler_command(name)
    identity = helper_identity(runtime, command)
    cache = runtime / 'precompiled' / name
    with tempfile.TemporaryDirectory(prefix='p2f_precompile_') as directory:
        build = Path(directory)
        # Use upstream's own helper ordering, compiler options and cache metadata.
        (build / 'input.py').write_text(
            'import numpy as np\nx = np.array([1.0, 2.0, 3.0])\nprint(np.mean(x))\n',
            encoding='utf-8')
        subprocess.run([sys.executable, str(runtime / 'xp2f.py'), 'input.py', '--flat',
                        '--compile', '--compiler', command], cwd=build, check=True)
        files = sorted(path for path in build.iterdir()
                       if path.suffix in {'.o', '.mod', '.smod', '.flags'})
        required = {'python.o', 'lapack_d.o', 'python.o.flags', 'lapack_d.o.flags'}
        if not required <= {path.name for path in files}:
            raise RuntimeError('Upstream did not produce both helper objects and cache metadata')
        cache.mkdir(parents=True, exist_ok=True)
        artifacts = {}
        for path in files:
            shutil.copyfile(path, cache / path.name)
            artifacts[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
        (cache / 'manifest.json').write_text(
            json.dumps({'identity': identity, 'artifacts': artifacts}, indent=2) + '\n',
            encoding='utf-8')
    print(f'Precompiled helpers: {name}', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('compiler', choices=('gfortran', 'ifx', 'flang'))
    parser.add_argument('--runtime', type=Path, default=Path('/opt/p2f/runtime'))
    options = parser.parse_args()
    precompile(options.runtime.resolve(), options.compiler)


if __name__ == '__main__':
    main()
