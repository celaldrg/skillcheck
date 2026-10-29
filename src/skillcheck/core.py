"""Rules for Agent Skills, following the open SKILL.md format (agentskills.io)."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import frontmatter

NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
KNOWN_KEYS = {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
# Keys some agents read even though the open spec does not define them.
TOLERATED_KEYS = {
    "version", "model", "disable-model-invocation", "user-invocable", "argument-hint",
    "globs", "alwaysApply", "environments", "context", "agent", "hooks", "when_to_use",
}
RESERVED = ("anthropic", "claude")
MAX_NAME = 64
MAX_DESC = 1024
MAX_COMPAT = 500
BODY_LINES_WARN = 500
BODY_TOKENS_WARN = 5000
LINK_RE = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)|!\[[^\]]*\]\(([^)\s]+)\)")
CODE_FENCE_RE = re.compile(r"^\s*(```|~~~)")
TRIGGER_HINTS = re.compile(r"\b(use (it |this )?(when|for|to|if)|when (the )?user|whenever|triggers?)\b", re.I)


@dataclass
class Finding:
    path: str
    line: int
    level: str  # "error" | "warning"
    rule: str
    message: str

    def as_dict(self):
        return self.__dict__.copy()


@dataclass
class Skill:
    dir: Path
    name: str | None = None
    description: str | None = None
    body_lines: int = 0
    approx_tokens: int = 0
    findings: list = field(default_factory=list)


def approx_tokens(text: str) -> int:
    """Rough token estimate: about four characters per token for English prose."""
    return (len(text) + 3) // 4


def _links(body: str, body_start: int):
    in_code = False
    for off, line in enumerate(body.splitlines()):
        if CODE_FENCE_RE.match(line):
            in_code = not in_code
            continue
        if in_code:
            continue
        clean = re.sub(r"`[^`]*`", "", line)
        for m in LINK_RE.finditer(clean):
            yield body_start + off, (m.group(1) or m.group(2))


def check_skill_dir(skill_dir) -> Skill:
    skill_dir = Path(skill_dir)
    sk = Skill(dir=skill_dir)
    md = skill_dir / "SKILL.md"
    rel = str(md)

    def add(line, level, rule, msg):
        sk.findings.append(Finding(rel, line, level, rule, msg))

    if not md.is_file():
        others = [p.name for p in skill_dir.iterdir() if p.name.lower() == "skill.md"] if skill_dir.is_dir() else []
        if others:
            add(1, "error", "file-name", f"found '{others[0]}', but the file must be named exactly 'SKILL.md'")
        else:
            add(1, "error", "missing-skill-md", "no SKILL.md in this folder")
        return sk

    raw = md.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        add(1, "error", "encoding", "SKILL.md is not valid UTF-8")
        return sk
    if "\r\n" in text:
        text = text.replace("\r\n", "\n")

    try:
        fm_lines, body, body_start = frontmatter.split(text)
        data, where = frontmatter.parse(fm_lines)
    except frontmatter.FrontmatterError as e:
        add(e.line, "error", "frontmatter", str(e))
        return sk

    # name
    name = data.get("name")
    nl = where.get("name", 1)
    if name is None or name == "":
        add(nl, "error", "name-missing", "frontmatter needs a 'name'")
    elif not isinstance(name, str):
        add(nl, "error", "name-type", "'name' must be a string")
    else:
        sk.name = name
        if len(name) > MAX_NAME:
            add(nl, "error", "name-length", f"name is {len(name)} characters; the limit is {MAX_NAME}")
        if not NAME_RE.match(name):
            add(nl, "error", "name-format",
                f"name '{name}' must be lowercase letters, digits and single hyphens, not starting or ending with a hyphen")
        if name != skill_dir.resolve().name:
            add(nl, "error", "name-dir-mismatch",
                f"name '{name}' must match its folder name '{skill_dir.resolve().name}'")
        for word in RESERVED:
            if word in name:
                add(nl, "warning", "name-reserved",
                    f"name contains '{word}', which some platforms reject in skill names")

    # description
    desc = data.get("description")
    dl = where.get("description", 1)
    if desc is None or (isinstance(desc, str) and desc.strip() == ""):
        add(dl, "error", "description-missing",
            "frontmatter needs a non-empty 'description'; agents decide when to load a skill from it")
    elif not isinstance(desc, str):
        add(dl, "error", "description-type", "'description' must be a string")
    else:
        d = desc.strip()
        sk.description = d
        if len(d) > MAX_DESC:
            add(dl, "error", "description-length", f"description is {len(d)} characters; the limit is {MAX_DESC}")
        if len(d) < 40:
            add(dl, "warning", "description-short",
                "description is very short; say what the skill does and when to use it")
        elif not TRIGGER_HINTS.search(d):
            add(dl, "warning", "description-no-trigger",
                "description does not say when to use the skill (for example 'Use when ...')")
        if re.search(r"<[A-Za-z/][^>]*>", d):
            add(dl, "warning", "description-xml", "description contains XML-like tags, which some platforms reject")
        if re.match(r"^(I|I'm|I can|You can)\b", d):
            add(dl, "warning", "description-person",
                "write the description in the third person ('Extracts ...'), since it is injected into the system prompt")

    # optional fields
    if "compatibility" in data:
        c = data["compatibility"]
        if not isinstance(c, str):
            add(where["compatibility"], "error", "compatibility-type", "'compatibility' must be a string")
        elif len(c) > MAX_COMPAT:
            add(where["compatibility"], "error", "compatibility-length",
                f"compatibility is {len(c)} characters; the limit is {MAX_COMPAT}")
    if "metadata" in data and not isinstance(data["metadata"], dict):
        add(where["metadata"], "error", "metadata-type", "'metadata' must be a mapping of string keys to string values")
    if "allowed-tools" in data and not isinstance(data["allowed-tools"], (str, list)):
        add(where["allowed-tools"], "error", "allowed-tools-type",
            "'allowed-tools' must be a space-separated string or a list")
    if "license" in data and not isinstance(data["license"], str):
        add(where["license"], "error", "license-type", "'license' must be a string")
    for key in data:
        if key not in KNOWN_KEYS and key not in TOLERATED_KEYS:
            add(where[key], "warning", "unknown-key", f"unknown frontmatter key '{key}'; agents will ignore it")

    # body
    lines = body.splitlines()
    sk.body_lines = len(lines)
    sk.approx_tokens = approx_tokens(body)
    if not body.strip():
        add(body_start, "warning", "body-empty", "SKILL.md has no instructions after the frontmatter")
    if sk.body_lines > BODY_LINES_WARN:
        add(body_start, "warning", "body-long",
            f"body is {sk.body_lines} lines; keep SKILL.md under {BODY_LINES_WARN} and move detail into referenced files")
    elif sk.approx_tokens > BODY_TOKENS_WARN:
        add(body_start, "warning", "body-long",
            f"body is about {sk.approx_tokens} tokens; keep it under {BODY_TOKENS_WARN} and move detail into referenced files")

    # links to bundled files
    root = skill_dir.resolve()
    for line, target in _links(body, body_start):
        if re.match(r"^[a-z][a-z0-9+.-]*:", target, re.I) or target.startswith("#"):
            continue
        path_part = target.split("#", 1)[0].split("?", 1)[0]
        if not path_part:
            continue
        if path_part.startswith("/"):
            add(line, "warning", "absolute-link", f"link '{target}' is absolute; use a path relative to the skill folder")
            continue
        dest = (skill_dir / path_part).resolve()
        if not str(dest).startswith(str(root) + os.sep) and dest != root:
            add(line, "warning", "link-outside", f"link '{target}' points outside the skill folder, which may not ship with it")
        elif not dest.exists():
            add(line, "error", "broken-link", f"link '{target}' points to a file that does not exist")
        if "\\" in target:
            add(line, "warning", "backslash-path", f"link '{target}' uses backslashes; use forward slashes")

    # scripts should be runnable
    scripts = skill_dir / "scripts"
    if scripts.is_dir():
        for p in sorted(scripts.rglob("*")):
            if p.is_file() and p.suffix in (".sh", ".py", ".bash", ".rb", ".pl"):
                head = p.read_bytes()[:2]
                if head == b"#!" and not os.access(p, os.X_OK):
                    sk.findings.append(Finding(str(p), 1, "warning", "script-not-executable",
                                               "script has a shebang but is not executable (chmod +x)"))
    return sk


def find_skill_dirs(path):
    path = Path(path)
    if path.is_file():
        return [path.parent]
    if (path / "SKILL.md").is_file():
        return [path]
    found = []
    for dirpath, dirnames, filenames in os.walk(path):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith(".") or d in (".claude", ".cursor", ".agents", ".github", ".codex"))
        dirnames[:] = [d for d in dirnames if d not in ("node_modules", "__pycache__", "venv", ".venv")]
        if any(f.lower() == "skill.md" for f in filenames):
            found.append(Path(dirpath))
    return found


def check_paths(paths):
    """Check every skill folder under ``paths``. Returns a list of Skill."""
    skills, seen = [], {}
    for p in paths:
        for d in find_skill_dirs(p):
            if d.resolve() in seen:
                continue
            sk = check_skill_dir(d)
            seen[d.resolve()] = sk
            skills.append(sk)
    by_name = {}
    for sk in skills:
        if sk.name:
            by_name.setdefault(sk.name, []).append(sk)
    for name, group in by_name.items():
        if len(group) > 1:
            for sk in group:
                others = ", ".join(str(o.dir) for o in group if o is not sk)
                sk.findings.append(Finding(str(sk.dir / "SKILL.md"), 2, "error", "duplicate-name",
                                           f"skill name '{name}' is also used by {others}"))
    return skills
