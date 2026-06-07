from __future__ import annotations

from pathlib import Path

from ctxgraph_code.config.settings import create_default_config


def init_project(repo_path: Path) -> Path:
    cfg_dir = repo_path / ".ctxgraph"
    cfg_dir.mkdir(parents=True, exist_ok=True)

    create_default_config(repo_path)

    return cfg_dir
