"""Seasons - the world has a rhythm (b13 «Мир живой 2»).

A season lasts `days_per_season` in-game days (config `seasons` / `days_per_season`).
Everything seasonal is a **multiplier**, so switching seasons off (`"seasons": false`)
gives exactly the b12 behaviour back.

    spring  - the world wakes up: forests grow back fast
    summer  - long days, plenty of everything (the neutral season)
    autumn  - mushrooms and berries everywhere, resources thin out
    winter  - the ground is frozen: almost nothing grows back, wolves roam

Server side the season changes a few numbers; the client shows it in the HUD,
paints a light tint over the world and lets snow fall in winter.
"""

SPRING, SUMMER, AUTUMN, WINTER = "spring", "summer", "autumn", "winter"
ORDER = (SPRING, SUMMER, AUTUMN, WINTER)

NAME_KEYS = {
    SPRING: "season.spring",
    SUMMER: "season.summer",
    AUTUMN: "season.autumn",
    WINTER: "season.winter",
}

# How fast the world grows resources back in each season (server: respawn timer)
RESOURCE_REGROWTH = {SPRING: 1.25, SUMMER: 1.0, AUTUMN: 0.9, WINTER: 0.45}

# Mushrooms like the wet autumn, spring berries come with the new grass
FORAGE_BONUS = {SPRING: 1.1, SUMMER: 1.0, AUTUMN: 1.35, WINTER: 0.6}

# Movement: deep snow and mud of a thaw slow everybody a little
MOVE_SPEED = {SPRING: 1.0, SUMMER: 1.0, AUTUMN: 0.98, WINTER: 0.92}

# Weather is drawn from a different bag in every season (winter -> no rain storms)
WEATHER_BAG = {
    SPRING: ("clear", "clear", "rain", "rain", "fog"),
    SUMMER: ("clear", "clear", "clear", "clear", "rain"),
    AUTUMN: ("clear", "rain", "fog", "fog", "rain"),
    WINTER: ("clear", "clear", "fog", "fog", "fog"),
}

# A tint the client paints over the map to make the season visible (r, g, b, alpha)
TINT = {
    SPRING: (60, 140, 70, 12),
    SUMMER: (255, 240, 180, 10),
    AUTUMN: (180, 120, 40, 26),
    WINTER: (190, 215, 245, 42),
}


def season_of(day: int, days_per_season: int = 3, enabled: bool = True) -> str:
    """Which season a (1-based) in-game day belongs to."""
    if not enabled:
        return SUMMER
    length = max(1, int(days_per_season or 3))
    index = (max(1, int(day)) - 1) // length % len(ORDER)
    return ORDER[index]


def is_winter(season: str) -> bool:
    return season == WINTER


def regrowth(season: str, enabled: bool = True) -> float:
    if not enabled:
        return 1.0
    return RESOURCE_REGROWTH.get(season, 1.0)


def forage_bonus(season: str, enabled: bool = True) -> float:
    if not enabled:
        return 1.0
    return FORAGE_BONUS.get(season, 1.0)


def move_speed(season: str, enabled: bool = True) -> float:
    if not enabled:
        return 1.0
    return MOVE_SPEED.get(season, 1.0)


def weather_bag(season: str, enabled: bool = True):
    if not enabled:
        return ("clear", "clear", "clear", "rain", "fog")
    return WEATHER_BAG.get(season, WEATHER_BAG[SUMMER])


def tint(season: str, enabled: bool = True):
    if not enabled:
        return None
    return TINT.get(season)
