"""JS/TS chunking: top-level function/class/arrow/type declarations found by a brace-aware scanner.

Limitation: regex literals containing quotes/braces can confuse the scanner; if no end is found the
declaration is skipped and its lines fall into a module/gap chunk (still exact line ranges).
"""
import re

from . import Span, fill

_DECLS = [
    (re.compile(r"^(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s*([\w$]+)"), "function"),
    (re.compile(r"^(?:export\s+)?(?:default\s+)?(?:abstract\s+)?class\s+([\w$]+)"), "class"),
    (re.compile(r"^(?:export\s+)?(?:const|let|var)\s+([\w$]+)\s*(?::[^=]+)?=\s*(?:async\s*)?(?:\(|function\b|[\w$]+\s*=>)"), "function"),
    (re.compile(r"^(?:export\s+)?(?:declare\s+)?(?:interface|type|enum)\s+([\w$]+)"), "type"),
]
_CONT = ("=>", "=", "(", ",", "+", "-", "*", "/", "&&", "||", "?", ":", "|", "&")


def _find_end(lines: list[str], i: int) -> int | None:
    """Zero-based index of the line where the declaration starting at line i ends."""
    depth, seen_brace, state = 0, False, None
    for li in range(i, len(lines)):
        line, j = lines[li], 0
        while j < len(line):
            c, two = line[j], line[j:j + 2]
            if state == "/*":
                if two == "*/":
                    state, j = None, j + 1
            elif state == "`":
                if c == "\\":
                    j += 1
                elif c == "`":
                    state = None
            elif state in ("'", '"'):
                if c == "\\":
                    j += 1
                elif c == state:
                    state = None
            else:
                if two == "//":
                    break
                if two == "/*":
                    state, j = "/*", j + 1
                elif c in "'\"`":
                    state = c
                elif c in "({[":
                    depth += 1
                    seen_brace = seen_brace or c == "{"
                elif c in ")}]":
                    depth -= 1
                    if c == "}" and depth <= 0 and seen_brace:
                        return li
                elif c == ";" and depth <= 0:
                    return li
            j += 1
        if state in ("'", '"'):
            state = None  # unterminated quote: don't let it swallow the file
        if depth <= 0 and state is None and not seen_brace and not line.rstrip().endswith(_CONT):
            return li
    return None


def js_spans(lines: list[str]) -> list[Span]:
    spans, i = [], 0
    while i < len(lines):
        line = lines[i]
        hit = next(((m.group(1), kind) for rx, kind in _DECLS if (m := rx.match(line))), None) if line[:1].strip() else None
        end = _find_end(lines, i) if hit else None
        if hit and end is not None:
            s = i + 1
            while s > 1 and lines[s - 2].strip().startswith(("//", "/*", "*", "@")):
                s -= 1
            spans.append(Span(hit[0], hit[1], s, end + 1))
            i = end + 1
        else:
            i += 1
    return fill(lines, spans, 1, len(lines), "<module>", "module")
