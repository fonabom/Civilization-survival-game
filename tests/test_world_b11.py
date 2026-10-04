"""b11 «По воде и в человеческом облике»: wading through water, the character
sprite, the inventory that no longer shows one stack twice and the small
quality-of-life bits (swim hint, tutorial's first line).

The server-side checks drive the real `WorldState` / real server; the client
bits are drawn on a dummy SDL surface.
"""

import math
import os
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

from server import server as server_module                       # noqa: E402
from server.world_state import STONE, TILE_SIZE, WATER, WorldState  # noqa: E402
from shared.speed import SWIM_SPEED, move_multiplier, terrain_speed  # noqa: E402
from shared.structures import get_speed                          # noqa: E402

from tests.helpers import RawClient, free_port                    # noqa: E402


class SwimRulesTest(unittest.TestCase):
    """The numbers behind "walk into the water, but slowly"."""

    def setUp(self):
        self.world = WorldState()

    def water_tile(self):
        return sorted(self.world.water_tiles)[0]

    def stone_tile(self):
        for gy in range(self.world.height):
            for gx in range(self.world.width):
                if self.world.terrain[gy][gx] == STONE:
                    return gx, gy
        self.fail("the map has no rock at all")

    def test_water_slows_a_player_down(self):
        gx, gy = self.water_tile()
        self.world.players["p"] = {"x": gx * TILE_SIZE + 16.0, "y": gy * TILE_SIZE + 16.0,
                                   "name": "p", "hp": 100, "inventory": {}, "rev": 0}
        x0 = self.world.players["p"]["x"]
        self.world.move_player("p", 10, 0)
        step = self.world.players["p"]["x"] - x0
        self.assertAlmostEqual(step, 10 * SWIM_SPEED, places=3)

    def test_dry_land_keeps_the_full_step(self):
        for gy in range(self.world.height):
            for gx in range(self.world.width):
                if self.world.terrain[gy][gx] == 0:
                    self.world.players["p"] = {"x": gx * TILE_SIZE + 16.0,
                                               "y": gy * TILE_SIZE + 16.0,
                                               "name": "p", "hp": 100,
                                               "inventory": {}, "rev": 0}
                    x0 = self.world.players["p"]["x"]
                    self.world.move_player("p", 10, 0)
                    self.assertAlmostEqual(self.world.players["p"]["x"] - x0, 10.0, places=3)
                    return
        self.fail("no grass on the map")

    def test_rock_still_blocks_everybody(self):
        self.assertFalse(self.world.passable(*self.stone_tile()))

    def test_a_bridge_over_the_water_beats_wading(self):
        gx, gy = self.water_tile()
        self.assertGreater(get_speed("bridge"), 1.0)
        self.world.place_building(gx, gy, "bridge", "0", 1, 1)
        factor = self.world.move_factor(gx * TILE_SIZE + 16, gy * TILE_SIZE + 16)
        self.assertEqual(factor, get_speed("bridge"))
        self.assertGreater(factor, SWIM_SPEED)

    def test_the_client_and_the_server_agree(self):
        """The prediction must use the same multiplier, or every step in the
        water would be pulled back by the server (rubber-banding)."""
        for tile in (0, 1, 2, 3):
            for weather in ("clear", "rain", "fog"):
                self.assertAlmostEqual(
                    move_multiplier(tile, weather),
                    terrain_speed(tile) * {"clear": 1.0, "rain": 0.85,
                                           "fog": 0.95}[weather], places=5)

    def test_swim_speed_from_the_config_is_used(self):
        self.world.swim_speed = 0.9
        gx, gy = self.water_tile()
        self.world.players["p"] = {"x": gx * TILE_SIZE + 16.0, "y": gy * TILE_SIZE + 16.0,
                                   "name": "p", "hp": 100, "inventory": {}, "rev": 0}
        x0 = self.world.players["p"]["x"]
        self.world.move_player("p", 10, 0)
        self.assertAlmostEqual(self.world.players["p"]["x"] - x0, 9.0, places=3)


