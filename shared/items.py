"""Items, recipes and smelting rules shared by client and server.

Item fields that matter to the game logic:

    type        tool / weapon / food / material / armor / seed / ammo / resource
    durability  hit points of the item itself (tools and weapons wear out)
    efficiency  how many resource units one swing gives (tools)
    damage      melee/ranged damage
    range       reach in pixels
    ammo        ammo item consumed per shot (pistol -> ammo, bow -> arrow)
    cooldown    seconds between shots
    targets     resource types the tool is good at
    food        {"hunger": +x, "heal": +y}
    armor       damage reduction points (armor pieces)

Recipe format:

    "iron_sword": {
        "cost": {"wood": 1, "iron_ingot": 2},   # resources that are consumed
        "output": 1,                            # how many you get
        "category": "weapon",                   # grouping in the crafting menu
        "station": "crafting_table",            # must stand next to it (None = anywhere)
    }
"""

ITEMS = {
    # Resources / materials -------------------------------------------------
    "wood": {"type": "resource", "category": "material"},
    "stone": {"type": "resource", "category": "material"},
    "iron_ore": {"type": "resource", "category": "material"},
    "gold_ore": {"type": "resource", "category": "material"},
    "coal_ore": {"type": "resource", "category": "material"},
    "iron_ingot": {"type": "material", "category": "material"},
    "gold_ingot": {"type": "material", "category": "material"},
    "sulfur_ore": {"type": "resource", "category": "material"},
    "sulfur": {"type": "material", "category": "material"},
    "gunpowder": {"type": "material", "category": "material", "volatile": True},
    "coal": {"type": "fuel", "category": "material", "energy": 10},
    "oil_barrel": {"type": "fuel", "category": "material", "energy": 100},
    "leather": {"type": "material", "category": "material"},
    "wool": {"type": "material", "category": "material"},
    "string": {"type": "material", "category": "material"},
    "flour": {"type": "material", "category": "material"},

    # Tools -----------------------------------------------------------------
    "pickaxe": {"type": "tool", "category": "tool", "durability": 50,
                "efficiency": 2, "damage": 3, "range": 40, "targets": ["rock", "ore"]},
    "axe": {"type": "tool", "category": "tool", "durability": 50,
            "efficiency": 2, "damage": 4, "range": 40, "targets": ["tree"]},
    "iron_pickaxe": {"type": "tool", "category": "tool", "durability": 150,
                     "efficiency": 4, "damage": 5, "range": 40, "targets": ["rock", "ore"]},
    "iron_axe": {"type": "tool", "category": "tool", "durability": 150,
                 "efficiency": 4, "damage": 6, "range": 40, "targets": ["tree"]},
    "sickle": {"type": "tool", "category": "tool", "durability": 80,
               "efficiency": 3, "damage": 3, "range": 40, "targets": ["bush"]},

    # Weapons ---------------------------------------------------------------
    "sword": {"type": "weapon", "category": "weapon", "damage": 10, "range": 50,
              "durability": 50},
    "iron_sword": {"type": "weapon", "category": "weapon", "damage": 20, "range": 50,
                   "durability": 150},
    "pistol": {"type": "weapon", "category": "weapon", "damage": 40, "range": 300,
               "cooldown": 2.0, "ammo": "ammo"},
    "bow": {"type": "weapon", "category": "weapon", "damage": 25, "range": 260,
            "cooldown": 1.0, "ammo": "arrow", "durability": 120},
    "shield": {"type": "weapon", "category": "weapon", "damage": 2, "range": 45,
               "durability": 200, "block": 0.7},

    # Armor -----------------------------------------------------------------
    "leather_helmet": {"type": "armor", "category": "armor", "slot": "helmet", "armor": 2},
    "leather_chestplate": {"type": "armor", "category": "armor", "slot": "chest",
                           "armor": 4},
    "leather_leggings": {"type": "armor", "category": "armor", "slot": "legs",
                         "armor": 3},
    "leather_boots": {"type": "armor", "category": "armor", "slot": "feet", "armor": 2},
    "iron_helmet": {"type": "armor", "category": "armor", "slot": "helmet", "armor": 4},
    "iron_chestplate": {"type": "armor", "category": "armor", "slot": "chest",
                        "armor": 7},
    "iron_leggings": {"type": "armor", "category": "armor", "slot": "legs", "armor": 5},
    "iron_boots": {"type": "armor", "category": "armor", "slot": "feet", "armor": 3},

    # Food / farming --------------------------------------------------------
    "wheat_seeds": {"type": "seed", "category": "food"},
    "wheat": {"type": "food", "category": "food", "food": {"hunger": 8, "heal": 2}},
    "flour_bag": {"type": "material", "category": "material"},
    "bread": {"type": "food", "category": "food", "food": {"hunger": 30, "heal": 8}},
    "apple": {"type": "food", "category": "food", "food": {"hunger": 12, "heal": 4}},
    "berries": {"type": "food", "category": "food", "food": {"hunger": 8, "heal": 3}},
    "raw_meat": {"type": "food", "category": "food", "food": {"hunger": 10, "heal": 0},
                 "poison": 0.35},
    "cooked_meat": {"type": "food", "category": "food", "food": {"hunger": 35, "heal": 12}},
    "fish": {"type": "food", "category": "food", "food": {"hunger": 14, "heal": 4},
             "poison": 0.25},
    "cooked_fish": {"type": "food", "category": "food", "food": {"hunger": 26, "heal": 9}},
    "mushroom": {"type": "food", "category": "food", "food": {"hunger": 10, "heal": 2},
                 "poison": 0.10},

    # Machines (placeable via buildings, kept here for the inventory icons) --
    "drill": {"type": "machine", "category": "machine"},
    "advanced_workbench": {"type": "machine", "category": "machine"},
    "pump": {"type": "machine", "category": "machine"},
    "chemical_plant": {"type": "machine", "category": "machine"},

    # Ammunition ------------------------------------------------------------
    "ammo": {"type": "ammo", "category": "ammo"},
    "arrow": {"type": "ammo", "category": "ammo"},
    "oil_deposit": {"type": "resource", "category": "material"},

    # Fishing (b9) ----------------------------------------------------------
    "fishing_rod": {"type": "tool", "category": "tool", "durability": 60,
                    "efficiency": 1, "targets": []},

    # Medicine (b10) --------------------------------------------------------
    # A medkit heals wounds and cures poison. It is not food: it is used with
    # the "use" packet (key H), so eating does not silently waste it.
    "medkit": {"type": "material", "category": "material", "heal": 45,
               "cures_poison": True, "consumable": True},
    "bandage": {"type": "material", "category": "material", "heal": 15,
                "consumable": True},

    # Animals (icons for the drops and the animals themselves) --------------
    "sheep": {"type": "animal", "category": "animal"},
    "cow": {"type": "animal", "category": "animal"},
    "chicken": {"type": "animal", "category": "animal"},
    "wolf": {"type": "animal", "category": "animal"},
    "bear": {"type": "animal", "category": "animal"},
}

