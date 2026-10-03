"""Test unchanged pinned helpers with LFortran; save diagnostics, never deploy."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import shlex
import sys
import tempfile
import threading

from xrun import DEFAULT_LFORTRAN, compare_outputs, run_command

ROOT = Path(__file__).resolve().parent
DEFAULT_COMPILER = DEFAULT_LFORTRAN


def probe_modal(compiler=DEFAULT_COMPILER):
    """Build a test-only image, retrieve its report, and terminate the reader."""
    import modal
    image = (modal.Image.micromamba(python_version='3.12')
             .micromamba_install('lfortran=0.66.0=hd7e4fe6_4', channels=['conda-forge'])
             .pip_install('numpy==2.2.6'))
    for name in ('xrun.py', 'xprobe_lfortran.py', 'upstream.json',
                 'site/vendor/manifest.json', 'site/vendor/upstream.zip'):
        image = image.add_local_file(ROOT / name, '/opt/p2f/' + name, copy=True)
    image = image.run_commands(
        'mkdir -p /opt/p2f/runtime',
        "PYTHONPATH=/opt/p2f python -c \"from pathlib import Path; from xrun import unpack_runtime; unpack_runtime(Path('/opt/p2f/runtime'))\"",
        'PYTHONPATH=/opt/p2f python /opt/p2f/xprobe_lfortran.py --out /opt/p2f/lfortran_results.json'
        + ' --compiler ' + shlex.quote(compiler))
    app = modal.App.lookup('p2f-playground-execution', create_if_missing=False)
    with modal.enable_output():
        image = image.build(app)
    reader = modal.Sandbox.create(
        'python', '-c', "from pathlib import Path; print(Path('/opt/p2f/lfortran_results.json').read_text())",
        app=app, image=image, runtime='gvisor', block_network=True,
        cpu=(0.5, 1.0), memory=(512, 1024), timeout=60,
        secrets=[], volumes={}, include_oidc_identity_token=False)
    try:
        reader.wait()
        report = json.loads(reader.stdout.read())
    finally:
        reader.terminate()
    report['probe_image'] = image.object_id
    report['package'] = 'conda-forge/linux-64/lfortran-0.66.0-hd7e4fe6_4.conda'
    report['package_sha256'] = '0af9ff64eed869ebf98aefe5a11e4ede0d409673a610532b577c416586280c0d'
    report['upstream'] = json.loads((ROOT / 'upstream.json').read_text(encoding='utf-8'))
    return report


def probe(runtime, compiler=DEFAULT_COMPILER):
    report = {'compiler': compiler, 'helpers': {}, 'translations': {}}
    compiler_parts = shlex.split(compiler)
    cancel = threading.Event()
    with tempfile.TemporaryDirectory(prefix='p2f_lfortran_probe_') as directory:
        work = Path(directory)
        report['version'] = run_command(compiler_parts + ['--version'], work, cancel, 15)
        report['compiler_options'] = run_command(compiler_parts + ['--help'], work, cancel, 15)
        for name in ('lapack_d.f90', 'python.f90'):
            source = runtime / name
            build = work / source.stem
            build.mkdir()
            result = run_command(compiler_parts + ['-c', str(source), '-o', source.stem + '.o'],
                                 build, cancel, 120)
            report['helpers'][name] = {
                'sha256': hashlib.sha256(source.read_bytes()).hexdigest(), **result,
                'artifacts': {p.name: p.stat().st_size for p in build.iterdir()}}
            print(f'{name}: {"PASS" if result["ok"] else "FAIL"} ({result["seconds"]:.2f} s)', flush=True)
        cases = {
            'arithmetic': 'total = 0\nfor i in range(1, 11):\n    total += i*i\nprint(total)\n',
            'NumPy helpers': 'import numpy as np\nx = np.array([1.0, 2.0, 3.0])\nprint(np.mean(x), np.std(x))\n',
            'LAPACK': 'import numpy as np\na = np.array([[2.0,0.0],[0.0,4.0]])\nb = np.array([2.0,8.0])\nx = np.linalg.solve(a,b)\nprint(x[0],x[1])\n',
        }
        for index, (name, source) in enumerate(cases.items()):
            build = work / f'case_{index}'
            build.mkdir()
            # Reuse only objects made by this probe with these exact options.
            # Avoid recompiling the large helpers for every test program.
            for helper, outcome in report['helpers'].items():
                if outcome['ok']:
                    helper_build = work / Path(helper).stem
                    for artifact in helper_build.iterdir():
                        if artifact.suffix in {'.o', '.mod', '.smod'}:
                            shutil.copy2(artifact, build / artifact.name)
                    (build / (Path(helper).stem + '.o.flags')).write_text(
                        ' '.join(compiler_parts), encoding='utf-8')
            (build / 'input.py').write_text(source, encoding='utf-8')
            command = [sys.executable, str(runtime / 'xp2f.py'), 'input.py', '--flat',
                       '--compile', '--compiler', compiler]
            result = {'build': run_command(command, build, cancel, 120)}
            if (build / 'input_p.f90').exists():
                result['fortran'] = (build / 'input_p.f90').read_text(encoding='utf-8')
            if result['build']['ok']:
                result['python'] = run_command([sys.executable, 'input.py'], build, cancel, 30)
                result['execution'] = run_command([str(build / 'input_p.exe')], build, cancel, 30)
                result['matches'] = (result['python']['ok'] and result['execution']['ok']
                                     and compare_outputs(result['python']['stdout'],
                                                         result['execution']['stdout']))
            report['translations'][name] = result
            print(f'{name}: {"PASS" if result.get("matches") else "FAIL"}', flush=True)
    report['ready'] = (all(item['ok'] for item in report['helpers'].values())
                       and all(item.get('matches', False) for item in report['translations'].values()))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', type=Path, default=Path('/opt/p2f/runtime'))
    parser.add_argument('--compiler', default=DEFAULT_COMPILER)
    parser.add_argument('--out', type=Path, default=Path('lfortran_results.json'))
    parser.add_argument('--modal', action='store_true', help='Use a pinned test-only Modal image (incurs compute usage)')
    options = parser.parse_args()
    if not options.modal and not shutil.which(shlex.split(options.compiler)[0]):
        parser.error('LFortran is not on PATH; install/activate its Conda environment first')
    report = probe_modal(options.compiler) if options.modal else probe(options.runtime.resolve(), options.compiler)
    options.out.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(f'LFortran ready: {report["ready"]}; diagnostics: {options.out}', flush=True)


if __name__ == '__main__':
    main()
