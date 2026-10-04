"""Create a resource pack (a texture set) from the built-in assets.

    python tools/make_resourcepack.py --name neon --style neon
    python tools/make_resourcepack.py --name nights --style dark --all

The generated pack lands in `resourcepacks/<name>/`:

    resourcepacks/neon/
        pack.json
        textures/*.png

Textures are derived from assets/*.png with a colour transform, so you get a
visibly different pack without drawing anything by hand. Replace any PNG with
your own art (same file names) and the game will use it - missing files fall
back to the built-in textures automatically.
"""

import argparse
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pygame  # noqa: E402


def shift(surface, style: str):
    """Return a recoloured copy of a texture."""
    out = surface.copy()
    width, height = out.get_size()
    out.lock()
    for y in range(height):
        for x in range(width):
            r, g, b, a = out.get_at((x, y))
            if a == 0:
                continue
            if style == "neon":
                peak = max(r, g, b) or 1
                r, g, b = (int(255 * r / peak), int(255 * g / peak), int(255 * b / peak))
                r = min(255, int(r * 0.55 + 60))
                g = min(255, int(g * 0.55 + 180))
                b = min(255, int(b * 0.55 + 255))
            elif style == "dark":
                r, g, b = int(r * 0.45), int(g * 0.5), int(b * 0.75)
            elif style == "desert":
                r, g, b = min(255, int(r * 1.15 + 30)), int(g * 0.95), int(b * 0.6)
            elif style == "invert":
                r, g, b = 255 - r, 255 - g, 255 - b
            out.set_at((x, y), (r, g, b, a))
    out.unlock()
    return out


STYLES = {
    "neon": ("Neon", "glowing recolour of the original textures"),
    "dark": ("Nights", "dark blue night-time textures"),
    "desert": ("Desert", "sandy warm textures"),
    "invert": ("Inverted", "inverted colours, for the brave"),
}


def build_pack(name: str, style: str):
    assets = ROOT / "assets"
    if not assets.is_dir():
        raise SystemExit("assets/ folder not found - run this from the game folder")
    target = ROOT / "resourcepacks" / name
    textures = target / "textures"
    textures.mkdir(parents=True, exist_ok=True)

    pygame.init()
    pygame.display.set_mode((64, 64))

    count = 0
    for entry in sorted(assets.iterdir()):
        if entry.suffix != ".png":
            continue
        try:
            image = pygame.image.load(str(entry)).convert_alpha()
        except pygame.error as exc:
            print(f"  ! skipped {entry.name}: {exc}")
            continue
        pygame.image.save(shift(image, style), str(textures / entry.name))
        count += 1

    pygame.quit()
    pretty, description = STYLES.get(style, (name.title(), f"{style} style"))
    (target / "pack.json").write_text(json.dumps({
        "name": pretty,
        "author": "make_resourcepack.py",
        "description": description,
        "style": style,
    }, indent=1), encoding="utf-8")
    print(f"Resource pack '{name}' written to {target} ({count} textures, style {style})")
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", default="neon", help="folder name of the pack")
    parser.add_argument("--style", default="neon", choices=sorted(STYLES),
                        help="colour transform to apply")
    parser.add_argument("--all", action="store_true",
                        help="create one pack per style (neon, dark, desert, invert)")
    args = parser.parse_args()

    if args.all:
        for style in STYLES:
            build_pack(style, style)
    else:
        build_pack(args.name, args.style)
    print("Pick it in game: settings -> resource pack.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
