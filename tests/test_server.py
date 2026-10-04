"""Server / world-state / gameplay tests (end-to-end over a real TCP socket)."""

import os
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server import server as server_module
from server.world_state import WorldState, TILE_SIZE
from shared.items import (CRAFTING_RECIPES, craftable_amount, pay_for_craft, recipe_cost,
                          recipe_output, recipe_station)
from shared.structures import STRUCTURES, can_afford, get_cost, get_size, get_station, get_tech

from tests.helpers import RawClient, free_port


class StructuresTest(unittest.TestCase):
    def test_cost_excludes_meta_keys(self):
        self.assertEqual(get_cost("wall"), {"wood": 2})
        self.assertEqual(get_cost("drill"), {"iron_ingot": 20, "stone": 20})
        self.assertEqual(get_size("town_center"), (2, 2))
        self.assertEqual(get_tech("chemical_plant"), "chemistry")
        self.assertEqual(get_station("crafting_table"), "crafting_table")

    def test_structure_costs_never_contain_meta_keys(self):
        for name in STRUCTURES:
            for key in get_cost(name):
                self.assertNotIn(key, {"w", "h", "tech", "station"}, f"{name} leaks {key}")

    def test_wall_affordable_with_two_wood(self):
        self.assertTrue(can_afford("wall", {"wood": 2}))
        self.assertFalse(can_afford("wall", {"wood": 1}))


class RecipesTest(unittest.TestCase):
    def test_recipes_declare_station_and_output(self):
        self.assertEqual(recipe_station("axe"), "crafting_table")
        self.assertEqual(recipe_station("pistol"), "advanced_workbench")
        self.assertEqual(recipe_output("ammo"), 5)
        self.assertEqual(recipe_cost("axe"), {"wood": 2, "stone": 3})

    def test_craftable_amount_and_payment(self):
        inventory = {"wood": 4, "stone": 6}
        self.assertEqual(craftable_amount("axe", inventory), 2)
        produced = pay_for_craft("axe", inventory, 2)
        self.assertEqual(produced, 2)
        self.assertEqual(inventory, {})          # empty stacks are dropped, not left as 0

    def test_batch_recipe_output(self):
        inventory = {"iron_ingot": 2, "gunpowder": 2}
        self.assertEqual(pay_for_craft("ammo", inventory, 2), 10)

    def test_all_recipes_have_valid_costs(self):
        for name, recipe in CRAFTING_RECIPES.items():
            self.assertIn("cost", recipe, name)
            self.assertTrue(recipe["cost"], name)
            for resource in recipe["cost"]:
                self.assertIn(resource, ("wood", "stone", "iron_ingot", "gold_ingot",
                                         "coal", "sulfur", "gunpowder", "oil_barrel",
                                         "leather", "wool", "string", "wheat", "flour",
                                         "mushroom"))
            self.assertGreaterEqual(recipe.get("output", 1), 1)


class WorldStateTest(unittest.TestCase):
    def test_occupied_tracking(self):
        world = WorldState()
        world.place_building(10, 10, "town_center", "0", 2, 2)
        self.assertIn("10,10", world.occupied)
        self.assertIn("11,11", world.tile_building)
        self.assertFalse(world.can_place(11, 11, 1, 1))

    def test_movement_blocked_by_building(self):
        world = WorldState()
        world.add_player("0")
        world.players["0"]["x"], world.players["0"]["y"] = 10 * TILE_SIZE, 10 * TILE_SIZE
        world.place_building(11, 10, "wall", "1", 1, 1)
        # b13: множитель биома (болото 0.8, тундра 0.85) делает шаг короче тайла,
        # поэтому шагаем с запасом - проверяем именно стену, а не длину шага
        self.assertFalse(world.move_player("0", 2 * TILE_SIZE, 0))
        self.assertTrue(world.move_player("0", 0, 2 * TILE_SIZE))

    def test_farms_stay_walkable(self):
        world = WorldState()
        world.add_player("0")
        world.players["0"]["x"], world.players["0"]["y"] = 10 * TILE_SIZE, 10 * TILE_SIZE
        world.place_building(11, 10, "farm", "1", 2, 2)
        self.assertTrue(world.move_player("0", TILE_SIZE, 0))

    def test_terrain_is_deterministic(self):
        self.assertEqual(WorldState().terrain_string(), WorldState().terrain_string())

    def test_terrain_blocks_movement(self):
        world = WorldState()
        world.add_player("0")
        gx, gy = 50, 50
        # b11: the player has to stand on dry land, or the water would slow the
        # step down so much that he never reaches the rock at all
        world.terrain[gy][gx - 1] = 0
        world.terrain[gy][gx] = 1
        world.players["0"]["x"] = gx * TILE_SIZE - 4
        world.players["0"]["y"] = gy * TILE_SIZE
        self.assertEqual(world.move_factor(gx * TILE_SIZE - 4, gy * TILE_SIZE), 1.0)
        self.assertFalse(world.move_player("0", 8, 0))


