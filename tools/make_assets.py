"""Draw the textures the game needs (pixel art, generated with pygame).

New items and buildings used to be invisible because `assets/` had no picture
for them. This script draws every missing texture - no external art needed.

    python tools/make_assets.py            # only what is missing
    python tools/make_assets.py --force    # redraw everything from here
    python tools/make_assets.py --list     # show what would be created

Pictures land in `assets/` and are picked up automatically (resource packs may
override them). Feel free to replace any PNG with your own art later.
"""

import argparse
import os
import sys
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pygame  # noqa: E402

SIZE = 32
TRANSPARENT = (0, 0, 0, 0)


# ------------------------------------------------------------------ helpers
def shade(color, factor):
    return tuple(max(0, min(255, int(channel * factor))) for channel in color[:3])


def new_surface():
    surface = pygame.Surface((SIZE, SIZE), pygame.SRCALPHA)
    surface.fill(TRANSPARENT)
    return surface


def rect(surface, color, x, y, w, h):
    pygame.draw.rect(surface, color, (x, y, w, h))


def circle(surface, color, x, y, radius):
    pygame.draw.circle(surface, color, (x, y), radius)


def outline(surface, color, points):
    pygame.draw.polygon(surface, color, points)


def border(surface, color):
    pygame.draw.rect(surface, color, (0, 0, SIZE, SIZE), 2)


# ------------------------------------------------------------------ items
def draw_bread(s):
    rect(s, (150, 96, 44), 4, 10, 24, 14)
    rect(s, (196, 140, 74), 4, 10, 24, 5)
    rect(s, (120, 72, 30), 4, 21, 24, 3)
    for x in (8, 14, 20):
        rect(s, (240, 214, 160), x, 8, 3, 3)


def draw_apple(s):
    circle(s, (196, 40, 40), 16, 19, 10)
    circle(s, (232, 90, 70), 12, 15, 4)
    rect(s, (96, 62, 32), 15, 7, 2, 5)
    pygame.draw.ellipse(s, (60, 150, 60), (17, 5, 9, 5))


def draw_berries(s):
    for x, y in ((11, 13), (20, 12), (15, 20), (23, 20), (12, 23)):
        circle(s, (150, 30, 90), x, y, 5)
        circle(s, (210, 70, 140), x - 1, y - 1, 2)
    pygame.draw.ellipse(s, (60, 140, 60), (4, 4, 24, 8))


def draw_cooked_meat(s):
    pygame.draw.ellipse(s, (140, 76, 40), (4, 12, 20, 14))
    rect(s, (226, 214, 190), 20, 14, 9, 5)
    circle(s, (226, 214, 190), 27, 13, 3)
    circle(s, (226, 214, 190), 27, 20, 3)
    circle(s, (196, 120, 70), 12, 17, 3)


def draw_raw_meat(s):
    pygame.draw.ellipse(s, (206, 110, 110), (4, 12, 20, 14))
    rect(s, (238, 226, 210), 20, 14, 9, 5)
    circle(s, (238, 226, 210), 27, 13, 3)
    circle(s, (238, 226, 210), 27, 20, 3)
    circle(s, (176, 70, 70), 12, 17, 3)


def draw_fish(s):
    pygame.draw.ellipse(s, (120, 150, 176), (4, 12, 18, 11))
    outline(s, (96, 124, 150), [(22, 17), (30, 11), (30, 24)])
    circle(s, (30, 30, 40), 9, 16, 2)
    circle(s, (240, 240, 240), 8, 15, 2)


def draw_leather(s):
    rect(s, (176, 128, 72), 3, 8, 26, 18)
    rect(s, (206, 158, 96), 3, 8, 26, 5)
    rect(s, (140, 96, 50), 3, 23, 26, 3)
    for x in (7, 15, 23):
        rect(s, (120, 80, 40), x, 14, 2, 6)


def draw_wool(s):
    circle(s, (238, 238, 230), 16, 17, 11)
    circle(s, (250, 250, 246), 12, 13, 5)
    circle(s, (216, 214, 206), 21, 21, 5)
    circle(s, (246, 244, 236), 20, 12, 4)


def draw_string(s):
    pygame.draw.lines(s, (230, 226, 210), False,
                      [(6, 24), (12, 12), (18, 22), (24, 10)], 2)


# ------------------------------------------------------------------ weapons / armor
def draw_bow(s):
    pygame.draw.arc(s, (140, 92, 40), (6, 3, 20, 26), -1.4, 1.4, 3)
    pygame.draw.line(s, (238, 232, 210), (18, 5), (18, 27), 1)
    pygame.draw.line(s, (238, 232, 210), (6, 15), (28, 16), 1)


