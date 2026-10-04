from app.chunking import MAX_LINES, chunk_file, split_lines


def check(text, chunks):
    """Core invariant: every chunk maps back to the exact source lines."""
    lines = split_lines(text)
    for c in chunks:
        assert 1 <= c.start_line <= c.end_line <= len(lines)
        assert c.content == "\n".join(lines[c.start_line - 1:c.end_line])
        assert c.content.strip() and len(c.content_hash) == 64
        assert c.end_line - c.start_line + 1 <= MAX_LINES
    return {(c.symbol, c.kind): (c.start_line, c.end_line) for c in chunks}


PY = '''"""mod doc"""
import os

X = 1

# helper docs
@decorator
def a(x):
    return x


class K:
    """doc"""
    attr = 1

    def m(self):
        return 2

async def b():
    pass
'''


def test_python_structure_and_exact_lines():
    m = check(PY, chunk_file("m.py", PY, "python"))
    assert m[("a", "function")] == (6, 9)          # leading comment + decorator included
    assert m[("K", "class")] == (12, 17)
    assert m[("b", "function")] == (19, 20)
    assert m[("<module>", "module")] == (1, 4)     # docstring, imports, constants


def test_python_large_class_split_into_methods():
    body = "\n".join(f"    def m{i}(self):\n        a = {i}\n        b = a\n        return b\n" for i in range(40))
    src = f"class Big:\n    \"\"\"doc\"\"\"\n    x = 1\n\n{body}"
    m = check(src, chunk_file("b.py", src, "python"))
    assert ("Big.m0", "method") in m and ("Big.m39", "method") in m and ("Big", "class") in m


def test_large_function_split_contiguously():
    src = "def f():\n" + "\n".join(f"    x{i} = {i}" for i in range(300))
    chunks = chunk_file("f.py", src, "python")
    check(src, chunks)
    assert [c.symbol for c in chunks][:2] == ["f (part 1)", "f (part 2)"]
    assert chunks[0].start_line == 1 and chunks[-1].end_line == 301
    assert all(b.start_line == a.end_line + 1 for a, b in zip(chunks, chunks[1:]))


def test_syntax_error_falls_back():
    src = "def broken(:\n    pass\n"
    m = check(src, chunk_file("x.py", src, "python"))
    assert m == {("<module>", "module"): (1, 2)}


JS = '''// handles checkout
export async function handle(req, res) {
  const s = "}{"; // braces in string
  if (x) { return `}${y}`; }
}

class Cart {
  add() { return 1 }
}

const total = (a, b) => a + b;

export const make = async (x) => {
  return x;
};

interface P { a: number }
type Q = 'a' | 'b';
'''


def test_js_declarations_with_tricky_braces():
    m = check(JS, chunk_file("a.ts", JS, "typescript"))
    assert m == {("handle", "function"): (1, 5), ("Cart", "class"): (7, 9), ("total", "function"): (11, 11),
                 ("make", "function"): (13, 15), ("P", "type"): (17, 17), ("Q", "type"): (18, 18)}


def test_markdown_sections_ignore_fenced_headings():
    md = "intro\n\n# A\ntext\n```\n# not heading\n```\n## B\nmore\n"
    m = check(md, chunk_file("R.md", md, "markdown"))
    assert m == {("<intro>", "section"): (1, 1), ("A", "section"): (3, 7), ("B", "section"): (8, 9)}


def test_fallback_windows_cover_every_line():
    src = "\n".join(f"line {i}" for i in range(1, 201))
    chunks = chunk_file("data.txt", src, None)
    check(src, chunks)
    covered = set()
    for c in chunks:
        covered |= set(range(c.start_line, c.end_line + 1))
    assert covered == set(range(1, 201)) and all(c.kind == "block" for c in chunks)


def test_crlf_and_empty():
    m = check("a = 1\r\nb = 2\r\n", chunk_file("c.py", "a = 1\r\nb = 2\r\n", "python"))
    assert m == {("<module>", "module"): (1, 2)}
    assert chunk_file("e.py", "", "python") == [] and chunk_file("e.py", "\n\n", "python") == []
