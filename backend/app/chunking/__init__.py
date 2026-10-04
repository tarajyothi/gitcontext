"""Code-aware chunking.

Every chunk is an exact, contiguous, 1-based inclusive line range of the source file:
    content == "\\n".join(file_lines[start_line-1:end_line])
Supported structure: Python (ast), JS/TS (declaration scanner), Markdown (headings).
Anything else, or any parse failure, uses a line-window fallback.
"""
import hashlib
import re
from dataclasses import dataclass

MAX_LINES = 120   # chunks longer than this are split into numbered parts
WINDOW = 60       # fallback window size
OVERLAP = 10      # fallback overlap


@dataclass
class Span:
    symbol: str | None
    kind: str
    start: int
    end: int


@dataclass
class CodeChunk:
    file_path: str
    symbol: str | None
    kind: str  # function | method | class | type | section | module | block
    language: str | None
    start_line: int
    end_line: int
    content: str
    content_hash: str


def split_lines(text: str) -> list[str]:
    lines = re.split(r"\r\n|\n|\r", text)
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def trim(lines: list[str], s: int, e: int) -> tuple[int, int] | None:
    while s <= e and not lines[s - 1].strip():
        s += 1
    while e >= s and not lines[e - 1].strip():
        e -= 1
    return (s, e) if s <= e else None


def fill(lines, spans: list[Span], rs: int, re_: int, symbol: str, kind: str) -> list[Span]:
    """Return spans plus 'gap' spans for non-blank code between them inside [rs, re_]."""
    out, cur = [], rs
    for sp in sorted(spans, key=lambda s: s.start):
        sp.start = max(sp.start, cur)  # never overlap the previous span
        if sp.start > cur and (t := trim(lines, cur, sp.start - 1)):
            out.append(Span(symbol, kind, *t))
        out.append(sp)
        cur = sp.end + 1
    if cur <= re_ and (t := trim(lines, cur, re_)):
        out.append(Span(symbol, kind, *t))
    return out


def split_large(lines, sp: Span) -> list[Span]:
    if sp.end - sp.start + 1 <= MAX_LINES:
        return [sp]
    out, i, part = [], sp.start, 1
    while i <= sp.end:
        j = min(i + MAX_LINES - 1, sp.end)
        if t := trim(lines, i, j):
            out.append(Span(f"{sp.symbol} (part {part})" if sp.symbol else None, sp.kind, *t))
            part += 1
        i = j + 1
    return out


def fallback_spans(lines) -> list[Span]:
    n = len(lines)
    if n <= WINDOW:
        t = trim(lines, 1, n)
        return [Span("<module>", "module", *t)] if t else []
    out, i = [], 1
    while i <= n:
        j = min(i + WINDOW - 1, n)
        if t := trim(lines, i, j):
            out.append(Span(None, "block", *t))
        if j == n:
            break
        i = j - OVERLAP + 1
    return out


_HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$")


def markdown_spans(lines) -> list[Span]:
    heads, fence = [], False
    for i, ln in enumerate(lines, 1):
        if ln.lstrip().startswith(("```", "~~~")):
            fence = not fence
        elif not fence and (m := _HEADING.match(ln)):
            heads.append((i, m.group(1)))
    if not heads:
        return []
    spans = []
    if heads[0][0] > 1 and (t := trim(lines, 1, heads[0][0] - 1)):
        spans.append(Span("<intro>", "section", *t))
    for idx, (ln, title) in enumerate(heads):
        end = heads[idx + 1][0] - 1 if idx + 1 < len(heads) else len(lines)
        if t := trim(lines, ln, end):
            spans.append(Span(title, "section", *t))
    return spans


JS_LANGS = {"javascript", "typescript"}


def chunk_file(file_path: str, text: str, language: str | None) -> list[CodeChunk]:
    from .js_chunker import js_spans
    from .python_chunker import python_spans

    lines = split_lines(text)
    if not lines:
        return []
    spans = None
    try:
        if language == "python":
            spans = python_spans(text, lines)
        elif language in JS_LANGS:
            spans = js_spans(lines)
        elif language == "markdown":
            spans = markdown_spans(lines)
    except Exception:  # SyntaxError or scanner failure -> fallback, never crash indexing
        spans = None
    if not spans:
        spans = fallback_spans(lines)
    chunks = []
    for sp in spans:
        for p in split_large(lines, sp):
            content = "\n".join(lines[p.start - 1:p.end])
            chunks.append(CodeChunk(file_path, p.symbol, p.kind, language, p.start, p.end, content,
                                    hashlib.sha256(content.encode()).hexdigest()))
    return chunks
