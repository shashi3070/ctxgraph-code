from __future__ import annotations

import os
import platform
from pathlib import Path


def get_global_claude_commands_dir() -> Path:
    return Path.home() / ".claude" / "commands"
