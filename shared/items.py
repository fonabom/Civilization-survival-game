ITEMS = {
    # Resources
    "wood": {"type": "resource"},
    "stone": {"type": "resource"},
    "iron_ore": {"type": "resource"},
    "gold_ore": {"type": "resource"},
    "coal_ore": {"type": "resource"}, # New
    "coal": {"type": "fuel"},
    "iron_ingot": {"type": "material"},
    "gold_ingot": {"type": "material"},
    
    # Tools (Stone)
    "pickaxe": {"type": "tool", "durability": 50, "efficiency": 2},
    "axe": {"type": "tool", "durability": 50, "efficiency": 2},
    "sword": {"type": "weapon", "damage": 10, "durability": 50},
    
    # Tools (Iron)
    "iron_pickaxe": {"type": "tool", "durability": 150, "efficiency": 4},
    "iron_axe": {"type": "tool", "durability": 150, "efficiency": 4},
    "iron_sword": {"type": "weapon", "damage": 20, "durability": 150},

    # Farming
    "wheat_seeds": {"type": "seed"},
    "wheat": {"type": "food"},
    
    # Industrial
    "oil_deposit": {"type": "resource"},
    "oil_barrel": {"type": "fuel", "energy": 100},
    "drill": {"type": "machine"}, 
    "advanced_workbench": {"type": "machine"},
    
    # Gunpowder
    "sulfur_ore": {"type": "resource"},
    "sulfur": {"type": "material"},
    "gunpowder": {"type": "material", "volatile": True},
    "pistol": {"type": "weapon", "range": 300, "damage": 40, "cooldown": 2.0},
    "ammo": {"type": "ammo"}
}

# Recipes for simple crafting (Crafting Table)
CRAFTING_RECIPES = {
    "pickaxe": {"wood": 2, "stone": 3},
    "axe": {"wood": 2, "stone": 3},
    "sword": {"wood": 1, "stone": 2},
    
    "iron_pickaxe": {"wood": 2, "iron_ingot": 3},
    "iron_axe": {"wood": 2, "iron_ingot": 3},
    "iron_sword": {"wood": 1, "iron_ingot": 2},
    
    # Gunpowder Tech
    "gunpowder": {"coal": 1, "sulfur": 1},
    "pistol": {"iron_ingot": 10, "wood": 5},
    "ammo": {"iron_ingot": 1, "gunpowder": 1} # Yields maybe 5? For now 1.
}

# Smelting Recipes (Furnace)
SMELTING_RECIPES = {
    "iron_ore": "iron_ingot",
    "gold_ore": "gold_ingot"
}
