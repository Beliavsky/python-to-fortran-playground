"""Build optional, pinned Caffeine/GASNet runtimes inside compiler images only."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import urllib.request

CAFFEINE_COMMIT = '0f9ca691cbe6782838266a9bb5005ae187f253a2'  # 0.8.4
ASSERT_COMMIT = 'c1443971bacb7015f1110704bfd86f625f9b22ee'  # 3.2.0
GASNET_VERSION = '2025.8.0'
GASNET_SHA256 = 'bd5919099477d1d2f59c247d006e9d1ac017c9190c974f5e069667418e5bf48d'
RUNTIME_ROOT = Path('/opt/p2f/coarrays')


def checkout(repository, commit, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(['git', 'init', str(destination)], check=True)
    subprocess.run(['git', '-C', str(destination), 'fetch', '--depth=1',
                    'https://github.com/' + repository + '.git', commit], check=True)
    subprocess.run(['git', '-C', str(destination), 'checkout', '--detach', 'FETCH_HEAD'], check=True)
    actual = subprocess.check_output(['git', '-C', str(destination), 'rev-parse', 'HEAD'], text=True).strip()
    if actual != commit:
        raise RuntimeError('Dependency commit did not match its pin')


def download_gasnet(destination):
    url = f'https://github.com/BerkeleyLab/gasnet/releases/download/gex-{GASNET_VERSION}/GASNet-{GASNET_VERSION}.tar.gz'
    with urllib.request.urlopen(url, timeout=120) as response:
        data = response.read()
    if hashlib.sha256(data).hexdigest() != GASNET_SHA256:
        raise RuntimeError('GASNet archive checksum mismatch')
    destination.write_bytes(data)


def pinned_installer(source, archive):
    """Replace the upstream moving GASNet download with our verified local archive."""
    lines = source.splitlines()
    for name, value in [('GASNET_VERSION', GASNET_VERSION), ('GASNET_SOURCE_URL', archive.as_uri())]:
        matches = [i for i, line in enumerate(lines) if line.startswith(name + '=')]
        if len(matches) != 1:
            raise RuntimeError('Caffeine installer layout changed: ' + name)
        lines[matches[0]] = f'{name}="{value}"'
    text = '\n'.join(lines) + '\n'
    # 0.8.4 omits a separator before LFortran's include directory. Conda CFLAGS
    # ending in -g0 would otherwise become the invalid single token -g0-I/path.
    broken = '  APPEND_CFLAGS+=-I$($FC --print-c-include-dir)'
    if text.count(broken) != 1:
        raise RuntimeError('Caffeine LFortran include-flag workaround needs review')
    return text.replace(broken, '  APPEND_CFLAGS+=" -I$($FC --print-c-include-dir)"')


def build(compiler):
    prefix = RUNTIME_ROOT / compiler
    prefix.mkdir(parents=True, exist_ok=True)
    manifest = prefix / 'link-flags.json'
    manifest.unlink(missing_ok=True)  # An interrupted rebuild cannot advertise stale support.
    with tempfile.TemporaryDirectory(prefix='p2f_caffeine_') as directory:
        work = Path(directory)
        source = work / 'caffeine'
        checkout('BerkeleyLab/caffeine', CAFFEINE_COMMIT, source)
        checkout('BerkeleyLab/assert', ASSERT_COMMIT, source / 'build' / 'dependencies' / 'assert')
        installer = source / 'install.sh'
        text = installer.read_text()
        if 'DEPENDENCIES_DIR="build/dependencies"' not in text:
            raise RuntimeError('Caffeine dependency directory changed')
        archive = work / f'GASNet-{GASNET_VERSION}.tar.gz'
        download_gasnet(archive)
        installer.write_text(pinned_installer(text, archive))
        environment = dict(os.environ)
        environment.update(FC='flang-23' if compiler == 'flang' else 'lfortran',
                           CC='clang-23' if compiler == 'flang' else 'clang',
                           CXX='clang++-23' if compiler == 'flang' else 'clang++',
                           CI='true', MAKE='make')
        if compiler == 'lfortran':
            includes = subprocess.check_output(['lfortran', '--print-c-include-dir'], text=True).strip()
            environment['CPPFLAGS'] = f'-I{includes} -DCAF_IMPORT_CONSTANTS'
        log = prefix / 'install.log'
        try:
            with log.open('w') as output:
                subprocess.run(['bash', str(installer), '--yes', '--enable-cmake', '--network=smp',
                                '--disable-threads', '--prefix=' + str(prefix)],
                               cwd=source, env=environment, stdout=output, stderr=subprocess.STDOUT,
                               check=True, timeout=1200)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            lines = log.read_text(errors='replace').splitlines()
            selected = set(range(max(0, len(lines) - 25), len(lines)))
            for index, line in enumerate(lines):
                if any(word in line.lower() for word in ('error:', 'error ', 'failed', 'not found')):
                    selected.update(range(max(0, index - 2), min(len(lines), index + 4)))
            print('\n'.join(lines[index] for index in sorted(selected)), flush=True)
            raise
        environment['PKG_CONFIG_PATH'] = str(prefix / 'lib' / 'pkgconfig')
        def pkg(*arguments):
            return shlex.split(subprocess.check_output(['pkg-config', *arguments, 'caffeine'],
                               env=environment, text=True))
        # Follow Caffeine's native-client link order; include the system libraries
        # from pkg-config and retain its runtime library search paths.
        flags = (pkg('--libs-only-L') +
                 [flag for flag in pkg('--libs-only-other') if flag.startswith('-Wl,-rpath')] +
                 pkg('--libs-only-l'))
        if not flags or not all((prefix / 'lib' / name).is_file() for name in
                               ('libcaffeine-smp-seq.a', 'libgasnet-smp-seq.a')):
            raise RuntimeError('Caffeine installation is missing its link flags or libraries')
        for name, dependency in [('caffeine', source), ('assert', source / 'build' / 'dependencies' / 'assert'),
                                 ('gasnet', source / 'build' / 'dependencies' / f'GASNet-{GASNET_VERSION}')]:
            notices = prefix / 'share' / 'licenses' / name
            notices.mkdir(parents=True, exist_ok=True)
            for file in dependency.iterdir():
                if file.is_file() and file.name.lower().startswith(('license', 'copying', 'copyright')):
                    shutil.copyfile(file, notices / file.name)
        manifest.write_text(json.dumps({'flags': flags, 'caffeine_commit': CAFFEINE_COMMIT,
                                       'assert_commit': ASSERT_COMMIT, 'gasnet': GASNET_VERSION}))
    print(f'{compiler}: installed experimental Caffeine shared-memory runtime', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compiler', choices=('flang', 'lfortran'), required=True)
    compiler = parser.parse_args().compiler
    try:
        build(compiler)
    except Exception as error:
        (RUNTIME_ROOT / compiler / 'link-flags.json').unlink(missing_ok=True)
        print(f'WARNING: {compiler} Caffeine installation failed: {error}', flush=True)
        print('Coarrays stay unavailable; ordinary compilation remains enabled.', flush=True)


if __name__ == '__main__':
    main()
