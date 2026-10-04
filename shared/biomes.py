"""Biomes - what kind of land a tile is (b13 «Мир живой 2»).

The terrain (grass / rock / water / cave) says what a tile *is*; the biome says
what it *looks and feels* like: a meadow, a forest, a desert, a snowy tundra or
a swamp. Both travel to the client (terrain + biome strings), so the client can
predict movement with exactly the server's numbers.

Biome codes are small integers, the same way terrain is encoded:

    0 meadow   1 forest   2 desert   3 snow   4 swamp   5 cave

Caves are their own biome (dark, ore rich) even though the terrain there is
"cave floor"; a tile that is rock or water has no useful biome and keeps the
one of its neighbours.
"""

MEADOW, FOREST, DESERT, SNOW, SWAMP, CAVE = 0, 1, 2, 3, 4, 5

BIOMES = (MEADOW, FOREST, DESERT, SNOW, SWAMP, CAVE)

NAMES = {
    MEADOW: "biome.meadow",
    FOREST: "biome.forest",
    DESERT: "biome.desert",
    SNOW: "biome.snow",
    SWAMP: "biome.swamp",
    CAVE: "biome.cave",
}

# Walking is not equally easy everywhere: sand is quick, a swamp or deep snow
# slow you down. Planks and roads still beat all of them (shared/structures.py).
SPEED = {
    MEADOW: 1.0,
    FOREST: 0.95,          # roots and undergrowth
    DESERT: 1.05,          # open sand
    SNOW: 0.85,            # you sink in
    SWAMP: 0.8,            # water and mud
    CAVE: 1.0,
}

# How willing each biome is to grow things (resource generation weights)
TREE_WEIGHT = {MEADOW: 0.6, FOREST: 2.2, DESERT: 0.0, SNOW: 0.15, SWAMP: 0.9, CAVE: 0.0}
MUSHROOM_WEIGHT = {MEADOW: 0.5, FOREST: 1.0, DESERT: 0.0, SNOW: 0.15, SWAMP: 1.6, CAVE: 2.0}
ORE_WEIGHT = {MEADOW: 1.0, FOREST: 0.9, DESERT: 1.3, SNOW: 1.2, SWAMP: 1.0, CAVE: 1.0}

# Where animals like to live (spawn weights)
ANIMAL_WEIGHT = {
    "sheep": {MEADOW: 2.0, FOREST: 1.0, DESERT: 0.2, SNOW: 0.5, SWAMP: 0.3},
    "cow": {MEADOW: 1.6, FOREST: 0.8, DESERT: 0.2, SNOW: 0.4, SWAMP: 0.6},
    "chicken": {MEADOW: 1.4, FOREST: 1.2, DESERT: 0.4, SNOW: 0.4, SWAMP: 0.5},
    "wolf": {MEADOW: 0.4, FOREST: 1.8, DESERT: 0.6, SNOW: 1.5, SWAMP: 0.5},
    "bear": {MEADOW: 0.3, FOREST: 1.6, DESERT: 0.3, SNOW: 1.2, SWAMP: 0.7},
}

# Colours for the minimap and the fallback (no texture pack) map painting
COLORS = {
    MEADOW: (50, 160, 50),
    FOREST: (30, 110, 45),
    DESERT: (196, 176, 112),
    SNOW: (226, 234, 240),
    SWAMP: (74, 110, 62),
    CAVE: (58, 52, 48),
}

DEFAULT = MEADOW


def speed(code) -> float:
    """Movement multiplier of a biome (never zero: you always trudge on)."""
    return float(SPEED.get(code, 1.0))


def name_key(code) -> str:
    return NAMES.get(code, NAMES[MEADOW])


def encode(codes: list) -> str:
    """A biome map as one string, the same trick the terrain uses."""
    return "".join(str(int(code)) for code in codes)


def decode(text: str, width: int = 0) -> list:
    rows = []
    if not text:
        return rows
    step = width or 1
    values = [int(ch) if ch.isdigit() and int(ch) in BIOMES else DEFAULT for ch in text]
    if not width:
        return values
    for start in range(0, len(values), step):
        rows.append(values[start:start + step])
    return rows
