"""Secret-Leak-Check: sucht ein Geheimnis (z. B. das Test-Passwort) in Texten und Dateibäumen.

Nutzbar aus den Tests (find_secret_in_paths) und als Skript:
    python tests/acceptance/leak_check.py <secret> <pfad-oder-datei> [...]
Exit 1, wenn das Geheimnis gefunden wurde (auch URL-/Base64-kodiert).
"""

from __future__ import annotations

import base64
import sys
import urllib.parse
from pathlib import Path


def variants(secret: str) -> list[bytes]:
    raw = secret.encode("utf-8")
    out = {raw, urllib.parse.quote(secret).encode(), urllib.parse.quote_plus(secret).encode(), base64.b64encode(raw)}
    return sorted(out)


def find_secret_in_text(secret: str, text: str | bytes) -> bool:
    data = text.encode("utf-8", "replace") if isinstance(text, str) else text
    return any(v in data for v in variants(secret))


def find_secret_in_paths(secret: str, paths: list[Path]) -> list[Path]:
    hits: list[Path] = []
    for root in paths:
        root = Path(root)
        if not root.exists():
            continue
        files = [root] if root.is_file() else [p for p in root.rglob("*") if p.is_file() and not p.is_symlink()]
        for f in files:
            try:
                if find_secret_in_text(secret, f.read_bytes()):
                    hits.append(f)
            except OSError:
                continue
    return hits


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(2)
    hits = find_secret_in_paths(sys.argv[1], [Path(p) for p in sys.argv[2:]])
    for h in hits:
        print(f"LEAK: {h}")
    sys.exit(1 if hits else 0)