def draw_arrow(s):
    rect(s, (150, 108, 62), 5, 15, 20, 2)
    outline(s, (200, 200, 205), [(25, 16), (30, 12), (30, 20)])
    rect(s, (226, 220, 200), 5, 12, 4, 8)


def draw_shield(s):
    outline(s, (108, 76, 44), [(16, 3), (28, 8), (26, 24), (16, 30), (6, 24), (4, 8)])
    outline(s, (150, 110, 62), [(16, 6), (25, 10), (23, 22), (16, 27), (9, 22), (7, 10)])
    rect(s, (200, 168, 90), 15, 9, 3, 14)
    rect(s, (200, 168, 90), 10, 14, 13, 3)


def _armor(s, color, part):
    if part == "helmet":
        pygame.draw.ellipse(s, color, (6, 6, 20, 18))
        rect(s, shade(color, 0.6), 6, 15, 20, 4)
        rect(s, (30, 30, 40), 11, 13, 4, 3)
        rect(s, (30, 30, 40), 18, 13, 4, 3)
    elif part == "chestplate":
        outline(s, color, [(10, 6), (22, 6), (26, 12), (24, 27), (8, 27), (6, 12)])
        rect(s, shade(color, 0.65), 6, 20, 20, 3)
        rect(s, shade(color, 1.25), 14, 6, 4, 22)
    elif part == "leggings":
        rect(s, color, 8, 5, 16, 10)
        rect(s, color, 8, 15, 6, 13)
        rect(s, color, 18, 15, 6, 13)
        rect(s, shade(color, 0.65), 8, 5, 16, 3)
    else:                                    # boots
        rect(s, color, 7, 8, 7, 14)
        rect(s, color, 18, 8, 7, 14)
        rect(s, shade(color, 0.6), 5, 22, 11, 5)
        rect(s, shade(color, 0.6), 16, 22, 11, 5)


def draw_iron_helmet(s):
    _armor(s, (196, 200, 210), "helmet")


def draw_iron_chestplate(s):
    _armor(s, (196, 200, 210), "chestplate")


def draw_iron_leggings(s):
    _armor(s, (176, 180, 192), "leggings")


def draw_iron_boots(s):
    _armor(s, (176, 180, 192), "boots")


def draw_leather_helmet(s):
    _armor(s, (168, 120, 66), "helmet")


def draw_leather_chestplate(s):
    _armor(s, (168, 120, 66), "chestplate")


def draw_leather_leggings(s):
    _armor(s, (150, 106, 58), "leggings")


def draw_leather_boots(s):
    _armor(s, (150, 106, 58), "boots")


# ------------------------------------------------------------------ tools
def draw_sickle(s):
    pygame.draw.arc(s, (206, 206, 214), (6, 4, 22, 22), 0.2, 2.6, 4)
    rect(s, (120, 80, 40), 15, 16, 3, 12)


# ------------------------------------------------------------------ structures
def draw_chest(s):
    rect(s, (140, 92, 46), 4, 12, 24, 16)
    rect(s, (176, 122, 62), 4, 8, 24, 6)
    rect(s, (100, 64, 32), 4, 8, 24, 3)
    rect(s, (222, 190, 90), 14, 12, 4, 8)
    border(s, (90, 58, 28))


def draw_door(s, open_door=False):
    rect(s, (120, 80, 44), 8, 2, 16, 28)
    if open_door:
        rect(s, (86, 56, 30), 8, 2, 6, 28)
        rect(s, (170, 130, 74), 16, 4, 8, 24)
    else:
        rect(s, (176, 122, 62), 10, 4, 12, 24)
        rect(s, (206, 158, 96), 11, 6, 10, 8)
        rect(s, (222, 190, 90), 20, 16, 3, 3)


def draw_torch(s):
    rect(s, (120, 82, 44), 14, 12, 4, 18)
    circle(s, (250, 190, 60), 16, 10, 6)
    circle(s, (255, 230, 120), 16, 9, 3)


def draw_campfire(s):
    rect(s, (110, 74, 40), 6, 20, 20, 4)
    rect(s, (140, 96, 52), 8, 24, 16, 3)
    outline(s, (240, 140, 40), [(16, 6), (23, 22), (9, 22)])
    outline(s, (250, 210, 90), [(16, 12), (20, 22), (12, 22)])


def draw_well(s):
    rect(s, (110, 110, 118), 6, 14, 20, 14)
    rect(s, (140, 140, 148), 6, 14, 20, 3)
    rect(s, (60, 60, 70), 10, 17, 12, 6)
    rect(s, (130, 90, 50), 8, 4, 16, 3)
    rect(s, (130, 90, 50), 8, 7, 3, 10)
    rect(s, (130, 90, 50), 21, 7, 3, 10)


