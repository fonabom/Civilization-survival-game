import random
import threading

from server.civilization import CivManager
from shared.biomes import (ANIMAL_WEIGHT, BIOMES, DESERT, FOREST, MEADOW,
                           MUSHROOM_WEIGHT, ORE_WEIGHT, SNOW, SWAMP, TREE_WEIGHT,
                           CAVE as CAVE_BIOME, speed as biome_speed)
from shared.seasons import move_speed as season_move
from shared.speed import SWIM_SPEED, terrain_speed
from shared.structures import (get_hp, get_light, get_power, get_speed, get_storage,
                               is_walkable, needs_power)

# World size in tiles (kept in sync with client/settings.py)
TILE_SIZE = 32
WORLD_WIDTH = 100
WORLD_HEIGHT = 100

GRASS = 0
STONE = 1
WATER = 2      # lakes and rivers - nobody swims, but bridges go over them
CAVE = 3       # dark cave floor: rich ore inside, no sunlight

TILE_CHARS = {GRASS: "0", STONE: "1", WATER: "2", CAVE: "3"}

TERRAIN_SEED = 1337

# Resource population that the world tries to keep
# How the b9 world is shaped
LAKE_COUNT = 5             # number of lakes / rivers carved into the map
CAVE_COUNT = 7             # number of caves (dark, rich in ore)
CAVE_RADIUS = (3, 6)       # min/max radius of a cave in tiles
# per cave: what grows inside the dark (multiplied by the number of caves)
CAVE_ORE = {"iron_ore": 3, "gold_ore": 2, "coal_ore": 2, "sulfur_ore": 2, "mushroom": 5}
CAVE_YIELD_BONUS = 2       # gathering inside a cave pays double

RESOURCE_TARGETS = {
    "tree": 400,
    "rock": 200,
    "iron_ore": 100,
    "gold_ore": 50,
    "coal_ore": 100,
    "sulfur_ore": 60,
    "oil_deposit": 20,
    "bush": 120,
    "mushroom": 60,
}

# Animals that live in the world (b8). Peaceful ones wander, wolves hunt.
ANIMAL_TYPES = {
    "sheep": {"hp": 30, "speed": 0.5, "drops": {"wool": 2, "raw_meat": 1}, "hostile": False},
    "cow": {"hp": 40, "speed": 0.45, "drops": {"leather": 2, "raw_meat": 2}, "hostile": False},
    "chicken": {"hp": 15, "speed": 0.6, "drops": {"raw_meat": 1, "string": 1}, "hostile": False},
    "wolf": {"hp": 60, "speed": 1.1, "drops": {"leather": 1, "raw_meat": 1},
             "hostile": True, "damage": 8, "range": 34, "pack": True},
    "bear": {"hp": 140, "speed": 0.9, "drops": {"leather": 3, "raw_meat": 4},
             "hostile": True, "damage": 18, "range": 38, "cave": True},
}
ANIMAL_TARGETS = {"sheep": 40, "cow": 30, "chicken": 40, "wolf": 20, "bear": 5}
WOLF_PACK_SIZE = (3, 5)     # wolves spawn in packs of this size
PACK_ALERT_RANGE = 380      # a pack mate this close joins the hunt
ANIMAL_IDLE = 3.0          # seconds between wander steps
ANIMAL_AGGRO_RANGE = 420   # pixels: how far a wolf notices a player
ANIMAL_ATTACK_COOLDOWN = 2.0


