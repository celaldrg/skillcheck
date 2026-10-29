import json
from pathlib import Path

import pytest

from skillcheck import check_paths, check_skill_dir
from skillcheck.cli import main
from skillcheck.frontmatter import FrontmatterError, parse, split

EX = Path(__file__).resolve().parent.parent / "examples"


def make(tmp_path, name, text, files=None):
    d = tmp_path / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(text, encoding="utf-8")
    for rel, content in (files or {}).items():
        p = d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    return d


def rules(sk):
    return {f.rule for f in sk.findings}


GOOD = "---\nname: {n}\ndescription: Formats SQL files consistently. Use when the user asks to format or tidy SQL.\n---\n\n# Steps\n1. Run it.\n"


def test_good_example_is_clean():
    [sk] = check_paths([EX / "skills"])
    assert sk.name == "pdf-forms"
    assert sk.findings == []


def test_broken_examples_report_expected_rules():
    skills = {sk.dir.name: rules(sk) for sk in check_paths([EX / "broken"])}
    assert {"name-format", "unknown-key", "description-short", "broken-link"} <= skills["Release_Notes"]
    assert "frontmatter" in skills["deploy-helper"]


def test_name_must_match_folder(tmp_path):
    sk = check_skill_dir(make(tmp_path, "sql-format", GOOD.format(n="sql-formatter")))
    assert "name-dir-mismatch" in rules(sk)


@pytest.mark.parametrize("bad", ["SQL", "-sql", "sql-", "sql--fmt", "sql_fmt", "a" * 65])
def test_name_format(tmp_path, bad):
    sk = check_skill_dir(make(tmp_path, bad, GOOD.format(n=bad)))
    assert rules(sk) & {"name-format", "name-length"}


def test_missing_frontmatter(tmp_path):
    sk = check_skill_dir(make(tmp_path, "x", "# no frontmatter\n"))
    assert rules(sk) == {"frontmatter"}


def test_unclosed_frontmatter(tmp_path):
    sk = check_skill_dir(make(tmp_path, "x", "---\nname: x\n"))
    assert sk.findings[0].message.startswith("frontmatter is opened")


def test_description_limits(tmp_path):
    long = "Use when needed. " + "x" * 1100
    sk = check_skill_dir(make(tmp_path, "x", f"---\nname: x\ndescription: {long}\n---\nbody\n"))
    assert "description-length" in rules(sk)
    sk = check_skill_dir(make(tmp_path / "b", "x", "---\nname: x\n---\nbody\n"))
    assert "description-missing" in rules(sk)


def test_description_without_trigger_warns(tmp_path):
    d = "Converts Markdown tables into CSV files and back again, keeping alignment."
    sk = check_skill_dir(make(tmp_path, "x", f"---\nname: x\ndescription: {d}\n---\nbody\n"))
    assert rules(sk) == {"description-no-trigger"}


def test_folded_description(tmp_path):
    text = "---\nname: x\ndescription: >\n  Tidies SQL.\n  Use when the user asks to format SQL.\n---\nbody\n"
    sk = check_skill_dir(make(tmp_path, "x", text))
    assert sk.description == "Tidies SQL. Use when the user asks to format SQL."
    assert sk.findings == []


def test_broken_and_outside_links(tmp_path):
    body = "See [a](ref/a.md), [b](ref/missing.md), [c](../other/c.md), [d](https://example.com), [e](#top).\n```\n[f](not/checked.md)\n```\n"
    sk = check_skill_dir(make(tmp_path, "x", GOOD.format(n="x") + body, {"ref/a.md": "a"}))
    broken = [f for f in sk.findings if f.rule == "broken-link"]
    assert [f.message.split("'")[1] for f in broken] == ["ref/missing.md"]
    assert "link-outside" in rules(sk)


def test_long_body_warns(tmp_path):
    sk = check_skill_dir(make(tmp_path, "x", GOOD.format(n="x") + "line\n" * 600))
    assert "body-long" in rules(sk)


def test_duplicate_names(tmp_path):
    make(tmp_path / "a", "fmt", GOOD.format(n="fmt"))
    make(tmp_path / "b", "fmt", GOOD.format(n="fmt"))
    skills = check_paths([tmp_path])
    assert len(skills) == 2 and all("duplicate-name" in rules(s) for s in skills)


def test_script_not_executable(tmp_path):
    d = make(tmp_path, "x", GOOD.format(n="x"), {"scripts/run.sh": "#!/bin/sh\necho hi\n"})
    (d / "scripts/run.sh").chmod(0o644)
    assert "script-not-executable" in rules(check_skill_dir(d))


def test_lowercase_filename(tmp_path):
    d = tmp_path / "x"
    d.mkdir()
    (d / "skill.md").write_text(GOOD.format(n="x"))
    assert "file-name" in rules(check_skill_dir(d)) or "missing-skill-md" in rules(check_skill_dir(d))


def test_parser_subset():
    lines, body, start = split("---\na: 'it''s'\nb: \"q\\\"x\"\nc:\n  - one\n  - two\nd:\n  k: v\ne: |\n  l1\n  l2\n---\nhi")
    data, where = parse(lines)
    assert data == {"a": "it's", "b": 'q"x', "c": ["one", "two"], "d": {"k": "v"}, "e": "l1\nl2\n"}
    assert body == "hi" and start == 13 and where["c"] == 4
    assert parse(["t: [a, 'b c']"])[0] == {"t": ["a", "b c"]}
    with pytest.raises(FrontmatterError):
        parse(["a: x", "a: y"])
    with pytest.raises(FrontmatterError):
        parse(["a: {b: 1}"])


def test_cli_exit_codes_and_json(tmp_path, capsys):
    assert main([str(EX / "skills")]) == 0
    assert main([str(EX / "broken")]) == 1
    capsys.readouterr()
    assert main([str(EX / "broken"), "--format", "json"]) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["errors"] >= 3
    assert main([str(tmp_path)]) == 2
    d = make(tmp_path, "x", "---\nname: x\ndescription: Converts Markdown tables into CSV files and back again, keeping alignment.\n---\nbody\n")
    assert main([str(d)]) == 0
    assert main([str(d), "--strict"]) == 1
    assert main([str(d), "--strict", "--ignore", "description-no-trigger"]) == 0


def test_github_format(capsys):
    main([str(EX / "broken"), "--format", "github"])
    out = capsys.readouterr().out
    assert out.startswith("::") and "title=skillcheck" in out
