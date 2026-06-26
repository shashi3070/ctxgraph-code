from __future__ import annotations

from pathlib import Path
from typing import Optional


DEFAULT_EXCLUDE = [
    "__pycache__",
    "*.pyc",
    ".git",
    ".svn",
    ".hg",
    "node_modules",
    "venv",
    ".venv",
    "env",
    ".env",
    "dist",
    "build",
    "*.egg-info",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".tox",
    ".nox",
    "migrations",
    "tests/",
    "test/",
    "*.min.js",
    "*.min.css",
]


def should_exclude(
    file_path: Path,
    root_path: Path,
    user_patterns: Optional[list[str]] = None,
) -> bool:
    patterns = list(DEFAULT_EXCLUDE)
    if user_patterns:
        patterns.extend(user_patterns)

    rel_path = _relative_path(file_path, root_path)

    for pattern in patterns:
        if _matches_pattern(rel_path, pattern):
            return True

    return False


def _matches_pattern(path: str, pattern: str) -> bool:
    if pattern.startswith("*."):
        return path.endswith(pattern[1:])

    if pattern.endswith("/"):
        return pattern.rstrip("/") in path.split("/")

    if "*" not in pattern:
        return pattern in path.split("/")

    if pattern.startswith("*") and pattern.endswith("*"):
        mid = pattern[1:-1]
        return mid in path
    elif pattern.startswith("*"):
        return path.endswith(pattern[1:])
    elif pattern.endswith("*"):
        return path.startswith(pattern[:-1])

    return pattern in path


def _relative_path(file_path: Path, root_path: Path) -> str:
    try:
        return str(file_path.relative_to(root_path)).replace("\\", "/")
    except ValueError:
        return file_path.name