# --------------------------------------------------------------------- recipes
CRAFTING_RECIPES = {
    # tools
    "axe": {"cost": {"wood": 2, "stone": 3}, "output": 1, "category": "tool",
            "station": "crafting_table"},
    "pickaxe": {"cost": {"wood": 2, "stone": 3}, "output": 1, "category": "tool",
                "station": "crafting_table"},
    "sickle": {"cost": {"wood": 2, "iron_ingot": 1}, "output": 1, "category": "tool",
               "station": "crafting_table"},
    "fishing_rod": {"cost": {"wood": 3, "string": 2}, "output": 1, "category": "tool",
                    "station": "crafting_table"},
    "iron_axe": {"cost": {"wood": 2, "iron_ingot": 3}, "output": 1, "category": "tool",
                 "station": "advanced_workbench"},
    "iron_pickaxe": {"cost": {"wood": 2, "iron_ingot": 3}, "output": 1,
                     "category": "tool", "station": "advanced_workbench"},
    # weapons
    "sword": {"cost": {"wood": 1, "stone": 2}, "output": 1, "category": "weapon",
              "station": "crafting_table"},
    "iron_sword": {"cost": {"wood": 1, "iron_ingot": 2}, "output": 1,
                   "category": "weapon", "station": "advanced_workbench"},
    "pistol": {"cost": {"iron_ingot": 10, "wood": 5}, "output": 1, "category": "weapon",
               "station": "advanced_workbench"},
    "bow": {"cost": {"wood": 6, "string": 3}, "output": 1, "category": "weapon",
            "station": "crafting_table"},
    "shield": {"cost": {"wood": 4, "leather": 3}, "output": 1, "category": "weapon",
               "station": "crafting_table"},
    # ammunition
    "ammo": {"cost": {"iron_ingot": 1, "gunpowder": 1}, "output": 5, "category": "ammo",
             "station": "crafting_table"},
    "arrow": {"cost": {"wood": 1, "stone": 1}, "output": 5, "category": "ammo",
              "station": "crafting_table"},
    # armor
    "leather_helmet": {"cost": {"leather": 3}, "output": 1, "category": "armor",
                       "station": "crafting_table"},
    "leather_chestplate": {"cost": {"leather": 5}, "output": 1, "category": "armor",
                           "station": "crafting_table"},
    "leather_leggings": {"cost": {"leather": 4}, "output": 1, "category": "armor",
                         "station": "crafting_table"},
    "leather_boots": {"cost": {"leather": 2}, "output": 1, "category": "armor",
                      "station": "crafting_table"},
    "iron_helmet": {"cost": {"iron_ingot": 5}, "output": 1, "category": "armor",
                    "station": "advanced_workbench"},
    "iron_chestplate": {"cost": {"iron_ingot": 8}, "output": 1, "category": "armor",
                        "station": "advanced_workbench"},
    "iron_leggings": {"cost": {"iron_ingot": 7}, "output": 1, "category": "armor",
                      "station": "advanced_workbench"},
    "iron_boots": {"cost": {"iron_ingot": 4}, "output": 1, "category": "armor",
                   "station": "advanced_workbench"},
    # materials
    "gunpowder": {"cost": {"coal": 1, "sulfur": 1}, "output": 1, "category": "material",
                  "station": "chemical_plant"},
    "flour": {"cost": {"wheat": 2}, "output": 1, "category": "material",
              "station": "crafting_table"},
    "string": {"cost": {"wool": 1}, "output": 2, "category": "material",
               "station": "crafting_table"},
    # medicine (b10)
    "bandage": {"cost": {"string": 2, "leather": 1}, "output": 2, "category": "material",
                "station": "crafting_table"},
    "medkit": {"cost": {"string": 4, "leather": 2, "mushroom": 2}, "output": 1,
               "category": "material", "station": "hospital"},
    # machines
    "advanced_workbench": {"cost": {"iron_ingot": 25, "wood": 10}, "output": 1,
                           "category": "machine", "station": "crafting_table"},
}

