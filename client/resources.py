"""Resource packs - swappable texture sets.

Layout of a pack:

    resourcepacks/<pack folder>/
        pack.json          {"name": ..., "author": ..., "description": ...}
        textures/*.png     same file names as assets/ (player.png, tree.png, ...)

Any texture missing from the pack falls back to the built-in `assets/` folder,
so a pack may contain just one recoloured image. The built-in textures are
treated as the "default" pack.
"""

import json
from pathlib import Path

import pygame

PACKS_DIRNAME = "resourcepacks"
DEFAULT_PACK = "default"


def project_root() -> Path:
    from shared.paths import data_root
    return data_root()


def packs_directory() -> Path:
    return project_root() / PACKS_DIRNAME


def assets_directory() -> Path:
    return project_root() / "assets"


class ResourcePack:
    def __init__(self, pack_id: str, directory=None, meta=None):
        self.id = pack_id
        self.directory = Path(directory) if directory else None
        self.meta = meta or {}
        self.textures = {}

    @property
    def name(self) -> str:
        return self.meta.get("name", self.id)

    @property
    def description(self) -> str:
        return self.meta.get("description", "")

    @property
    def is_default(self) -> bool:
        return self.directory is None

    def texture_path(self, filename: str):
        if self.directory is None:
            return None
        for sub in ("textures", ""):
            candidate = self.directory / (sub if sub else "") / filename
            if candidate.is_file():
                return candidate
        return None


def discover_packs() -> dict:
    """All available packs, always including the built-in 'default'."""
    packs = {DEFAULT_PACK: ResourcePack(DEFAULT_PACK,
                                        meta={"name": "default (built in)",
                                              "description": "original textures"})}
    root = packs_directory()
    if not root.is_dir():
        return packs
    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue
        meta = {}
        meta_file = entry / "pack.json"
        if meta_file.is_file():
            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                meta = {}
        meta.setdefault("name", entry.name)
        packs[entry.name] = ResourcePack(entry.name, entry, meta)
    return packs


class ResourceManager:
    """Loads textures for the active pack with a fallback to the built-in ones."""

    def __init__(self, pack_id: str = DEFAULT_PACK):
        self.packs = discover_packs()
        self.pack_id = pack_id if pack_id in self.packs else DEFAULT_PACK
        self.images = {}
        self.loaded_from = {}      # filename -> pack id actually used
        self.reload()

    # ------------------------------------------------------------------ loading
    def _load_image(self, path) -> "pygame.Surface | None":
        try:
            return pygame.image.load(str(path)).convert_alpha()
        except (pygame.error, OSError, FileNotFoundError):
            return None

    def reload(self, pack_id: str = None):
        if pack_id is not None:
            self.pack_id = pack_id if pack_id in self.packs else DEFAULT_PACK
        pack = self.packs[self.pack_id]
        self.images = {}
        self.loaded_from = {}

        names = set()
        assets = assets_directory()
        if assets.is_dir():
            names.update(entry.name for entry in assets.iterdir() if entry.suffix == ".png")
        if pack.directory is not None:
            textures = pack.directory / "textures"
            folder = textures if textures.is_dir() else pack.directory
            names.update(entry.name for entry in folder.iterdir() if entry.suffix == ".png")

        for filename in sorted(names):
            image = None
            source = DEFAULT_PACK
            if not pack.is_default:
                path = pack.texture_path(filename)
                if path is not None:
                    image = self._load_image(path)
                    if image is not None:
                        source = self.pack_id
            if image is None:
                builtin = assets / filename
                image = self._load_image(builtin) if builtin.is_file() else None
            if image is not None:
                self.images[filename] = image
                self.images[filename.rsplit(".", 1)[0]] = image
                self.loaded_from[filename] = source

    # ------------------------------------------------------------------ helpers
    def get(self, name: str):
        """Texture by file name or bare name ("tree" or "tree.png")."""
        if name in self.images:
            return self.images[name]
        return self.images.get(f"{name}.png")

    @property
    def pack(self) -> ResourcePack:
        return self.packs[self.pack_id]

    def stats(self) -> dict:
        replaced = sum(1 for source in self.loaded_from.values() if source != DEFAULT_PACK)
        return {"total": len(self.loaded_from), "from_pack": replaced,
                "pack": self.pack_id}
