"""Where the game keeps its files — from source, from a folder or from an EXE.

b12 gave the project a real release pipeline (installer + PyInstaller builds),
so paths can no longer be "two folders above this file": a packaged game lives
next to its own executable and must be able to write its settings where a
normal user is allowed to (Program Files is read-only).

Three questions, three answers:

    data_root()      read-only game data: assets, locales, packs, build.txt
    writable_root()  config.json, launcher settings, server_config.json
    app_root()       where the game itself sits (exe folder / project folder)

Everything can be overridden for tests or portable installs:
`CIV_DATA_DIR`, `CIV_WRITE_DIR`, `CIV_APP_DIR`.
"""

import os
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_APP_NAME = "Civilization"


def _env(name: str):
    value = os.environ.get(name, "").strip()
    return Path(value) if value else None


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _executable_dir():
    try:
        return Path(sys.executable).resolve().parent
    except (OSError, AttributeError):
        return _PROJECT_ROOT


def app_root() -> Path:
    """The folder the game runs from (folder of the EXE when frozen)."""
    override = _env("CIV_APP_DIR")
    if override is not None:
        return override
    if is_frozen():
        return _executable_dir()
    return _PROJECT_ROOT


def data_root() -> Path:
    """Read-only data: assets, locales, resource packs, build.txt."""
    override = _env("CIV_DATA_DIR")
    if override is not None:
        return override
    if is_frozen():
        # one-folder build: the data lies next to the executable;
        # one-file build: PyInstaller unpacked it into _MEIPASS
        here = _executable_dir()
        if (here / "assets").is_dir() or (here / "build.txt").exists():
            return here
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass)
        return here
    return _PROJECT_ROOT


def writable_root() -> Path:
    """Where the game may write: settings, config, logs.

    Frozen builds use the per-user folder (`%APPDATA%\\Civilization` on Windows,
    `~/.local/share/Civilization` elsewhere) because the install folder may be
    read-only. Running from source keeps everything in the project.
    """
    override = _env("CIV_WRITE_DIR")
    if override is not None:
        return override
    if not is_frozen():
        return _PROJECT_ROOT
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA")
        root = Path(base) if base else Path.home() / "AppData" / "Roaming"
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support"
    else:
        root = Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share"))
    return root / _APP_NAME


def ensure_writable() -> Path:
    root = writable_root()
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError:
        return app_root()
    return root


def config_file(name: str) -> Path:
    """A settings file: user copy first, packaged default as the fallback."""
    writable = writable_root()
    candidate = writable / name
    if candidate.exists():
        return candidate
    packaged = data_root() / name
    if packaged.exists():
        return packaged
    return candidate


def data_file(name: str) -> Path:
    return data_root() / name