class ServerTestCase(unittest.TestCase):
    """Base class: a real server on a free port, one client per test."""

    @classmethod
    def setUpClass(cls):
        cls.port = free_port()
        cls.server = server_module.GameServer(
            host="127.0.0.1", port=cls.port, accounts_path=None,
            config={**server_module.DEFAULT_CONFIG, "hunger_rate": 0.0, "tasks": False,
                    "durability": False, "animals": False, "day_length": 100000,
                    "start_kit": {}})
        threading.Thread(target=cls.server.run, daemon=True).start()
        time.sleep(0.6)

    @classmethod
    def tearDownClass(cls):
        cls.server.running = False
        time.sleep(0.3)

    def setUp(self):
        self._isolate_world()
        self.client = RawClient(self.port)
        self.welcome = self.client.auth(name="Tester")
        self.assertIsNotNone(self.welcome, "auth failed")
        self.pid = self.welcome["id"]
        self.player = self.server.world.players[self.pid]
        self.addCleanup(self.client.close)
        self.addCleanup(self._drop_player)

    def _isolate_world(self):
        """Each test starts from a clean map: no leftovers from other tests."""
        from server.civilization import CivManager
        world = self.server.world
        with world.lock:
            world.buildings.clear()
            world.occupied.clear()
            world.tile_building.clear()
            world.civs = CivManager()
            world.touch("buildings", "civs")

    def _drop_player(self):
        self.server.world.players.pop(self.pid, None)
        time.sleep(0.05)

    def give(self, **items):
        self.player["inventory"].update(items)

    def place(self, x, y, structure="crafting_table", w=1, h=1):
        self.server.world.place_building(x, y, structure, self.pid, w, h)

    def teleport(self, tile_x, tile_y):
        self.player["x"] = tile_x * TILE_SIZE
        self.player["y"] = tile_y * TILE_SIZE


class ConnectionTest(ServerTestCase):
    def test_welcome_contains_build_and_world(self):
        self.assertIn("build", self.welcome)
        self.assertIn("terrain", self.welcome)
        self.assertEqual(len(self.welcome["terrain"]), 100 * 100)
        self.assertIn("name", self.welcome)

    def test_initial_state_is_full(self):
        states = [m for m in self.client.inbox if m.get("type") == "state"]
        self.assertTrue(states)
        self.assertIn("resources", states[0])
        self.assertIn("buildings", states[0])

    def test_state_broadcast_without_input(self):
        self.client.clear()
        self.assertGreaterEqual(len(self.client.of_type("state", 0.7)), 3)

    def test_guest_names_are_sanitised(self):
        client = RawClient(self.port)
        try:
            welcome = client.auth(name="<script>alert(1)</script>")
            self.assertIsNotNone(welcome)
            self.assertNotIn("<", welcome["name"])
        finally:
            client.close()

    def test_malformed_packets_do_not_kill_the_session(self):
        self.client.send({"type": "join_country", "country": "Nope"})
        self.client.send({"type": "totally_unknown"})
        self.client.send({"type": "move", "dx": "not-a-number"})
        self.client.send({"type": "build", "structure": 42})
        self.client.poll(0.5)
        self.client.clear()
        self.client.send({"type": "ping", "t": 1})
        types = [m.get("type") for m in self.client.poll(0.6)]
        self.assertNotIn("DISCONNECTED", types)
        self.assertIn("pong", types)

    def test_movement_is_clamped(self):
        self.teleport(20, 20)
        before = self.player["x"]
        self.client.send({"type": "move", "dx": 100000, "dy": 0})
        self.client.poll(0.3)
        # b13: биом и сезон умножают шаг (пустыня 1.05), поэтому верхняя граница
        # чуть выше самого лимита - важно, что запрос обрезан, а не прошёл целиком
        self.assertLessEqual(self.player["x"] - before,
                             server_module.MAX_MOVE_STEP * 1.1)


