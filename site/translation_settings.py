"""Shared, safe settings and non-semantic Fortran comment filtering."""
def validate_options(selection=None):
    if selection is None:
        selection = {}
    if not isinstance(selection, dict) or set(selection) - {'int_kind', 'preserve_comments'}:
        raise ValueError('Choose supported translation options, not raw arguments.')
    kind = selection.get('int_kind', 'default')
    comments = selection.get('preserve_comments', True)
    if not isinstance(kind, str) or kind not in ('default', 'int32', 'int64') or not isinstance(comments, bool):
        raise ValueError('Invalid integer kind or comment setting.')
    return {'int_kind': kind, 'preserve_comments': comments}


def strip_fortran_comments(source):
    # Do not remove compiler directives, or ! characters inside string literals.
    output = []
    quote = None
    for line in source.splitlines(keepends=True):
        if not quote and line.lstrip().lower().startswith(('!$', '!dir$', '!dec$', '!gcc$')):
            output.append(line)
            continue
        i, cut = 0, None
        while i < len(line):
            char = line[i]
            if quote:
                if char == quote:
                    if i + 1 < len(line) and line[i + 1] == quote:
                        i += 1
                    else:
                        quote = None
            elif char in ('"', "'"):
                quote = char
            elif char == '!':
                cut = i
                break
            i += 1
        if cut is None:
            output.append(line)
        elif line[:cut].strip():
            newline = '\r\n' if line.endswith('\r\n') else '\n' if line.endswith('\n') else ''
            output.append(line[:cut].rstrip() + newline)
    return ''.join(output)
