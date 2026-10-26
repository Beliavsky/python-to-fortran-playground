"""Optional pyplot-fortran support and bounded PNG results (standard library only)."""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import struct
import sys
import zlib

ROOT = Path(__file__).resolve().parent
MAX_PNG_BYTES = 1024 * 1024  # Aggregate, before base64; fits hosted result limits.
MAX_PLOTS = 4


def uses_pyplot(source):
    lines = '\n'.join(line.split('!', 1)[0] for line in source.splitlines())
    lines = re.sub(r'&\s*\n\s*&?', ' ', lines)
    return bool(re.search(r'(?:^|;)\s*use\s*(?:,\s*non_intrinsic\s*)?(?:::\s*)?pyplot_module\b', lines, re.I | re.M))


def module_source():
    """Select upstream's default real64 branch without requiring preprocessing."""
    vendor = ROOT / 'vendor/pyplot-fortran'
    data = (vendor / 'src/pyplot_module.F90').read_bytes()
    expected = json.loads((vendor / 'upstream.json').read_text())['sha256']['src/pyplot_module.F90']
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError('Vendored pyplot-fortran checksum mismatch')
    output, active = [], True
    for line in data.decode('utf-8').splitlines():
        if line.startswith('#ifdef '):
            active = False
        elif line.startswith('#elif '):
            active = False
        elif line == '#else':
            active = True
        elif line == '#endif':
            active = True
        elif active:
            output.append(line)
    return '\n'.join(output) + '\n'


def install_module(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / 'pyplot_module.f90'
    path.write_text(module_source(), encoding='utf-8')
    return path


def provides_pyplot(directory):
    """Avoid injecting a second copy when an FPM tree already supplies it."""
    count = 0
    for parent, folders, files in os.walk(directory):
        folders[:] = [name for name in folders if not name.startswith('.') and name not in {'build', 'node_modules'}]
        for name in files:
            count += 1
            if count > 20000:
                return False
            path = Path(parent) / name
            if path.is_symlink() or path.stat().st_size > 1000000:
                continue
            if name == 'fpm.toml':
                import tomllib
                manifest = tomllib.loads(path.read_text(encoding='utf-8-sig'))
                for key, spec in manifest.get('dependencies', {}).items():
                    if key.lower().replace('_', '-') == 'pyplot-fortran':
                        return True
                    if isinstance(spec, dict) and str(spec.get('git', '')).removesuffix('.git').rstrip('/').endswith('/pyplot-fortran'):
                        return True
            elif path.suffix.lower() in {'.f90', '.f95', '.f03', '.f08'}:
                if re.search(r'^\s*module\s+pyplot_module\b', path.read_text(encoding='utf-8-sig', errors='replace'), re.I | re.M):
                    return True
    return False


def plotting_environment(environment=None, *, directory=None):
    env = dict(os.environ if environment is None else environment)
    env['MPLBACKEND'] = 'Agg'
    env['PATH'] = str(Path(sys.executable).parent) + os.pathsep + env.get('PATH', os.environ.get('PATH', ''))
    if directory is not None:
        root = Path(directory).resolve()
        env['MPLCONFIGDIR'] = str(root / '.matplotlib')
        env['XDG_CACHE_HOME'] = str(root / '.cache')
    return env


def snapshot(directory):
    values = {}
    # Only the working directory, never package sources or arbitrary trees.
    with os.scandir(directory) as entries:
        for index, entry in enumerate(entries):
            if index >= 10000:
                break
            if entry.name.lower().endswith('.png') and entry.is_file(follow_symlinks=False):
                info = Path(entry.path).lstat()
                values[entry.name] = (info.st_mtime_ns, info.st_size, info.st_ino)
    return values


def valid_png(data):
    if not data.startswith(b'\x89PNG\r\n\x1a\n'):
        return False
    offset, header, image = 8, False, False
    while offset + 12 <= len(data):
        size = int.from_bytes(data[offset:offset + 4], 'big')
        end = offset + 12 + size
        if end > len(data):
            return False
        kind, payload = data[offset + 4:offset + 8], data[offset + 8:offset + 8 + size]
        if kind in {b'acTL', b'fcTL', b'fdAT'}:
            return False  # This bounded result format supports static PNGs only.
        if zlib.crc32(kind + payload) & 0xffffffff != int.from_bytes(data[end - 4:end], 'big'):
            return False
        if not header:
            if kind != b'IHDR' or size != 13:
                return False
            width, height = struct.unpack('>II', payload[:8])
            if not (0 < width <= 4096 and 0 < height <= 4096 and width * height <= 8000000):
                return False
            header = True
        image |= kind == b'IDAT'
        if kind == b'IEND':
            return size == 0 and end == len(data) and image
        offset = end
    return False


def collect_plots(directory, before=None):
    plots, notes, total = [], [], 0
    before = before or {}
    for name, identity in sorted(snapshot(directory).items()):
        if before.get(name) == identity:
            continue
        if len(plots) >= MAX_PLOTS or identity[1] > MAX_PNG_BYTES - total:
            notes.append('Additional or oversized PNG omitted (four plots / 1 MiB total limit).')
            break
        path = Path(directory) / name
        descriptor = None
        try:
            descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0) | getattr(os, 'O_BINARY', 0))
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or (info.st_mtime_ns, info.st_size, info.st_ino) != identity:
                continue
            with os.fdopen(descriptor, 'rb') as stream:
                descriptor = None
                data = stream.read(MAX_PNG_BYTES - total + 1)
            if len(data) > MAX_PNG_BYTES - total or not valid_png(data):
                notes.append(f'{name}: invalid or oversized PNG omitted.')
                continue
            plots.append({'name': name, 'mime': 'image/png', 'data': base64.b64encode(data).decode('ascii')})
            total += len(data)
        except OSError:
            notes.append(f'{name}: PNG could not be read.')
        finally:
            if descriptor is not None:
                os.close(descriptor)
    return {'plots': plots, 'plot_notes': list(dict.fromkeys(notes))}


def save_plots(result, directory, compiler):
    """CLI download: validate returned images again and ignore supplied paths."""
    destination = Path(directory) / compiler
    files, total = [], 0
    for index, plot in enumerate(result.get('plots', [])[:MAX_PLOTS]):
        data = base64.b64decode(plot.get('data', ''), validate=True)
        total += len(data)
        if total > MAX_PNG_BYTES or plot.get('mime') != 'image/png' or not valid_png(data):
            raise ValueError('Invalid PNG result')
        destination.mkdir(parents=True, exist_ok=True)
        path = destination / f'plot-{index + 1}.png'
        path.write_bytes(data)
        files.append(path)
    return files