class MultiplayerTest(ServerTestCase):
    def test_other_player_sees_movement(self):
        other = RawClient(self.port)
        try:
            self.assertIsNotNone(other.auth(name="Watcher"))
            other.clear()
            for _ in range(5):
                self.client.send({"type": "move", "dx": 6, "dy": 0})
            states = [m for m in other.of_type("state", 1.0)
                      if self.pid in m.get("players", {})]
            self.assertTrue(states, "no state broadcasts reached the second player")
            # weather scales movement, so positions are floats now
            position = states[-1]["players"][self.pid]["x"]
            self.assertGreaterEqual(position, 0)
            self.assertLess(position, 100 * TILE_SIZE)
        finally:
            other.close()

    def test_join_and_leave_notifications_use_keys(self):
        other = RawClient(self.port)
        try:
            other.clear()
            other.auth(name="Newcomer")
            keys = other.notif_keys(0.6)
            self.assertIn("auth.guest", keys)
        finally:
            other.close()

    def test_chat_carries_names(self):
        self.player["name"] = "Alice"
        other = RawClient(self.port)
        try:
            other.auth(name="Bob")
            other.clear()
            self.client.send({"type": "chat", "text": "hello"})
            chats = [m for m in other.of_type("chat", 0.7)]
            self.assertTrue(chats)
            self.assertEqual(chats[-1]["name"], "Alice")
            self.assertEqual(chats[-1]["msg"], "hello")
        finally:
            other.close()


class InventoryTest(ServerTestCase):
    def test_inventory_is_private(self):
        other = RawClient(self.port)
        try:
            other.auth(name="Snoop")
            self.give(wood=7)
            self.server.world.touch_inventory(self.pid)
            other.clear()
            self.client.clear()
            own = [m for m in self.client.of_type("state", 0.7) if m.get("partial")]
            self.assertTrue(own, "owner never got an inventory packet")
            self.assertEqual(own[-1]["players"][self.pid]["inventory"]["wood"], 7)
            for message in other.of_type("state", 0.5):
                if message.get("partial"):
                    self.assertNotIn(self.pid, message["players"])
                else:
                    self.assertNotIn("inventory", message["players"].get(self.pid, {}))
        finally:
            other.close()

    def test_select_item_sets_the_hand_and_rejects_missing(self):
        self.give(iron_sword=1)
        self.client.clear()
        self.client.send({"type": "select_item", "item": "iron_sword"})
        keys = self.client.notif_keys(0.6)
        self.assertIn("notify.item_in_hand", keys)
        self.assertEqual(self.player["selected"], "iron_sword")

        self.client.clear()
        self.client.send({"type": "select_item", "item": "pistol"})
        keys = self.client.notif_keys(0.6)
        self.assertIn("notify.no_such_item", keys)
        self.assertEqual(self.player["selected"], "iron_sword")   # unchanged

    def test_select_item_can_empty_the_hand(self):
        self.give(sword=1)
        self.client.send({"type": "select_item", "item": "sword"})
        self.client.poll(0.3)
        self.client.send({"type": "select_item", "item": None})
        self.client.poll(0.4)
        self.assertIsNone(self.player["selected"])

    def test_holding_a_tool_increases_gathering(self):
        self.teleport(40, 40)
        self.server.world.resources["40,40"] = {"x": 40 * TILE_SIZE + 4,
                                                "y": 40 * TILE_SIZE, "type": "tree"}
        # bare hands: 1 wood
        self.client.send({"type": "gather"})
        self.client.poll(0.4)
        self.assertEqual(self.player["inventory"]["wood"], 1)

        # with an iron axe in hand: efficiency 4
        self.give(iron_axe=1)
        self.client.send({"type": "select_item", "item": "iron_axe"})
        self.client.poll(0.3)
        self.server.world.resources["40,40"] = {"x": 40 * TILE_SIZE + 4,
                                                "y": 40 * TILE_SIZE, "type": "tree"}
        self.client.clear()
        self.client.send({"type": "gather"})
        self.client.poll(0.4)
        self.assertEqual(self.player["inventory"]["wood"], 5)
        self.assertIn("notify.gathered", [m.get("key") for m in self.client.inbox])