class WorldState:
    """Authoritative world state.

    Every mutation is protected by `self.lock` because the network threads,
    the broadcast thread and the game loop all touch this object.
    """

    def __init__(self, seed: int = TERRAIN_SEED, width: int = WORLD_WIDTH,
                 height: int = WORLD_HEIGHT):
        self.lock = threading.RLock()
        self.width = width
        self.height = height
        self.players = {}    # id -> {x, y, name, hp, inventory, rev}
        self.resources = {}  # "x,y" -> {x, y, type}
        self.buildings = {}  # "gx,gy" -> {x, y, type, owner, w, h, ...}
        self.occupied = set()  # every tile covered by a building
        self.tile_building = {}  # "gx,gy" -> key of the building covering that tile
        self.civs = CivManager()
        self.animals = {}   # id -> {x, y, type, hp, ...}
        self.next_animal = 0
        self.trades = {}    # id -> market offer (b9)
        self.next_trade = 0
        # goods owed to players who are offline (market sales pay into this)
        self.pending_payments = {}   # name(lower) -> [ {item: count}, ... ]
        self.seed = seed
        # b11: wading through water (the server may switch it off in the config)
        self.swim = True
        self.swim_speed = SWIM_SPEED
        # Progress of players who are currently offline (name -> saved data)
        self.saved_players = {}

        # Revision counters: clients only receive a section when it changed.
        self.rev = {"resources": 1, "buildings": 1, "civs": 1, "animals": 1,
                    "trades": 1}

        self.biomes = self.generate_biomes(seed)
        self.season = "summer"
        self.season_enabled = True
        self.terrain = self.generate_terrain(seed)
        self._apply_cave_biome()
        self._generate_resources()
        self.spawn_animals(initial=True)

    # ------------------------------------------------------------------ world
    def generate_terrain(self, seed: int) -> list:
        """Deterministic terrain so client and server agree on what blocks.

        Bit of rock noise -> lakes and rivers -> caves (dark, ore rich).
        The world is built from the same seed on every machine, so the client
        only receives the compact `terrain_string()`.
        """
        rng = random.Random(seed)
        cols, rows = self.width // 4 + 1, self.height // 4 + 1
        # coarse noise, then a smoothing pass
        coarse = [[1 if rng.random() < 0.22 else 0 for _ in range(cols)] for _ in range(rows)]
        tiles = [[GRASS] * self.width for _ in range(self.height)]
        for y in range(self.height):
            for x in range(self.width):
                cy, cx = y // 4, x // 4
                neighbours = sum(coarse[min(cy + dy, rows - 1)][min(cx + dx, cols - 1)]
                                 for dy in (0, 1) for dx in (0, 1))
                tiles[y][x] = STONE if neighbours >= 3 else GRASS

        water = self._carve_water(tiles, rng)
        caves = self._carve_caves(tiles, rng, water)
        self.water_tiles = water
        self.cave_tiles = caves
        return tiles

    def generate_biomes(self, seed: int) -> list:
        """Two smooth noise maps (warmth and moisture) -> five biomes.

        Standard library only: a coarse random grid is smoothed twice, so the
        result is large readable regions instead of a checkerboard. The poles of
        the map are cold (snow) and the middle is warm, which makes the world
        feel like a small continent instead of a patchwork.
        """
        rng = random.Random(seed + 99)
        cols, rows = self.width // 5 + 1, self.height // 5 + 1

        def smooth(grid):
            out = [[0.0] * cols for _ in range(rows)]
            for y in range(rows):
                for x in range(cols):
                    total = 0.0
                    for dy in (-1, 0, 1):
                        for dx in (-1, 0, 1):
                            total += grid[min(max(y + dy, 0), rows - 1)][
                                min(max(x + dx, 0), cols - 1)]
                    out[y][x] = total / 9.0
            return out

        warmth = smooth(smooth([[rng.random() for _ in range(cols)] for _ in range(rows)]))
        wetness = smooth(smooth([[rng.random() for _ in range(cols)] for _ in range(rows)]))

        # thresholds tuned against the real noise (median warmth/wetness ~0.48)
        def pick(y, x):
            t = warmth[min(y // 5, rows - 1)][min(x // 5, cols - 1)]
            m = wetness[min(y // 5, rows - 1)][min(x // 5, cols - 1)]
            latitude = y / max(1, self.height - 1)
            # the poles are colder whatever the noise says
            t -= max(0.0, 0.18 - latitude) * 1.3
            t -= max(0.0, latitude - 0.82) * 1.3
            if t < 0.372:
                return SNOW
            if m > 0.552:
                return SWAMP
            if m < 0.452 and t > 0.462:
                return DESERT
            if m > 0.488:
                return FOREST
            return MEADOW

        biomes = [[pick(y, x) for x in range(self.width)] for y in range(self.height)]
        # the area around the spawn stays friendly meadow
        cx, cy = self.width // 2, self.height // 2
        for y in range(max(0, cy - 4), min(self.height, cy + 5)):
            for x in range(max(0, cx - 4), min(self.width, cx + 5)):
                biomes[y][x] = MEADOW
        return biomes

    def _apply_cave_biome(self):
        """Cave floors are their own biome; rock and water keep a neighbour's."""
        for (x, y) in self.cave_tiles:
            self.biomes[y][x] = CAVE_BIOME
        for y in range(self.height):
            for x in range(self.width):
                if self.terrain[y][x] in (STONE, WATER):
                    self.biomes[y][x] = self._neighbour_biome(x, y)

    def _neighbour_biome(self, gx: int, gy: int) -> int:
        for radius in (1, 2, 3):
            for dy in range(-radius, radius + 1):
                for dx in range(-radius, radius + 1):
                    x, y = gx + dx, gy + dy
                    if not (0 <= x < self.width and 0 <= y < self.height):
                        continue
                    if self.terrain[y][x] not in (STONE, WATER):
                        return self.biomes[y][x]
        return MEADOW

    def biome_at(self, gx: int, gy: int) -> int:
        if gx < 0 or gy < 0 or gx >= self.width or gy >= self.height:
            return MEADOW
        return self.biomes[gy][gx]

    def biome_string(self) -> str:
        """The biome map the same way terrain travels: one digit per tile."""
        return "".join("".join(str(code) for code in row) for row in self.biomes)

    def load_biomes(self, text: str = None, size=None) -> bool:
        if size and len(size) == 2:
            self.width, self.height = int(size[0]), int(size[1])
        if not text or len(text) < self.width * self.height:
            self.biomes = self.generate_biomes(self.seed)
            return False
        rows = []
        for y in range(self.height):
            chunk = text[y * self.width:(y + 1) * self.width]
            rows.append([int(ch) if ch.isdigit() and int(ch) in BIOMES else MEADOW
                         for ch in chunk])
        self.biomes = rows
        return True

    # -- world features ----------------------------------------------------
    def _outline(self, tiles, gx, gy):
        """True when the tile or one of its 8 neighbours is stone (a rock edge)."""
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                x, y = gx + dx, gy + dy
                if 0 <= x < self.width and 0 <= y < self.height and tiles[y][x] == STONE:
                    return True
        return False

    def _carve_water(self, tiles, rng) -> set:
        """Lakes plus a river or two; returns the set of water tiles."""
        water = set()

        def blob(cx, cy, radius):
            for y in range(max(1, cy - radius), min(self.height - 1, cy + radius + 1)):
                for x in range(max(1, cx - radius), min(self.width - 1, cx + radius + 1)):
                    if (x - cx) ** 2 + (y - cy) ** 2 > radius * radius:
                        continue
                    if tiles[y][x] == STONE and rng.random() < 0.4:
                        continue          # rock stays rock, water flows around
                    tiles[y][x] = WATER
                    water.add((x, y))

        for _ in range(LAKE_COUNT):
            cx = rng.randint(10, self.width - 11)
            cy = rng.randint(10, self.height - 11)
            blob(cx, cy, rng.randint(3, 5))
        # one river: a wobbly line from one edge to another
        x = rng.randint(10, self.width - 11)
        for y in range(2, self.height - 2):
            x += rng.choice((-1, 0, 0, 1))
            x = max(3, min(self.width - 4, x))
            for dx in (0, 1):
                tiles[y][x + dx] = WATER
                water.add((x + dx, y))
        return water

    def _carve_caves(self, tiles, rng, water: set) -> set:
        """Dark caves with a single entrance; every cave gets a ring of rock."""
        caves = set()
        for _ in range(CAVE_COUNT):
            for _attempt in range(30):
                cx = rng.randint(8, self.width - 9)
                cy = rng.randint(8, self.height - 9)
                radius = rng.randint(*CAVE_RADIUS)
                overlaps_water = any((cx + dx, cy + dy) in water
                                     for dx in range(-radius - 1, radius + 2)
                                     for dy in range(-radius - 1, radius + 2))
                if overlaps_water:
                    continue
                break
            else:
                continue
            floor = []
            for y in range(cy - radius, cy + radius + 1):
                for x in range(cx - radius, cx + radius + 1):
                    if not (1 <= x < self.width - 1 and 1 <= y < self.height - 1):
                        continue
                    distance = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
                    if distance <= radius:
                        floor.append((x, y))
            if len(floor) < 6:
                continue
            # rock around the cave, grass stays visible from the outside
            for (x, y) in floor:
                for dy in (-1, 0, 1):
                    for dx in (-1, 0, 1):
                        tx, ty = x + dx, y + dy
                        if not (0 <= tx < self.width and 0 <= ty < self.height):
                            continue
                        if (tx, ty) in floor:
                            continue
                        if tiles[ty][tx] == GRASS:
                            tiles[ty][tx] = STONE
            for (x, y) in floor:
                tiles[y][x] = CAVE
                caves.add((x, y))
            # one entrance: a short corridor towards a random direction
            ex, ey = rng.choice(floor)
            dx, dy = rng.choice(((1, 0), (-1, 0), (0, 1), (0, -1)))
            for step in range(1, radius + 3):
                tx, ty = ex + dx * step, ey + dy * step
                if not (1 <= tx < self.width - 1 and 1 <= ty < self.height - 1):
                    break
                tiles[ty][tx] = CAVE
                caves.add((tx, ty))
                if tiles[ty][tx] == WATER:
                    break
        return caves

    def load_terrain(self, terrain: str = None, size=None) -> bool:
        """Restore terrain from a save file ('010110...' + [width, height])."""
        if size and len(size) == 2:
            self.width, self.height = int(size[0]), int(size[1])
        if not terrain or len(terrain) < self.width * self.height:
            self.terrain = self.generate_terrain(self.seed)
            return False
        lookup = {char: tile for tile, char in TILE_CHARS.items()}
        self.terrain = [
            [lookup.get(terrain[y * self.width + x], GRASS) for x in range(self.width)]
            for y in range(self.height)
        ]
        self.water_tiles = {(x, y) for y in range(self.height) for x in range(self.width)
                            if self.terrain[y][x] == WATER}
        self.cave_tiles = {(x, y) for y in range(self.height) for x in range(self.width)
                           if self.terrain[y][x] == CAVE}
        return True

    def terrain_string(self) -> str:
        """Compact rendering of the map for the initial packet (0 grass..3 cave)."""
        return "".join("".join(TILE_CHARS.get(t, "0") for t in row) for row in self.terrain)

    def is_blocked_tile(self, gx: int, gy: int) -> bool:
        """Rock and water block walking (bridges are checked in `passable`)."""
        if gx < 0 or gy < 0 or gx >= self.width or gy >= self.height:
            return True
        return self.terrain[gy][gx] in (STONE, WATER)

    def is_water(self, gx: int, gy: int) -> bool:
        if gx < 0 or gy < 0 or gx >= self.width or gy >= self.height:
            return False
        return self.terrain[gy][gx] == WATER

    def is_cave(self, gx: int, gy: int) -> bool:
        if gx < 0 or gy < 0 or gx >= self.width or gy >= self.height:
            return False
        return self.terrain[gy][gx] == CAVE

    def in_cave(self, x: float, y: float) -> bool:
        """Is this world position (pixels) inside a cave?"""
        return self.is_cave(int(x // TILE_SIZE), int(y // TILE_SIZE))

    def nearest_water(self, x: float, y: float, tiles: int = 2):
        """Closest water tile to a position, or None (used by fishing)."""
        gx, gy = int(x // TILE_SIZE), int(y // TILE_SIZE)
        best, best_distance = None, None
        for dy in range(-tiles, tiles + 1):
            for dx in range(-tiles, tiles + 1):
                wx, wy = gx + dx, gy + dy
                if not self.is_water(wx, wy):
                    continue
                distance = max(abs(dx), abs(dy))
                if best_distance is None or distance < best_distance:
                    best, best_distance = (wx, wy), distance
        return best

    def _generate_resources(self):
        rng = random.Random(self.seed + 1)
        W, H = self.width * TILE_SIZE, self.height * TILE_SIZE

        def add(count, rtype, weights=None):
            """Surface resources: never on rock, never in water, never in caves.

            b13: `weights` says how much a biome likes this resource, so trees
            fill the forests, ore hides in deserts and mountains, and a snowy
            tundra stays poor. Weight 0 means "never grows here".
            """
            placed = 0
            attempts = 0
            while placed < count and attempts < count * 60:
                attempts += 1
                rx = rng.randint(0, W - 1)
                ry = rng.randint(0, H - 1)
                gx, gy = rx // TILE_SIZE, ry // TILE_SIZE
                if self.is_blocked_tile(gx, gy) or self.is_cave(gx, gy):
                    continue
                if weights is not None:
                    chance = weights.get(self.biomes[gy][gx], 0.0)
                    if chance <= 0:
                        continue
                    if rng.random() > min(1.0, chance / 2.2):
                        continue          # the best biome keeps the full weight
                self.resources[f"{rx},{ry}"] = {"x": rx, "y": ry, "type": rtype}
                placed += 1

        add(RESOURCE_TARGETS["bush"], "bush", TREE_WEIGHT)
        add(RESOURCE_TARGETS["tree"], "tree", TREE_WEIGHT)
        add(RESOURCE_TARGETS["rock"], "rock", ORE_WEIGHT)
        add(RESOURCE_TARGETS["iron_ore"], "iron_ore", ORE_WEIGHT)
        add(RESOURCE_TARGETS["gold_ore"], "gold_ore", ORE_WEIGHT)
        add(RESOURCE_TARGETS["coal_ore"], "coal_ore", ORE_WEIGHT)
        add(RESOURCE_TARGETS["sulfur_ore"], "sulfur_ore", ORE_WEIGHT)
        add(RESOURCE_TARGETS["oil_deposit"], "oil_deposit", ORE_WEIGHT)
        self._generate_cave_resources(rng)
        self.touch("resources")

    def _generate_cave_resources(self, rng=None):
        """Ore and mushrooms inside caves; caves are the reason to carry a torch."""
        rng = rng or random.Random(self.seed + 7)
        caves = sorted(self.cave_tiles)
        if not caves:
            return
        caves_found = max(1, len(caves) // 40)      # roughly one "cave" per 40 tiles
        for rtype, per_cave in CAVE_ORE.items():
            count = per_cave * caves_found
            placed = 0
            for _ in range(count * 20):
                if placed >= count:
                    break
                gx, gy = rng.choice(caves)
                rx = gx * TILE_SIZE + rng.randint(0, TILE_SIZE - 1)
                ry = gy * TILE_SIZE + rng.randint(0, TILE_SIZE - 1)
                key = f"{rx},{ry}"
                if key in self.resources:
                    continue
                self.resources[key] = {"x": rx, "y": ry, "type": rtype}
                placed += 1

    def regenerate_resources(self) -> bool:
        """Top the world back up towards RESOURCE_TARGETS (a few nodes at a time)."""
        with self.lock:
            counts = {}
            for r in self.resources.values():
                counts[r["type"]] = counts.get(r["type"], 0) + 1

            rng = random.Random()
            W, H = self.width * TILE_SIZE, self.height * TILE_SIZE
            changes = False
            for rtype, target in RESOURCE_TARGETS.items():
                missing = target - counts.get(rtype, 0)
                for _ in range(min(missing, 5)):
                    if rtype == "mushroom":
                        if not self.cave_tiles:
                            break
                        gx, gy = rng.choice(sorted(self.cave_tiles))
                        x, y = gx * TILE_SIZE + rng.randint(0, TILE_SIZE - 1), \
                            gy * TILE_SIZE + rng.randint(0, TILE_SIZE - 1)
                        if f"{x},{y}" in self.resources:
                            continue
                        self.resources[f"{x},{y}"] = {"x": x, "y": y, "type": rtype}
                        changes = True
                        continue
                    weights = MUSHROOM_WEIGHT if rtype == "mushroom" else \
                        (TREE_WEIGHT if rtype in ("tree", "bush")
                         else (ORE_WEIGHT if rtype.endswith("_ore") or rtype in
                               ("rock", "oil_deposit", "sulfur_ore") else None))
                    for _try in range(12):
                        x, y = rng.randint(0, W), rng.randint(0, H)
                        if f"{x},{y}" in self.resources:
                            continue
                        gx, gy = x // TILE_SIZE, y // TILE_SIZE
                        if self.is_blocked_tile(gx, gy):
                            continue
                        if weights is not None:
                            chance = weights.get(self.biomes[gy][gx], 0.0)
                            if chance <= 0 or rng.random() > min(1.0, chance / 2.2):
                                continue
                        self.resources[f"{x},{y}"] = {"x": x, "y": y, "type": rtype}
                        changes = True
                        break
            if changes:
                self.touch("resources")
            return changes

    def trade_payload(self) -> list:
        with self.lock:
            return [dict(offer) for offer in self.trades.values()]

    def add_trade(self, offer: dict) -> str:
        with self.lock:
            trade_id = str(self.next_trade)
            self.next_trade += 1
            offer = dict(offer)
            offer["id"] = trade_id
            self.trades[trade_id] = offer
            self.touch("trades")
            return trade_id

    def drop_trade(self, trade_id: str):
        with self.lock:
            if self.trades.pop(str(trade_id), None) is not None:
                self.touch("trades")

    def queue_payment(self, name: str, items: dict):
        """Pay somebody who is offline: the goods wait for their next login."""
        with self.lock:
            key = (name or "?").lower()
            self.pending_payments.setdefault(key, []).append(dict(items))

    def take_payments(self, name: str) -> list:
        with self.lock:
            return self.pending_payments.pop((name or "?").lower(), [])

    def reset(self):
        """wipe: clear everything except players."""
        with self.lock:
            self.resources.clear()
            self.buildings.clear()
            self.trades.clear()
            self.occupied.clear()
            self.tile_building.clear()
            self.civs = CivManager()
            self.saved_players.clear()   # /wipe = fresh world, fresh progress
            self.animals.clear()
            self.touch("resources", "buildings", "civs", "animals")
            self._generate_resources()
            self.spawn_animals(initial=True)

    # ----------------------------------------------------------------- players
    def spawn_point(self):
        """A free grass tile, used for spawns and respawns."""
        rng = random.Random()
        for _ in range(100):
            x = rng.randint(5, max(6, self.width - 6)) * TILE_SIZE
            y = rng.randint(5, max(6, self.height - 6)) * TILE_SIZE
            if not self.is_blocked_tile(x // TILE_SIZE, y // TILE_SIZE) and \
                    f"{x // TILE_SIZE},{y // TILE_SIZE}" not in self.occupied:
                return x, y
        return self.width * TILE_SIZE // 2, self.height * TILE_SIZE // 2

    def add_player(self, player_id: str, name: str = None, account: str = None):
        with self.lock:
            # spawn on a free grass tile
            rng = random.Random()
            x = y = 500
            for _ in range(50):
                x = rng.randint(5, max(6, self.width - 6)) * TILE_SIZE
                y = rng.randint(5, max(6, self.height - 6)) * TILE_SIZE
                if not self.is_blocked_tile(x // TILE_SIZE, y // TILE_SIZE) and \
                        f"{x // TILE_SIZE},{y // TILE_SIZE}" not in self.buildings:
                    break
            self.players[player_id] = {
                "x": x,
                "y": y,
                "name": name or f"Player {player_id}",
                "account": account,
                "hp": 100,
                "hunger": 100,
                "armor": {},               # slot -> item
                "durability": {},          # item -> remaining hit points
                "stats": {},               # achievements / progress counters
                "tasks": {},               # accepted tasks and their progress
                "pets": [],
                "selected": None,          # item in hand
                "inventory": {"wood": 0, "stone": 0},
                "rev": 0,
                "died_at": 0,
            }

    def remove_player(self, player_id):
        with self.lock:
            self.players.pop(player_id, None)

    def player_pos(self, player_id):
        with self.lock:
            p = self.players.get(player_id)
            return (p["x"], p["y"]) if p else (None, None)

    def touch_inventory(self, player_id):
        with self.lock:
            p = self.players.get(player_id)
            if p is not None:
                p["rev"] = p.get("rev", 0) + 1

    def move_player(self, player_id, dx, dy) -> bool:
        """Move a player by (dx, dy) pixels if the target tile is free.

        The ground under the player decides how much of the step really
        happens: deep water slows a swimmer down (b11), a bridge or a road
        carries him at full speed.
        """
        with self.lock:
            player = self.players.get(player_id)
            if player is None:
                return False
            factor = self.move_factor(player["x"], player["y"])
            nx = player["x"] + dx * factor
            ny = player["y"] + dy * factor

            gx = int(nx // TILE_SIZE)
            gy = int(ny // TILE_SIZE)
            if not self.passable(gx, gy):
                return False

            player["x"] = nx
            player["y"] = ny
            return True

    # --------------------------------------------------------------- buildings
    def tile_allows_building(self, gx, gy, structure) -> bool:
        """Rock never, a bridge only on water, everything else only on land."""
        from shared.structures import is_water_only
        if gx < 0 or gy < 0 or gx >= self.width or gy >= self.height:
            return False
        tile = self.terrain[gy][gx]
        if tile == STONE:
            return False
        if is_water_only(structure):
            return tile == WATER
        return tile != WATER

    def can_place(self, gx, gy, w, h, structure=None) -> bool:
        with self.lock:
            for dx in range(w):
                for dy in range(h):
                    tx, ty = gx + dx, gy + dy
                    if structure is None:
                        if self.is_blocked_tile(tx, ty):
                            return False
                    elif not self.tile_allows_building(tx, ty, structure):
                        return False
                    key = f"{tx},{ty}"
                    if key in self.occupied or key in self.buildings:
                        return False
            return True

    def place_building(self, gx, gy, structure, owner, w, h):
        with self.lock:
            key = f"{gx},{gy}"
            hp = get_hp(structure)
            self.buildings[key] = {
                "x": gx, "y": gy, "type": structure, "owner": owner, "w": w, "h": h,
                "hp": hp, "max_hp": hp,
            }
            if structure == "door":
                self.buildings[key]["open"] = False
            if get_storage(structure):
                self.buildings[key]["items"] = {}
            self._mark_occupied(gx, gy, w, h, key)
            self.touch("buildings")
            return key

    def _mark_occupied(self, gx, gy, w, h, key=None):
        for dx in range(w):
            for dy in range(h):
                tile = f"{gx + dx},{gy + dy}"
                self.occupied.add(tile)
                if key is not None:
                    self.tile_building[tile] = key

    def rebuild_occupancy(self):
        with self.lock:
            self.occupied = set()
            self.tile_building = {}
            for key, b in self.buildings.items():
                self._mark_occupied(b["x"], b["y"], b.get("w", 1), b.get("h", 1), key)

    # ---------------------------------------------------------------- animals
    def _animal_spot(self, rng, cave: bool = False, atype: str = ""):
        """A free tile for an animal: near a cave when it likes the dark.

        b13: a sheep looks for a meadow, a wolf for a forest or a snowy waste -
        the biome weights in `shared/biomes.py` decide. Weight 0 biomes are
        skipped entirely.
        """
        W, H = self.width * TILE_SIZE, self.height * TILE_SIZE
        if cave and self.cave_tiles:
            for _ in range(40):
                gx, gy = rng.choice(sorted(self.cave_tiles))
                if f"{gx},{gy}" in self.occupied:
                    continue
                return gx * TILE_SIZE + TILE_SIZE // 2, gy * TILE_SIZE + TILE_SIZE // 2
        weights = ANIMAL_WEIGHT.get(atype) or {}
        for _ in range(60):
            x = rng.randint(64, max(65, W - 64))
            y = rng.randint(64, max(65, H - 64))
            gx, gy = x // TILE_SIZE, y // TILE_SIZE
            if self.is_blocked_tile(gx, gy) or f"{gx},{gy}" in self.occupied:
                continue
            if self.is_cave(gx, gy):
                continue
            chance = weights.get(self.biomes[gy][gx])
            if chance is not None:
                if chance <= 0:
                    continue
                if rng.random() > min(1.0, chance / 2.0):
                    continue
            return x, y
        return None

    def _add_animal(self, atype, x, y, pack=None):
        data = ANIMAL_TYPES[atype]
        self.animals[str(self.next_animal)] = {
            "x": x, "y": y, "type": atype, "hp": data["hp"],
            "max_hp": data["hp"], "target": None, "owner": None,
            "last_move": 0.0, "last_attack": 0.0,
            "home_x": x, "home_y": y, "pack": pack,
        }
        self.next_animal += 1
        return True

    def spawn_animals(self, initial: bool = False, amount: int = 0):
        """Top the world up with animals.

        Peaceful animals pop up anywhere on the grass; wolves arrive in packs
        (so a night hunt is a real fight) and bears keep to the caves.
        """
        with self.lock:
            counts = {}
            for animal in self.animals.values():
                counts[animal["type"]] = counts.get(animal["type"], 0) + 1
            rng = random.Random()
            wanted = ANIMAL_TARGETS if initial else {k: amount for k in ANIMAL_TARGETS}
            for atype, target in wanted.items():
                missing = target - counts.get(atype, 0)
                if not initial:
                    missing = min(missing, max(0, amount))
                if missing <= 0:
                    continue
                data = ANIMAL_TYPES[atype]
                if atype == "wolf":
                    self._spawn_wolf_packs(rng, missing)
                    continue
                for _ in range(missing * 3):
                    if missing <= 0:
                        break
                    spot = self._animal_spot(rng, cave=data.get("cave", False), atype=atype)
                    if spot is None:
                        continue
                    self._add_animal(atype, *spot)
                    missing -= 1
            self.touch("animals")

    def _spawn_wolf_packs(self, rng, missing: int):
        """Wolves spawn in groups that share a `pack` number."""
        guard = 0
        while missing > 0 and guard < 40:
            guard += 1
            pack_size = min(missing, rng.randint(*WOLF_PACK_SIZE))
            anchor = self._animal_spot(rng)
            if anchor is None:
                continue
            pack = f"pack{self.next_animal}"
            for _ in range(pack_size):
                x = anchor[0] + rng.randint(-TILE_SIZE, TILE_SIZE)
                y = anchor[1] + rng.randint(-TILE_SIZE, TILE_SIZE)
                gx, gy = int(x // TILE_SIZE), int(y // TILE_SIZE)
                if self.is_blocked_tile(gx, gy):
                    x, y = anchor
                self._add_animal("wolf", x, y, pack=pack)
                missing -= 1

    def animal_payload(self) -> dict:
        with self.lock:
            return {aid: {"x": a["x"], "y": a["y"], "type": a["type"], "hp": a["hp"],
                          "max_hp": a.get("max_hp", a["hp"]), "owner": a.get("owner")}
                    for aid, a in self.animals.items()}

    def damage_animal(self, animal_id: str, damage: int, attacker: str = None):
        """Returns (killed, drops dict)."""
        with self.lock:
            animal = self.animals.get(animal_id)
            if animal is None:
                return False, {}
            animal["hp"] -= damage
            if animal["owner"]:
                animal["target"] = attacker        # pets fight back
            if animal["hp"] > 0:
                return False, {}
            drops = dict(ANIMAL_TYPES.get(animal["type"], {}).get("drops", {}))
            del self.animals[animal_id]
            self.touch("animals")
            return True, drops

    def move_animal(self, animal_id: str, dx: float, dy: float) -> bool:
        with self.lock:
            animal = self.animals.get(animal_id)
            if animal is None:
                return False
            nx, ny = animal["x"] + dx, animal["y"] + dy
            gx, gy = int(nx // TILE_SIZE), int(ny // TILE_SIZE)
            if gx < 1 or gy < 1 or gx >= self.width - 1 or gy >= self.height - 1:
                return False
            if self.is_blocked_tile(gx, gy) or f"{gx},{gy}" in self.occupied:
                return False
            animal["x"], animal["y"] = nx, ny
            return True

    # -------------------------------------------------------------- buildings
    def set_building_health(self, key: str, value: int):
        with self.lock:
            building = self.buildings.get(key)
            if building is not None:
                building["hp"] = max(0, int(value))
                building["max_hp"] = building.get("max_hp", value)

    def damage_building(self, key: str, damage: int):
        """Returns (destroyed, building) - the building is removed when it breaks."""
        with self.lock:
            building = self.buildings.get(key)
            if building is None:
                return False, None
            building["hp"] = int(building.get("hp", 100)) - damage
            if building["hp"] > 0:
                self.touch("buildings")
                return False, building
            self.remove_building(key)
            return True, building

    def remove_building(self, key: str):
        with self.lock:
            building = self.buildings.pop(key, None)
            if building is None:
                return None
            for dx in range(building.get("w", 1)):
                for dy in range(building.get("h", 1)):
                    tile = f"{building['x'] + dx},{building['y'] + dy}"
                    self.occupied.discard(tile)
                    if self.tile_building.get(tile) == key:
                        self.tile_building.pop(tile, None)
            self.touch("buildings")
            return building

    def building_at(self, tile_x: int, tile_y: int):
        """The building covering a tile, or None."""
        with self.lock:
            key = self.tile_building.get(f"{tile_x},{tile_y}")
            return (key, self.buildings[key]) if key in self.buildings else (None, None)

    def passable(self, gx: int, gy: int) -> bool:
        """Can a player walk into this tile?

        Buildings are checked first: that is what lets a bridge carry a player
        over water and a closed door keep him out. b11: water itself can be
        entered (you wade through it slowly) unless the server switched
        swimming off with `swim: false` - only rock always blocks.
        """
        if gx < 0 or gy < 0 or gx >= self.width or gy >= self.height:
            return False
        key = self.tile_building.get(f"{gx},{gy}")
        building = self.buildings.get(key) if key is not None else None
        if building is not None:
            if building["type"] == "door":
                return bool(building.get("open", False))
            return is_walkable(building["type"])
        if self.terrain[gy][gx] == WATER and not self.swim:
            return False
        return self.terrain[gy][gx] != STONE

    def move_factor(self, x: float, y: float) -> float:
        """Movement multiplier of the ground under a position (b11).

        Water is slow (you wade through it), planks and roads are quick - a
        bridge over a lake is a real shortcut, not just a way to cross it.
        """
        gx, gy = int(x // TILE_SIZE), int(y // TILE_SIZE)
        if gx < 0 or gy < 0 or gx >= self.width or gy >= self.height:
            return 1.0
        key = self.tile_building.get(f"{gx},{gy}")
        building = self.buildings.get(key) if key is not None else None
        if building is not None:
            return float(get_speed(building["type"]) or 1.0)
        factor = terrain_speed(self.terrain[gy][gx], self.swim, self.swim_speed)
        if factor <= 0:
            return factor
        factor *= biome_speed(self.biomes[gy][gx])
        return factor * season_move(self.season, getattr(self, "season_enabled", True))

    def in_water(self, x: float, y: float) -> bool:
        return self.is_water(int(x // TILE_SIZE), int(y // TILE_SIZE))

    def light_sources(self) -> list:
        """(x, y, radius) of every light - used by the client at night.

        b10: lamps only shine while a generator (power plant) is close enough.
        """
        with self.lock:
            lights = []
            generators = []
            for b in self.buildings.values():
                cx = b["x"] * TILE_SIZE + TILE_SIZE // 2
                cy = b["y"] * TILE_SIZE + TILE_SIZE // 2
                if get_power(b["type"]) > 0:
                    generators.append((cx, cy, get_power(b["type"])))
                if get_light(b["type"]) > 0:
                    lights.append((b, cx, cy))
            out = []
            for building, cx, cy in lights:
                if needs_power(building["type"]):
                    powered = any(((cx - gx) ** 2 + (cy - gy) ** 2) ** 0.5 <= span
                                  for gx, gy, span in generators)
                    if not powered:
                        continue
                out.append((cx, cy, get_light(building["type"])))
            return out

    # -------------------------------------------------------------- revisions
    def touch(self, *sections):
        with self.lock:
            for s in sections:
                self.rev[s] = self.rev.get(s, 0) + 1