class SwimServerTest(unittest.TestCase):
    """The whole way: a real server, a real client, a real swim."""

    @classmethod
    def setUpClass(cls):
        cls.port = free_port()
        cls.server = server_module.GameServer(
            host="127.0.0.1", port=cls.port, accounts_path=None,
            config={**server_module.DEFAULT_CONFIG, "day_length": 100000,
                    "animals": False, "wolves": False, "tasks": False,
                    "hunger_rate": 0, "start_kit": {}, "swim": True})
        threading.Thread(target=cls.server.run, daemon=True).start()
        time.sleep(0.6)

    @classmethod
    def tearDownClass(cls):
        cls.server.running = False
        time.sleep(0.3)

    def setUp(self):
        self.clients = []
        self.addCleanup(self._reset)

    def join(self, name):
        client = RawClient(self.port)
        welcome = client.auth(name=name)
        self.assertIsNotNone(welcome, f"{name} could not log in")
        client.pid = welcome["id"]
        self.clients.append(client)
        return client, client.pid, welcome

    def _reset(self):
        world = self.server.world
        with world.lock:
            for client in self.clients:
                world.players.pop(getattr(client, "pid", None), None)
            world.buildings.clear()
            world.occupied.clear()
            world.tile_building.clear()
            world.touch("buildings")
        for client in self.clients:
            client.close()

    def test_the_welcome_packet_carries_the_movement_rules(self):
        client, _pid, welcome = self.join("Swimmer")
        rules = welcome.get("rules")
        self.assertIsInstance(rules, dict)
        self.assertTrue(rules.get("swim"))
        self.assertAlmostEqual(rules.get("swim_speed"), SWIM_SPEED, places=3)

    def test_a_player_can_walk_into_the_water_and_is_slower_there(self):
        client, pid, _welcome = self.join("Swimmer")
        gx, gy = sorted(self.server.world.water_tiles)[0]
        with self.server.world.lock:
            player = self.server.world.players[pid]
            player["x"], player["y"] = (gx - 3) * TILE_SIZE + 16.0, gy * TILE_SIZE + 16.0
        # walk to the right, straight into the lake: it must be possible now
        for _ in range(60):
            client.send({"type": "move", "dx": 4, "dy": 0})
            client.poll(0.05)
            with self.server.world.lock:
                x, y = player["x"], player["y"]
            if self.server.world.is_water(int(x // TILE_SIZE), int(y // TILE_SIZE)):
                break
        self.assertTrue(self.server.world.in_water(x, y),
                        f"the player never got into the water (x={x:.0f} y={y:.0f})")

        # inside the water every request moves him by swim_speed * dx
        before = x
        client.send({"type": "move", "dx": 10, "dy": 0})
        client.poll(0.3)
        with self.server.world.lock:
            after = player["x"]
        self.assertLess(abs(after - before), 10)
        self.assertGreater(abs(after - before), 10 * SWIM_SPEED - 1.5)

    def test_a_swimmer_gets_a_friendly_hint_once(self):
        client, pid, _welcome = self.join("Swimmer")
        gx, gy = sorted(self.server.world.water_tiles)[0]
        with self.server.world.lock:
            player = self.server.world.players[pid]
            player["x"], player["y"] = gx * TILE_SIZE + 16.0, gy * TILE_SIZE + 16.0
        client.clear()
        for _ in range(4):                       # keep swimming for a while
            client.send({"type": "move", "dx": 3, "dy": 0})
            client.poll(0.4)
        # `poll` returns everything received so far, so this counts the real
        # number of hints the server sent us in the whole session
        hints = client.notif_keys(0.2).count("notify.swim_hint")
        self.assertEqual(hints, 1, "the hint has to come exactly once per session")

    def test_fishing_still_works_from_the_water_edge(self):
        """Wading must not break the neighbouring systems (b9 fishing)."""
        client, pid, _welcome = self.join("Fisher")
        gx, gy = sorted(self.server.world.water_tiles)[0]
        with self.server.world.lock:
            player = self.server.world.players[pid]
            player["inventory"] = {"fishing_rod": 1}
            player["x"], player["y"] = (gx - 1) * TILE_SIZE + 16.0, gy * TILE_SIZE + 16.0
        client.clear()
        client.send({"type": "fish"})
        keys = [m.get("key") for m in client.poll(1.2) if m.get("type") == "notification"]
        self.assertTrue(any(key and key.startswith("notify.fish") or key == "notify.fishing"
                            for key in keys), f"fishing answered with {keys}")


class BuildingRightsTest(unittest.TestCase):
    """b11 bug hunt: a building had to stand where the player may build.

    The b10 territory gate looked only at the tile the *player* stood on, so
    an outsider could stand just outside the walls (the build range is 8 tiles)
    and drop a tower inside somebody's city. The message was misleading too: it
    named the city at the player's feet, not the one that refused.
    """

    RADIUS = 300.0               # a tier 1 city

    @classmethod
    def setUpClass(cls):
        cls.port = free_port()
        cls.server = server_module.GameServer(
            host="127.0.0.1", port=cls.port, accounts_path=None,
            config={**server_module.DEFAULT_CONFIG, "day_length": 100000,
                    "animals": False, "wolves": False, "tasks": False,
                    "hunger_rate": 0, "start_kit": {"wood": 40, "stone": 40}})
        threading.Thread(target=cls.server.run, daemon=True).start()
        time.sleep(0.6)

    @classmethod
    def tearDownClass(cls):
        cls.server.running = False
        time.sleep(0.3)

    def setUp(self):
        self.clients = []
        self.addCleanup(self._reset)

    # ------------------------------------------------------------------ setup
    def join(self, name):
        client = RawClient(self.port)
        welcome = client.auth(name=name)
        self.assertIsNotNone(welcome, f"{name} could not log in")
        client.pid = welcome["id"]
        self.clients.append(client)
        return client, client.pid

    def _reset(self):
        world = self.server.world
        with world.lock:
            for client in self.clients:
                world.players.pop(getattr(client, "pid", None), None)
            world.buildings.clear()
            world.occupied.clear()
            world.tile_building.clear()
            world.civs.cities.clear()
            world.civs.countries.clear()
            world.touch("buildings")
            world.touch("civs")
        for client in self.clients:
            client.close()

    def place(self, pid, x, y):
        with self.server.world.lock:
            self.server.world.players[pid]["x"] = float(x)
            self.server.world.players[pid]["y"] = float(y)

    def found_city(self, client, name, x, y):
        """A city of radius 300 px with the client as its leader."""
        self.place(client.pid, x, y)
        client.clear()
        client.send({"type": "create_city", "name": name})
        keys = [m.get("key") for m in client.poll(0.8) if m.get("type") == "notification"]
        self.assertIn("notify.city_founded", keys, f"no city: {keys}")

    def wall_spot(self, cx, cy):
        """(tile inside the walls, spot outside them, still in build range)."""
        world = self.server.world
        for step in range(24):                          # every 15 degrees
            angle = step * math.pi / 12
            for inside in (272.0, 256.0, 288.0):
                tx = cx + inside * math.cos(angle)
                ty = cy + inside * math.sin(angle)
                gx, gy = int(tx // TILE_SIZE), int(ty // TILE_SIZE)
                if not world.can_place(gx, gy, 1, 1, "wall"):
                    continue
                centre = (gx * TILE_SIZE + TILE_SIZE / 2, gy * TILE_SIZE + TILE_SIZE / 2)
                if ((centre[0] - cx) ** 2 + (centre[1] - cy) ** 2) ** 0.5 >= self.RADIUS:
                    continue                            # the tile itself must be inside
                for outside in (inside + 120, inside + 150, inside + 180):
                    ox, oy = cx + outside * math.cos(angle), cy + outside * math.sin(angle)
                    ogx, ogy = int(ox // TILE_SIZE), int(oy // TILE_SIZE)
                    if not world.passable(ogx, ogy):
                        continue
                    if ((ox - cx) ** 2 + (oy - cy) ** 2) ** 0.5 <= self.RADIUS:
                        continue                        # still inside the walls
                    reach = max(abs(centre[0] - ox), abs(centre[1] - oy))
                    if reach > 8 * TILE_SIZE:
                        continue                        # out of the build range
                    # a spot inside the walls, close enough to reach the tile
                    inner = max(inside - 90.0, 0.0)
                    return (gx, gy), (ox, oy), (cx + inner * math.cos(angle),
                                                cy + inner * math.sin(angle))
        return None, None, None

    def base(self):
        """A free corner of the map with a wall spot and a spot for an outsider."""
        world = self.server.world
        for gy in range(8, world.height - 8, 5):
            for gx in range(8, world.width - 8, 5):
                cx = gx * TILE_SIZE + TILE_SIZE / 2
                cy = gy * TILE_SIZE + TILE_SIZE / 2
                target, spot, inner = self.wall_spot(cx, cy)
                if target and spot:
                    return (cx, cy), target, spot, inner
        return None, None, None, None

    def keys_of(self, client):
        return [m.get("key") for m in client.poll(0.8) if m.get("type") == "notification"]

    # ------------------------------------------------------------------ tests
    def test_the_leader_may_build_inside_his_own_city(self):
        leader, pid = self.join("Leader")
        centre, target, _spot, inner = self.base()
        self.assertIsNotNone(centre, "no free spot with a wall place on the map")
        self.found_city(leader, "Home", *centre)
        self.place(pid, *inner)                     # inside the walls, near the tile
        leader.clear()
        leader.send({"type": "build", "structure": "wall",
                     "x": target[0], "y": target[1]})
        keys = self.keys_of(leader)
        self.assertIn("notify.built", keys,
                      f"the leader was refused: {keys} centre={centre} target={target} "
                      f"me=({inner[0]:.0f},{inner[1]:.0f})")

    def test_an_outsider_cannot_build_through_the_walls(self):
        leader, _lid = self.join("Leader")
        outsider, opid = self.join("Outsider")
        centre, target, spot, _inner = self.base()
        self.assertIsNotNone(centre, "no free spot with a wall place on the map")
        self.found_city(leader, "Home", *centre)
        self.place(opid, *spot)                     # outside the walls, in reach
        distance = ((spot[0] - centre[0]) ** 2 + (spot[1] - centre[1]) ** 2) ** 0.5
        self.assertGreater(distance, self.RADIUS, "the outsider stands inside")
        outsider.clear()
        outsider.send({"type": "build", "structure": "wall",
                       "x": target[0], "y": target[1]})
        keys = self.keys_of(outsider)
        self.assertNotIn("notify.built", keys,
                         f"a wall was squeezed into somebody's city: {keys}")
        self.assertIn("notify.build_fail_territory", keys,
                      f"the refusal named the wrong reason: {keys}")

    def test_a_citizen_is_told_which_city_refused_him(self):
        leader, _lid = self.join("Leader")
        citizen, cpid = self.join("Citizen")
        centre, target, _spot, inner = self.base()
        self.assertIsNotNone(centre, "no free spot with a wall place on the map")
        self.found_city(leader, "Home", *centre)
        citizen.clear()
        citizen.send({"type": "join_city", "name": "Home"})
        keys = self.keys_of(citizen)
        self.assertIn("notify.joined_city", keys, f"could not join: {keys}")
        self.place(cpid, *inner)                    # inside the walls, no role
        citizen.clear()
        citizen.send({"type": "build", "structure": "wall",
                      "x": target[0], "y": target[1]})
        messages = [m for m in citizen.poll(0.8) if m.get("type") == "notification"]
        keys = [m.get("key") for m in messages]
        self.assertIn("notify.build_fail_role", keys, f"the citizen built anyway: {keys}")
        named = [m.get("args", {}).get("city") for m in messages
                 if m.get("key") == "notify.build_fail_role"]
        self.assertEqual(named, ["Home"], f"the wrong city was blamed: {messages}")


class BridgePlacementTest(unittest.TestCase):
    """b11 bug hunt: the client used to refuse a bridge on water.

    `World.is_blocked()` counts water as blocked, and the placement preview
    asked it - so the player saw "you cannot build here" on a river although
    the server was perfectly happy. Both sides now share one rule.
    """

    def setUp(self):
        from client.world import World
        self.client = World()
        self.server = WorldState()
        self.client.set_terrain("".join(str(t) for row in self.server.terrain
                                        for t in row),
                                (self.server.width, self.server.height))

    def test_the_two_sides_agree_on_every_tile_of_the_map(self):
        from shared.structures import STRUCTURES
        structures = [name for name in STRUCTURES if name != "road"] or list(STRUCTURES)
        water_seen = stone_seen = land_seen = 0
        for gy in range(self.server.height):
            for gx in range(self.server.width):
                tile = self.server.terrain[gy][gx]
                if tile == WATER:
                    water_seen += 1
                    structures = [name for name in structures
                                  if name == "bridge"] or ["bridge"]
                elif tile == STONE:
                    stone_seen += 1
                else:
                    land_seen += 1
                for name in structures:
                    mine = self.client.blocks_building(gx, gy, name)
                    him = not self.server.tile_allows_building(gx, gy, name)
                    self.assertEqual(mine, him,
                                     f"{name} at {gx},{gy} tile={tile}: "
                                     f"client blocked={mine} server blocked={him}")
        self.assertGreater(water_seen, 0, "the map must have water to test")
        self.assertGreater(stone_seen, 0)
        self.assertGreater(land_seen, 0)

    def test_a_bridge_is_placeable_on_water_but_a_house_is_not(self):
        for gy in range(self.server.height):
            for gx in range(self.server.width):
                if self.server.terrain[gy][gx] != WATER:
                    continue
                self.assertFalse(self.client.blocks_building(gx, gy, "bridge"))
                self.assertTrue(self.client.blocks_building(gx, gy, "house"))
                self.assertTrue(self.client.blocks_building(gx, gy, "wall"))
                return
        self.fail("no water on the map")

    def test_rock_blocks_everything_including_a_bridge(self):
        for gy in range(self.server.height):
            for gx in range(self.server.width):
                if self.server.terrain[gy][gx] != STONE:
                    continue
                for name in ("bridge", "house", "wall"):
                    self.assertTrue(self.client.blocks_building(gx, gy, name),
                                    f"rock must block {name}")
                return
        self.fail("no rock on the map")

    def test_a_bridge_on_dry_land_is_refused_by_both_sides(self):
        for gy in range(self.server.height):
            for gx in range(self.server.width):
                if self.server.terrain[gy][gx] != 0:
                    continue
                self.assertTrue(self.client.blocks_building(gx, gy, "bridge"))
                self.assertFalse(self.server.tile_allows_building(gx, gy, "bridge"))
                self.assertFalse(self.client.blocks_building(gx, gy, "house"))
                self.assertTrue(self.server.tile_allows_building(gx, gy, "house"))
                return
        self.fail("no grass on the map")

    def test_outside_the_map_is_blocked(self):
        self.assertTrue(self.client.blocks_building(-1, 5, "house"))
        self.assertTrue(self.client.blocks_building(self.server.width + 2, 5, "house"))


class ClientSideTest(unittest.TestCase):
    """The parts that only exist on screen: the sprite and the inventory."""

    @classmethod
    def setUpClass(cls):
        import pygame
        cls.pygame = pygame
        pygame.init()
        cls.screen = pygame.display.set_mode((640, 480))
        from client.resources import ResourceManager
        cls.resources = ResourceManager()

    @classmethod
    def tearDownClass(cls):
        cls.pygame.quit()

    def test_the_player_texture_is_a_character_not_a_square(self):
        from client.player import Player
        sprite = Player("1").sprite(self.resources)
        self.assertIsNotNone(sprite, "assets/player.png is missing")
        width, height = sprite.get_size()
        colors = {tuple(sprite.get_at((x, y))) for x in range(width) for y in range(height)}
        self.assertGreater(len(colors), 8, "the character needs more than one colour")
        self.assertTrue(any(pixel[3] == 0 for pixel in colors),
                        "the area around the character must be transparent")
        # the body itself (everything that is not transparent) is a standing
        # person: head, body, arms and legs - not a filled square
        solid = [(x, y) for x in range(width) for y in range(height)
                 if sprite.get_at((x, y))[3] > 0]
        body_w = max(x for x, _y in solid) - min(x for x, _y in solid) + 1
        body_h = max(y for _x, y in solid) - min(y for _x, y in solid) + 1
        self.assertGreater(body_h, body_w, "a person stands taller than he is wide")
        self.assertLess(body_w, width, "the character does not fill the whole tile")

    def test_every_player_gets_his_own_colour(self):
        from client.player import Player
        one, two = Player("1"), Player("2")
        self.assertNotEqual(one.color, two.color)
        self.assertIsNotNone(one.sprite(self.resources))
        self.assertIsNotNone(two.sprite(self.resources))

    def test_the_character_faces_the_way_he_walks(self):
        from client.player import Player
        player = Player("1")
        player.update_from_server({"x": 100, "y": 100})
        for _ in range(20):                      # walk right until we arrive
            player.update()
        self.assertEqual(player.facing, 1)
        right = player.sprite(self.resources)
        player.update_from_server({"x": 40, "y": 100})      # now turn around
        for _ in range(4):
            player.update()
        self.assertEqual(player.facing, -1)
        left = player.sprite(self.resources)
        self.assertNotEqual(self.pygame.image.tostring(right, "RGBA"),
                            self.pygame.image.tostring(left, "RGBA"))

    def test_drawing_a_player_works_on_water_and_on_land(self):
        from client.player import Player
        from client.camera import Camera
        player = Player("7", "Tester")
        player.update_from_server({"x": 500, "y": 500})
        player.selected = "sword"
        camera = Camera()
        camera.x, camera.y = 400, 400
        player.draw(self.screen, camera, is_me=True, resources=self.resources,
                    in_water=False)
        player.draw(self.screen, camera, is_me=False, resources=self.resources,
                    in_water=True)

    def test_the_inventory_does_not_show_a_stack_twice(self):
        """b11: a hotbar item used to appear in the grid *and* on the bar."""
        from client.ui.inventory_menu import InventoryMenu

        class Stub:
            def __init__(self, resources):
                self.inventory = {"wood": 116, "stone": 4, "axe": 1}
                self.hotbar = ["wood", "axe", None, None, None, None, None, None, None]
                self.hotbar_index = 0
                self.me = None
                self.resources = resources

            def held_item(self):
                return "wood"

            def set_hotbar_item(self, index, item):
                pass

            def select_hotbar(self, index):
                pass

        menu = InventoryMenu(Stub(self.resources))
        listed = [item for item, _count in menu._items()]
        self.assertEqual(listed, ["stone"])
        self.assertNotIn("wood", listed)
        self.assertNotIn("axe", listed)
        menu.visible = True
        menu.draw(self.screen)


class LocaleTest(unittest.TestCase):
    """The new texts are in every language."""

    def test_the_new_keys_exist_in_three_languages(self):
        import json
        from pathlib import Path
        root = Path(__file__).resolve().parent.parent
        for lang in ("en", "pl", "ru"):
            data = json.loads((root / "locales" / f"{lang}.json").read_text(encoding="utf-8"))
            for key in ("hint.look", "notify.swim_hint"):
                self.assertIn(key, data, f"{lang}.json is missing {key}")
                self.assertTrue(data[key].strip(), key)
            self.assertIn("{n}", data["notify.swim_hint"], "the hint shows the speed")


if __name__ == "__main__":
    unittest.main()
