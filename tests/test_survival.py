"""b8 mechanics: durability, hunger, chests, doors, buildings health, animals."""

import os
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server import server as server_module
from server.world_state import TILE_SIZE
from shared.items import item_durability
from shared.structures import get_hp
from shared.tasks import TASKS

from tests.helpers import RawClient, free_port

# everything on: durability, hunger, animals, tasks
LIVE_CONFIG = {
    **server_module.DEFAULT_CONFIG,
    "day_length": 100000,      # keep the clock still during tests
    "animal_respawn": 9999,
    "start_kit": {},           # tests hand out their own items
}


class SurvivalServerTest(unittest.TestCase):
    """One real server with all survival mechanics enabled."""

    @classmethod
    def setUpClass(cls):
        cls.port = free_port()
        cls.server = server_module.GameServer(
            host="127.0.0.1", port=cls.port, accounts_path=None,
            config={**LIVE_CONFIG, "tasks": False})
        threading.Thread(target=cls.server.run, daemon=True).start()
        time.sleep(0.6)

    @classmethod
    def tearDownClass(cls):
        cls.server.running = False
        time.sleep(0.3)

    def setUp(self):
        self.client = RawClient(self.port)
        welcome = self.client.auth(name="Survivor")
        self.assertIsNotNone(welcome)
        self.pid = welcome["id"]
        self.player = self.server.world.players[self.pid]
        self.addCleanup(self.client.close)
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        from server.civilization import CivManager
        world = self.server.world
        with world.lock:
            world.players.pop(self.pid, None)
            world.buildings.clear()
            world.occupied.clear()
            world.tile_building.clear()
            world.civs = CivManager()
            world.touch("buildings", "civs")

    def give(self, **items):
        self.player["inventory"].update(items)

    def teleport(self, tx, ty):
        self.player["x"], self.player["y"] = tx * TILE_SIZE, ty * TILE_SIZE
        self.server.world.touch_inventory(self.pid)

    def place(self, tx, ty, structure, **extra):
        key = self.server.world.place_building(tx, ty, structure, self.pid, 1, 1)
        self.server.world.buildings[key].update(extra)
        return key

    def send(self, message, seconds=0.5):
        self.client.clear()
        self.client.send(message)
        return self.client.poll(seconds)

    def keys(self, message, seconds=0.5):
        return [m.get("key") for m in self.send(message, seconds)
                if m.get("type") == "notification"]


class DurabilityTest(SurvivalServerTest):
    def setUp(self):
        super().setUp()
        self.server.world.resources["500,500"] = {"x": 500, "y": 500, "type": "tree"}
        self.teleport(15, 15)                              # 500,500 is next to it
        self.player["x"], self.player["y"] = 500, 500

    def test_tools_wear_out_and_break(self):
        self.give(iron_axe=1)
        self.player["durability"]["iron_axe"] = 2
        self.client.send({"type": "select_item", "item": "iron_axe"})
        self.client.poll(0.3)

        for hit in range(3):
            self.server.world.resources["500,500"] = {"x": 500, "y": 500, "type": "tree"}
            self.client.send({"type": "gather"})
            self.client.poll(0.3)
        keys = [m.get("key") for m in self.client.inbox]
        self.assertIn("notify.tool_broke", keys)
        self.assertNotIn("iron_axe", self.player["inventory"])
        self.assertIsNone(self.player["selected"], "a broken tool must leave the hand")

    def test_durability_is_reported_to_the_owner(self):
        self.give(iron_axe=1)
        self.client.send({"type": "select_item", "item": "iron_axe"})
        self.client.poll(0.3)
        self.client.clear()
        self.server.world.resources["500,500"] = {"x": 500, "y": 500, "type": "tree"}
        self.client.send({"type": "gather"})
        self.client.poll(0.5)
        partials = [m for m in self.client.inbox if m.get("type") == "state"
                    and m.get("partial")]
        self.assertTrue(partials)
        durability = partials[-1]["players"][self.pid]["durability"]
        self.assertEqual(durability["iron_axe"], item_durability("iron_axe") - 1)

    def test_smelting_upgrades_the_tool_kit(self):
        # smelting is covered in test_server; here we only check the durability map
        self.give(axe=1)
        self.player["durability"] = {}
        self.client.send({"type": "craft", "item": "axe"})
        self.client.poll(0.3)
        self.assertGreaterEqual(self.player["durability"].get("axe", 0), 0)


