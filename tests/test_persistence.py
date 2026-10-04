"""World saving / loading tests.

Covers the on-disk format, the restart flow (server A saves, server B restores)
and the "your progress comes back when you rejoin with the same name" rule.
"""
import json
import os
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server import server as server_module
from server.persistence import SAVE_VERSION, WorldStore
from server.world_state import WorldState, TILE_SIZE

from tests.helpers import RawClient, free_port


def make_world():
    world = WorldState()
    world.add_player("0", "Alice")
    world.add_player("1", "Bob")
    world.players["0"]["inventory"] = {"wood": 42, "iron_ingot": 7}
    world.place_building(10, 10, "town_center", "0", 2, 2)
    world.place_building(12, 10, "furnace", "1", 1, 1)
    world.civs.create_city("Rome", "0", 100, 200)
    world.civs.join_city("Rome", "1")
    world.civs.create_country("Italy", "0")
    world.civs.join_country("Rome", "Italy", "0")
    world.civs.cities["Rome"].tier = 2
    world.civs.countries["Italy"].techs.append("industrialization")
    world.resources = {"100,100": {"x": 100, "y": 100, "type": "tree"}}
    return world


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "world.json")

    def tearDown(self):
        self.tmp.cleanup()

    def test_round_trip(self):
        world = make_world()
        store = WorldStore(self.path)
        self.assertTrue(store.save(world))
        self.assertTrue(os.path.exists(self.path))

        restored = WorldState()
        self.assertTrue(store.load(restored))

        self.assertEqual(restored.terrain_string(), world.terrain_string())
        self.assertEqual(restored.resources, world.resources)
        self.assertEqual(set(restored.buildings), {"10,10", "12,10"})
        self.assertEqual(restored.buildings["10,10"]["type"], "town_center")
        self.assertEqual(restored.occupied, world.occupied)
        self.assertEqual(restored.civs.cities["Rome"].tier, 2)
        self.assertEqual(restored.civs.cities["Rome"].members, ["0", "1"])
        self.assertEqual(restored.civs.countries["Italy"].techs, ["industrialization"])
        self.assertIs(restored.civs.countries["Italy"].cities[0], restored.civs.cities["Rome"])
        self.assertEqual(restored.saved_players["Alice"]["inventory"]["wood"], 42)
        # occupancy is rebuilt, so the restored world blocks movement again
        self.assertIn("11,11", restored.tile_building)

    def test_save_file_is_valid_json_with_version(self):
        store = WorldStore(self.path)
        store.save(make_world())
        payload = json.loads(open(self.path, encoding="utf-8").read())
        self.assertEqual(payload["save_version"], SAVE_VERSION)
        self.assertIn("saved_at", payload)
        self.assertIn("terrain", payload)

    def test_no_save_path_disables_persistence(self):
        store = WorldStore(None)
        self.assertFalse(store.save(make_world()))
        self.assertFalse(store.load(WorldState()))

    def test_missing_file_is_not_an_error(self):
        self.assertFalse(WorldStore(self.path).load(WorldState()))

    def test_corrupted_file_does_not_crash_the_server(self):
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write("{not json at all")
        world = WorldState()
        before = world.terrain_string()
        self.assertFalse(WorldStore(self.path).load(world))
        self.assertEqual(world.terrain_string(), before)      # fresh world kept

    def test_newer_save_version_is_ignored(self):
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump({"save_version": SAVE_VERSION + 1, "terrain": "0"}, handle)
        self.assertFalse(WorldStore(self.path).load(WorldState()))


