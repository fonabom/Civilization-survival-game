import random

import pygame

from client.settings import TILE_SIZE, WORLD_WIDTH, WORLD_HEIGHT, TERRAIN_SEED
from shared.biomes import CAVE as CAVE_BIOME
from shared.biomes import COLORS as BIOME_COLORS
from shared.biomes import MEADOW, decode as decode_biomes

GRASS = 0
STONE = 1
WATER = 2
CAVE = 3

GRASS_COLOR = (50, 160, 50)
GRASS_EDGE = (30, 100, 30)
STONE_COLOR = (100, 100, 100)
STONE_EDGE = (80, 80, 80)
WATER_COLOR = (44, 96, 168)          # lakes and rivers (b9)
WATER_EDGE = (34, 74, 140)
WATER_SHINE = (86, 140, 200)
CAVE_COLOR = (58, 52, 48)            # cave floor: dark, no sunlight
CAVE_EDGE = (42, 38, 34)
CAVE_ROCK = (74, 70, 66)             # cave walls (rock, but darker than surface)


class World:
    """Client-side view of the map.

    Terrain comes from the server (`set_terrain`), so collisions and visuals
    agree between players. A locally generated fallback map is used until the
    server packet arrives. Textures come from the active resource pack.
    """

    def __init__(self, resources=None):
        self.width = WORLD_WIDTH
        self.height = WORLD_HEIGHT
        self.tiles = self._generate_local_tiles(TERRAIN_SEED)
        self.biomes = [[MEADOW] * self.width for _ in range(self.height)]
        self.resources = {}
        self.buildings = {}
        self._building_grid = {}
        self._building_grid_from = None
        if resources is None:
            from client.resources import ResourceManager
            resources = ResourceManager()
        self.set_textures(resources)

    # ------------------------------------------------------------------ setup
    def _generate_local_tiles(self, seed):
        rng = random.Random(seed)
        return [[STONE if rng.random() < 0.2 else GRASS for _ in range(WORLD_WIDTH)]
                for _ in range(WORLD_HEIGHT)]

    TILES = {"0": GRASS, "1": STONE, "2": WATER, "3": CAVE}

    def set_biomes(self, text: str, size=None):
        """The biome map arrives next to the terrain (b13)."""
        if size and len(size) == 2:
            self.width, self.height = int(size[0]), int(size[1])
        if not text or len(text) < self.width * self.height:
            return
        self.biomes = decode_biomes(text, self.width)

    def building_at(self, gx, gy):
        """The building standing on this tile, or None (b13).

        The client only receives the origin tile of every building, so the
        footprint (w x h) is used to cover the remaining tiles as well - a big
        wall or a market covers more than one tile, and walking on a road must
        use the road's speed no matter which of its tiles you stand on.
        """
        key = f"{gx},{gy}"
        building = self.buildings.get(key)
        if building is not None:
            return building
        if self._building_grid_from is not self.buildings:
            grid = {}
            for other in self.buildings.values():
                width = int(other.get("w", 1) or 1)
                height = int(other.get("h", 1) or 1)
                if width == 1 and height == 1:
                    continue
                for dx in range(width):
                    for dy in range(height):
                        cell = f"{int(other.get('x', 0)) + dx},{int(other.get('y', 0)) + dy}"
                        grid.setdefault(cell, other)
            self._building_grid = grid
            self._building_grid_from = self.buildings
        return self._building_grid.get(key)

    def biome(self, gx, gy) -> int:
        if gx < 0 or gy < 0 or gx >= self.width or gy >= self.height:
            return MEADOW
        try:
            return self.biomes[gy][gx]
        except IndexError:
            return MEADOW

    def set_terrain(self, terrain: str, size=None):
        """Receive the authoritative map: a string of '0'/'1'/'2'/'3' rows."""
        if size and len(size) == 2:
            self.width, self.height = int(size[0]), int(size[1])
        if not terrain or len(terrain) < self.width * self.height:
            return
        self.tiles = [
            [self.TILES.get(terrain[y * self.width + x], GRASS) for x in range(self.width)]
            for y in range(self.height)
        ]

    def set_textures(self, resources):
        """Swap the texture set (called when the resource pack changes)."""
        self.manager = resources

    @property
    def assets(self):
        """Backwards compatible view of the loaded textures."""
        return getattr(self.manager, "images", {})

    def get_asset(self, name):
        return self.manager.get(name)

    # ------------------------------------------------------------------- logic
    def tile_at(self, screen_x, screen_y, camera):
        """Tile kind under a screen position (used for the cave darkness)."""
        gx = int((screen_x + camera.x) // TILE_SIZE)
        gy = int((screen_y + camera.y) // TILE_SIZE)
        return self.tile(gx, gy)

    def tile(self, gx, gy):
        if gx < 0 or gy < 0 or gx >= self.width or gy >= self.height:
            return STONE
        return self.tiles[gy][gx]

    def is_water(self, gx, gy):
        return self.tile(gx, gy) == WATER

    def is_cave(self, gx, gy):
        return self.tile(gx, gy) == CAVE

    def is_blocked(self, x, y):
        gx, gy = int(x // TILE_SIZE), int(y // TILE_SIZE)
        if gx < 0 or gy < 0 or gx >= self.width or gy >= self.height:
            return True
        return self.tiles[gy][gx] in (STONE, WATER)

    def blocks_building(self, gx, gy, structure) -> bool:
        """May this building stand on that tile?

        The very same rule as `WorldState.tile_allows_building` (b11: it used to
        be copied by hand and the copy thought water blocks a bridge).
        """
        from shared.structures import is_water_only
        if gx < 0 or gy < 0 or gx >= self.width or gy >= self.height:
            return True
        tile = self.tiles[gy][gx]
        if tile == STONE:
            return True
        if is_water_only(structure):
            return tile != WATER
        return tile == WATER

    # -------------------------------------------------------------------- draw
    def _cave_wall(self, gx, gy) -> bool:
        """Rock that touches a cave floor is drawn darker."""
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if self.tile(gx + dx, gy + dy) == CAVE:
                    return True
        return False

    def cave_at(self, gx, gy) -> bool:
        return self.is_cave(gx, gy)

    def draw(self, screen, camera):
        """Draw only the tiles that are actually on screen."""
        first_col = max(0, int(camera.x // TILE_SIZE))
        last_col = min(self.width, first_col + screen.get_width() // TILE_SIZE + 2)
        first_row = max(0, int(camera.y // TILE_SIZE))
        last_row = min(self.height, first_row + screen.get_height() // TILE_SIZE + 2)

        water_phase = pygame.time.get_ticks() // 600
        for y in range(first_row, last_row):
            row = self.tiles[y]
            screen_y = int(y * TILE_SIZE - camera.y)
            for x in range(first_col, last_col):
                screen_x = int(x * TILE_SIZE - camera.x)
                tile = row[x]
                if tile == GRASS:
                    # b13: the biome decides the colour of the ground
                    colour = BIOME_COLORS.get(self.biome(x, y), GRASS_COLOR)
                    pygame.draw.rect(screen, colour, (screen_x, screen_y, TILE_SIZE, TILE_SIZE))
                    edge = tuple(max(0, channel - 26) for channel in colour)
                    pygame.draw.rect(screen, edge, (screen_x, screen_y, TILE_SIZE, TILE_SIZE), 1)
                elif tile == WATER:
                    pygame.draw.rect(screen, WATER_COLOR, (screen_x, screen_y, TILE_SIZE, TILE_SIZE))
                    pygame.draw.rect(screen, WATER_EDGE, (screen_x, screen_y, TILE_SIZE, TILE_SIZE), 1)
                    # two moving highlights make the water feel alive
                    offset = (x + y + water_phase) % 8
                    pygame.draw.rect(screen, WATER_SHINE,
                                     (screen_x + 4, screen_y + 6 + offset, 10, 2))
                    pygame.draw.rect(screen, WATER_SHINE,
                                     (screen_x + 18, screen_y + 20 - offset, 8, 2))
                elif tile == CAVE:
                    pygame.draw.rect(screen, CAVE_COLOR, (screen_x, screen_y, TILE_SIZE, TILE_SIZE))
                    pygame.draw.rect(screen, CAVE_EDGE, (screen_x, screen_y, TILE_SIZE, TILE_SIZE), 1)
                elif tile == STONE and self._cave_wall(x, y):
                    pygame.draw.rect(screen, CAVE_ROCK, (screen_x, screen_y, TILE_SIZE, TILE_SIZE))
                    pygame.draw.rect(screen, STONE_EDGE, (screen_x, screen_y, TILE_SIZE, TILE_SIZE), 1)
                else:
                    pygame.draw.rect(screen, STONE_COLOR, (screen_x, screen_y, TILE_SIZE, TILE_SIZE))
                    pygame.draw.rect(screen, STONE_EDGE, (screen_x, screen_y, TILE_SIZE, TILE_SIZE), 1)

        margin = 64
        # Resources
        for res in self.resources.values():
            rx = int(res["x"] - camera.x)
            ry = int(res["y"] - camera.y)
            if not (-margin < rx < screen.get_width() + margin and
                    -margin < ry < screen.get_height() + margin):
                continue
            rtype = res["type"]
            asset = self.get_asset(rtype)
            if asset:
                screen.blit(asset, (rx, ry))
                continue
            if rtype == "tree":
                pygame.draw.circle(screen, (34, 139, 34), (rx, ry), 10)
            elif rtype == "rock":
                pygame.draw.circle(screen, (128, 128, 128), (rx, ry), 8)
            elif rtype == "oil_deposit":
                pygame.draw.ellipse(screen, (10, 10, 10), (rx - 12, ry - 8, 24, 16))
            elif "ore" in rtype:
                color = (139, 0, 0)
                if "iron" in rtype:
                    color = (150, 120, 100)
                elif "gold" in rtype:
                    color = (255, 215, 0)
                elif "coal" in rtype:
                    color = (20, 20, 20)
                pygame.draw.circle(screen, color, (rx, ry), 6)
            else:
                pygame.draw.circle(screen, (150, 150, 150), (rx, ry), 15)

        # Buildings
        for b in self.buildings.values():
            bx = int(b["x"] * TILE_SIZE - camera.x)
            by = int(b["y"] * TILE_SIZE - camera.y)
            asset = self.get_asset(b["type"])
            if asset:
                screen.blit(asset, (bx, by))
            else:
                color = (150, 100, 50) if b["type"] == "crafting_table" else (100, 100, 100)
                pygame.draw.rect(screen, color,
                                 (bx, by, TILE_SIZE * b.get("w", 1), TILE_SIZE * b.get("h", 1)))
