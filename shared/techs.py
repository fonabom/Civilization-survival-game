"""Technology tree (country level) and tiers (city level).

Countries research techs with resources; techs unlock buildings, items and
recipes. Everything lives here so the server, the research menu and the tests
read the same data (before b8 the list was hard-coded inside server.py).

    TECH_REQUIREMENTS -> what a tech needs before it can be researched
"""

TECHS = {
    # code -> {name key, description key, cost, requires, unlocks}
    "agriculture": {
        "cost": {"wood": 40, "stone": 20},
        "requires": [],
        "unlocks": {"structures": ["well"], "recipes": ["sickle", "bread", "fishing_rod"]},
    },
    "masonry": {
        "cost": {"stone": 60, "wood": 30},
        "requires": [],
        "unlocks": {"structures": ["stone_wall", "door", "bridge"]},
    },
    "military": {
        "cost": {"wood": 80, "iron_ingot": 20},
        "requires": [],
        "unlocks": {"structures": ["barracks"], "recipes": ["bow", "arrow", "shield"]},
    },
    "logistics": {
        "cost": {"wood": 60, "stone": 40},
        "requires": [],
        "unlocks": {"structures": ["road", "warehouse", "chest", "market"]},
    },
    "industrialization": {
        "cost": {"iron_ingot": 50, "gold_ingot": 50},
        "requires": [],
        "unlocks": {"structures": ["advanced_workbench", "drill", "pump"],
                    "recipes": ["iron_axe", "iron_pickaxe", "pistol"]},
    },
    "chemistry": {
        "cost": {"oil_barrel": 20},
        "requires": ["industrialization"],
        "unlocks": {"structures": ["chemical_plant"], "recipes": ["gunpowder"]},
    },
    # --- b10 «Цивилизация» -------------------------------------------------
    "medicine": {
        "cost": {"wood": 50, "leather": 20, "string": 20},
        "requires": ["agriculture"],
        "unlocks": {"structures": ["hospital"], "recipes": ["bandage", "medkit"]},
    },
    "electricity": {
        "cost": {"iron_ingot": 60, "gold_ingot": 40, "oil_barrel": 10},
        "requires": ["industrialization"],
        "unlocks": {"structures": ["generator", "lamp"], "recipes": []},
    },
}

# Order in which the research menu shows them
TECH_ORDER = ["agriculture", "masonry", "military", "logistics", "medicine",
              "industrialization", "chemistry", "electricity"]

# Cities: cost of the upgrade to the given tier
CITY_TIER_COST = {
    2: {"wood": 100, "stone": 100},
    3: {"wood": 200, "stone": 200, "iron_ingot": 50},
}
MAX_CITY_TIER = 3


def tech_cost(tech: str) -> dict:
    return dict(TECHS.get(tech, {}).get("cost", {}))


def tech_requires(tech: str) -> list:
    return list(TECHS.get(tech, {}).get("requires", []))


def unlocked_structures(techs) -> set:
    out = set()
    for tech in techs or []:
        out.update(TECHS.get(tech, {}).get("unlocks", {}).get("structures", []))
    return out


def unlocked_recipes(techs) -> set:
    out = set()
    for tech in techs or []:
        out.update(TECHS.get(tech, {}).get("unlocks", {}).get("recipes", []))
    return out


def techs_for_structure(structure: str) -> list:
    """Which techs unlock this building (empty = available from the start)."""
    return [tech for tech, data in TECHS.items()
            if structure in data.get("unlocks", {}).get("structures", [])]


def tech_for_recipe(recipe: str) -> str:
    for tech, data in TECHS.items():
        if recipe in data.get("unlocks", {}).get("recipes", []):
            return tech
    return ""


def tier_cost(tier: int) -> dict:
    return dict(CITY_TIER_COST.get(tier, {}))


# ------------------------------------------------------------------- epochs
# A country climbs through the ages by researching. An age needs *all* of its
# techs, so the age is a summary of what the country can do (b10).
AGES = [
    ("stone", []),                                            # the start
    ("bronze", ["agriculture", "masonry"]),
    ("iron", ["military", "logistics"]),
    ("industrial", ["industrialization", "medicine"]),
    ("electric", ["electricity", "chemistry"]),
]
AGE_ORDER = [code for code, _techs in AGES]


def age_of(techs) -> str:
    """The age a country is in, given the techs it has researched."""
    known = set(techs or [])
    current = AGE_ORDER[0]
    for code, required in AGES:
        if all(tech in known for tech in required):
            current = code
        else:
            break
    return current


def age_index(age: str) -> int:
    return AGE_ORDER.index(age) if age in AGE_ORDER else 0


def age_at_least(techs, age: str) -> bool:
    """Has the country reached this age (or a later one)?"""
    return age_index(age_of(techs)) >= age_index(age)
