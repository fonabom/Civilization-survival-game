"""Player settings stored in `config.json` next to the game."""

import json
import os
from pathlib import Path

CONFIG_NAME = "config.json"
HOTBAR_SIZE = 9

DEFAULTS = {
    "sound": True,
    "sound_volume": 0.7,
    "music": True,             # b13: background music
    "music_volume": 0.45,
    "tutorial": True,
    "quiet_notifications": False,   # hide "somebody built something" broadcasts
    "language": "en",
    "resource_pack": "default",
    "fullscreen": False,
    "show_debug": True,
    "remember_login": True,
    "last_server": "127.0.0.1:5555",
    "last_login": "",
    "guest_name": "Player",
    "hotbar": [],
    "skip_menu": False,
}


def config_path() -> Path:
    """User settings file.

    From source this is simply config.json in the project. A packaged game
    (installer / PyInstaller) is not allowed to write into its own folder, so
    there the file lives in the per-user folder (b12).
    """
    from shared.paths import config_file
    return config_file(CONFIG_NAME)


class Config:
    def __init__(self, path=None):
        self.path = Path(path) if path else config_path()
        self.data = dict(DEFAULTS)
        self.load()

    # ------------------------------------------------------------------ file io
    def load(self) -> bool:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        if isinstance(raw, dict):
            for key, value in raw.items():
                if key in DEFAULTS:
                    self.data[key] = value
        # keep the hotbar sane
        hotbar = self.data.get("hotbar")
        if not isinstance(hotbar, list):
            hotbar = []
        self.data["hotbar"] = [slot if isinstance(slot, str) else None
                               for slot in hotbar[:HOTBAR_SIZE]]
        self.data["hotbar"] += [None] * (HOTBAR_SIZE - len(self.data["hotbar"]))
        return True

    def save(self) -> bool:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.data, indent=1, ensure_ascii=False),
                                 encoding="utf-8")
            return True
        except OSError as exc:
            print(f"[config] could not save {self.path}: {exc}")
            # a packaged game may only read its own folder (b12): fall back to
            # the per-user settings file instead of losing the settings
            try:
                from shared.paths import ensure_writable
                fallback = ensure_writable() / self.path.name
                fallback.write_text(json.dumps(self.data, indent=1, ensure_ascii=False),
                                    encoding="utf-8")
                self.path = fallback
                return True
            except OSError:
                return False

    # ------------------------------------------------------------------ access
    def get(self, key, default=None):
        return self.data.get(key, DEFAULTS.get(key, default))

    def set(self, key, value):
        self.data[key] = value

    def __getitem__(self, key):
        return self.get(key)

    def __setitem__(self, key, value):
        self.set(key, value)


# Handy module level defaults for other modules
def default_server() -> str:
    return DEFAULTS["last_server"]


def env_language() -> str:
    """CIV_LANG=ru forces a language (used by tests and for quick switching)."""
    return os.environ.get("CIV_LANG", "")
