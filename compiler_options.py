"""Server-owned, ABI-compatible user-code options; reject unlisted arguments."""
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
        'extras': {'warnings': ['-Wall', '-Wextra'], 'fast_math': ['-ffast-math'], 'preprocess': ['-cpp']},
        'note': 'Debug includes bounds and runtime checks. Strict adds pedantic diagnostics; select the standard separately.'},
    'ifx': {
        'presets': {'default': [], 'debug': ['-O0', '-g', '-check', 'all', '-traceback'],
                    'optimized': ['-O3', '-fp-model', 'precise'],
                    'strict': ['-warn', 'all']},
        'standards': {year: ['-stand', flag] for year, flag in
                      [('1995', 'f95'), ('2003', 'f03'), ('2008', 'f08'), ('2018', 'f18'), ('2023', 'f23')]},
        'standard_note': 'Intel reports standard-conformance warnings, rather than necessarily rejecting extensions.',
        'extras': {'warnings': ['-warn', 'all'], 'fast_math': ['-fp-model', 'fast'], 'preprocess': ['-fpp']},
        'note': 'Linux Intel options; Debug enables runtime checks. Strict adds warnings; select the standard separately.'},
    'flang': {
        'presets': {'default': [], 'debug': ['-O0', '-g'],
                    'optimized': ['-O3'], 'strict': ['-pedantic']},
        'extras': {'fast_math': ['-ffast-math'], 'preprocess': ['-cpp']},
        'standards': {}, 'standard_note': 'No standard-selection options have been verified for this compiler.',
        'note': 'Debug adds symbols without promising GNU-style runtime checks. Strict enables pedantic diagnostics.'},
    'lfortran': {
        'presets': {'default': []}, 'extras': {'fast_math': ['--fast'], 'preprocess': ['--cpp']},
        'standards': {}, 'standard_note': 'No standard-selection options have been verified for this compiler.',
        'note': 'Experimental: Default, preprocessing, and advanced --fast are offered; --fast enables additional optimization.'},
}


def single_flags(*values):
    return [[value] for value in values]


# Each group contains mutually exclusive choices, expressed as argument lists.
# No paths, output controls, response files, plugins, or ABI-changing flags.
ADDITIONAL = {
    'gfortran': {
        'optimization': single_flags('-O0', '-O1', '-O2', '-O3', '-Os'),
        'debug': [['-g']], 'checks': single_flags('-fcheck=all', '-fcheck=bounds'),
        'backtrace': single_flags('-fbacktrace', '-fno-backtrace'),
        'warnings': [['-Wall']], 'extra_warnings': [['-Wextra']],
        'implicit_interface': [['-Wimplicit-interface']], 'pedantic': [['-pedantic']],
        'fast_math': single_flags('-ffast-math', '-fno-fast-math'),
        'preprocess': [['-cpp']],
        'traps': [['-ffpe-trap=invalid,zero,overflow']]},
    'ifx': {
        'optimization': single_flags('-O0', '-O1', '-O2', '-O3'),
        'debug': [['-g']], 'checks': [['-check', 'all'], ['-check', 'bounds']],
        'backtrace': [['-traceback']], 'warnings': [['-warn', 'all']],
        'fast_math': [['-fp-model', 'precise'], ['-fp-model', 'fast'], ['-fp-model', 'strict']],
        'preprocess': [['-fpp']]},
    'flang': {
        'optimization': single_flags('-O0', '-O1', '-O2', '-O3'),
        'debug': [['-g']], 'pedantic': [['-pedantic']],
        'fast_math': single_flags('-ffast-math', '-fno-fast-math'), 'preprocess': [['-cpp']]},
    'lfortran': {'fast_math': [['--fast']], 'preprocess': [['--cpp']]},
    'ofort': {},
}
for name, groups in ADDITIONAL.items():
    OPTIONS[name]['additional_options'] = groups


def additional_flags(spec, flags, additional):
    """Validate bounded token lists against the same catalog advertised to clients."""
    if (not isinstance(additional, list) or len(additional) > 32 or
            any(not isinstance(arg, str) or not arg or len(arg) > 128 for arg in additional)):
        raise ValueError('Additional options must be a list of at most 32 short argument strings.')
    if not additional:
        return flags
    groups = spec.get('additional_options', {})
    if not groups:
        raise ValueError('Additional options are unavailable for this compiler/service.')
    choices = [(group, choice) for group, values in groups.items() for choice in values]
    seen = {}
    for arguments, strict in [(flags, False), (additional, True)]:
        index = 0
        while index < len(arguments):
            match = next(((group, choice) for group, choice in choices
                          if arguments[index:index + len(choice)] == choice), None)
            if match is None:
                if strict:
                    raise ValueError(f'Unsupported additional option: {arguments[index]}. Choose an advertised option.')
                index += 1
                continue
            group, choice = match
            if group in seen and seen[group] != choice:
                raise ValueError(f'Conflicting {group} options: {" ".join(seen[group])} and {" ".join(choice)}.')
            seen[group] = choice
            index += len(choice)
    return flags + additional


def user_flags(compiler, selection=None, *, standards=None):
    if selection is None:
        selection = {}
    if not isinstance(selection, dict) or set(selection) - {'preset', 'warnings', 'fast_math', 'standard', 'preprocess', 'additional'}:
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
    for key in ('warnings', 'fast_math', 'preprocess'):
        enabled = selection.get(key, False)
        if not isinstance(enabled, bool) or (enabled and key not in spec['extras']):
            raise ValueError('This compiler does not support the selected option.')
        if enabled:
            flags.extend(spec['extras'][key])
    return additional_flags(spec, flags, selection.get('additional', []))