def draw_stone_wall(s):
    rect(s, (120, 120, 128), 0, 8, 32, 24)
    for row in range(3):
        y = 8 + row * 8
        offset = 0 if row % 2 == 0 else 8
        for x in range(-8 + offset, 32, 16):
            rect(s, (150, 150, 158), max(0, x), y, 15, 7)
            pygame.draw.rect(s, (96, 96, 104), (max(0, x), y, 15, 7), 1)


def draw_barracks(s):
    rect(s, (128, 96, 76), 2, 12, 28, 18)
    outline(s, (150, 40, 40), [(1, 13), (16, 2), (31, 13)])
    rect(s, (70, 50, 36), 12, 20, 8, 10)
    rect(s, (232, 214, 120), 5, 16, 4, 4)


def draw_road(s):
    rect(s, (168, 152, 118), 0, 0, 32, 32)
    rect(s, (186, 170, 132), 2, 2, 28, 28)
    for x in (6, 20):
        rect(s, (150, 134, 100), x, 4, 3, 3)
        rect(s, (150, 134, 100), x + 6, 22, 3, 3)


def draw_warehouse(s):
    rect(s, (140, 110, 70), 2, 10, 28, 20)
    outline(s, (110, 80, 50), [(1, 11), (16, 3), (31, 11)])
    rect(s, (90, 60, 34), 11, 16, 10, 14)
    rect(s, (206, 158, 96), 4, 14, 5, 5)
    rect(s, (206, 158, 96), 23, 14, 5, 5)


# ------------------------------------------------------------------ animals
def draw_sheep(s):
    circle(s, (240, 240, 232), 15, 17, 10)
    circle(s, (40, 40, 46), 24, 14, 5)
    rect(s, (60, 60, 66), 8, 24, 3, 6)
    rect(s, (60, 60, 66), 19, 24, 3, 6)


def draw_cow(s):
    pygame.draw.ellipse(s, (240, 238, 230), (3, 9, 24, 15))
    circle(s, (40, 40, 46), 25, 12, 6)
    circle(s, (60, 50, 46), 12, 14, 4)
    rect(s, (60, 60, 66), 6, 23, 3, 7)
    rect(s, (60, 60, 66), 18, 23, 3, 7)


def draw_chicken(s):
    pygame.draw.ellipse(s, (246, 244, 238), (5, 12, 18, 14))
    circle(s, (246, 244, 238), 22, 12, 5)
    circle(s, (230, 180, 40), 24, 11, 2)
    outline(s, (220, 90, 40), [(27, 7), (31, 10), (27, 12)])
    rect(s, (230, 180, 40), 10, 25, 2, 5)
    rect(s, (230, 180, 40), 18, 25, 2, 5)


def draw_wolf(s):
    pygame.draw.ellipse(s, (120, 122, 132), (2, 12, 22, 12))
    circle(s, (140, 142, 152), 25, 13, 6)
    outline(s, (100, 102, 112), [(22, 8), (24, 3), (27, 8)])
    outline(s, (100, 102, 112), [(27, 8), (30, 3), (31, 9)])
    circle(s, (240, 220, 90), 27, 12, 2)
    rect(s, (100, 102, 112), 8, 22, 3, 8)
    rect(s, (100, 102, 112), 16, 22, 3, 8)


def draw_bush(s):
    circle(s, (48, 120, 52), 16, 20, 12)
    circle(s, (62, 148, 66), 11, 16, 8)
    for x, y in ((12, 18), (20, 16), (16, 24), (24, 22)):
        circle(s, (170, 40, 100), x, y, 3)


def draw_sulfur_ore(s):
    circle(s, (110, 110, 116), 16, 18, 12)
    for x, y in ((12, 14), (20, 16), (16, 22), (23, 22)):
        circle(s, (226, 214, 80), x, y, 3)




def draw_mushroom(s):
    rect(s, (236, 226, 208), 14, 16, 4, 11)
    pygame.draw.ellipse(s, (196, 60, 60), (5, 8, 22, 13))
    circle(s, (240, 200, 200), 12, 12, 2)
    circle(s, (240, 200, 200), 20, 15, 2)
    rect(s, (170, 40, 40), 5, 18, 22, 3)


def draw_cooked_fish(s):
    pygame.draw.ellipse(s, (196, 140, 76), (4, 12, 18, 11))
    outline(s, (168, 110, 54), [(22, 17), (30, 11), (30, 24)])
    circle(s, (40, 30, 20), 9, 16, 2)
    for x in (11, 17):
        rect(s, (150, 96, 46), x, 12, 2, 8)