class CombatTest(ServerTestCase):
    def setUp(self):
        super().setUp()
        self.other = RawClient(self.port)
        self.target_welcome = self.other.auth(name="Victim")
        self.assertIsNotNone(self.target_welcome)
        self.target_id = self.target_welcome["id"]
        self.target = self.server.world.players[self.target_id]
        self.addCleanup(self.other.close)

    def _stand_next_to_target(self):
        self.target["x"], self.target["y"] = 1000, 1000
        self.player["x"], self.player["y"] = 1010, 1000

    def test_fists_do_little_damage(self):
        self._stand_next_to_target()
        self.target["hp"] = 100
        self.client.send({"type": "attack", "target_id": self.target_id})
        self.client.poll(0.4)
        self.assertEqual(self.target["hp"], 95)

    def test_sword_in_hand_does_weapon_damage(self):
        self._stand_next_to_target()
        self.give(iron_sword=1)
        self.client.send({"type": "select_item", "item": "iron_sword"})
        self.client.poll(0.3)
        self.client.clear()
        self.client.send({"type": "attack", "target_id": self.target_id})
        self.client.poll(0.4)
        self.assertEqual(self.target["hp"], 80)
        self.assertIn("notify.hit", [m.get("key") for m in self.client.inbox])

    def test_pistol_requires_and_consumes_ammo(self):
        self._stand_next_to_target()
        self.give(pistol=1)
        self.client.send({"type": "select_item", "item": "pistol"})
        self.client.poll(0.3)
        self.client.clear()
        self.client.send({"type": "attack", "target_id": self.target_id})
        keys = self.client.notif_keys(0.5)
        self.assertIn("notify.no_ammo", keys)
        self.assertEqual(self.target["hp"], 100)

        self.give(ammo=2)
        self.player["last_shot"] = 0                       # cooldown has passed
        self.client.clear()
        self.client.send({"type": "attack", "target_id": self.target_id})
        self.client.poll(0.4)
        self.assertEqual(self.target["hp"], 60)
        self.assertEqual(self.player["inventory"]["ammo"], 1)

    def test_target_is_told_about_the_hit_and_defeat_respawns(self):
        self._stand_next_to_target()
        self.give(iron_sword=1)
        self.client.send({"type": "select_item", "item": "iron_sword"})
        self.client.poll(0.3)
        self.target["hp"] = 10
        self.other.clear()
        self.client.send({"type": "attack", "target_id": self.target_id})
        self.client.poll(0.5)
        keys = [m.get("key") for m in self.other.poll(0.4) if m.get("type") == "notification"]
        self.assertTrue({"notify.you_hit", "notify.respawn"} & set(keys), keys)
        self.assertEqual(self.target["hp"], 100)
        self.assertNotEqual((self.target["x"], self.target["y"]), (1000, 1000))

    def test_out_of_range_is_reported(self):
        self.target["x"], self.target["y"] = 5000, 5000
        self.player["x"], self.player["y"] = 1000, 1000
        self.client.clear()
        self.client.send({"type": "attack", "target_id": self.target_id})
        self.assertIn("notify.out_of_range", self.client.notif_keys(0.5))


