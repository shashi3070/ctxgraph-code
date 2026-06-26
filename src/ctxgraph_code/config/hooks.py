from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from ctxgraph_code.graph.builder import get_available_graphs, get_storage


HOOKS_CONFIG = {
    "hooks": {
        "PreToolUse": [
            {
                "matcher": "Bash|Glob|Grep",
                "hooks": [
                    {
                        "type": "command",
                        "command": "python -m ctxgraph_code hook-check",
                        "timeout": 5,
                        "statusMessage": "ctxgraph-code: checking graph...",
                    }
                ],
            }
        ]
    }
}


def install_hooks(project_path: Path, local: bool = False) -> Optional[Path]:
    claude_dir = project_path / ".claude"
    if local:
        settings_path = claude_dir / "settings.local.json"
    else:
        settings_path = claude_dir / "settings.json"

    claude_dir.mkdir(parents=True, exist_ok=True)

    existing = {}
    if settings_path.exists():
        try:
            existing = json.loads(settings_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            existing = {}

    if "hooks" not in existing:
        existing["hooks"] = {}

    existing["hooks"]["PreToolUse"] = HOOKS_CONFIG["hooks"]["PreToolUse"]

    settings_path.write_text(
        json.dumps(existing, indent=2) + "\n", encoding="utf-8"
    )
    return settings_path


def uninstall_hooks(project_path: Path, local: bool = False) -> bool:
    claude_dir = project_path / ".claude"
    settings_path = claude_dir / ("settings.local.json" if local else "settings.json")
    if not settings_path.exists():
        return False

    try:
        existing = json.loads(settings_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False

    if "hooks" in existing:
        existing["hooks"].pop("PreToolUse", None)
        if not existing["hooks"]:
            existing.pop("hooks", None)

    if existing:
        settings_path.write_text(
            json.dumps(existing, indent=2) + "\n", encoding="utf-8"
        )
    else:
        settings_path.unlink(missing_ok=True)
    return True


def compute_hint_summary(repo_path: Path) -> Optional[str]:
    avail = get_available_graphs(repo_path)
    if not avail["_combined"] and not avail["dirs"]:
        return None

    storage: Optional[object] = None
    if avail["_combined"]:
        storage = get_storage(repo_path)
    elif avail["dirs"]:
        storage = get_storage(repo_path, dir_name=avail["dirs"][0])

    if not storage:
        return None

    try:
        stats = storage.stats()
        total_nodes = stats.get("nodes", 0)
        total_edges = stats.get("edges", 0)
        types = stats.get("types", {})

        file_count = types.get("file", 0)
        class_count = types.get("class", 0)
        func_count = types.get("function", 0)

        lines = [
            f"ctxgraph-code: Knowledge graph exists "
            f"({total_nodes} nodes, {total_edges} edges).",
        ]
        if file_count:
            lines.append(f"Files: {file_count} | Classes: {class_count} | Functions: {func_count}.")

        lines.append(
            "Use `ctxgraph-code probe` or `/ctxgraph-code` for help."
        )

        return "\n".join(lines)
    finally:
        storage.close()