def draw_fishing_rod(s):
    pygame.draw.line(s, (150, 108, 60), (5, 27), (24, 6), 3)
    pygame.draw.line(s, (110, 170, 210), (24, 6), (26, 24), 1)
    circle(s, (226, 226, 226), 26, 25, 2)
    rect(s, (90, 70, 50), 6, 20, 6, 6)
    circle(s, (200, 200, 206), 8, 22, 2)


def draw_bear(s):
    circle(s, (96, 66, 44), 16, 19, 12)
    circle(s, (120, 84, 56), 12, 14, 5)
    circle(s, (70, 48, 32), 8, 8, 4)
    circle(s, (70, 48, 32), 24, 8, 4)
    rect(s, (60, 40, 26), 9, 26, 6, 4)
    rect(s, (60, 40, 26), 18, 26, 6, 4)


def draw_bridge(s):
    rect(s, (150, 108, 62), 0, 8, 32, 16)
    for x in (2, 8, 14, 20, 26):
        rect(s, (120, 84, 46), x, 8, 4, 16)
    rect(s, (176, 132, 82), 0, 8, 32, 3)
    rect(s, (110, 78, 44), 0, 23, 32, 3)


def draw_market(s):
    rect(s, (120, 84, 48), 3, 14, 26, 15)
    rect(s, (160, 118, 70), 3, 14, 26, 4)
    pygame.draw.polygon(s, (200, 60, 60), [(1, 13), (31, 13), (26, 4), (6, 4)])
    rect(s, (236, 226, 190), 7, 18, 6, 5)
    rect(s, (236, 226, 190), 19, 18, 6, 5)
    rect(s, (90, 62, 36), 3, 27, 26, 3)




def draw_medkit(s):
    rect(s, (232, 232, 236), 4, 8, 24, 18)
    rect(s, (208, 208, 214), 4, 8, 24, 4)
    rect(s, (60, 62, 70), 4, 23, 24, 3)
    rect(s, (206, 60, 60), 14, 13, 5, 10)
    rect(s, (206, 60, 60), 11, 16, 11, 4)


def draw_bandage(s):
    pygame.draw.ellipse(s, (238, 232, 220), (4, 10, 24, 12))
    rect(s, (214, 205, 190), 4, 12, 24, 3)
    rect(s, (214, 205, 190), 4, 18, 24, 3)
    for x in (10, 16, 22):
        rect(s, (206, 60, 60), x, 14, 3, 4)


def draw_hospital(s):
    rect(s, (232, 232, 236), 2, 8, 28, 21)
    rect(s, (206, 206, 212), 2, 8, 28, 4)
    pygame.draw.polygon(s, (198, 72, 72), [(0, 9), (32, 9), (16, 2)])
    rect(s, (200, 60, 60), 13, 14, 6, 14)
    rect(s, (200, 60, 60), 9, 18, 14, 6)
    rect(s, (120, 150, 190), 6, 14, 4, 5)
    rect(s, (120, 150, 190), 22, 14, 4, 5)


def draw_generator(s):
    rect(s, (96, 100, 110), 3, 9, 26, 20)
    rect(s, (140, 146, 158), 3, 9, 26, 4)
    rect(s, (60, 64, 74), 7, 15, 18, 8)
    circle(s, (240, 214, 90), 16, 19, 4)
    rect(s, (60, 64, 74), 6, 26, 8, 4)
    rect(s, (60, 64, 74), 18, 26, 8, 4)


def draw_lamp(s):
    rect(s, (80, 84, 94), 14, 12, 4, 15)
    rect(s, (60, 64, 74), 9, 26, 14, 4)
    pygame.draw.polygon(s, (250, 226, 130), [(8, 12), (24, 12), (20, 3), (12, 3)])
    circle(s, (255, 246, 200), 16, 13, 4)


def draw_wonder(s):
    rect(s, (226, 214, 176), 3, 20, 26, 9)
    rect(s, (206, 192, 150), 3, 20, 26, 3)
    for x in (6, 11, 16, 21, 26):
        rect(s, (238, 228, 192), x, 12, 2, 9)
    pygame.draw.polygon(s, (222, 210, 172), [(2, 12), (30, 12), (16, 5)])
    circle(s, (250, 220, 120), 16, 8, 3)
    rect(s, (186, 172, 134), 2, 28, 28, 3)


