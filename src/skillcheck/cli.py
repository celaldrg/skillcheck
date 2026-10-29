from __future__ import annotations

import argparse
import json
import sys

from . import __version__
from .core import check_paths


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="skillcheck",
        description="Lint Agent Skills (folders with a SKILL.md) before an agent loads them.",
    )
    ap.add_argument("paths", nargs="*", default=["."], help="skill folders, SKILL.md files, or folders to search (default: .)")
    ap.add_argument("--format", choices=["text", "json", "github"], default="text")
    ap.add_argument("--strict", action="store_true", help="exit 1 on warnings too")
    ap.add_argument("--ignore", action="append", default=[], metavar="RULE", help="skip a rule (repeatable)")
    ap.add_argument("--quiet", "-q", action="store_true", help="print only problems")
    ap.add_argument("--version", action="version", version=f"skillcheck {__version__}")
    args = ap.parse_args(argv)

    skills = check_paths(args.paths)
    for sk in skills:
        sk.findings = [f for f in sk.findings if f.rule not in args.ignore]
    findings = [f for sk in skills for f in sk.findings]
    errors = sum(f.level == "error" for f in findings)
    warnings = sum(f.level == "warning" for f in findings)

    if args.format == "json":
        json.dump({
            "skills": [{
                "dir": str(sk.dir), "name": sk.name, "body_lines": sk.body_lines,
                "approx_tokens": sk.approx_tokens, "findings": [f.as_dict() for f in sk.findings],
            } for sk in skills],
            "errors": errors, "warnings": warnings,
        }, sys.stdout, indent=2, ensure_ascii=False)
        print()
    elif args.format == "github":
        for f in findings:
            print(f"::{f.level} file={f.path},line={f.line},title=skillcheck {f.rule}::{f.message}")
    else:
        if not skills:
            print("no skills found (looked for SKILL.md)", file=sys.stderr)
        for sk in skills:
            label = sk.name or sk.dir.name
            if not sk.findings:
                if not args.quiet:
                    print(f"ok    {label}  ({sk.body_lines} lines, ~{sk.approx_tokens} tokens)")
                continue
            mark = "FAIL" if any(f.level == "error" for f in sk.findings) else "warn"
            print(f"{mark}  {label}  ({sk.body_lines} lines, ~{sk.approx_tokens} tokens)")
            for f in sk.findings:
                print(f"      {f.path}:{f.line}  {f.level}  {f.rule}  {f.message}")
        if not args.quiet or findings:
            print(f"\n{len(skills)} skill(s), {errors} error(s), {warnings} warning(s)")

    if not skills:
        return 2
    if errors or (args.strict and warnings):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