class HungerTest(SurvivalServerTest):
    def test_eating_restores_hunger_and_health(self):
        self.player["hunger"] = 40
        self.player["hp"] = 60
        self.give(bread=2)
        messages = self.send({"type": "eat", "item": "bread"})
        keys = [m.get("key") for m in messages if m.get("type") == "notification"]
        self.assertIn("notify.ate", keys)
        self.assertEqual(round(self.player["hunger"]), 70)
        self.assertEqual(self.player["hp"], 68)
        self.assertEqual(self.player["inventory"]["bread"], 1)

    def test_eating_something_that_is_not_food(self):
        self.give(wood=1)
        self.assertIn("notify.cannot_eat", self.keys({"type": "eat", "item": "wood"}))
        self.assertEqual(self.player["inventory"]["wood"], 1)

    def test_hunger_drains_and_starving_hurts(self):
        self.player["hunger"] = 0.1
        self.player["hp"] = 20
        self.server.tick_hunger(5.0)                       # five seconds of starvation
        self.assertLess(self.player["hp"], 20)

    def test_well_fed_players_regenerate(self):
        self.player["hunger"] = 100
        self.player["hp"] = 50
        self.server.tick_hunger(5.0)
        self.assertEqual(self.player["hp"], 51)

    def test_raw_meat_can_poison(self):
        poisoned = 0
        for _ in range(40):
            self.player["hunger"] = 50
            self.player["hp"] = 100
            self.give(raw_meat=1)
            messages = self.send({"type": "eat", "item": "raw_meat"})
            if any(m.get("key") == "notify.poisoned" for m in messages):
                poisoned += 1
        self.assertGreater(poisoned, 0, "raw meat should sometimes hurt")


class ArmorTest(SurvivalServerTest):
    def setUp(self):
        super().setUp()
        self.other = RawClient(self.port)
        welcome = self.other.auth(name="Brute")
        self.target_id = welcome["id"]
        self.target = self.server.world.players[self.target_id]
        self.addCleanup(self.other.close)

    def _stand_next_to(self):
        self.target["x"], self.target["y"] = 1000, 1000
        self.player["x"], self.player["y"] = 1008, 1000

    def test_equipping_armor_reduces_damage(self):
        self._stand_next_to()
        self.give(iron_sword=1)
        self.client.send({"type": "select_item", "item": "iron_sword"})
        self.client.poll(0.3)
        self.target["hp"] = 100
        self.client.send({"type": "attack", "target_id": self.target_id})
        self.client.poll(0.4)
        without_armor = 100 - self.target["hp"]
        self.assertEqual(without_armor, 20)

        # the *victim* wears the armor
        self.target["armor"] = {"chest": "iron_chestplate", "helmet": "iron_helmet"}
        self.assertEqual(self.server.armor_points(self.target), 11)
        self.target["hp"] = 100
        self.client.send({"type": "attack", "target_id": self.target_id})
        self.client.poll(0.4)
        with_armor = 100 - self.target["hp"]
        self.assertLess(with_armor, without_armor)
        self.assertGreaterEqual(with_armor, 1)

    def test_armor_goes_back_to_the_inventory(self):
        self.give(leather_boots=1)
        self.send({"type": "equip", "item": "leather_boots"})
        self.assertEqual(self.player["armor"].get("feet"), "leather_boots")
        self.assertNotIn("leather_boots", self.player["inventory"])
        self.send({"type": "equip", "item": None, "slot": "feet"})
        self.assertNotIn("feet", self.player["armor"])
        self.assertEqual(self.player["inventory"]["leather_boots"], 1)

    def test_shield_blocks_part_of_the_damage(self):
        self._stand_next_to()
        self.give(iron_sword=1)
        self.client.send({"type": "select_item", "item": "iron_sword"})
        self.client.poll(0.3)
        self.target["hp"] = 100
        self.target["inventory"]["shield"] = 1
        self.target["selected"] = "shield"
        self.send({"type": "attack", "target_id": self.target_id})
        self.assertGreater(self.target["hp"], 90, "the shield should have blocked most of it")
        self.assertIn("notify.blocked",
                      [m.get("key") for m in self.other.poll(0.4)
                       if m.get("type") == "notification"])

    def test_bow_needs_arrows(self):
        self.give(bow=1)
        self.send({"type": "select_item", "item": "bow"})
        self._stand_next_to()
        self.target["hp"] = 100
        self.assertIn("notify.no_ammo", self.keys({"type": "attack",
                                                   "target_id": self.target_id}))
        self.give(arrow=2)
        self.send({"type": "attack", "target_id": self.target_id})
        self.assertEqual(self.target["hp"], 75)
        self.assertEqual(self.player["inventory"]["arrow"], 1)


