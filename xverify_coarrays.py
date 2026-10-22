"""Probe coarray exchange in a deployment sandbox, before advertising support."""
import argparse
import json
from pathlib import Path
import shlex
import sys
import tempfile
import threading

from compiler_options import OPTIONS, coarray_environment, coarray_command, coarray_link_flags
from xrun import compiler_command, run_command

SOURCE = '''program coarray_probe
implicit none
integer :: value[*], other, n
n = num_images()
value = this_image()
sync all
other = value[mod(this_image(), n) + 1]
if (other /= mod(this_image(), n) + 1) error stop 1
sync all
if (this_image() == 1) print '(I0)', n
end program coarray_probe
'''


def probe_output_matches(compiler, output, count):
    lines = [line.strip() for line in output.strip().splitlines()]
    if compiler == 'lfortran':
        # LFortran 0.66's PRIF termination emits STOP on stdout for each image,
        # including normal END PROGRAM. Preserve those messages in user jobs.
        lines = [line for line in lines if line != 'STOP']
    return lines == [str(count)]


def probe(compiler, *, diagnostics=False):
    supported = {}
    with tempfile.TemporaryDirectory(prefix='p2f_coarrays_') as directory:
        work = Path(directory)
        (work / 'probe.f90').write_text(SOURCE, encoding='utf-8')
        for count, flags in OPTIONS[compiler].get('coarray_images', {}).items():
            link_flags = coarray_link_flags(compiler, int(count))
            built = run_command(shlex.split(compiler_command(compiler)) + flags + ['probe.f90', '-o', 'probe.exe'] + link_flags,
                                work, threading.Event(), 8)
            if not built['ok']:
                if diagnostics:
                    print(f'{compiler}, {count} image(s), compile failed: ' +
                          (built.get('stderr', '') or built.get('stdout', ''))[-4000:], file=sys.stderr)
                continue
            ran = run_command(coarray_command(compiler, work / 'probe.exe', int(count)),
                              work, threading.Event(), 4,
                              env=coarray_environment(compiler, int(count)))
            if ran['ok'] and probe_output_matches(compiler, ran['stdout'], count):
                supported[count] = flags
            elif diagnostics:
                print(f'{compiler}, {count} image(s), exchange failed: ' +
                      (ran.get('stderr', '') + ran.get('stdout', ''))[-4000:], file=sys.stderr)
    return supported


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compiler', choices=('gfortran', 'gfortran17', 'ifx', 'flang', 'lfortran'), required=True)
    print(json.dumps(probe(parser.parse_args().compiler, diagnostics=True)))
