import json
import os
from pathlib import Path


def config_path() -> Path:
    root = os.environ.get("XDG_CONFIG_HOME")
    if root:
        return Path(root) / "goodtool" / "config.json"
    return Path.home() / ".config" / "goodtool" / "config.json"


def load_config():
    path = config_path()
    try:
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def save_config(config) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(config, handle, ensure_ascii=False, indent=2)
    os.chmod(path, 0o600)


def remove_config() -> None:
    try:
        config_path().unlink()
    except FileNotFoundError:
        pass
