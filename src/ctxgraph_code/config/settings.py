from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional


DEFAULT_CONFIG = {
    "graph": {
        "exclude": [],
        "follow_symlinks": False,
        "max_file_size_mb": 5,
    },
}


class Settings:
    def __init__(self, repo_path: Optional[Path] = None):
        self.repo_path = Path(repo_path).resolve() if repo_path else Path.cwd()
        self._data = dict(DEFAULT_CONFIG)
        self._load()

    def _load(self):
        config_paths = [
            self.repo_path / ".ctxgraph" / "config.toml",
            self.repo_path / ".ctxgraph" / "config.json",
            self.repo_path / "ctxgraph-code.toml",
            self.repo_path / "ctxgraph-code.json",
        ]

        for path in config_paths:
            if path.exists():
                self._load_file(path)
                break

    def _load_file(self, path: Path):
        text = path.read_text(encoding="utf-8")
        if path.suffix == ".json":
            parsed = json.loads(text)
            self._deep_merge(self._data, parsed)
        elif path.suffix == ".toml":
            parsed = self._parse_toml(text)
            self._deep_merge(self._data, parsed)

    @property
    def exclude_patterns(self) -> list[str]:
        return self._data["graph"].get("exclude", [])

    def to_dict(self) -> dict:
        return dict(self._data)

    @staticmethod
    def _parse_toml(text: str) -> dict:
        result = {}
        current_section = result

        for line in text.split("\n"):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("[") and line.endswith("]"):
                section_name = line[1:-1].strip()
                current_section = result.setdefault(section_name, {})
            elif "=" in line:
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip()

                if (value.startswith('"') and value.endswith('"')) or \
                   (value.startswith("'") and value.endswith("'")):
                    value = value[1:-1]
                else:
                    value = Settings._parse_toml_value(value)

                current_section[key] = value

        return result

    @staticmethod
    def _parse_toml_value(value: str):
        if value.lower() in ("true", "false"):
            return value.lower() == "true"
        try:
            if "." in value:
                return float(value)
            return int(value)
        except ValueError:
            return value

    @staticmethod
    def _deep_merge(base: dict, override: dict):
        for key, value in override.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                Settings._deep_merge(base[key], value)
            else:
                base[key] = value


def create_default_config(repo_path: Path):
    config_dir = repo_path / ".ctxgraph"
    config_dir.mkdir(parents=True, exist_ok=True)

    config_path = config_dir / "config.toml"
    if config_path.exists():
        return

    config_path.write_text(
        """# ctxgraph-code configuration

[graph]
# Additional exclude patterns (gitignore is used automatically)
exclude = []
# Follow symlinks when scanning files
follow_symlinks = false
# Skip files larger than this many MB
max_file_size_mb = 5
""",
        encoding="utf-8",
    )
    return config_path
