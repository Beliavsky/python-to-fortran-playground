"""Server-owned, ABI-compatible user-code options; never accept raw flags."""
OPTIONS = {
    'gfortran': {
        'presets': {'default': [], 'debug': ['-O0', '-g', '-fcheck=all', '-fbacktrace'],
                    'optimized': ['-O3'], 'strict': ['-std=f2018', '-pedantic', '-Wall', '-Wextra']},
        'extras': {'warnings': ['-Wall', '-Wextra'], 'fast_math': ['-ffast-math']},
        'note': 'Debug includes bounds and runtime checks. Strict checks Fortran 2018.'},
    'ifx': {
        'presets': {'default': [], 'debug': ['-O0', '-g', '-check', 'all', '-traceback'],
                    'optimized': ['-O3', '-fp-model', 'precise'],
                    'strict': ['-stand', 'f18', '-warn', 'all']},
        'extras': {'warnings': ['-warn', 'all'], 'fast_math': ['-fp-model', 'fast']},
        'note': 'Linux Intel options; Debug enables runtime checks. Strict reports standards warnings.'},
    'flang': {
        'presets': {'default': [], 'debug': ['-O0', '-g'],
                    'optimized': ['-O3'], 'strict': ['-pedantic']},
        'extras': {'fast_math': ['-ffast-math']},
        'note': 'Debug adds symbols without promising GNU-style runtime checks. Strict enables pedantic diagnostics.'},
    'lfortran': {
        'presets': {'default': []}, 'extras': {'fast_math': ['--fast']},
        'note': 'Experimental: only Default and advanced --fast are offered; --fast enables additional optimization.'},
}


def user_flags(compiler, selection=None):
    if selection is None:
        selection = {}
    if not isinstance(selection, dict) or set(selection) - {'preset', 'warnings', 'fast_math'}:
        raise ValueError('Choose supported compiler options, not raw flags.')
    spec = OPTIONS[compiler]
    preset = selection.get('preset', 'default')
    if not isinstance(preset, str) or preset not in spec['presets']:
        raise ValueError('This compiler does not support the selected preset.')
    flags = list(spec['presets'][preset])
    for key in ('warnings', 'fast_math'):
        enabled = selection.get(key, False)
        if not isinstance(enabled, bool) or (enabled and key not in spec['extras']):
            raise ValueError('This compiler does not support the selected option.')
        if enabled:
            flags.extend(spec['extras'][key])
    return flags