# Smelting: furnace + fuel. `cook` entries turn raw food into safe food.
SMELTING_RECIPES = {
    "smelt_iron": {"input": "iron_ore", "output": "iron_ingot", "fuel": "coal"},
    "smelt_gold": {"input": "gold_ore", "output": "gold_ingot", "fuel": "coal"},
    "cook_meat": {"input": "raw_meat", "output": "cooked_meat", "fuel": "coal"},
    "cook_fish": {"input": "fish", "output": "cooked_fish", "fuel": "coal"},
    "bake_bread": {"input": "flour", "output": "bread", "fuel": "coal"},
}

# What a resource node gives when gathered (base amount, before tools)
RESOURCE_YIELD = {
    "mushroom": ("mushroom", 2),
    "tree": ("wood", 1),
    "rock": ("stone", 1),
    "stone": ("stone", 1),
    "iron_ore": ("iron_ore", 1),
    "gold_ore": ("gold_ore", 1),
    "coal_ore": ("coal", 1),
    "sulfur_ore": ("sulfur", 1),
    "oil_deposit": ("oil_barrel", 1),
    "bush": ("berries", 2),
}

CATEGORY_ORDER = ["tool", "weapon", "armor", "ammo", "material", "machine"]


# ------------------------------------------------------------------- helpers
def item_data(item: str) -> dict:
    return ITEMS.get(item, {})