class BuildingTest(ServerTestCase):
    def test_build_next_to_the_player(self):
        self.give(wood=10)
        self.teleport(30, 30)
        self.client.clear()
        self.client.send({"type": "build", "structure": "wall", "x": 31, "y": 30})
        self.assertTrue(any(m.get("key") == "notify.built"
                            for m in self.client.notifications(0.6)))
        self.assertIn("31,30", self.server.world.buildings)
        self.assertEqual(self.player["inventory"]["wood"], 8)

    def test_build_at_the_player_tile_without_coordinates(self):
        self.give(wood=10)
        self.teleport(35, 35)
        self.client.send({"type": "build", "structure": "wall"})
        self.client.poll(0.5)
        self.assertIn("35,35", self.server.world.buildings)

    def test_build_far_away_is_refused(self):
        self.give(wood=10)
        self.teleport(20, 20)
        self.client.clear()
        self.client.send({"type": "build", "structure": "wall", "x": 60, "y": 60})
        self.assertIn("notify.build_fail_range", self.client.notif_keys(0.6))
        self.assertNotIn("60,60", self.server.world.buildings)

    def test_build_reports_missing_resources(self):
        self.player["inventory"] = {"wood": 0, "stone": 0}
        self.client.clear()
        self.client.send({"type": "build", "structure": "town_center", "x": 10, "y": 10})
        keys = self.client.notif_keys(0.6)
        self.assertIn("notify.build_fail_resources", keys)
        self.assertNotIn("10,10", self.server.world.buildings)

    def test_build_reports_occupied_space(self):
        self.give(wood=20)
        self.place(50, 50, "wall")
        self.teleport(49, 50)
        self.client.clear()
        self.client.send({"type": "build", "structure": "wall", "x": 50, "y": 50})
        self.assertIn("notify.build_fail_space", self.client.notif_keys(0.6))

    def test_tech_locked_building_is_refused(self):
        self.give(iron_ingot=100, stone=100)
        self.teleport(45, 45)
        self.client.clear()
        self.client.send({"type": "build", "structure": "drill", "x": 45, "y": 46})
        self.assertIn("notify.build_fail_tech", self.client.notif_keys(0.6))

    def test_builder_is_pushed_out_of_the_footprint(self):
        self.give(wood=60, stone=60)
        self.teleport(60, 60)
        self.client.send({"type": "build", "structure": "town_center", "x": 60, "y": 60})
        self.client.poll(0.5)
        tile = f"{int(self.player['x'] // TILE_SIZE)},{int(self.player['y'] // TILE_SIZE)}"
        self.assertNotIn(tile, self.server.world.occupied)

    def test_unknown_structure(self):
        self.client.clear()
        self.client.send({"type": "build", "structure": "spaceship", "x": 1, "y": 1})
        self.assertIn("notify.build_fail_unknown", self.client.notif_keys(0.5))


class CraftingTest(ServerTestCase):
    def test_crafting_requires_the_station(self):
        self.give(wood=10, stone=10)
        self.teleport(70, 70)
        self.client.clear()
        self.client.send({"type": "craft", "item": "axe"})
        self.assertIn("craft.station_missing", self.client.notif_keys(0.6))
        self.assertNotIn("axe", self.player["inventory"])

    def test_crafting_next_to_a_table(self):
        self.give(wood=10, stone=10)
        self.teleport(70, 70)
        self.place(71, 70, "crafting_table")
        self.client.clear()
        self.client.send({"type": "craft", "item": "axe"})
        self.assertTrue(any(m.get("key") == "notify.crafted"
                            for m in self.client.notifications(0.6)))
        self.assertEqual(self.player["inventory"]["axe"], 1)
        self.assertEqual(self.player["inventory"]["wood"], 8)

    def test_crafting_five_at_once(self):
        self.give(wood=20, stone=30)
        self.teleport(70, 70)
        self.place(71, 70, "crafting_table")
        self.client.clear()
        self.client.send({"type": "craft", "item": "pickaxe", "count": 5})
        self.client.poll(0.6)
        self.assertEqual(self.player["inventory"]["pickaxe"], 5)

    def test_craft_count_is_limited_by_resources(self):
        self.give(wood=4, stone=6)
        self.teleport(70, 70)
        self.place(71, 70, "crafting_table")
        self.client.send({"type": "craft", "item": "axe", "count": 64})
        self.client.poll(0.6)
        self.assertEqual(self.player["inventory"]["axe"], 2)
        self.assertEqual(self.player["inventory"].get("wood", 0), 0)

    def test_batch_recipe_gives_five_ammo(self):
        self.give(iron_ingot=1, gunpowder=1)
        self.teleport(70, 70)
        self.place(71, 70, "crafting_table")
        self.client.send({"type": "craft", "item": "ammo"})
        self.client.poll(0.6)
        self.assertEqual(self.player["inventory"]["ammo"], 5)

    def test_unknown_recipe(self):
        self.client.clear()
        self.client.send({"type": "craft", "item": "rocket_launcher"})
        self.assertIn("craft.unknown", self.client.notif_keys(0.5))


