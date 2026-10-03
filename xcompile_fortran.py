"""Compile a submitted single-file Fortran program with trusted compiler options."""
import argparse
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys


def helper_modules(source):
    # Normalize only for detecting USE, never rewrite the submitted program.
    lines = '\n'.join(line.split('!', 1)[0] for line in source.splitlines())
    lines = re.sub(r'&\s*\n\s*&?', ' ', lines)
    return re.findall(r'(?:^|;)\s*use\b\s*(?:,\s*non_intrinsic\s*)?(?:::\s*)?(\w+)\b',
                      lines, re.I | re.M)


def uses_python_mod(source):
    return 'python_mod' in [name.lower() for name in helper_modules(source)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--compiler', required=True)
    parser.add_argument('--user-flags', default='[]')
    options = parser.parse_args()
    parts = shlex.split(options.compiler)
    helpers = []
    source = Path('input_p.f90').read_text(encoding='utf-8')
    if any(name.lower().endswith(('_mod', '_module')) for name in helper_modules(source)):
        sys.path.insert(0, str(options.runtime.resolve()))
        # Reuse the pinned upstream's ordering and cache checks, not its transpiler.
        import xp2f
        # The upstream scanner handles generated USE lines. Also recognize
        # user-written USE ::, continuations and semicolon-separated statements.
        explicit = []
        defined = xp2f._modules_defined_in_source(source)
        for module in helper_modules(source):
            module = module.lower()
            if module in defined:
                continue
            filename = module.removesuffix('_module').removesuffix('_mod') + '.f90'
            if module == 'time_sleep_mod':
                filename = 'time_sleep_windows.f90' if os.name == 'nt' else 'time_sleep_posix.f90'
            candidate = options.runtime / filename
            if candidate.is_file() and str(candidate) not in explicit:
                explicit.append(str(candidate))
        helper_files, _, missing = xp2f.resolve_helper_files_for_build('input_p.f90', explicit)
        if missing:
            print('Build: FAIL (missing helper modules):', missing, flush=True)
            return 1
        helpers, failure, _ = xp2f._prepare_helper_link_inputs(
            helper_files, parts)
        if failure is not None:
            print('Build: FAIL (helper compile)', flush=True)
            print(failure.stdout, end='')
            print(failure.stderr, end='', file=sys.stderr)
            return failure.returncode or 1
    command = parts + json.loads(options.user_flags) + helpers + ['input_p.f90', '-o', 'input_p.exe']
    print('Build:', ' '.join(command), flush=True)
    result = subprocess.run(command, check=False)
    print('Build: PASS' if result.returncode == 0 else 'Build: FAIL', flush=True)
    return result.returncode


if __name__ == '__main__':
    sys.exit(main())