def item_type(item: str) -> str:
    return ITEMS.get(item, {}).get("type", "material")


def item_durability(item: str) -> int:
    return int(ITEMS.get(item, {}).get("durability", 0) or 0)


def item_efficiency(item: str) -> int:
    return int(ITEMS.get(item, {}).get("efficiency", 1))


def item_damage(item: str) -> int:
    return int(ITEMS.get(item, {}).get("damage", 0))


def item_range(item: str) -> int:
    return int(ITEMS.get(item, {}).get("range", 40))


def item_ammo(item: str):
    return ITEMS.get(item, {}).get("ammo")


def item_cooldown(item: str) -> float:
    return float(ITEMS.get(item, {}).get("cooldown", 0.0))


def item_targets(item: str) -> list:
    return list(ITEMS.get(item, {}).get("targets", []))


def item_armor_points(item: str) -> int:
    return int(ITEMS.get(item, {}).get("armor", 0))


def item_slot(item: str):
    return ITEMS.get(item, {}).get("slot")


def item_food(item: str):
    return ITEMS.get(item, {}).get("food")


def item_poison(item: str) -> float:
    return float(ITEMS.get(item, {}).get("poison", 0.0))


def item_heal(item: str) -> int:
    """How much health a consumable restores (0 = it is not medicine)."""
    return int(ITEMS.get(item, {}).get("heal", 0))


def cures_poison(item: str) -> bool:
    return bool(ITEMS.get(item, {}).get("cures_poison"))


def is_consumable(item: str) -> bool:
    return item_heal(item) > 0 or bool(ITEMS.get(item, {}).get("consumable"))


def item_block(item: str) -> float:
    return float(ITEMS.get(item, {}).get("block", 0.0))


def is_food(item: str) -> bool:
    return bool(item_food(item))


def is_armor(item: str) -> bool:
    return item_type(item) == "armor"


# ------------------------------------------------------------------- recipes
def recipe_cost(recipe: str) -> dict:
    return dict(CRAFTING_RECIPES.get(recipe, {}).get("cost", {}))


def recipe_output(recipe: str) -> int:
    return int(CRAFTING_RECIPES.get(recipe, {}).get("output", 1))


def recipe_station(recipe: str):
    return CRAFTING_RECIPES.get(recipe, {}).get("station")


def recipe_category(recipe: str) -> str:
    return CRAFTING_RECIPES.get(recipe, {}).get("category", "material")


def craftable_amount(recipe: str, inventory: dict) -> int:
    """How many times the recipe fits into the inventory."""
    cost = recipe_cost(recipe)
    if not cost:
        return 0
    return min(inventory.get(res, 0) // amount for res, amount in cost.items())


def pay_for_craft(recipe: str, inventory: dict, count: int = 1) -> int:
    """Consume the resources, return how many items were produced."""
    cost = recipe_cost(recipe)
    for res, amount in cost.items():
        inventory[res] = inventory.get(res, 0) - amount * count
    for res, amount in list(cost.items()):
        if inventory.get(res, 0) <= 0:
            inventory.pop(res, None)
    return recipe_output(recipe) * count
