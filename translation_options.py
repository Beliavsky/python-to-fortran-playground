"""Host adapter for the shared browser/service translation settings."""
import importlib.util
from pathlib import Path
spec = importlib.util.spec_from_file_location('playground_translation_settings',
    Path(__file__).resolve().parent / 'site' / 'translation_settings.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
validate_options = module.validate_options
strip_fortran_comments = module.strip_fortran_comments


def cli_options(selection):
    options = validate_options(selection)
    flags = [] if options['int_kind'] == 'default' else ['--int-kind', options['int_kind']]
    return flags
