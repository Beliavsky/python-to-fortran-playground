"""Format one private job's free-form Fortran file; never execute its contents."""
import io
from pathlib import Path
import sys


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--indent', type=int, choices=(2, 3, 4), default=3)
    options = parser.parse_args()
    # Import only inside this subprocess: fprettify initializes its stdio wrappers.
    from fprettify import reformat_ffile
    source = Path('input.f90').read_text(encoding='utf-8')
    output = io.StringIO()
    # Use the library API so source annotations cannot override trusted settings.
    reformat_ffile(io.StringIO(source), output, orig_filename='input.f90',
                   indent_size=options.indent, case_dict={}, impose_replacements=False)
    sys.stdout.write(output.getvalue())


if __name__ == '__main__':
    main()
