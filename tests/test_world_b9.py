"""b9 «living world»: water and fishing, caves, weather, packs, diplomacy, trade."""

import os
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server import server as server_module
from server.world_state import (ANIMAL_TYPES, CAVE, TILE_SIZE, WATER, WorldState)
from shared.items import item_durability

from tests.helpers import RawClient, free_port

LIVE_CONFIG = {
    **server_module.DEFAULT_CONFIG,
    "day_length": 100000,
    "animal_respawn": 9999,
    "start_kit": {},
}


class WorldGenTest(unittest.TestCase):
    """The generated world has water, caves and ore inside them."""

    @classmethod
    def setUpClass(cls):
        cls.world = WorldState()

    def test_water_and_caves_exist(self):
        counts = {}
        for row in self.world.terrain:
            for tile in row:
                counts[tile] = counts.get(tile, 0) + 1
        self.assertGreater(counts.get(WATER, 0), 50, "no water on the map")
        self.assertGreater(counts.get(CAVE, 0), 100, "no caves on the map")

    def test_terrain_string_round_trips(self):
        text = self.world.terrain_string()
        self.assertEqual(len(text), self.world.width * self.world.height)
        self.assertIn("2", text)          # water
        self.assertIn("3", text)          # cave floor
        restored = WorldState()
        self.assertTrue(restored.load_terrain(text, [self.world.width, self.world.height]))
        self.assertEqual(restored.terrain, self.world.terrain)

    def test_water_is_walkable_but_a_bridge_is_faster(self):
        """b11: you may wade into the water (slowly) instead of being stuck at
        the shore; a bridge over it stays the quick way across, and rock is the
        only ground that always blocks."""
        water = sorted(self.world.water_tiles)[0]
        self.assertTrue(self.world.passable(*water),
                        "since b11 a player can wade into the water")
        self.assertTrue(self.world.tile_allows_building(*water, "bridge"))
        self.assertFalse(self.world.tile_allows_building(*water, "wall"))
        wade = self.world.move_factor(water[0] * TILE_SIZE + 16, water[1] * TILE_SIZE + 16)
        self.assertLess(wade, 1.0)
        key = self.world.place_building(water[0], water[1], "bridge", "0", 1, 1)
        try:
            planks = self.world.move_factor(water[0] * TILE_SIZE + 16,
                                            water[1] * TILE_SIZE + 16)
            self.assertGreater(planks, wade, "planks must beat wading")
            self.assertTrue(self.world.passable(*water))
        finally:
            self.world.buildings.pop(key, None)
            self.world.tile_building.clear()

    def test_swimming_can_be_switched_off(self):
        """The old b9 rule is one config key away (`swim: false`)."""
        water = sorted(self.world.water_tiles)[0]
        self.world.swim = False
        try:
            self.assertFalse(self.world.passable(*water))
        finally:
            self.world.swim = True
        self.assertTrue(self.world.passable(*water))

    def test_caves_are_rich_but_surface_stays_clean(self):
        inside, outside = {}, {}
        for res in self.world.resources.values():
            gx, gy = res["x"] // TILE_SIZE, res["y"] // TILE_SIZE
            bucket = inside if self.world.is_cave(gx, gy) else outside
            bucket[res["type"]] = bucket.get(res["type"], 0) + 1
        self.assertGreater(inside.get("mushroom", 0), 10, "caves grow no mushrooms")
        self.assertGreater(inside.get("iron_ore", 0), 10, "caves hold no iron")
        self.assertNotIn("tree", inside, "trees must not grow inside caves")
        self.assertNotIn("mushroom", outside, "mushrooms only grow in caves")

    def test_cave_tiles_are_never_water_or_rock(self):
        for gx, gy in self.world.cave_tiles:
            self.assertIn(self.world.terrain[gy][gx], (CAVE,))

    def test_world_still_has_every_animal_kind(self):
        kinds = {a["type"] for a in self.world.animals.values()}
        self.assertTrue({"sheep", "cow", "chicken", "wolf", "bear"} <= kinds, kinds)

    def test_wolves_spawn_in_packs(self):
        packs = [a.get("pack") for a in self.world.animals.values() if a["type"] == "wolf"]
        self.assertTrue(packs)
        self.assertTrue(all(packs), "every wolf should belong to a pack")
        biggest = max(packs.count(pack) for pack in set(packs))
        self.assertGreaterEqual(biggest, 2, "wolves should arrive in groups")

    def test_bears_live_in_the_dark(self):
        bears = [a for a in self.world.animals.values() if a["type"] == "bear"]
        self.assertTrue(bears, "the world has no bears")
        in_cave = [b for b in bears
                   if self.world.is_cave(b["x"] // TILE_SIZE, b["y"] // TILE_SIZE)]
        self.assertTrue(in_cave, "bears should spawn in caves")
        self.assertGreater(ANIMAL_TYPES["bear"]["damage"], ANIMAL_TYPES["wolf"]["damage"])


class B9ServerTest(unittest.TestCase):
    """One real server with the b9 systems switched on."""

    @classmethod
    def setUpClass(cls):
        cls.port = free_port()
        cls.server = server_module.GameServer(
            host="127.0.0.1", port=cls.port, accounts_path=None,
            config={**LIVE_CONFIG, "tasks": False, "animals": False})
        threading.Thread(target=cls.server.run, daemon=True).start()
        time.sleep(0.6)

    @classmethod
    def tearDownClass(cls):
        cls.server.running = False
        time.sleep(0.3)

    def setUp(self):
        self.client = RawClient(self.port)
        welcome = self.client.auth(name="Fisher")
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
            world.trades.clear()
            world.pending_payments.clear()
            world.touch("buildings", "civs", "trades")

    def give(self, **items):
        self.player["inventory"].update(items)

    def send(self, message, seconds=0.5):
        self.client.clear()
        self.client.send(message)
        return self.client.poll(seconds)

    def keys(self, message, seconds=0.5):
        return [m.get("key") for m in self.send(message, seconds)
                if m.get("type") == "notification"]

    def put_on_water_edge(self):
        """Stand next to a water tile and return its coordinates."""
        water = sorted(self.server.world.water_tiles)[0]
        # find a walkable neighbour of that water tile
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            gx, gy = water[0] + dx, water[1] + dy
            if self.server.world.passable(gx, gy) and \
                    not self.server.world.is_water(gx, gy):
                self.player["x"] = gx * TILE_SIZE + TILE_SIZE / 2
                self.player["y"] = gy * TILE_SIZE + TILE_SIZE / 2
                self.server.world.touch_inventory(self.pid)
                return water
        self.skipTest("no shore found next to the first water tile")
        return None

    def clear_around(self, x, y, radius=70):
        """Remove nodes so a test knows exactly which one it is gathering."""
        with self.server.world.lock:
            for key, res in list(self.server.world.resources.items()):
                if ((res["x"] - x) ** 2 + (res["y"] - y) ** 2) ** 0.5 <= radius:
                    del self.server.world.resources[key]
            self.server.world.touch("resources")

    def put_in_cave(self):
        cave = sorted(self.server.world.cave_tiles)[0]
        x, y = cave[0] * TILE_SIZE + 8, cave[1] * TILE_SIZE + 8
        self.clear_around(x, y)
        self.server.world.resources[f"{x},{y}"] = {"x": x, "y": y, "type": "iron_ore"}
        self.server.world.touch("resources")
        self.player["x"] = cave[0] * TILE_SIZE + 8
        self.player["y"] = cave[1] * TILE_SIZE + 8
        self.server.world.touch_inventory(self.pid)
        return cave

    # ---------------------------------------------------------------- fishing
    def test_fishing_needs_a_rod(self):
        self.put_on_water_edge()
        self.assertIn("notify.need_rod", self.keys({"type": "fish"}))

    def test_fishing_needs_water(self):
        # far from any lake, in the middle of a big grass patch
        self.give(fishing_rod=1)
        self.player["x"], self.player["y"] = self._dry_spot()
        self.server.world.touch_inventory(self.pid)
        self.assertIn("notify.no_water", self.keys({"type": "fish"}))

    def _dry_spot(self):
        world = self.server.world
        for gy in range(5, world.height - 5):
            for gx in range(5, world.width - 5):
                if world.is_blocked_tile(gx, gy) or world.is_cave(gx, gy):
                    continue
                if any(world.is_water(gx + dx, gy + dy)
                       for dx in range(-3, 4) for dy in range(-3, 4)):
                    continue
                return gx * TILE_SIZE + 16, gy * TILE_SIZE + 16
        self.skipTest("the whole map has water in reach")
        return 0, 0

    def test_fishing_catches_fish_and_wears_the_rod(self):
        self.put_on_water_edge()
        self.give(fishing_rod=1)
        self.player["durability"]["fishing_rod"] = item_durability("fishing_rod")
        messages = self.send({"type": "fish"}, 0.6)
        keys = [m.get("key") for m in messages if m.get("type") == "notification"]
        self.assertIn("notify.fish_caught", keys)
        self.assertGreaterEqual(self.player["inventory"].get("fish", 0), 1)
        self.assertEqual(self.player["durability"]["fishing_rod"],
                         item_durability("fishing_rod") - 1)

    def test_fishing_has_a_cooldown(self):
        self.put_on_water_edge()
        self.give(fishing_rod=1)
        self.send({"type": "fish"}, 0.4)
        self.assertIn("notify.fishing_wait", self.keys({"type": "fish"}, 0.4))

    def test_fish_can_be_cooked(self):
        from shared.items import SMELTING_RECIPES
        self.assertEqual(SMELTING_RECIPES["cook_fish"]["output"], "cooked_fish")

    # ------------------------------------------------------------------ caves
    def test_gathering_in_a_cave_pays_double(self):
        self.player["inventory"].pop("iron_ore", None)
        self.put_in_cave()
        self.client.clear()
        self.client.send({"type": "gather"})
        self.client.poll(0.5)
        self.assertGreaterEqual(self.player["inventory"].get("iron_ore", 0), 2)
        keys = [m.get("key") for m in self.client.inbox
                if m.get("type") == "notification"]
        self.assertIn("notify.cave_bonus", keys)

    def test_surface_gathering_stays_normal(self):
        world = self.server.world
        for gy in range(3, world.height - 3):
            for gx in range(3, world.width - 3):
                if world.is_blocked_tile(gx, gy) or world.is_cave(gx, gy):
                    continue
                x, y = gx * TILE_SIZE + 8, gy * TILE_SIZE + 8
                self.clear_around(x, y)
                world.resources[f"{x},{y}"] = {"x": x, "y": y, "type": "rock"}
                self.player["x"] = self.player["y"] = 0
                self.player["x"], self.player["y"] = x, y
                self.player["inventory"].pop("stone", None)
                world.touch("resources")
                self.send({"type": "gather"}, 0.4)
                self.assertEqual(self.player["inventory"].get("stone", 0), 1)
                return
        self.skipTest("no free grass tile found")

    # ---------------------------------------------------------------- weather
    def _open_spot(self):
        """A free tile with free tiles to the east (for walking tests)."""
        world = self.server.world
        for gy in range(5, world.height - 5):
            for gx in range(5, world.width - 12):
                if all(world.passable(gx + dx, gy) for dx in range(12)):
                    return (gx + 1) * TILE_SIZE + 4, gy * TILE_SIZE + 4
        self.skipTest("no open stretch of land found")
        return 0, 0

    def test_rain_slows_walking_down(self):
        world = self.server.world
        start_x, start_y = self._open_spot()
        self.server.weather = "clear"
        self.player["x"], self.player["y"] = start_x, start_y
        world.touch_inventory(self.pid)
        for _ in range(4):
            self.client.send({"type": "move", "dx": 12, "dy": 0})
        self.client.poll(0.3)
        dry = self.player["x"]
        self.player["x"], self.player["y"] = start_x, start_y
        self.server.weather = "rain"
        for _ in range(4):
            self.client.send({"type": "move", "dx": 12, "dy": 0})
        self.client.poll(0.3)
        wet = self.player["x"]
        self.server.weather = "clear"
        self.assertLess(wet, dry, f"rain {wet} should be slower than {dry}")

    def test_fog_dims_the_lights(self):
        world = self.server.world
        world.place_building(20, 20, "torch", self.pid, 1, 1)
        world.touch("buildings")
        self.server.weather = "clear"
        clear = self.server.light_sources()
        self.server.weather = "fog"
        foggy = self.server.light_sources()
        self.server.weather = "clear"
        self.assertTrue(clear and foggy)
        self.assertLess(foggy[0][2], clear[0][2])

    def test_rain_speeds_the_farms_up(self):
        self.server.weather = "clear"
        slow = self.server.farm_growth_seconds()
        self.server.weather = "rain"
        fast = self.server.farm_growth_seconds()
        self.server.weather = "clear"
        self.assertLess(fast, slow)


class DiplomacyTest(unittest.TestCase):
    """Two countries: peace by default, war by declaration, allies protected."""

    @classmethod
    def setUpClass(cls):
        cls.port = free_port()
        cls.server = server_module.GameServer(
            host="127.0.0.1", port=cls.port, accounts_path=None,
            config={**LIVE_CONFIG, "tasks": False, "animals": False,
                    "durability": False, "hunger_rate": 0.0})
        threading.Thread(target=cls.server.run, daemon=True).start()
        time.sleep(0.6)

    @classmethod
    def tearDownClass(cls):
        cls.server.running = False
        time.sleep(0.3)

    def setUp(self):
        self.alpha = RawClient(self.port)
        self.beta = RawClient(self.port)
        self.id_a = self.alpha.auth(name="Alpha")["id"]
        self.id_b = self.beta.auth(name="Beta")["id"]
        self.player_a = self.server.world.players[self.id_a]
        self.player_b = self.server.world.players[self.id_b]
        self.addCleanup(self.alpha.close)
        self.addCleanup(self.beta.close)
        self.addCleanup(self._cleanup)
        self._found_countries()

    def _cleanup(self):
        from server.civilization import CivManager
        world = self.server.world
        with world.lock:
            world.players.pop(self.id_a, None)
            world.players.pop(self.id_b, None)
            world.buildings.clear()
            world.occupied.clear()
            world.tile_building.clear()
            world.civs = CivManager()
            world.touch("buildings", "civs")

    def _found_countries(self):
        for client, name in ((self.alpha, "Alphaland"), (self.beta, "Betaland")):
            client.clear()
            client.send({"type": "create_city", "name": f"{name} City"})
            client.poll(0.3)
            client.send({"type": "create_country", "name": name})
            client.poll(0.3)

    def stand_apart(self, distance=24):
        self.player_a["x"], self.player_a["y"] = 1000, 1000
        self.player_b["x"], self.player_b["y"] = 1000 + distance, 1000
        self.server.world.touch_inventory(self.id_a)

    def hit(self, client, keys=0.5):
        client.clear()
        client.send({"type": "attack", "target_id": self.id_b})
        return [m.get("key") for m in client.poll(keys)
                if m.get("type") == "notification"]

    def test_peace_blocks_player_damage(self):
        self.stand_apart()
        self.player_b["hp"] = 100
        keys = self.hit(self.alpha)
        self.assertIn("notify.at_peace", keys)
        self.assertEqual(self.player_b["hp"], 100)

    def test_war_opens_the_fight(self):
        self.stand_apart()
        keys = self.send_diplomacy(self.alpha, "war")
        self.assertIn("notify.declared_war", keys)
        self.player_b["hp"] = 100
        notes = self.hit(self.alpha)
        self.assertNotIn("notify.at_peace", notes)
        self.assertLess(self.player_b["hp"], 100)

    def send_diplomacy(self, client, action, target=None):
        client.clear()
        client.send({"type": "diplomacy", "action": action, "target": target or "Betaland"})
        return [m.get("key") for m in client.poll(0.5)
                if m.get("type") == "notification"]

    def test_peace_can_be_made_again(self):
        self.send_diplomacy(self.alpha, "war")
        keys = self.send_diplomacy(self.alpha, "peace")
        self.assertIn("notify.made_peace", keys)
        self.stand_apart()
        self.player_b["hp"] = 100
        self.assertIn("notify.at_peace", self.hit(self.alpha))

    def test_allies_cannot_hurt_each_other(self):
        self.send_diplomacy(self.alpha, "ally")
        self.send_diplomacy(self.beta, "ally")
        self.stand_apart()
        self.player_b["hp"] = 100
        self.assertIn("notify.at_peace", self.hit(self.alpha))

    def test_peace_protects_buildings_too(self):
        key = self.server.world.place_building(31, 30, "wall", self.id_b, 1, 1)
        self.player_a["x"], self.player_a["y"] = 31 * TILE_SIZE + 8, 31 * TILE_SIZE
        self.alpha.clear()
        self.alpha.send({"type": "attack_building", "x": 31, "y": 30})
        keys = [m.get("key") for m in self.alpha.poll(0.5)
                if m.get("type") == "notification"]
        self.assertIn("notify.at_peace", keys)
        self.assertIn(key, self.server.world.buildings)
        # after a war declaration the same hit lands
        self.send_diplomacy(self.alpha, "war")
        self.alpha.clear()
        self.alpha.send({"type": "attack_building", "x": 31, "y": 30})
        self.alpha.poll(0.5)
        self.assertLess(self.server.world.buildings[key]["hp"],
                        self.server.world.buildings[key]["max_hp"])

    def test_players_without_countries_are_not_restricted(self):
        stranger = RawClient(self.port)
        try:
            stranger_id = stranger.auth(name="Nomad")["id"]
            nomad = self.server.world.players[stranger_id]
            nomad["x"], nomad["y"] = 2000, 2000
            self.player_a["x"], self.player_a["y"] = 2024, 2000
            stranger.clear()
            self.server.on_attack_or_nothing = True
            self.alpha.clear()
            self.alpha.send({"type": "attack", "target_id": stranger_id})
            keys = [m.get("key") for m in self.alpha.poll(0.5)
                    if m.get("type") == "notification"]
            self.assertNotIn("notify.at_peace", keys)
            self.assertLess(nomad["hp"], 100)
        finally:
            stranger.close()

    def test_diplomacy_needs_the_country_leader(self):
        outsider = RawClient(self.port)
        try:
            outsider.auth(name="Outsider")
            outsider.clear()
            outsider.send({"type": "diplomacy", "action": "war", "target": "Betaland"})
            keys = [m.get("key") for m in outsider.poll(0.5)
                    if m.get("type") == "notification"]
            self.assertIn("notify.only_country_leader", keys)
        finally:
            outsider.close()

    def test_relations_are_saved(self):
        self.send_diplomacy(self.alpha, "war")
        data = self.server.world.civs.to_save()
        self.assertIn("Betaland", data["countries"]["Alphaland"]["wars"])
        restored = type(self.server.world.civs)()
        restored.load_save(data)
        self.assertTrue(restored.countries["Alphaland"].wars)


class TradeTest(unittest.TestCase):
    """Market offers: goods are held by the market until somebody pays."""

    @classmethod
    def setUpClass(cls):
        cls.port = free_port()
        cls.server = server_module.GameServer(
            host="127.0.0.1", port=cls.port, accounts_path=None,
            config={**LIVE_CONFIG, "tasks": False, "animals": False,
                    "durability": False, "hunger_rate": 0.0})
        threading.Thread(target=cls.server.run, daemon=True).start()
        time.sleep(0.6)

    @classmethod
    def tearDownClass(cls):
        cls.server.running = False
        time.sleep(0.3)

    def setUp(self):
        self.seller = RawClient(self.port)
        self.buyer = RawClient(self.port)
        self.seller_id = self.seller.auth(name="Seller")["id"]
        self.buyer_id = self.buyer.auth(name="Buyer")["id"]
        self.addCleanup(self.seller.close)
        self.addCleanup(self.buyer.close)
        self.addCleanup(self._cleanup)
        # a market for each of them, and goods to trade
        self.market_key = self.server.world.place_building(40, 40, "market",
                                                           self.seller_id, 2, 2)
        self.player(self.seller_id)["x"] = 40 * TILE_SIZE + 16
        self.player(self.seller_id)["y"] = 40 * TILE_SIZE + 16
        self.player(self.buyer_id)["x"] = 41 * TILE_SIZE + 16
        self.player(self.buyer_id)["y"] = 41 * TILE_SIZE + 16
        self.player(self.seller_id)["inventory"] = {"wood": 20, "stone": 5}
        self.player(self.buyer_id)["inventory"] = {"iron_ingot": 4}
        self.server.world.touch("buildings")
        self.server.world.touch_inventory(self.seller_id)
        self.server.world.touch_inventory(self.buyer_id)

    def _cleanup(self):
        from server.civilization import CivManager
        world = self.server.world
        with world.lock:
            world.players.pop(self.seller_id, None)
            world.players.pop(self.buyer_id, None)
            world.buildings.clear()
            world.occupied.clear()
            world.tile_building.clear()
            world.civs = CivManager()
            world.trades.clear()
            world.pending_payments.clear()
            world.touch("buildings", "civs", "trades")

    def player(self, pid):
        return self.server.world.players[pid]

    def send(self, client, message, seconds=0.5):
        client.clear()
        client.send(message)
        return client.poll(seconds)

    def post(self, give="wood", give_count=10, want="iron_ingot", want_count=2):
        self.send(self.seller, {"type": "trade_post", "give_item": give,
                                "give_count": give_count, "want_item": want,
                                "want_count": want_count})
        offers = self.server.world.trade_payload()
        self.assertTrue(offers, "the offer was not created")
        return offers[-1]["id"]

    def test_market_is_required(self):
        far = self.player(self.buyer_id)
        far["x"], far["y"] = 5 * TILE_SIZE, 5 * TILE_SIZE
        keys = [m.get("key") for m in
                self.send(self.buyer, {"type": "trade_post", "give_item": "iron_ingot",
                                       "give_count": 1, "want_item": "wood",
                                       "want_count": 1})
                if m.get("type") == "notification"]
        self.assertIn("notify.no_market", keys)

    def test_posting_holds_the_goods(self):
        trade_id = self.post(give_count=10)
        self.assertEqual(self.player(self.seller_id)["inventory"]["wood"], 10)
        offer = self.server.world.trades[trade_id]
        self.assertEqual(offer["give_count"], 10)
        self.assertEqual(offer["want_item"], "iron_ingot")

    def test_posting_more_than_you_have_is_refused(self):
        keys = [m.get("key") for m in
                self.send(self.seller, {"type": "trade_post", "give_item": "wood",
                                        "give_count": 999, "want_item": "iron_ingot",
                                        "want_count": 1})
                if m.get("type") == "notification"]
        self.assertIn("notify.trade_need", keys)
        self.assertEqual(self.player(self.seller_id)["inventory"]["wood"], 20)

    def test_buying_swaps_the_goods(self):
        trade_id = self.post()
        messages = self.send(self.buyer, {"type": "trade_take", "id": trade_id})
        keys = [m.get("key") for m in messages if m.get("type") == "notification"]
        self.assertIn("notify.trade_done", keys)
        self.assertEqual(self.player(self.buyer_id)["inventory"]["wood"], 10)
        self.assertEqual(self.player(self.buyer_id)["inventory"].get("iron_ingot"), 2)
        # the seller is online, so the payment goes straight into the bag
        self.assertEqual(self.player(self.seller_id)["inventory"].get("iron_ingot"), 2)
        self.assertEqual(self.server.world.trades, {})

    def test_buying_without_the_goods_is_refused(self):
        trade_id = self.post(want="gold_ingot", want_count=3)
        keys = [m.get("key") for m in
                self.send(self.buyer, {"type": "trade_take", "id": trade_id})
                if m.get("type") == "notification"]
        self.assertIn("notify.trade_need", keys)
        self.assertIn(trade_id, self.server.world.trades)

    def test_you_cannot_buy_your_own_offer(self):
        trade_id = self.post()
        keys = [m.get("key") for m in
                self.send(self.seller, {"type": "trade_take", "id": trade_id})
                if m.get("type") == "notification"]
        self.assertIn("notify.trade_own", keys)

    def test_cancelling_returns_the_goods(self):
        trade_id = self.post(give_count=7)
        keys = [m.get("key") for m in
                self.send(self.seller, {"type": "trade_cancel", "id": trade_id})
                if m.get("type") == "notification"]
        self.assertIn("notify.trade_cancelled", keys)
        self.assertEqual(self.player(self.seller_id)["inventory"]["wood"], 20)
        self.assertEqual(self.server.world.trades, {})

    def test_payment_waits_for_an_offline_seller(self):
        # a seller who leads a city but is not connected any more
        self.seller.send({"type": "create_city", "name": "Sellville"})
        self.seller.poll(0.4)
        trade_id = self.post(give_count=5, want="iron_ingot", want_count=1)
        self.player(self.seller_id)["inventory"]["wood"] = 0
        self.seller.close()                     # the seller logs off
        for _ in range(40):
            if self.seller_id not in self.server.world.players:
                break
            time.sleep(0.1)
        self.assertNotIn(self.seller_id, self.server.world.players,
                         "the seller should be gone from the world")
        self.send(self.buyer, {"type": "trade_take", "id": trade_id})
        # the city storage took the payment because the leader is offline
        with self.server.world.lock:
            city = self.server.world.civs.cities.get("Sellville")
            stored = dict(city.storage) if city else {}
        self.assertEqual(stored.get("iron_ingot"), 1)

    def test_the_offer_list_reaches_the_client(self):
        self.post()
        messages = self.send(self.buyer, {"type": "ping", "t": 1}, 0.6)
        states = [m for m in messages if m.get("type") == "state" and "trades" in m]
        self.assertTrue(states, "the state packet should carry the offers")

    def test_trade_offers_are_listed_in_chat(self):
        self.post()
        messages = [m for m in self.send(self.buyer, {"type": "chat", "text": "/trade"})
                    if m.get("type") == "chat"]
        self.assertTrue(any("wood" in m.get("msg", "") for m in messages),
                        [m.get("msg") for m in messages])


if __name__ == "__main__":
    unittest.main()
