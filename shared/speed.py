"""Movement speed rules - shared by the server and the client.

b11: a player may walk into the water. He does not swim like a fish: he wades
slowly (40 % of the normal speed), never drowns and can always climb back onto
the shore. A bridge over the water is still worth building - on planks you move
at full speed.

The client predicts its own movement with exactly these numbers, otherwise the
server would pull the player back on every step (rubber-banding).
"""

GRASS, STONE, WATER, CAVE = 0, 1, 2, 3

SWIM_SPEED = 0.4                      # of the normal walking speed
WEATHER_SPEED = {"clear": 1.0, "rain": 0.85, "fog": 0.95}
SPEED_MIN = 0.05                      # never freeze a player completely


def terrain_speed(tile, swim: bool = True, swim_speed: float = SWIM_SPEED) -> float:
    """How fast you move over this kind of ground."""
    if tile == WATER:
        return float(swim_speed) if swim else 0.0
    return 1.0


def weather_speed(weather: str, enabled: bool = True) -> float:
    """Rain makes everybody slower, fog almost nothing."""
    if not enabled:
        return 1.0
    return WEATHER_SPEED.get(weather or "clear", 1.0)


def move_multiplier(tile, weather: str = "clear", swim: bool = True,
                    swim_speed: float = SWIM_SPEED,
                    weather_enabled: bool = True) -> float:
    """The whole movement multiplier for a tile + the current weather."""
    factor = terrain_speed(tile, swim, swim_speed)
    return max(SPEED_MIN, factor * weather_speed(weather, weather_enabled))