class ServerPersistenceTest(unittest.TestCase):
    """Restart flow: server A saves, server B continues from the same file."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "world.json")

    def tearDown(self):
        self.tmp.cleanup()

    def _start(self, port, accounts_path=None):
        server = server_module.GameServer(host="127.0.0.1", port=port, save_path=self.path,
                                          accounts_path=accounts_path)
        threading.Thread(target=server.run, daemon=True).start()
        time.sleep(0.6)
        return server

    def test_world_survives_a_restart(self):
        port = free_port()
        server = self._start(port)
        server.world.add_player("0", "Alice")
        server.world.players["0"]["inventory"]["wood"] = 25
        server.world.place_building(30, 30, "crafting_table", "0", 1, 1)
        server.world.civs.create_city("Krakow", "0", 500, 500)
        server.world.touch("civs")
        self.assertTrue(server.save_world(quiet=True))
        server.running = False
        time.sleep(0.2)

        port2 = free_port()
        server2 = self._start(port2)
        try:
            self.assertTrue(server2.loaded_save)
            self.assertIn("30,30", server2.world.buildings)
            self.assertIn("Krakow", server2.world.civs.cities)
            self.assertEqual(
                server2.world.saved_players.get("Alice", {}).get("inventory", {}).get("wood"), 25)
        finally:
            server2.running = False
            time.sleep(0.2)

    def test_account_progress_survives_a_restart(self):
        """Accounts are the way progress survives now (see tests/test_accounts.py)."""
        accounts_path = os.path.join(self.tmp.name, "accounts.json")
        port = free_port()
        server = self._start(port, accounts_path=accounts_path)
        client = RawClient(port)
        client.poll(0.4)
        client.send({"type": "register", "username": "Alice", "password": "hunter2"})
        client.poll(0.8)
        welcome = next(m for m in client.inbox if m.get("type") == "welcome")
        player = server.world.players[welcome["id"]]
        player["inventory"]["gold_ingot"] = 99
        player["x"], player["y"] = 1234, 567
        self.assertTrue(server.save_world(quiet=True))
        client.close()
        time.sleep(0.5)
        server.running = False
        time.sleep(0.2)

        server2 = self._start(free_port(), accounts_path=accounts_path)
        client2 = RawClient(server2.port)
        client2.poll(0.4)
        client2.inbox.clear()
        client2.send({"type": "login", "username": "Alice", "password": "hunter2"})
        messages = client2.poll(0.8)
        try:
            keys = [m.get("key") for m in messages if m.get("type") == "notification"]
            self.assertIn("auth.welcome_back", keys)
            new_id = next(pid for pid in server2.world.players
                          if server2.world.players[pid]["name"] == "Alice")
            player = server2.world.players[new_id]
            self.assertEqual(player["inventory"].get("gold_ingot"), 99)
            self.assertEqual((player["x"], player["y"]), (1234, 567))
        finally:
            client2.close()
            server2.running = False
            time.sleep(0.2)

    def test_save_chat_command_writes_the_file(self):
        port = free_port()
        server = self._start(port)
        client = RawClient(port)
        client.auth(name="Saver")
        client.clear()
        self.assertFalse(os.path.exists(self.path))
        client.send({"type": "chat", "text": "/save"})
        messages = client.poll(0.6)
        try:
            self.assertTrue(os.path.exists(self.path))
            keys = [m.get("key") for m in messages if m.get("type") == "notification"]
            self.assertIn("notify.saved", keys)
        finally:
            client.close()
            server.running = False
            time.sleep(0.2)

    def test_wipe_command_clears_progress_and_buildings(self):
        port = free_port()
        server = self._start(port)
        server.world.place_building(40, 40, "wall", "0", 1, 1)
        server.world.saved_players["Ghost"] = {"x": 1, "y": 1, "inventory": {"wood": 5}}
        client = RawClient(port)
        client.auth(name="Wiper")
        client.clear()
        client.send({"type": "chat", "text": "/wipe"})
        messages = client.poll(0.8)
        try:
            self.assertEqual(server.world.buildings, {})
            self.assertEqual(server.world.saved_players, {})
            self.assertEqual(server.world.occupied, set())
            keys = [m.get("key") for m in messages if m.get("type") == "notification"]
            self.assertIn("notify.world_wiped", keys)
        finally:
            client.close()
            server.running = False
            time.sleep(0.2)

    def test_no_save_flag_writes_nothing(self):
        port = free_port()
        server = server_module.GameServer(host="127.0.0.1", port=port, save_path=None,
                                          accounts_path=None)
        self.assertFalse(server.loaded_save)
        self.assertFalse(server.save_world(quiet=True))
        self.assertFalse(os.path.exists(self.path))

    def test_shutdown_keeps_online_players_in_the_save(self):
        """Players online during shutdown must still be written to the save."""
        port = free_port()
        server = self._start(port)
        client = RawClient(port)
        self.assertIsNotNone(client.auth(name="Keeper"))
        server.running = False                      # shutdown begins
        client.close()
        time.sleep(0.5)
        names = [p.get("name") for p in server.world.players.values()]
        self.assertIn("Keeper", names)

    def test_building_and_restoring_keeps_collision(self):
        """A restored town center must still block movement after a reload."""
        world = make_world()
        store = WorldStore(self.path)
        store.save(world)
        restored = WorldState()
        store.load(restored)
        restored.add_player("9", "Tester")
        # stand just right of the restored furnace (12,10) and walk into it
        restored.players["9"]["x"] = 13 * TILE_SIZE
        restored.players["9"]["y"] = 10 * TILE_SIZE
        self.assertFalse(restored.move_player("9", -TILE_SIZE, 0))
        self.assertTrue(restored.move_player("9", 0, TILE_SIZE))


if __name__ == "__main__":
    unittest.main()
