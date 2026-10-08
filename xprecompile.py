"""Build compiler-specific helper caches while constructing execution images."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading

from xrun import compiler_command, helper_identity, execute, probe_standards
from compiler_options import OPTIONS


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
            json.dumps({'identity': identity, 'artifacts': artifacts,
                        'standards': probe_standards(command, name)}, indent=2) + '\n',
            encoding='utf-8')
    print(f'Precompiled helpers: {name}', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('compiler', choices=('gfortran', 'ifx', 'flang', 'lfortran'))
    parser.add_argument('--runtime', type=Path, default=Path('/opt/p2f/runtime'))
    parser.add_argument('--verify-only', action='store_true', help='Verify cached helpers without recompiling them')
    options = parser.parse_args()
    if options.verify_only:
        manifest_path = options.runtime / 'precompiled' / options.compiler / 'manifest.json'
        manifest = json.loads(manifest_path.read_text())
        manifest['standards'] = probe_standards(compiler_command(options.compiler), options.compiler)
        manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')
    else:
        precompile(options.runtime.resolve(), options.compiler)
    verify_options(options.runtime.resolve(), options.compiler)


def verify_options(runtime, compiler):
    """Reject an optional image if advertised user flags fail with cached helpers."""
    selections = [{'preset': preset} for preset in OPTIONS[compiler]['presets']]
    selections += [{key: True} for key in OPTIONS[compiler]['extras']]
    manifest_path = runtime / 'precompiled' / compiler / 'manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    standards = manifest.get('standards', {})
    ft = '''program option_check
use, intrinsic :: iso_fortran_env, only: real64
use python_mod, only: mean
implicit none
real(real64) :: x(3) = [1.0_real64, 2.0_real64, 3.0_real64]
print *, mean(x)
end program option_check
'''
    for selection in selections:
        result = execute(runtime, '', 'fortran-edit', threading.Event(), compiler_name=compiler,
                         compiler_options=selection, fortran_source=ft)
        if (not result['ok'] or not result.get('precompiled_helpers')
                or 'Build helper:' in result['build']['stdout']
                or float(result['execution']['stdout']) != 2.0):
            raise RuntimeError(f'{compiler} option verification failed: {selection}: {result}')
        print(f'{compiler} user options {selection}: PASS', flush=True)
    # A Fortran-95-compatible caller can still use modern precompiled helpers.
    standard_source = '''program standard_check
use python_mod, only: mean
implicit none
real(kind(1.0d0)) :: x(3) = (/ 1.0d0, 2.0d0, 3.0d0 /)
print *, mean(x)
end program standard_check
'''
    verified = {}
    for year, flags in standards.items():
        result = execute(runtime, '', 'fortran-edit', threading.Event(), compiler_name=compiler,
                         compiler_options={'standard': year}, fortran_source=standard_source)
        if (result['ok'] and result.get('precompiled_helpers')
                and 'Build helper:' not in result['build']['stdout']
                and float(result['execution']['stdout']) == 2.0):
            verified[year] = flags
            print(f'{compiler} Fortran {year} with cached helpers: PASS', flush=True)
        else:
            print(f'{compiler} Fortran {year}: not advertised (verification failed)', flush=True)
    manifest['standards'] = verified
    manifest_path.write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
