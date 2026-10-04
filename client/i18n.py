"""Tiny localisation layer.

Translations live in `locales/<code>.json` next to the project root, so players
(and resource packs) can add languages without touching the code.
"""

import json
import os
from pathlib import Path

DEFAULT_LANGUAGE = "en"

# Shown in the settings menu; native names on purpose
LANGUAGE_NAMES = {
    "en": "English",
    "pl": "Polski",
    "ru": "Русский",
}


def locales_dir() -> Path:
    from shared.paths import data_root
    return data_root() / "locales"


class I18n:
    def __init__(self, directory=None):
        self.directory = Path(directory) if directory else locales_dir()
        self.language = DEFAULT_LANGUAGE
        self._cache = {}
        self._strings = self._load(DEFAULT_LANGUAGE)

    # ------------------------------------------------------------------ loading
    def _load(self, language: str) -> dict:
        if language in self._cache:
            return self._cache[language]
        path = self.directory / f"{language}.json"
        data = {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            if language != DEFAULT_LANGUAGE:
                data = dict(self._load(DEFAULT_LANGUAGE))
        self._cache[language] = data
        return data

    def available_languages(self) -> list:
        """Language codes that have a file on disk (at least English)."""
        found = set()
        try:
            for entry in os.listdir(self.directory):
                if entry.endswith(".json"):
                    found.add(entry[:-5])
        except OSError:
            pass
        if DEFAULT_LANGUAGE not in found:
            found.add(DEFAULT_LANGUAGE)
        return sorted(found, key=lambda code: (code != DEFAULT_LANGUAGE, code))

    def set_language(self, language: str) -> bool:
        if not language:
            return False
        self.language = language
        self._strings = self._load(language)
        return True

    def next_language(self) -> str:
        codes = self.available_languages()
        try:
            index = codes.index(self.language)
        except ValueError:
            index = -1
        return codes[(index + 1) % len(codes)]

    # ------------------------------------------------------------------ lookup
    def has(self, key: str) -> bool:
        return key in self._strings

    def translate(self, key: str, **kwargs) -> str:
        text = self._strings.get(key)
        if text is None:
            text = self._load(DEFAULT_LANGUAGE).get(key, key)
        if kwargs:
            try:
                return text.format(**kwargs)
            except (KeyError, IndexError, ValueError):
                return text
        return text

    def item_name(self, item_id: str) -> str:
        """Human readable item/structure/resource name for an id."""
        for prefix in ("item.", "structure.", "resource."):
            key = prefix + item_id
            if self.has(key):
                return self.translate(key)
        return str(item_id).replace("_", " ").title()


_instance = I18n()


def t(key: str, **kwargs) -> str:
    """Translate a key, e.g. t("notify.gathered", n=3, item=t("item.wood"))."""
    return _instance.translate(key, **kwargs)


def set_language(language: str) -> bool:
    return _instance.set_language(language)


def get_language() -> str:
    return _instance.language


def available_languages() -> list:
    return _instance.available_languages()


def language_name(code: str) -> str:
    return LANGUAGE_NAMES.get(code, code.upper())


def name_of(identifier: str) -> str:
    """Name of an item / structure / resource type by id."""
    return _instance.item_name(identifier)