def draw_player(s):
    """The character (b11): a little person, drawn in light greys.

    The game tints this sprite with the colour of every player, so everything
    here is deliberately pale: the tint multiplies it into a proper character
    (the eyes and the outline stay dark). Resource packs may replace it with
    their own art.
    """
    skin = (238, 218, 192)
    hair = (150, 116, 84)
    shirt = (236, 240, 248)
    shirt_dark = (198, 204, 216)
    pants = (176, 186, 204)
    pants_dark = (146, 156, 176)
    boot = (104, 96, 88)
    line = (26, 28, 36)

    figure = new_surface()
    # legs and boots
    rect(figure, pants, 11, 20, 4, 8)
    rect(figure, pants_dark, 17, 20, 4, 8)
    rect(figure, boot, 10, 27, 6, 3)
    rect(figure, boot, 16, 27, 6, 3)
    # body
    rect(figure, shirt, 11, 12, 10, 9)
    rect(figure, shirt_dark, 11, 19, 10, 2)
    # arms + hands
    rect(figure, shirt_dark, 7, 13, 4, 8)
    rect(figure, shirt_dark, 21, 13, 4, 8)
    rect(figure, skin, 7, 20, 4, 3)
    rect(figure, skin, 21, 20, 4, 3)
    # head: hair, face, eyes, mouth
    rect(figure, hair, 10, 3, 12, 5)
    rect(figure, skin, 10, 6, 12, 6)
    rect(figure, hair, 10, 3, 3, 6)
    rect(figure, line, 13, 9, 2, 2)
    rect(figure, line, 17, 9, 2, 2)
    rect(figure, (196, 120, 110), 15, 11, 2, 1)
    # a 1 px dark outline around the whole silhouette
    mask = pygame.mask.from_surface(figure)
    silhouette = mask.to_surface(setcolor=line, unsetcolor=(0, 0, 0, 0))
    for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1),
                   (-1, -1), (1, -1), (-1, 1), (1, 1)):
        s.blit(silhouette, (dx, dy))
    s.blit(figure, (0, 0))


# ------------------------------------------------------------------ registry
TEXTURES = {
    # food & materials
    "bread": draw_bread, "apple": draw_apple, "berries": draw_berries,
    "cooked_meat": draw_cooked_meat, "raw_meat": draw_raw_meat, "fish": draw_fish,
    "leather": draw_leather, "wool": draw_wool, "string": draw_string,
    "sulfur_ore": draw_sulfur_ore, "bush": draw_bush, "mushroom": draw_mushroom,
    "cooked_fish": draw_cooked_fish, "fishing_rod": draw_fishing_rod,
    "medkit": draw_medkit, "bandage": draw_bandage,
    # weapons / armor / tools
    "bow": draw_bow, "arrow": draw_arrow, "shield": draw_shield,
    "sickle": draw_sickle,
    "iron_helmet": draw_iron_helmet, "iron_chestplate": draw_iron_chestplate,
    "iron_leggings": draw_iron_leggings, "iron_boots": draw_iron_boots,
    "leather_helmet": draw_leather_helmet, "leather_chestplate": draw_leather_chestplate,
    "leather_leggings": draw_leather_leggings, "leather_boots": draw_leather_boots,
    # structures
    "chest": draw_chest, "door": lambda s: draw_door(s, False),
    "door_open": lambda s: draw_door(s, True), "torch": draw_torch,
    "campfire": draw_campfire, "well": draw_well, "stone_wall": draw_stone_wall,
    "barracks": draw_barracks, "road": draw_road, "warehouse": draw_warehouse,
    "bridge": draw_bridge, "market": draw_market,
    "hospital": draw_hospital, "generator": draw_generator, "lamp": draw_lamp,
    "wonder": draw_wonder,
    # characters
    "player": draw_player,
    # animals
    "sheep": draw_sheep, "cow": draw_cow, "chicken": draw_chicken, "wolf": draw_wolf,
    "bear": draw_bear,
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="redraw existing files too")
    parser.add_argument("--list", action="store_true", help="only list what is missing")
    args = parser.parse_args()

    assets = ROOT / "assets"
    assets.mkdir(exist_ok=True)
    missing = [name for name in TEXTURES if not (assets / f"{name}.png").exists()]
    if args.list:
        print("missing:", ", ".join(sorted(missing)) or "nothing")
        return 0

    pygame.init()
    pygame.display.set_mode((64, 64))

    created = []
    for name, painter in sorted(TEXTURES.items()):
        target = assets / f"{name}.png"
        if target.exists() and not args.force:
            continue
        surface = new_surface()
        painter(surface)
        pygame.image.save(surface, str(target))
        created.append(name)

    pygame.quit()
    if created:
        print(f"created {len(created)} texture(s): {', '.join(created)}")
    else:
        print("nothing to do - every texture already exists (use --force to redraw)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