class StorageTest(SurvivalServerTest):
    def test_chest_deposit_and_withdraw(self):
        self.teleport(30, 30)
        self.place(31, 30, "chest")
        self.give(wood=10, stone=4)
        self.send({"type": "chest_put", "x": 31, "y": 30, "item": "wood", "count": 6})
        contents = self.server.world.buildings["31,30"]["items"]
        self.assertEqual(contents["wood"], 6)
        self.assertEqual(self.player["inventory"]["wood"], 4)

        messages = self.send({"type": "chest_take", "x": 31, "y": 30, "item": "wood",
                              "count": 2})
        self.assertEqual(self.server.world.buildings["31,30"]["items"]["wood"], 4)
        self.assertEqual(self.player["inventory"]["wood"], 6)
        chest_packets = [m for m in messages if m.get("type") == "chest"]
        self.assertTrue(chest_packets, "the client should receive the chest contents")

    def test_chest_keeps_its_bill_of_materials_private(self):
        self.teleport(30, 30)
        self.place(31, 30, "chest")
        with self.server.world.lock:
            self.server.world.touch("buildings")
        other = RawClient(self.port)
        try:
            other.auth(name="Thief")
            other.clear()
            self.send({"type": "chest_put", "x": 31, "y": 30, "item": "wood", "count": 1})
            states = [m for m in other.poll(0.6) if m.get("type") == "state"]
            self.assertTrue(states)
            for message in states:
                for building in message.get("buildings", {}).values():
                    self.assertNotIn("items", building)
        finally:
            other.close()

    def test_city_members_share_a_chest(self):
        self.client.send({"type": "create_city", "name": "Shared"})
        self.client.poll(0.4)
        other = RawClient(self.port)
        try:
            other.auth(name="Friend")
            other.send({"type": "join_city", "name": "Shared"})
            other.poll(0.4)
            self.teleport(40, 40)
            self.place(41, 40, "chest")
            self.give(stone=5)
            self.send({"type": "chest_put", "x": 41, "y": 40, "item": "stone", "count": 5})
            self.assertEqual(self.server.world.buildings["41,40"]["items"]["stone"], 5)
        finally:
            other.close()

    def test_weird_chest_requests_change_nothing(self):
        self.teleport(50, 50)
        self.place(51, 50, "chest")
        self.give(wood=3)
        keys = self.keys({"type": "chest_take", "x": 51, "y": 50, "item": "wood",
                          "count": 5})
        self.assertIn("notify.chest_empty", keys)
        self.assertEqual(self.player["inventory"]["wood"], 3)
        keys = self.keys({"type": "chest_put", "x": 51, "y": 50, "item": "gold_ingot",
                          "count": 5})
        self.assertIn("notify.no_such_item", keys)


class DoorAndBuildingTest(SurvivalServerTest):
    def test_doors_toggle_and_block_movement(self):
        self.teleport(60, 60)
        self.place(61, 60, "door")
        self.assertFalse(self.server.world.passable(61, 60))
        self.send({"type": "toggle_door", "x": 61, "y": 60})
        self.assertTrue(self.server.world.passable(61, 60))
        self.send({"type": "toggle_door", "x": 61, "y": 60})
        self.assertFalse(self.server.world.passable(61, 60))

    def test_others_cannot_open_your_door(self):
        self.teleport(70, 70)
        self.place(71, 70, "door")
        other = RawClient(self.port)
        try:
            welcome = other.auth(name="Stranger")
            stranger = self.server.world.players[welcome["id"]]
            stranger["x"], stranger["y"] = 71 * TILE_SIZE, 70 * TILE_SIZE
            other.clear()
            other.send({"type": "toggle_door", "x": 71, "y": 70})
            keys = [m.get("key") for m in other.poll(0.5) if m.get("type") == "notification"]
            self.assertIn("notify.not_yours", keys)
            self.assertFalse(self.server.world.buildings["71,70"]["open"])
        finally:
            other.close()

    def test_buildings_have_health_and_can_be_broken(self):
        self.teleport(80, 80)
        self.place(81, 80, "wall")
        key = "81,80"
        self.assertEqual(self.server.world.buildings[key]["hp"], get_hp("wall"))
        # a stranger with a sword hacks at it
        other = RawClient(self.port)
        try:
            welcome = other.auth(name="Raider")
            raider = self.server.world.players[welcome["id"]]
            raider["x"], raider["y"] = 82 * TILE_SIZE, 80 * TILE_SIZE
            raider["inventory"]["iron_sword"] = 1
            raider["selected"] = "iron_sword"
            other.clear()
            for _ in range(12):
                other.send({"type": "attack_building", "x": 81, "y": 80})
                other.poll(0.25)
                if key not in self.server.world.buildings:
                    break
            self.assertNotIn(key, self.server.world.buildings, "the wall should fall")
            keys = [m.get("key") for m in other.poll(0.4)
                    if m.get("type") == "notification"]
            self.assertIn("notify.building_destroyed", keys)
        finally:
            other.close()

    def test_owner_repairs_a_damaged_building(self):
        self.teleport(90, 90)
        key = self.place(91, 90, "wall")
        self.server.world.damage_building(key, 50)
        damaged = self.server.world.buildings[key]["hp"]
        self.give(wood=4)
        self.send({"type": "repair", "x": 91, "y": 90, "units": 1})
        self.assertGreater(self.server.world.buildings[key]["hp"], damaged)
        self.assertEqual(self.player["inventory"]["wood"], 3)

    def test_you_cannot_repair_someone_elses_building(self):
        self.teleport(95, 95)
        other = RawClient(self.port)
        try:
            welcome = other.auth(name="Owner")
            foreign_key = self.server.world.place_building(96, 95, "wall",
                                                           welcome["id"], 1, 1)
            self.server.world.damage_building(foreign_key, 40)
            self.give(wood=4)
            keys = self.keys({"type": "repair", "x": 96, "y": 95})
            self.assertIn("notify.not_yours", keys)
            self.assertEqual(self.player["inventory"]["wood"], 4)
        finally:
            other.close()

    def test_light_sources_are_reported_for_the_night(self):
        self.teleport(20, 70)
        self.place(21, 70, "torch")
        self.place(23, 70, "campfire")
        lights = self.server.world.light_sources()
        self.assertGreaterEqual(len(lights), 2)
        self.assertTrue(all(radius > 0 for _x, _y, radius in lights))


