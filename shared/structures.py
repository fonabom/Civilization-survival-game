"""Structure (building) definitions.

Each entry mixes several kinds of data:
  * resource costs       -> wood / stone / iron_ingot / ... (the price)
  * footprint            -> "w" / "h"  (in tiles, default 1x1)
  * locked tech          -> "tech"     (country tech required to build it)
  * durability           -> "hp"       (hit points; buildings can be broken)
  * station              -> the crafting station this building provides
  * walkable             -> player may stand on it (doors when open, roads)

Use the helpers below instead of reading the dict directly: resource costs and
footprint live in the same mapping, and mixing them up was one of the bugs that
made building impossible (the server checked `inventory["w"] >= 1`).
"""

STRUCTURES = {
    "wall": {"wood": 2, "w": 1, "h": 1, "hp": 120},
    "stone_wall": {"stone": 6, "w": 1, "h": 1, "hp": 500, "tech": "masonry"},
    "door": {"wood": 4, "w": 1, "h": 1, "hp": 100, "walkable": True, "tech": "masonry"},
    "crafting_table": {"wood": 5, "w": 1, "h": 1, "station": "crafting_table", "hp": 100},
    "advanced_workbench": {"iron_ingot": 25, "wood": 10, "w": 2, "h": 1,
                           "tech": "industrialization", "station": "advanced_workbench",
                           "hp": 200},
    "furnace": {"stone": 8, "w": 1, "h": 1, "station": "furnace", "hp": 150},
    "campfire": {"wood": 5, "stone": 2, "w": 1, "h": 1, "hp": 60, "light": 140,
                 "station": "campfire", "walkable": True},
    "torch": {"wood": 1, "w": 1, "h": 1, "hp": 20, "light": 110, "walkable": True},
    "well": {"stone": 20, "wood": 10, "w": 1, "h": 1, "hp": 150, "tech": "agriculture"},
    "chest": {"wood": 8, "w": 1, "h": 1, "hp": 80, "storage": 12, "tech": "logistics"},
    "warehouse": {"wood": 40, "stone": 20, "w": 2, "h": 2, "hp": 300, "storage": 32,
                  "tech": "logistics"},
    "road": {"stone": 2, "w": 1, "h": 1, "hp": 60, "walkable": True, "speed": 1.35,
             "tech": "logistics"},
    "bridge": {"wood": 4, "w": 1, "h": 1, "hp": 70, "walkable": True, "water_only": True,
               "speed": 1.2, "tech": "masonry"},
    "market": {"wood": 60, "stone": 20, "w": 2, "h": 2, "hp": 180, "trade": True,
               "tech": "logistics"},
    "tower": {"wood": 10, "stone": 10, "w": 2, "h": 2, "hp": 400},
    "barracks": {"wood": 30, "stone": 20, "iron_ingot": 5, "w": 2, "h": 2, "hp": 350,
                 "tech": "military", "spawn": True},
    "farm": {"wood": 5, "w": 2, "h": 2, "hp": 80, "walkable": True},
    "town_center": {"wood": 50, "stone": 50, "w": 2, "h": 2, "hp": 800},
    "research_table": {"wood": 100, "stone": 100, "iron_ingot": 10, "w": 2, "h": 1,
                       "hp": 300},
    "drill": {"iron_ingot": 20, "stone": 20, "w": 1, "h": 1, "tech": "industrialization",
              "hp": 200},
    "pump": {"iron_ingot": 10, "stone": 5, "w": 1, "h": 1, "tech": "industrialization",
             "hp": 200},
    "chemical_plant": {"iron_ingot": 30, "stone": 30, "oil_barrel": 5, "w": 2, "h": 2,
                       "tech": "chemistry", "station": "chemical_plant", "hp": 400},

    # --- b10 «Цивилизация» -------------------------------------------------
    # Medicine: a hospital is a station for medkits and heals players around it.
    "hospital": {"wood": 80, "stone": 60, "leather": 10, "w": 2, "h": 2, "hp": 400,
                 "tech": "medicine", "station": "hospital", "heal": 6},
    # Electricity: a generator feeds lamps, both light the night up.
    "generator": {"iron_ingot": 40, "gold_ingot": 20, "stone": 20, "w": 2, "h": 2,
                  "hp": 220, "tech": "electricity", "power": 400},
    "lamp": {"iron_ingot": 6, "wood": 4, "w": 1, "h": 1, "hp": 40, "light": 220,
             "tech": "electricity", "walkable": True, "needs_power": True},
    # The wonder: the peaceful way to win the game.
    "wonder": {"wood": 400, "stone": 300, "iron_ingot": 150, "gold_ingot": 100,
               "w": 3, "h": 3, "hp": 2000, "tech": "industrialization",
               "wonder": True, "light": 200, "age": "industrial"},
}

