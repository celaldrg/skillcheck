"""skillcheck: lint Agent Skills (SKILL.md folders) before an agent loads them."""

__version__ = "0.1.0"

from .core import Finding, Skill, check_paths, check_skill_dir  # noqa: F401
