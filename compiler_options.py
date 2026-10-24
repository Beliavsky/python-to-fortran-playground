"""Server-owned, ABI-compatible user-code options; reject unlisted arguments."""
from copy import deepcopy
import json
from pathlib import Path
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


PORTABLE = {
    'gfortran': {'optimization': {str(level): [f'-O{level}'] for level in range(4)},
                 'bounds_check': {'true': ['-fcheck=bounds']},
                 'backtrace': {'true': ['-fbacktrace']}},
    'ifx': {'optimization': {str(level): [f'-O{level}'] for level in range(4)},
            'bounds_check': {'true': ['-check', 'bounds']},
            'backtrace': {'true': ['-traceback']}},
    'flang': {'optimization': {str(level): [f'-O{level}'] for level in range(4)}},
    'lfortran': {'optimization': {str(level): ['--fast'] if level else [] for level in range(4)}},
    'ofort': {'optimization': {str(level): [] for level in range(4)}},
}
for name, mappings in PORTABLE.items():
    OPTIONS[name]['portable_options'] = mappings

OPTIONS['lfortran']['portable_option_notes'] = {'optimization': {
    str(level): (f'optimization level {level} mapped to --fast; numbered levels are unavailable; '
                 'strict standard compliance is relaxed.' if level else
                 'optimization level 0 uses default mode; numbered levels are unavailable.')
    for level in range(4)}}
OPTIONS['ofort']['portable_option_notes'] = {'optimization': {
    str(level): f'optimization level {level} ignored; interpreter has no equivalent.'
    for level in range(4)}}

# Same option vocabulary, but a distinct command, image, and helper cache.
OPTIONS['gfortran17'] = deepcopy(OPTIONS['gfortran'])
OPTIONS['gfortran17']['note'] += ' Experimental GNU 17 snapshot, pinned to 2026-10-18.'
for name in ('gfortran', 'gfortran17'):
    OPTIONS[name]['coarray_images'] = {'1': ['-fcoarray=single'],
                                      '2': ['-fcoarray=lib'], '4': ['-fcoarray=lib']}
OPTIONS['ifx']['coarray_images'] = {
    str(count): ['-coarray=single'] if count == 1 else
                ['-coarray=shared', f'-coarray-num-images={count}']
    for count in (1, 2, 4)}
for name, flag in [('flang', '-fcoarray'), ('lfortran', '--coarray=true')]:
    OPTIONS[name]['coarray_images'] = {str(count): [flag] for count in (1, 2, 4)}
    OPTIONS[name]['coarray_note'] = ('Experimental coarrays via Caffeine/GASNet shared memory. '
        'Only sandbox-verified image counts are offered; some language features remain incomplete.')
OPTIONS['lfortran']['coarray_note'] += ' LFortran may print STOP on normal termination.'


COARRAY_RUNTIME_ROOT = Path('/opt/p2f/coarrays')


def coarray_link_flags(compiler, images=None):
    """Read image-owned build metadata; clients cannot provide paths or libraries."""
    if compiler in ('gfortran', 'gfortran17'):
        return ['-lcaf_shmem'] if images in (2, 4) else []
    if compiler not in ('flang', 'lfortran'):
        return []
    try:
        flags = json.loads((COARRAY_RUNTIME_ROOT / compiler / 'link-flags.json').read_text())['flags']
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise RuntimeError(f'{compiler} Caffeine runtime is unavailable in this image') from error
    if not isinstance(flags, list) or not flags or any(not isinstance(flag, str) or not flag for flag in flags):
        raise RuntimeError('Invalid Caffeine build metadata')
    return flags


def coarray_sandbox_runtime(compiler, images):
    # Intel MPI needs CPU topology/syscalls absent from gVisor's virtual kernel.
    return 'vm' if compiler == 'ifx' and type(images) is int and images in (2, 4) else 'gvisor'


def coarray_environment(compiler, images):
    """Trusted runtime settings shared by deployment probes and user execution."""
    if images is None:
        return None
    if compiler == 'ifx':
        return {'FOR_COARRAY_NUM_IMAGES': str(images), 'I_MPI_FABRICS': 'shm',
                'I_MPI_PIN': '0', 'I_MPI_WAIT_MODE': '1', 'I_MPI_HYDRA_IFACE': 'lo',
                # Keep MPI's backing file below the worker's 64 MiB file cap,
                # including four ranks. These are transport buffers, not a
                # limit on the program's total coarray allocation.
                'I_MPI_SHM_HEAP_VSIZE': '8',
                'I_MPI_SHM_CELL_FWD_NUM': '8', 'I_MPI_SHM_CELL_BWD_NUM': '8',
                'I_MPI_SHM_CELL_EXT_NUM_TOTAL': '8',
                'I_MPI_SHM_CELL_FWD_SIZE': '65536', 'I_MPI_SHM_CELL_BWD_SIZE': '65536',
                'I_MPI_SHM_CELL_EXT_SIZE': '65536'}
    if compiler in ('flang', 'lfortran'):
        return {'GASNET_PSHM_NODES': str(images), 'GASNET_MAX_SEGSIZE': '64M',
                'GASNET_EXITTIMEOUT': '2', 'GASNET_BACKTRACE': '0'}
    return {'GFORTRAN_NUM_IMAGES': str(images), 'GFORTRAN_SHARED_MEMORY_SIZE': '64M',
            'GFORTRAN_IMAGE_RESTARTS_LIMIT': '8'}


def coarray_command(compiler, executable, images):
    # Initialize Intel's MPI environment for the executable, separately from ifx.
    return (['p2f-ifx-run'] if compiler == 'ifx' and images is not None else []) + [str(executable)]


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


def user_flags(compiler, selection=None, *, standards=None, coarrays=None):
    if selection is None:
        selection = {}
    if not isinstance(selection, dict) or set(selection) - {'preset', 'warnings', 'fast_math', 'standard', 'preprocess', 'additional', 'images'}:
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
    if 'images' in selection:
        images = selection['images']
        supported_images = spec.get('coarray_images', {}) if coarrays is None else coarrays
        if type(images) is not int or str(images) not in supported_images or str(images) not in spec.get('coarray_images', {}):
            raise ValueError('Choose a verified coarray image count (1, 2, or 4) for a supported compiler.')
        flags.extend(spec['coarray_images'][str(images)])
    for key in ('warnings', 'fast_math', 'preprocess'):
        enabled = selection.get(key, False)
        if not isinstance(enabled, bool) or (enabled and key not in spec['extras']):
            raise ValueError('This compiler does not support the selected option.')
        if enabled:
            flags.extend(spec['extras'][key])
    return additional_flags(spec, flags, selection.get('additional', []))
