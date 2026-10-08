"""Server-owned, ABI-compatible user-code options; never accept raw flags."""
OPTIONS = {
    'ofort': {
        'presets': {'default': []}, 'extras': {}, 'standards': {},
        'standard_note': 'ofort interprets a Fortran subset; no standard selection is offered.',
        'note': 'Experimental interpreter. Standalone source only; no compiled python_mod helpers.',
        'interpreter': True,
    },
    'gfortran': {
        'presets': {'default': [], 'debug': ['-O0', '-g', '-fcheck=all', '-fbacktrace'],
                    'optimized': ['-O3'], 'strict': ['-pedantic', '-Wall', '-Wextra']},
        'standards': {year: ['-std=f' + ('95' if year == '1995' else year)]
                      for year in ('1995', '2003', '2008', '2018', '2023')},
        'standard_note': 'GNU rejects extensions beyond the selected standard; this does not guarantee complete language support.',
        'extras': {'warnings': ['-Wall', '-Wextra'], 'fast_math': ['-ffast-math']},
        'note': 'Debug includes bounds and runtime checks. Strict adds pedantic diagnostics; select the standard separately.'},
    'ifx': {
        'presets': {'default': [], 'debug': ['-O0', '-g', '-check', 'all', '-traceback'],
                    'optimized': ['-O3', '-fp-model', 'precise'],
                    'strict': ['-warn', 'all']},
        'standards': {year: ['-stand', flag] for year, flag in
                      [('1995', 'f95'), ('2003', 'f03'), ('2008', 'f08'), ('2018', 'f18'), ('2023', 'f23')]},
        'standard_note': 'Intel reports standard-conformance warnings, rather than necessarily rejecting extensions.',
        'extras': {'warnings': ['-warn', 'all'], 'fast_math': ['-fp-model', 'fast']},
        'note': 'Linux Intel options; Debug enables runtime checks. Strict adds warnings; select the standard separately.'},
    'flang': {
        'presets': {'default': [], 'debug': ['-O0', '-g'],
                    'optimized': ['-O3'], 'strict': ['-pedantic']},
        'extras': {'fast_math': ['-ffast-math']},
        'standards': {}, 'standard_note': 'No standard-selection options have been verified for this compiler.',
        'note': 'Debug adds symbols without promising GNU-style runtime checks. Strict enables pedantic diagnostics.'},
    'lfortran': {
        'presets': {'default': []}, 'extras': {'fast_math': ['--fast']},
        'standards': {}, 'standard_note': 'No standard-selection options have been verified for this compiler.',
        'note': 'Experimental: only Default and advanced --fast are offered; --fast enables additional optimization.'},
}


def user_flags(compiler, selection=None, *, standards=None):
    if selection is None:
        selection = {}
    if not isinstance(selection, dict) or set(selection) - {'preset', 'warnings', 'fast_math', 'standard'}:
        raise ValueError('Choose supported compiler options, not raw flags.')
    spec = OPTIONS[compiler]
    preset = selection.get('preset', 'default')
    if not isinstance(preset, str) or preset not in spec['presets']:
        raise ValueError('This compiler does not support the selected preset.')
    flags = list(spec['presets'][preset])
    standard = selection.get('standard', 'default')
    supported = spec['standards'] if standards is None else standards
    if not isinstance(standard, str) or (standard != 'default' and
            (standard not in supported or standard not in spec['standards'])):
        raise ValueError('This compiler does not support the selected standard.')
    if standard != 'default':
        flags.extend(spec['standards'][standard])
    for key in ('warnings', 'fast_math'):
        enabled = selection.get(key, False)
        if not isinstance(enabled, bool) or (enabled and key not in spec['extras']):
            raise ValueError('This compiler does not support the selected option.')
        if enabled:
            flags.extend(spec['extras'][key])
    return flags
