"""Python chunking via the stdlib ast: functions, classes, methods, module-level code."""
import ast

from . import MAX_LINES, Span, fill


def python_spans(text: str, lines: list[str]) -> list[Span]:
    tree = ast.parse(text)  # SyntaxError propagates -> caller uses fallback

    def start_of(node) -> int:
        s = min([node.lineno] + [d.lineno for d in getattr(node, "decorator_list", [])])
        while s > 1 and lines[s - 2].strip().startswith("#"):  # keep leading comments with the symbol
            s -= 1
        return s

    def region(body, rs, re_, symbol, kind, prefix="") -> list[Span]:
        spans = []
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                spans.append(Span(prefix + node.name, "method" if prefix else "function", start_of(node), node.end_lineno))
            elif isinstance(node, ast.ClassDef):
                s, e = start_of(node), node.end_lineno
                if e - s + 1 <= MAX_LINES:
                    spans.append(Span(prefix + node.name, "class", s, e))
                else:  # big class: one chunk per method + class header/attributes
                    name = prefix + node.name
                    spans.extend(region(node.body, s, e, name, "class", name + "."))
        return fill(lines, spans, rs, re_, symbol, kind)

    return region(tree.body, 1, len(lines), "<module>", "module")
