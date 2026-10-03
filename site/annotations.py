"""Suggest conservative Pyccel-compatible parameter annotations without execution.

Unlike the older header-rewriting tool, insert only annotations into the
original source. Unknown/conflicting evidence is rejected rather than widened.
No imports from submitted source are performed. Return annotations, methods,
nested functions, async functions, decorators and variadic functions are left
alone. This deliberately small inference subset is an aid, not a type checker.
"""
import ast
import json


def infer(node, known, numpy_names):
    if isinstance(node, ast.Constant):
        for cls, name in ((bool, 'bool'), (int, 'int'), (float, 'float'), (complex, 'complex'), (str, 'str')):
            if isinstance(node.value, cls):
                return (name, 0)
    if isinstance(node, ast.Name):
        return known.get(node.id)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        return infer(node.operand, known, numpy_names)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) and node.func.value.id in numpy_names:
        name = node.func.attr
        dtype = None
        for keyword in node.keywords:
            if keyword.arg == 'dtype':
                value = keyword.value
                raw = value.attr if isinstance(value, ast.Attribute) else value.id if isinstance(value, ast.Name) else value.value if isinstance(value, ast.Constant) else None
                dtype = {'int': 'int', 'int32': 'int32', 'int64': 'int64',
                         'float': 'float', 'float32': 'float32', 'float64': 'float',
                         'complex64': 'complex64', 'complex128': 'complex',
                         'bool': 'bool', 'bool_': 'bool'}.get(raw)
                if dtype is None:
                    return None
        if name in ('zeros', 'ones', 'empty', 'full') and node.args:
            shape = node.args[0]
            if isinstance(shape, ast.Constant) and isinstance(shape.value, int) and not isinstance(shape.value, bool):
                rank = 1
            elif isinstance(shape, (ast.Tuple, ast.List)) and shape.elts:
                rank = len(shape.elts)
            else:
                return None
            kind = dtype or 'float'
            if name == 'full' and dtype is None:
                fill = infer(node.args[1], known, numpy_names) if len(node.args) > 1 else None
                if not fill or fill[1]:
                    return None
                kind = fill[0]
            return (kind, rank)
        if name == 'array' and node.args:
            value = node.args[0]
            def literal(item):
                if isinstance(item, (ast.List, ast.Tuple)):
                    if not item.elts:
                        return None
                    parts = [literal(element) for element in item.elts]
                    if any(part is None for part in parts) or len(set(parts)) != 1:
                        return None
                    return parts[0][0], parts[0][1] + 1
                return infer(item, known, numpy_names)
            desc = literal(value)
            return (dtype or desc[0], desc[1]) if desc and desc[1] > 0 else None
    return None


