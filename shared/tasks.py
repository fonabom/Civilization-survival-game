"""Tasks and achievements.

One system for both: every entry watches a counter from `player["stats"]` and
completes automatically when the counter reaches `target`. Completions are stored
in `player["tasks"]` (and in the account progress, so they are permanent).

The quest menu (V -> Quests) shows them with progress bars; finishing one pops a
notification and pays the reward.
"""

# kind: "task" — a goal that pushes you forward, "achievement" — a milestone
TASKS = {
    # --- first steps -------------------------------------------------------
    "first_wood": {"kind": "task", "stat": "wood_gathered", "target": 20,
                   "reward": {"stone": 10}},
    "first_stone": {"kind": "task", "stat": "stone_gathered", "target": 20,
                    "reward": {"wood": 10}},
    "first_craft": {"kind": "task", "stat": "items_crafted", "target": 1,
                    "reward": {"wood": 5}},
    "first_meal": {"kind": "task", "stat": "food_eaten", "target": 1,
                   "reward": {"wheat_seeds": 3}},
    "first_build": {"kind": "task", "stat": "blocks_built", "target": 1,
                    "reward": {"wood": 10}},
    "first_city": {"kind": "task", "stat": "cities_founded", "target": 1,
                   "reward": {"stone": 50}},
    "first_research": {"kind": "task", "stat": "techs_researched", "target": 1,
                       "reward": {"iron_ingot": 5}},
    "first_hunt": {"kind": "task", "stat": "animals_hunted", "target": 1,
                   "reward": {"wood": 10}},
    "first_storage": {"kind": "task", "stat": "chests_used", "target": 1,
                      "reward": {"wood": 10}},
    "first_torch": {"kind": "task", "stat": "torches_placed", "target": 1,
                    "reward": {"coal": 3}},
    # --- longer goals ------------------------------------------------------
    "town_hall": {"kind": "task", "stat": "town_centers", "target": 1,
                  "reward": {"iron_ingot": 10, "stone": 50}},
    "big_builder": {"kind": "task", "stat": "blocks_built", "target": 50,
                    "reward": {"iron_ingot": 15}},
    "iron_worker": {"kind": "task", "stat": "iron_smelted", "target": 20,
                    "reward": {"coal": 10}},
    "traveler": {"kind": "task", "stat": "distance_walked", "target": 20000,
                 "reward": {"bread": 3}},
    "hunter": {"kind": "task", "stat": "animals_hunted", "target": 25,
               "reward": {"leather": 5}},
    "warrior": {"kind": "task", "stat": "enemies_defeated", "target": 3,
                "reward": {"iron_ingot": 10}},
    # --- achievements ------------------------------------------------------
    "ach_woodcutter": {"kind": "achievement", "stat": "wood_gathered", "target": 250,
                       "reward": {"iron_ingot": 5}},
    "ach_miner": {"kind": "achievement", "stat": "ore_gathered", "target": 150,
                  "reward": {"gold_ingot": 5}},
    "ach_crafter": {"kind": "achievement", "stat": "items_crafted", "target": 100,
                    "reward": {"iron_ingot": 10}},
    "ach_architect": {"kind": "achievement", "stat": "blocks_built", "target": 500,
                      "reward": {"gold_ingot": 10}},
    "ach_explorer": {"kind": "achievement", "stat": "distance_walked", "target": 200000,
                     "reward": {"oil_barrel": 5}},
    "ach_rich": {"kind": "achievement", "stat": "gold_mined", "target": 50,
                 "reward": {"gold_ingot": 20}},
    "ach_nightowl": {"kind": "achievement", "stat": "nights_survived", "target": 3,
                     "reward": {"ammo": 20}},
    "ach_hero": {"kind": "achievement", "stat": "players_defeated", "target": 10,
                 "reward": {"iron_ingot": 30}},
    "ach_smith": {"kind": "achievement", "stat": "items_smelted", "target": 100,
                  "reward": {"gold_ingot": 15}},
}

STAT_LABELS = {
    "wood_gathered": "stats.wood_gathered",
    "stone_gathered": "stats.stone_gathered",
    "ore_gathered": "stats.ore_gathered",
    "gold_mined": "stats.gold_mined",
    "animals_hunted": "stats.animals_hunted",
    "blocks_built": "stats.blocks_built",
    "items_crafted": "stats.items_crafted",
    "items_smelted": "stats.items_smelted",
    "iron_smelted": "stats.iron_smelted",
    "techs_researched": "stats.techs_researched",
    "cities_founded": "stats.cities_founded",
    "town_centers": "stats.town_centers",
    "enemies_defeated": "stats.enemies_defeated",
    "players_defeated": "stats.players_defeated",
    "distance_walked": "stats.distance_walked",
    "days_survived": "stats.days_survived",
    "nights_survived": "stats.nights_survived",
    "chests_used": "stats.chests_used",
    "food_eaten": "stats.food_eaten",
    "torches_placed": "stats.torches_placed",
}

TASK_ORDER = list(TASKS)


def task_data(code: str) -> dict:
    return TASKS.get(code, {})


def bump(stats: dict, stat: str, amount: float = 1) -> None:
    if amount:
        stats[stat] = stats.get(stat, 0) + amount


def completed_now(stats: dict, done: dict) -> list:
    """Codes of the tasks whose target has just been reached (not yet in `done`)."""
    finished = []
    for code, data in TASKS.items():
        if code in done:
            continue
        if stats.get(data["stat"], 0) >= data["target"]:
            finished.append(code)
    return finished


def progress(stats: dict, code: str) -> tuple:
    data = TASKS.get(code, {})
    target = max(1, data.get("target", 1))
    current = min(target, stats.get(data.get("stat", ""), 0))
    return current, target