# Keys that describe the structure itself rather than its price.
_NON_COST_KEYS = {"w", "h", "tech", "station", "hp", "light", "walkable", "storage",
                  "speed", "spawn", "water_only", "trade", "wonder", "age", "heal",
                  "power", "needs_power"}

# Buildings that can be walked through (doors do it only while open)
WALKABLE = {name for name, data in STRUCTURES.items() if data.get("walkable")}

# Interaction range for stations / menus, in pixels
STATION_RANGE = 64
# How far a player may place a building / interact with a chest
BUILD_RANGE_TILES = 8

# Repair: how much health one unit of the main resource restores
REPAIR_PER_UNIT = 40


def get_cost(structure: str) -> dict:
    """Resource-only price of a structure, e.g. {'wood': 2}."""
    return {k: v for k, v in STRUCTURES.get(structure, {}).items() if k not in _NON_COST_KEYS}


def get_size(structure: str) -> tuple:
    """Footprint of a structure in tiles, e.g. (2, 2)."""
    data = STRUCTURES.get(structure, {})
    return int(data.get("w", 1)), int(data.get("h", 1))


def get_tech(structure: str):
    """Country tech required to build it, or None."""
    return STRUCTURES.get(structure, {}).get("tech")


def get_station(structure: str):
    """The crafting station this building provides, or None."""
    return STRUCTURES.get(structure, {}).get("station")


def get_hp(structure: str) -> int:
    return int(STRUCTURES.get(structure, {}).get("hp", 100))


def get_light(structure: str) -> int:
    """Light radius in pixels (torches, campfires), 0 = no light."""
    return int(STRUCTURES.get(structure, {}).get("light", 0))


def get_storage(structure: str) -> int:
    """How many kinds of items fit inside (chest/warehouse), 0 = not storage."""
    return int(STRUCTURES.get(structure, {}).get("storage", 0))


def get_speed(structure: str) -> float:
    """Movement multiplier while standing on it (roads)."""
    return float(STRUCTURES.get(structure, {}).get("speed", 1.0))


def provides_spawn(structure: str) -> bool:
    return bool(STRUCTURES.get(structure, {}).get("spawn", False))


def is_walkable(structure: str) -> bool:
    return structure in WALKABLE


def is_storage(structure: str) -> bool:
    return get_storage(structure) > 0


def is_water_only(structure: str) -> bool:
    """Bridges may only be built on water."""
    return bool(STRUCTURES.get(structure, {}).get("water_only"))


def is_market(structure: str) -> bool:
    """Trading post - players post and take offers here."""
    return bool(STRUCTURES.get(structure, {}).get("trade"))


def is_wonder(structure: str) -> bool:
    """The victory building (b10)."""
    return bool(STRUCTURES.get(structure, {}).get("wonder"))


def get_age(structure: str):
    """Minimum country age needed for this building (None = any age)."""
    return STRUCTURES.get(structure, {}).get("age")


def get_power(structure: str) -> int:
    """How many tiles a generator powers (0 = it produces no power)."""
    return int(STRUCTURES.get(structure, {}).get("power", 0))


def needs_power(structure: str) -> bool:
    """Lamps only shine while a powered generator is close enough."""
    return bool(STRUCTURES.get(structure, {}).get("needs_power"))


def get_heal(structure: str) -> int:
    """Health per second a building gives to players around it (hospitals)."""
    return int(STRUCTURES.get(structure, {}).get("heal", 0))


def can_afford(structure: str, inventory: dict) -> bool:
    return all(inventory.get(res, 0) >= amount for res, amount in get_cost(structure).items())


def missing_for(structure: str, inventory: dict) -> dict:
    return {res: amount - inventory.get(res, 0)
            for res, amount in get_cost(structure).items()
            if inventory.get(res, 0) < amount}


def pay_for(structure: str, inventory: dict) -> None:
    for res, amount in get_cost(structure).items():
        inventory[res] = inventory.get(res, 0) - amount
    for res in list(get_cost(structure)):
        if inventory.get(res, 0) <= 0:
            inventory.pop(res, None)


def station_names() -> set:
    return {get_station(name) for name in STRUCTURES if get_station(name)}