def annotate(source):
    if not isinstance(source, str) or len(source.encode('utf-8')) > 100000:
        raise ValueError('Enter up to 100 KB of Python.')
    tree = ast.parse(source)
    numpy_names = {alias.asname or alias.name for node in tree.body if isinstance(node, ast.Import)
                   for alias in node.names if alias.name == 'numpy'}
    functions = {node.name: node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    bindings = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    bindings.setdefault(target.id, []).append(node.value)
    numpy_names -= set(bindings)  # A rebound alias is not reliable NumPy evidence.
    functions = {name: fn for name, fn in functions.items() if name not in bindings}
    known = {}
    # Only names assigned once are used as evidence. No mutable/rebound types.
    for _ in range(4):
        for name, values in bindings.items():
            if len(values) == 1:
                known[name] = infer(values[0], known, numpy_names)
    calls = {name: [] for name in functions}
    # All direct callers count as evidence, including unresolved calls inside
    # other functions. Unknown evidence blocks suggestions for that parameter.
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in calls:
            calls[node.func.id].append(node)
    parents = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node
    def in_function(node):
        while node in parents:
            node = parents[node]
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
                return True
        return False
    lines = source.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    edits, notes = [], []
    for name, fn in functions.items():
        if isinstance(fn, ast.AsyncFunctionDef) or fn.decorator_list or fn.args.vararg or fn.args.kwarg:
            notes.append(f'{name}: skipped (async, decorated or variadic function).')
            continue
        params = fn.args.posonlyargs + fn.args.args + fn.args.kwonlyargs
        for position, param in enumerate(params):
            if param.annotation is not None:
                notes.append(f'{name}({param.arg}): existing annotation preserved.')
                continue
            evidence = []
            for call in calls[name]:
                value = call.args[position] if position < len(call.args) and position < len(fn.args.posonlyargs + fn.args.args) else None
                keywords = [kw.value for kw in call.keywords if kw.arg == param.arg]
                if keywords:
                    value = keywords[0]
                if value is None:
                    # A missing actual may use a default, but cannot be guessed.
                    positional = fn.args.posonlyargs + fn.args.args
                    defaults = dict(zip([p.arg for p in positional[-len(fn.args.defaults):]] if fn.args.defaults else [], fn.args.defaults))
                    defaults.update({p.arg: d for p, d in zip(fn.args.kwonlyargs, fn.args.kw_defaults) if d is not None})
                    value = defaults.get(param.arg)
                desc = None if in_function(call) or any(isinstance(arg, ast.Starred) for arg in call.args) or any(kw.arg is None for kw in call.keywords) else infer(value, known, numpy_names)
                evidence.append(desc)
            if not evidence or any(item is None for item in evidence) or len(set(evidence)) != 1:
                notes.append(f'{name}({param.arg}): unresolved or conflicting caller types; unchanged.')
                continue
            kind, rank = evidence[0]
            annotation = repr(kind + '[' + ','.join(':' for _ in range(rank)) + ']') if rank else kind if kind in ('bool', 'int', 'float', 'complex', 'str') else repr(kind)
            # AST columns are UTF-8 byte offsets, not Unicode character offsets.
            line = lines[param.end_lineno - 1]
            col = len(line.encode('utf-8')[:param.end_col_offset].decode('utf-8'))
            edits.append((offsets[param.end_lineno - 1] + col, ': ' + annotation))
            notes.append(f'{name}({param.arg}): suggested {annotation}.')
    result = source
    for offset, insertion in sorted(edits, reverse=True):
        result = result[:offset] + insertion + result[offset:]
    # Verify header edits changed nothing except annotation nodes.
    candidate = ast.parse(result)
    for node in ast.walk(candidate):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            original = next((fn for fn in ast.walk(tree) if isinstance(fn, type(node)) and fn.lineno == node.lineno and fn.name == node.name), None)
            if original:
                for arg, old in zip(node.args.posonlyargs + node.args.args + node.args.kwonlyargs,
                                    original.args.posonlyargs + original.args.args + original.args.kwonlyargs):
                    arg.annotation = old.annotation
    if ast.dump(candidate) != ast.dump(tree):
        raise ValueError('Annotation preview would change program structure; no changes applied.')
    notes.append('Suggestions are not a type proof. Return annotations are not inferred; review before applying.')
    if len(result.encode('utf-8')) > 100000:
        raise ValueError('Annotated source exceeds 100 KB; no changes applied.')
    diagnostics = '\n'.join(notes)
    if len(diagnostics) > 50000:
        diagnostics = diagnostics[:50000] + '\n[Annotation diagnostics truncated.]'
    return {'ok': True, 'annotated': result, 'diagnostics': diagnostics, 'count': len(edits)}


def annotate_json(source):
    try:
        return json.dumps(annotate(source), ensure_ascii=False)
    except (ValueError, SyntaxError, RecursionError) as error:
        return json.dumps({'ok': False, 'diagnostics': str(error)})


if __name__ == '__main__':
    from pathlib import Path
    import sys
    print(annotate_json(Path(sys.argv[1]).read_text(encoding='utf-8')))