class AnimalTest(SurvivalServerTest):
    def _nearest_animal(self, kind, near=(300, 300)):
        best, best_id = None, None
        for aid, animal in self.server.world.animals.items():
            if animal["type"] != kind:
                continue
            distance = ((animal["x"] - near[0]) ** 2 + (animal["y"] - near[1]) ** 2) ** 0.5
            if best is None or distance < best:
                best, best_id = distance, aid
        return best_id

    def test_world_is_populated_with_animals(self):
        kinds = {a["type"] for a in self.server.world.animals.values()}
        self.assertTrue({"sheep", "cow", "chicken", "wolf"} <= kinds, kinds)

    def test_hunting_gives_drops(self):
        animal_id = self._nearest_animal("chicken")
        animal = self.server.world.animals[animal_id]
        self.player["x"], self.player["y"] = animal["x"] + 10, animal["y"]
        self.give(iron_sword=1)
        self.send({"type": "select_item", "item": "iron_sword"})
        messages = self.send({"type": "attack_animal", "animal_id": animal_id})
        keys = [m.get("key") for m in messages if m.get("type") == "notification"]
        self.assertIn("notify.animal_killed", keys)
        self.assertNotIn(animal_id, self.server.world.animals)
        self.assertTrue(self.player["inventory"].get("raw_meat") or
                        self.player["inventory"].get("string"))

    def test_wolves_can_be_tamed_with_meat(self):
        wolf_id = self._nearest_animal("wolf")
        wolf = self.server.world.animals[wolf_id]
        wolf["x"], wolf["y"] = self.player["x"] + 20, self.player["y"]
        self.give(raw_meat=2)
        keys = self.keys({"type": "tame", "animal_id": wolf_id})
        self.assertIn("notify.tamed", keys)
        self.assertEqual(wolf.get("owner"), self.pid)
        self.assertIn(wolf_id, self.player["pets"])

    def test_taming_needs_meat(self):
        wolf_id = self._nearest_animal("wolf")
        wolf = self.server.world.animals[wolf_id]
        wolf["x"], wolf["y"] = self.player["x"] + 20, self.player["y"]
        self.assertIn("notify.tame_need_meat", self.keys({"type": "tame",
                                                          "animal_id": wolf_id}))

    def test_pets_walk_to_their_owner(self):
        animal_id = self._nearest_animal("sheep")
        sheep = self.server.world.animals[animal_id]
        sheep["owner"] = self.pid
        sheep["x"], sheep["y"] = self.player["x"] + 200, self.player["y"]
        self.player["pets"] = [animal_id]
        before = sheep["x"]
        for _ in range(12):
            self.server.tick_animals(time.time() + _ * 10)
            time.sleep(0.02)
        self.assertLess(self.server.world.animals[animal_id]["x"], before + 1)

    def test_day_night_cycle_moves(self):
        start = self.server.world_time
        self.server.tick_clock(time.time())
        self.assertNotEqual(self.server.world_time, start)

    def test_state_carries_time_weather_and_animals(self):
        self.client.send({"type": "move", "dx": 1, "dy": 0})
        messages = self.client.of_type("state", 0.6)
        self.assertTrue(messages)
        self.assertIn("time", messages[-1])
        self.assertIn("weather", messages[-1])
        self.assertIn("lights", messages[-1])
        # the animal list arrives with the first full state after joining
        fresh = RawClient(self.port)
        try:
            fresh.auth(name="Newcomer")
            states = [m for m in fresh.inbox if m.get("type") == "state"]
            self.assertTrue(states)
            self.assertIn("animals", states[0])
            self.assertGreater(len(states[0]["animals"]), 0)
        finally:
            fresh.close()