class CivTest(ServerTestCase):
    def test_city_and_country_flow(self):
        self.client.send({"type": "create_city", "name": "Testville"})
        self.client.poll(0.4)
        self.assertIn("Testville", self.server.world.civs.cities)

        self.client.send({"type": "create_country", "name": "Testland"})
        self.client.poll(0.4)
        self.assertIn("Testland", self.server.world.civs.countries)

        self.client.send({"type": "join_country", "country": "Testland"})
        self.client.poll(0.4)
        self.assertIn(self.server.world.civs.cities["Testville"],
                      self.server.world.civs.countries["Testland"].cities)

    def test_research_charges_every_resource(self):
        self.client.send({"type": "create_city", "name": "Lab"})
        self.client.send({"type": "create_country", "name": "Labs"})
        self.client.poll(0.4)
        self.client.send({"type": "join_country", "country": "Labs"})
        self.client.poll(0.3)

        self.give(iron_ingot=50, gold_ingot=50)
        self.client.clear()
        self.client.send({"type": "research", "scope": "country", "country": "AUTO_FIND",
                          "tech": "industrialization"})
        self.assertTrue(any(m.get("key") == "notify.tech_done"
                            for m in self.client.notifications(0.6)))
        self.assertEqual(self.player["inventory"].get("iron_ingot", 0), 0)
        self.assertEqual(self.player["inventory"].get("gold_ingot", 0), 0)
        self.assertIn("industrialization",
                      [tech for country in self.server.world.civs.countries.values()
                       for tech in country.techs])

    def test_city_tier_upgrade(self):
        self.client.send({"type": "create_city", "name": "Tier Town"})
        self.client.poll(0.3)
        self.give(wood=100, stone=100)
        self.client.clear()
        self.client.send({"type": "research", "city": "AUTO_FIND"})
        self.assertTrue(any(m.get("key") == "notify.tier_up"
                            for m in self.client.notifications(0.6)))
        self.assertEqual(self.server.world.civs.cities["Tier Town"].tier, 2)

    def test_city_tier_three_and_max(self):
        self.client.send({"type": "create_city", "name": "Megacity"})
        self.client.poll(0.3)
        self.server.world.civs.cities["Megacity"].tier = 2
        self.give(wood=200, stone=200, iron_ingot=50)
        self.client.clear()
        self.client.send({"type": "research", "city": "AUTO_FIND"})
        self.assertTrue(any(m.get("key") == "notify.tier_up" and m["args"].get("tier") == 3
                            for m in self.client.notifications(0.6)))
        self.assertEqual(self.server.world.civs.cities["Megacity"].tier, 3)

        self.give(wood=500, stone=500, iron_ingot=500)
        self.client.clear()
        self.client.send({"type": "research", "city": "AUTO_FIND"})
        self.assertIn("notify.tier_max", self.client.notif_keys(0.6))

    def test_research_requires_the_previous_tech(self):
        self.client.send({"type": "create_city", "name": "Chemtown"})
        self.client.send({"type": "create_country", "name": "Chemland"})
        self.client.poll(0.4)
        self.client.send({"type": "join_country", "country": "Chemland"})
        self.client.poll(0.3)
        self.give(oil_barrel=50)
        self.client.clear()
        self.client.send({"type": "research", "scope": "country", "country": "AUTO_FIND",
                          "tech": "chemistry"})
        self.assertIn("notify.tech_requires", self.client.notif_keys(0.6))
        self.assertNotIn("chemistry",
                         self.server.world.civs.countries["Chemland"].techs)

    def test_duplicate_city_name_is_rejected(self):
        self.client.send({"type": "create_city", "name": "Twins"})
        self.client.poll(0.3)
        self.client.clear()
        other = RawClient(self.port)
        try:
            other.auth(name="Second")
            other.send({"type": "create_city", "name": "Twins"})
            self.assertIn("notify.city_name_taken", other.notif_keys(0.6))
        finally:
            other.close()


class SmeltingTest(ServerTestCase):
    def test_smelting_requires_furnace_and_fuel(self):
        self.give(iron_ore=2)
        self.teleport(80, 80)
        self.client.clear()
        self.client.send({"type": "smelt", "action": "smelt_iron"})
        self.assertIn("notify.smelt_no_furnace", self.client.notif_keys(0.5))

        self.place(81, 80, "furnace")
        self.client.clear()
        self.client.send({"type": "smelt", "action": "smelt_iron"})
        self.assertIn("notify.smelt_need_coal", self.client.notif_keys(0.5))

        self.give(coal=1)
        self.client.clear()
        self.client.send({"type": "smelt", "action": "smelt_iron"})
        self.client.poll(0.5)
        self.assertEqual(self.player["inventory"]["iron_ingot"], 1)
        self.assertEqual(self.player["inventory"]["coal"], 0)
        self.assertEqual(self.player["inventory"]["iron_ore"], 1)


if __name__ == "__main__":
    unittest.main()
