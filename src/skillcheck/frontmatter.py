"""A small, strict reader for the YAML subset used in SKILL.md frontmatter.

Supported: ``key: value`` scalars (plain, single- or double-quoted), block
scalars (``|`` and ``>`` with optional ``-``/``+`` chomping), one level of
nested mappings, and block lists (``- item``). Anything else raises
FrontmatterError with a line number, so a skill that only "works" because a
lenient loader guessed is reported instead of silently accepted.
"""

from __future__ import annotations

import re

KEY_RE = re.compile(r"^([A-Za-z0-9_][A-Za-z0-9_.-]*)\s*:(?:\s+(.*)|\s*)$")


class FrontmatterError(ValueError):
    def __init__(self, message: str, line: int):
        super().__init__(message)
        self.line = line


def split(text: str):
    """Return (frontmatter_lines, body, body_start_line) or raise.

    ``body_start_line`` is 1-based. Frontmatter must open on line 1.
    """
    if text.startswith("\ufeff"):
        text = text[1:]
    lines = text.splitlines()
    if not lines or lines[0].rstrip() != "---":
        raise FrontmatterError("SKILL.md must start with '---' frontmatter", 1)
    for i in range(1, len(lines)):
        if lines[i].rstrip() == "---":
            return lines[1:i], "\n".join(lines[i + 1 :]), i + 2
    raise FrontmatterError("frontmatter is opened with '---' but never closed", 1)


def _scalar(raw: str, line: int):
    raw = raw.strip()
    if raw == "":
        return ""
    if raw[0] == '"':
        m = re.match(r'^"((?:[^"\\]|\\.)*)"\s*(#.*)?$', raw)
        if not m:
            raise FrontmatterError("unterminated double-quoted string", line)
        s = m.group(1)
        return (
            s.replace('\\"', '"').replace("\\n", "\n").replace("\\t", "\t").replace("\\\\", "\\")
        )
    if raw[0] == "'":
        m = re.match(r"^'((?:[^']|'')*)'\s*(#.*)?$", raw)
        if not m:
            raise FrontmatterError("unterminated single-quoted string", line)
        return m.group(1).replace("''", "'")
    if raw[0] == "[":
        if not raw.rstrip().endswith("]"):
            raise FrontmatterError("unterminated flow list", line)
        inner = raw.rstrip()[1:-1].strip()
        if any(ch in inner for ch in "[]{}"):
            raise FrontmatterError("nested flow collections are not supported", line)
        return [_scalar(x, line) for x in inner.split(",")] if inner else []
    if raw[0] == "{":
        raise FrontmatterError("flow mappings ({...}) are not supported; use an indented mapping", line)
    # plain scalar: strip trailing comment
    raw = re.sub(r"\s+#.*$", "", raw)
    if ": " in raw:
        raise FrontmatterError(
            "plain value contains ': ', which YAML rejects; wrap the value in quotes", line
        )
    return raw


def _block(lines, start, style, base_indent):
    """Read a | or > block scalar beginning at lines[start]."""
    out, i, indent = [], start, None
    while i < len(lines):
        ln = lines[i]
        if ln.strip() == "":
            out.append("")
            i += 1
            continue
        cur = len(ln) - len(ln.lstrip(" "))
        if cur <= base_indent:
            break
        if indent is None:
            indent = cur
        if cur < indent:
            break
        out.append(ln[indent:])
        i += 1
    chomp = style[1:] if len(style) > 1 else ""
    while out and out[-1] == "" and chomp != "+":
        out.pop()
    if style[0] == "|":
        text = "\n".join(out)
    else:
        paras, cur_p = [], []
        for ln in out:
            if ln == "":
                paras.append(" ".join(cur_p))
                cur_p = []
            else:
                cur_p.append(ln.strip())
        paras.append(" ".join(cur_p))
        text = "\n".join(p for p in paras)
    if chomp != "-" and text:
        text += "\n"
    return text, i


def parse(fm_lines, first_line=2):
    """Parse frontmatter lines. Returns (dict, {key: line_number})."""
    data, where = {}, {}
    i = 0
    n = len(fm_lines)
    while i < n:
        ln = fm_lines[i]
        lineno = first_line + i
        if ln.strip() == "" or ln.lstrip().startswith("#"):
            i += 1
            continue
        if "\t" in ln[: len(ln) - len(ln.lstrip())]:
            raise FrontmatterError("tabs are not allowed for indentation in YAML", lineno)
        if ln[0] == " ":
            raise FrontmatterError("unexpected indentation", lineno)
        m = KEY_RE.match(ln)
        if not m:
            raise FrontmatterError(f"expected 'key: value', got {ln.strip()[:40]!r}", lineno)
        key, rest = m.group(1), (m.group(2) or "").strip()
        if key in data:
            raise FrontmatterError(f"duplicate key '{key}'", lineno)
        where[key] = lineno
        i += 1
        if rest[:1] in ("|", ">") and re.match(r"^[|>][-+]?\s*(#.*)?$", rest):
            data[key], i = _block(fm_lines, i, rest.split()[0], 0)
        elif rest == "":
            # nested mapping, list, or empty value
            children = []
            while i < n and (fm_lines[i].startswith(" ") or fm_lines[i].strip() == ""):
                children.append((first_line + i, fm_lines[i]))
                i += 1
            while children and children[-1][1].strip() == "":
                children.pop()
            if not children:
                data[key] = None
            elif children[0][1].lstrip().startswith("- ") or children[0][1].strip() == "-":
                items = []
                for cl, c in children:
                    s = c.strip()
                    if not s:
                        continue
                    if not s.startswith("-"):
                        raise FrontmatterError("mixed list and mapping under one key", cl)
                    items.append(_scalar(s[1:], cl))
                data[key] = items
            else:
                sub = {}
                for cl, c in children:
                    s = c.strip()
                    if not s or s.startswith("#"):
                        continue
                    mm = KEY_RE.match(s)
                    if not mm:
                        raise FrontmatterError(f"expected 'key: value' in '{key}'", cl)
                    sub[mm.group(1)] = _scalar(mm.group(2) or "", cl)
                data[key] = sub
        else:
            data[key] = _scalar(rest, lineno)
    return data, where
