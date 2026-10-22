"""Gate GNU images on compiler identity, source/options, helpers, and reruns."""
import argparse
from pathlib import Path
import shlex
import subprocess
import threading

from xrun import compiler_command, execute
from xverify_flang import verify as verify_helpers

SOURCE = 'program main\nimplicit none\nprint *, 42\nend program main\n'


def verify(runtime, compiler, *, check_version=True):
    if check_version:
        command = shlex.split(compiler_command(compiler))
        version = subprocess.check_output(command + ['-dumpfullversion'], text=True).strip()
        banner = subprocess.check_output(command + ['--version'], text=True)
        if compiler == 'gfortran' and version != '16.2.0':
            raise RuntimeError(f'Expected GNU 16.2.0, got {version}')
        if compiler == 'gfortran17' and (not version.startswith('17.') or '20261018' not in banner):
            raise RuntimeError(f'Expected GNU 17 snapshot 20261018, got {banner}')
    for options, source in [({}, SOURCE),
            ({'preprocess': True}, '#define ANSWER 42\n' + SOURCE.replace('42', 'ANSWER')),
            ({'additional': ['-O3', '-Wall', '-fcheck=bounds', '-fbacktrace']}, SOURCE),
            ({'preset': 'strict', 'standard': '2018'}, SOURCE)]:
        result = execute(runtime, '', 'fortran-edit', threading.Event(), compiler_name=compiler,
                         fortran_source=source, compiler_options=options)
        if not result['ok'] or result['execution']['stdout'].strip() != '42':
            raise RuntimeError(f'{compiler} standalone/options verification failed: {result}')
    failed = execute(runtime, '', 'fortran-compile', threading.Event(), compiler_name=compiler,
                     fortran_source='this is not a Fortran program\n')
    if failed['ok'] or failed['build']['ok']:
        raise RuntimeError('Invalid Fortran unexpectedly compiled')
    compiled = execute(runtime, '', 'fortran-compile', threading.Event(), compiler_name=compiler,
                       fortran_source=SOURCE, retain_executable=True)
    if not compiled['ok'] or not compiled.get('_artifact'):
        raise RuntimeError(f'{compiler} failed to retain an executable: {compiled}')
    rerun = execute(runtime, '', 'fortran-run', threading.Event(), compiler_name=compiler,
                    executable=compiled['_artifact'])
    if not rerun['ok'] or rerun['execution']['stdout'].strip() != '42':
        raise RuntimeError(f'{compiler} retained executable failed: {rerun}')
    verify_helpers(runtime, compiler)
    print(f'{compiler} identity, source/options, diagnostics, retained execution, and helpers: PASS', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compiler', choices=('gfortran', 'gfortran17'), required=True)
    verify(Path('/opt/p2f/runtime'), parser.parse_args().compiler)