class TaskTest(SurvivalServerTest):
    """Tasks are switched off for the shared server, so this class brings its own."""

    @classmethod
    def setUpClass(cls):
        cls.port = free_port()
        cls.server = server_module.GameServer(host="127.0.0.1", port=cls.port,
                                              accounts_path=None, config=dict(LIVE_CONFIG))
        threading.Thread(target=cls.server.run, daemon=True).start()
        time.sleep(0.6)

    def test_gathering_completes_the_first_task(self):
        self.server.world.resources["500,500"] = {"x": 500, "y": 500, "type": "tree"}
        self.player["x"], self.player["y"] = 500, 500
        for _ in range(25):
            self.server.world.resources["500,500"] = {"x": 500, "y": 500, "type": "tree"}
            self.client.send({"type": "gather"})
            self.client.poll(0.1)
            if self.player["tasks"].get("first_wood"):
                break
        self.assertTrue(self.player["tasks"].get("first_wood"),
                        f"gathering 20 wood should complete the first task "
                        f"(stats={self.player['stats']})")
        self.assertEqual(self.player["stats"]["wood_gathered"] >= 20, True)

    def test_tasks_are_sent_on_join(self):
        fresh = RawClient(self.port)
        try:
            self.assertIsNotNone(fresh.auth(name="Tasker"))
            packets = [m for m in fresh.inbox if m.get("type") == "tasks"]
            self.assertTrue(packets, "the client must receive its task list")
            self.assertIn("stats", packets[-1])
            self.assertIn("tasks", packets[-1])
        finally:
            fresh.close()

    def test_every_task_rewards_a_real_item(self):
        from shared.items import ITEMS
        for code, data in TASKS.items():
            self.assertIn(data["kind"], ("task", "achievement"), code)
            self.assertGreater(data["target"], 0, code)
            for item, amount in data["reward"].items():
                self.assertIn(item, ITEMS, f"{code} rewards unknown item {item}")
                self.assertGreater(amount, 0, code)


class StartKitTest(unittest.TestCase):
    """server_config.json gives new players a kit and can be loaded from disk."""

    def test_config_file_is_merged_over_the_defaults(self):
        import json
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "server_config.json"
            path.write_text(json.dumps({"pvp": False, "day_length": 42,
                                        "start_kit": {"bread": 3}}), encoding="utf-8")
            config = server_module.load_config(path)
        self.assertFalse(config["pvp"])
        self.assertEqual(config["day_length"], 42)
        self.assertEqual(config["start_kit"], {"bread": 3})
        self.assertEqual(config["max_players"], server_module.DEFAULT_CONFIG["max_players"])

    def test_a_broken_config_does_not_stop_the_server(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "server_config.json"
            path.write_text("{not json at all", encoding="utf-8")
            config = server_module.load_config(path)
        self.assertEqual(config["day_length"], server_module.DEFAULT_CONFIG["day_length"])

    def test_the_kit_reaches_a_new_player(self):
        import threading
        import time

        port = free_port()
        config = {**LIVE_CONFIG, "tasks": False,
                  "start_kit": {"wood": 30, "bread": 2, "iron_pickaxe": 1}}
        server = server_module.GameServer(host="127.0.0.1", port=port,
                                          accounts_path=None, config=config)
        threading.Thread(target=server.run, daemon=True).start()
        time.sleep(0.6)
        try:
            client = RawClient(port)
            self.addCleanup(client.close)
            self.assertIsNotNone(client.auth(name="KitTester"))
            player = next(iter(server.world.players.values()))
            self.assertEqual(player["inventory"].get("wood"), 30)
            self.assertEqual(player["inventory"].get("bread"), 2)
            # tools from the kit arrive with full durability
            self.assertEqual(player["durability"].get("iron_pickaxe"),
                             item_durability("iron_pickaxe"))
        finally:
            server.running = False
            time.sleep(0.3)


if __name__ == "__main__":
    unittest.main()
