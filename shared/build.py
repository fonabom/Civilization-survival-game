"""Build identifier shared by client, server and launcher.

There are no marketing versions here: every snapshot of the game is a build with
a short letters+digits id (b7, b42, ...). `build.txt` in the project root holds
the current one; the launcher compares it with the build published on GitHub.
"""

import os
from pathlib import Path

BUILD_FILE = "build.txt"
_FALLBACK = "b0"


def build_file_path() -> Path:
    from shared.paths import data_root
    return data_root() / BUILD_FILE


def read_build() -> str:
    override = os.environ.get("CIV_BUILD")
    if override:
        return override.strip()
    try:
        text = build_file_path().read_text(encoding="utf-8").strip()
    except OSError:
        return _FALLBACK
    return text or _FALLBACK


BUILD = read_build()


def is_newer(remote: str, local: str) -> bool:
    """Build ids are compared numerically when possible (b10 > b9)."""
    def number(value: str):
        digits = "".join(ch for ch in str(value) if ch.isdigit())
        return int(digits) if digits else -1

    remote = (remote or "").strip()
    local = (local or "").strip()
    if not remote or remote == local:
        return False
    remote_number, local_number = number(remote), number(local)
    if remote_number >= 0 and local_number >= 0 and remote_number != local_number:
        return remote_number > local_number
    return remote != local
