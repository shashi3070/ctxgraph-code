from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional


BUILD_STATUS_FILE = "build_status.json"


def _status_path(repo_path: Path) -> Path:
    return repo_path / ".ctxgraph" / BUILD_STATUS_FILE


def mark_build_started(repo_path: Path, pid: int) -> dict:
    data = {
        "status": "in_progress",
        "pid": pid,
        "started_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    p = _status_path(repo_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data), encoding="utf-8")
    return data


def mark_build_complete(repo_path: Path, duration_s: float):
    p = _status_path(repo_path)
    data = {"status": "complete", "duration_s": round(duration_s, 1)}
    p.write_text(json.dumps(data), encoding="utf-8")


def mark_build_failed(repo_path: Path, error: str):
    p = _status_path(repo_path)
    data = {"status": "failed", "error": error}
    p.write_text(json.dumps(data), encoding="utf-8")


def get_build_status(repo_path: Path) -> Optional[dict]:
    p = _status_path(repo_path)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data
    except (json.JSONDecodeError, OSError):
        return None


def check_pid_running(pid: int) -> bool:
    """Check if a process with the given PID is still running (Windows)."""
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        kernel32.CloseHandle(handle)
        return True
    except Exception:
        return False


def get_status_message(repo_path: Path) -> Optional[str]:
    status = get_build_status(repo_path)
    if not status:
        return None

    if status["status"] == "in_progress":
        pid = status.get("pid", 0)
        if pid and not check_pid_running(pid):
            mark_build_failed(repo_path, "process exited unexpectedly")
            return (
                "[red]Previous build appears to have crashed. "
                "Run [bold]ctxgraph-code build[/bold] to retry.[/red]"
            )
        started = status.get("started_at", "unknown")
        return (
            f"[yellow]Graph build in progress (PID {pid}, started {started})."
            f" Results may be partial. Check [bold]ctxgraph-code info[/bold]"
            f" for status.[/yellow]"
        )

    if status["status"] == "failed":
        err = status.get("error", "unknown error")
        return (
            f"[red]Previous build failed: {err}."
            f" Run [bold]ctxgraph-code build[/bold] to retry.[/red]"
        )

    return None
