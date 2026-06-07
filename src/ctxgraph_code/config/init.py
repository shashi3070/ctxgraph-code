from __future__ import annotations

from pathlib import Path
from typing import Optional

from ctxgraph_code.config.settings import create_default_config


def init_project(
    repo_path: Path,
    extensions: Optional[list[str]] = None,
    exclude_patterns: Optional[list[str]] = None,
) -> Path:
    cfg_dir = repo_path / ".ctxgraph"
    cfg_dir.mkdir(parents=True, exist_ok=True)

    create_default_config(repo_path, extensions=extensions, exclude_patterns=exclude_patterns)

    return cfg_dir
