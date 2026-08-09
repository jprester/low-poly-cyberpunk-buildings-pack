"""Small, Blender-independent helpers for release automation."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """Return a recursively merged copy without mutating either input."""
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("Configuration root must be a JSON object")
    return data


def resolve_from_repository(path_text: str) -> Path:
    path = Path(path_text).expanduser()
    if not path.is_absolute():
        path = REPOSITORY_ROOT / path
    return path.resolve()


def display_path(path: Path) -> str:
    """Prefer portable repository-relative paths in generated reports."""
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPOSITORY_ROOT).as_posix()
    except ValueError:
        return resolved.name


def write_json_atomic(path: Path, data: Dict[str, Any]) -> None:
    """Write complete JSON or leave the previous report untouched on failure."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=str(path.parent),
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_name = handle.name
            json.dump(data, handle, indent=2, sort_keys=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except Exception:
        if temporary_name and os.path.exists(temporary_name):
            os.unlink(temporary_name)
        raise
