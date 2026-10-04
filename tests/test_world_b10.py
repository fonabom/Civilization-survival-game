"""b10 «Цивилизация»: roles, taxes and the city fund, sieges and the capture
of cities, victory, epochs, medicine and electricity.

The tests drive the real server over the real protocol, like the bots do.
"""

import os
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server import server as server_module
from server.civilization import CivManager
from server.world_state import TILE_SIZE
from shared.structures import STRUCTURES, get_cost, get_size
from shared.techs import TECHS, age_of

from tests.helpers import RawClient, free_port

LIVE_CONFIG = {
    **server_module.DEFAULT_CONFIG,
    "day_length": 100000,
    "animal_respawn": 9999,
    "start_kit": {},
    "tasks": False,
    "animals": False,
    "wolves": False,
    "hunger_rate": 0,
    "durability": False,
    "taxes": True,
    "victory": True,
}

CITY_X, CITY_Y = 1600, 1600            # where the test cities are founded
CITY_TILE = (CITY_X // TILE_SIZE, CITY_Y // TILE_SIZE)


class B10BaseTest(unittest.TestCase):
    """One real server for the whole class, a clean world before every test."""

    @classmethod
    def setUpClass(cls):
        cls.port = free_port()
        cls.server = server_module.GameServer(
            host="127.0.0.1", port=cls.port, accounts_path=None,
            config=dict(LIVE_CONFIG))
        threading.Thread(target=cls.server.run, daemon=True).start()
        time.sleep(0.6)

    @classmethod
    def tearDownClass(cls):
        cls.server.running = False
        time.sleep(0.3)

    def setUp(self):
        self.clients = []
        self.addCleanup(self._reset)

    # ------------------------------------------------------------------ utils
    def join(self, name):
        """Connect a guest and return (client, player_id, player dict)."""
        client = RawClient(self.port)
        welcome = client.auth(name=name)
        self.assertIsNotNone(welcome, f"{name} could not log in")
        client.pid = welcome["id"]
        self.clients.append(client)
        return client, client.pid, self.server.world.players[client.pid]

    def place(self, player, x=CITY_X, y=CITY_Y):
        player["x"], player["y"] = float(x), float(y)

    def found_city(self, name, player_id, country=None, x=CITY_X, y=CITY_Y):
        """Create a city (and a country) - the map does not have to allow it."""
        with self.server.world.lock:
            civs = self.server.world.civs
            civs.create_city(name, player_id, x, y)
            if country:
                civs.create_country(country, player_id)
                civs.join_country(name, country, player_id)
            self.server.world.touch("civs")
        return self.server.world.civs.cities[name]

    def free_spot(self, px, py, structure, radius=6):
        """A tile near the player where the building really fits (water, rocks
        and neighbours make the plain map centre an unreliable choice)."""
        w, h = get_size(structure)
        gx0, gy0 = int(px // TILE_SIZE), int(py // TILE_SIZE)
        world = self.server.world
        for ring in range(0, radius + 1):
            for dx in range(-ring, ring + 1):
                for dy in range(-ring, ring + 1):
                    if max(abs(dx), abs(dy)) != ring:
                        continue
                    if world.can_place(gx0 + dx, gy0 + dy, w, h, structure):
                        return gx0 + dx, gy0 + dy
        self.fail(f"no free spot for {structure} next to {px},{py}")

    def build(self, client, player, structure, radius=6):
        """Try to build near the player; return the notification keys."""
        gx, gy = self.free_spot(player["x"], player["y"], structure, radius)
        self.clear_nodes(gx, gy)
        client.clear()
        client.send({"type": "build", "structure": structure, "x": gx, "y": gy})
        client.poll(0.5)
        return self.keys(client, 0.4)

    def send(self, client, message, seconds=0.5):
        client.clear()
        client.send(message)
        return client.poll(seconds)

    def keys(self, client, seconds=0.5):
        return [m.get("key") for m in client.poll(seconds)
                if m.get("type") == "notification"]

    def wait_for(self, predicate, timeout=4.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if predicate():
                return True
            time.sleep(0.05)
        return bool(predicate())

    def clear_nodes(self, gx, gy, radius=6):
        world = self.server.world
        with world.lock:
            for dx in range(-radius, radius + 1):
                for dy in range(-radius, radius + 1):
                    world.resources.pop(f"{gx + dx},{gy + dy}", None)
            world.touch("resources")

    def give_node(self, x, y, kind="tree"):
        world = self.server.world
        with world.lock:
            for key, res in list(world.resources.items()):
                if ((res["x"] - x) ** 2 + (res["y"] - y) ** 2) ** 0.5 <= 90:
                    del world.resources[key]
            world.resources[f"{x},{y}"] = {"x": x, "y": y, "type": kind}
            world.touch("resources")

    def gather(self, client, player, x, y, times=1):
        """Put a fresh node under the player's feet and gather it."""
        player["selected"] = "axe"                      # a tool gives more per swing
        player.setdefault("inventory", {})["axe"] = 1
        for _ in range(times):
            player["x"], player["y"] = float(x), float(y)
            self.clear_nodes(int(x // TILE_SIZE), int(y // TILE_SIZE))
            self.give_node(x, y)
            client.clear()
            client.send({"type": "gather"})
            client.poll(0.5)

    def _reset(self):
        """Undo everything a test did: world state and the victory flag."""
        world = self.server.world
        with world.lock:
            for client in self.clients:
                world.players.pop(getattr(client, "pid", None), None)
            world.buildings.clear()
            world.occupied.clear()
            world.tile_building.clear()
            world.civs = CivManager()
            world.trades.clear()
            world.pending_payments.clear()
            world.touch("buildings", "civs", "trades")
        self.server.victory = None
        self.server.tax_carry.clear()
        self.server.config["taxes"] = True
        self.server.config["victory"] = True
        for client in self.clients:
            client.close()


class RolesTest(B10BaseTest):
    """Who may build, store and research inside a city (b10)."""

    def setUp(self):
        super().setUp()
        self.leader, self.leader_id, self.leader_p = self.join("Leader")
        self.member, self.member_id, self.member_p = self.join("Member")
        self.stranger, self.stranger_id, self.stranger_p = self.join("Stranger")
        for player in (self.leader_p, self.member_p, self.stranger_p):
            self.place(player)
        self.city = self.found_city("Capita", self.leader_id)
        with self.server.world.lock:
            self.server.world.civs.join_city("Capita", self.member_id)
            self.server.world.touch("civs")

    def test_a_plain_member_cannot_build_in_the_city(self):
        self.assertFalse(self.server.territory_ok(self.member_id, CITY_X, CITY_Y))
        self.assertTrue(self.server.territory_ok(self.leader_id, CITY_X, CITY_Y))

    def test_a_stranger_cannot_build_in_a_foreign_city(self):
        self.assertFalse(self.server.territory_ok(self.stranger_id, CITY_X, CITY_Y))
        self.member_p["inventory"] = {"wood": 40, "stone": 40}
        keys = self.build(self.member, self.member_p, "crafting_table")
        self.assertIn("notify.build_fail_role", keys)

    def test_only_the_leader_hands_out_roles(self):
        self.send(self.member, {"type": "set_role", "target": "Member",
                                "role": "builder"})
        self.assertIn("notify.only_city_leader", self.keys(self.member))
        self.assertEqual(self.city.role_of(self.member_id), "citizen")

    def test_the_leader_can_promote_a_member(self):
        self.send(self.leader, {"type": "set_role", "target": "Member",
                                "role": "builder"})
        self.assertIn("notify.role_set", self.keys(self.leader))
        self.assertEqual(self.city.role_of(self.member_id), "builder")
        self.assertTrue(self.server.territory_ok(self.member_id, CITY_X, CITY_Y))
        self.assertIn("notify.role_given", self.keys(self.member))

    def test_roles_decide_what_a_member_may_do(self):
        self.assertFalse(self.city.may(self.member_id, "build"))
        self.assertFalse(self.city.may(self.member_id, "storage"))
        self.assertFalse(self.city.may(self.member_id, "research"))
        with self.server.world.lock:
            self.server.world.civs.set_role(self.city, self.member_id, "elder")
        self.assertTrue(self.city.may(self.member_id, "build"))
        self.assertTrue(self.city.may(self.member_id, "storage"))
        self.assertTrue(self.city.may(self.member_id, "research"))
        self.assertFalse(self.city.may(self.member_id, "manage"))
        self.assertTrue(self.city.may(self.leader_id, "manage"))

    def test_unknown_roles_are_refused(self):
        self.send(self.leader, {"type": "set_role", "target": "Member",
                                "role": "king"})
        self.assertIn("notify.role_unknown", self.keys(self.leader))

    def test_a_stranger_cannot_get_a_role(self):
        self.send(self.leader, {"type": "set_role", "target": "Stranger",
                                "role": "builder"})
        self.assertIn("notify.role_not_member", self.keys(self.leader))

    def test_a_member_keeps_his_normal_freedom(self):
        """Roles are about the city land: outside it a citizen is as free as ever."""
        self.assertTrue(self.server.territory_ok(self.member_id, CITY_X + 2000, CITY_Y))


class TaxAndFundTest(B10BaseTest):
    """The city fund: taxes on gathering and paying for the common buildings."""

    def setUp(self):
        super().setUp()
        self.leader, self.leader_id, self.leader_p = self.join("Leader")
        self.member, self.member_id, self.member_p = self.join("Member")
        self.place(self.leader_p)
        self.place(self.member_p)
        self.city = self.found_city("Capita", self.leader_id)
        with self.server.world.lock:
            self.server.world.civs.join_city("Capita", self.member_id)
            self.server.world.civs.set_role(self.city, self.member_id, "builder")
            self.server.world.touch("civs")

    def test_only_the_leader_sets_the_tax(self):
        self.send(self.member, {"type": "set_tax", "value": 20})
        self.assertIn("notify.only_city_leader", self.keys(self.member))
        self.send(self.leader, {"type": "set_tax", "value": 25})
        self.assertIn("notify.tax_set", self.keys(self.leader))
        self.assertEqual(self.city.tax, 25)

    def test_the_tax_is_capped(self):
        self.send(self.leader, {"type": "set_tax", "value": 900})
        self.keys(self.leader)
        self.assertEqual(self.city.tax, 40)

    def test_gathering_inside_the_city_pays_the_tax(self):
        with self.server.world.lock:
            self.server.world.civs.set_tax(self.city, 40)
        self.member.clear()
        self.gather(self.member, self.member_p, CITY_X + 60, CITY_Y + 60, times=3)
        self.wait_for(lambda: self.city.storage.get("wood", 0) > 0)
        self.assertIn("notify.tax_paid", self.keys(self.member))
        self.assertGreaterEqual(self.city.storage.get("wood", 0), 1)
        self.assertGreater(self.member_p["inventory"].get("wood", 0), 0)

    def test_gathering_outside_pays_nothing(self):
        with self.server.world.lock:
            self.server.world.civs.set_tax(self.city, 40)
        self.gather(self.member, self.member_p, CITY_X + 3000, CITY_Y, times=2)
        self.wait_for(lambda: self.member_p["inventory"].get("wood", 0) >= 2)
        self.assertEqual(self.city.storage.get("wood", 0), 0)
        self.assertNotIn("notify.tax_paid", self.keys(self.member))

    def test_the_server_can_switch_taxes_off(self):
        with self.server.world.lock:
            self.server.world.civs.set_tax(self.city, 40)
        self.server.config["taxes"] = False
        self.gather(self.member, self.member_p, CITY_X + 60, CITY_Y + 60, times=3)
        self.wait_for(lambda: self.member_p["inventory"].get("wood", 0) >= 2)
        self.assertEqual(self.city.storage.get("wood", 0), 0)

    def test_the_city_fund_pays_for_a_building(self):
        """A builder spends the city's money - that is what the tax is for."""
        with self.server.world.lock:
            self.city.storage = {"wood": 50, "stone": 20}
            self.server.world.touch("civs")
        self.member_p["inventory"] = {}
        keys = self.build(self.member, self.member_p, "crafting_table")
        self.assertIn("notify.built", keys)
        self.assertIn("notify.fund_used", keys)
        self.assertLess(self.city.storage.get("wood", 0), 50)
        self.assertEqual(self.member_p["inventory"].get("wood", 0), 0)

    def test_a_citizen_cannot_spend_the_fund(self):
        with self.server.world.lock:
            self.city.storage = {"wood": 50, "stone": 20}
            self.server.world.civs.set_role(self.city, self.member_id, "citizen")
        self.member_p["inventory"] = {"wood": 2, "stone": 3}
        keys = self.build(self.member, self.member_p, "crafting_table")
        self.assertIn("notify.build_fail_role", keys)
        self.assertEqual(self.city.storage.get("wood", 0), 50)
        self.assertEqual(self.member_p["inventory"].get("wood", 0), 2)


class SiegeTest(B10BaseTest):
    """Wars are about cities now: the town centre decides who owns the land."""

    def setUp(self):
        super().setUp()
        self.attacker, self.attacker_id, self.attacker_p = self.join("Attacker")
        self.defender, self.defender_id, self.defender_p = self.join("Defender")
        self.place(self.attacker_p)
        self.place(self.defender_p, CITY_X, CITY_Y)
        self.attacker_city = self.found_city("Aggressor", self.attacker_id,
                                             country="Horde",
                                             x=CITY_X + 1500, y=CITY_Y + 1500)
        self.city = self.found_city("Target", self.defender_id, country="Realm")
        gx, gy = CITY_TILE
        self.clear_nodes(gx, gy)
        self.center_key = self.server.world.place_building(
            gx, gy, "town_center", self.defender_id, 2, 2)
        self.attacker_p["x"] = gx * TILE_SIZE + TILE_SIZE
        self.attacker_p["y"] = gy * TILE_SIZE + 40

    def war(self):
        self.send(self.attacker, {"type": "diplomacy", "action": "war",
                                  "target": "Realm"}, 0.5)

    def hit(self, times=1):
        for _ in range(times):
            self.send(self.attacker, {"type": "attack_building",
                                      "x": CITY_TILE[0], "y": CITY_TILE[1]}, 0.3)

    def test_a_town_centre_is_safe_at_peace(self):
        self.hit()
        self.assertIn("notify.at_peace", self.keys(self.attacker))
        building = self.server.world.buildings[self.center_key]
        self.assertEqual(building["hp"], building["max_hp"])

    def test_at_war_the_city_is_warned_about_the_siege(self):
        self.war()
        self.defender.clear()
        self.hit()
        self.assertIn("notify.siege_hit", self.keys(self.attacker))
        self.assertIn("notify.under_siege", self.keys(self.defender))

    def test_destroying_the_town_centre_captures_the_city(self):
        # a second city keeps Realm alive, so we can watch the city change hands
        self.found_city("Far", self.defender_id, country="Realm",
                        x=CITY_X + 800, y=CITY_Y + 800)
        self.war()
        self.server.world.buildings[self.center_key]["hp"] = 1
        self.defender.clear()
        self.hit()
        self.wait_for(lambda: self.city.leader == self.attacker_id)
        self.assertEqual(self.city.leader, self.attacker_id)
        self.assertEqual(self.city.captured, 1)
        self.assertIn("notify.city_captured", self.keys(self.attacker))
        self.assertIn("notify.city_captured_news", self.keys(self.defender))
        countries = self.server.world.civs.countries
        self.assertIn(self.city, countries["Horde"].cities)
        self.assertNotIn(self.city, countries["Realm"].cities)

    def test_the_winner_loots_the_city_fund(self):
        self.war()
        with self.server.world.lock:
            self.city.storage["iron_ingot"] = 7
        self.server.world.buildings[self.center_key]["hp"] = 1
        self.hit()
        self.wait_for(lambda: self.attacker_p["inventory"].get("iron_ingot", 0) >= 7)
        self.assertEqual(self.attacker_p["inventory"].get("iron_ingot"), 7)
        self.assertEqual(self.city.storage.get("iron_ingot", 0), 0)

    def test_a_country_that_loses_its_last_city_is_gone(self):
        self.war()
        self.server.world.buildings[self.center_key]["hp"] = 1
        self.defender.clear()
        self.hit()
        self.wait_for(lambda: "Realm" not in self.server.world.civs.countries)
        self.assertNotIn("Realm", self.server.world.civs.countries)
        self.assertIn("notify.country_dissolved", self.keys(self.defender, 1.0))

    def test_the_defeated_leader_is_thrown_out_of_his_city(self):
        with self.server.world.lock:
            civs = self.server.world.civs
            civs.join_city("Target", "citizen-x")                 # an innocent citizen
            civs.set_role(self.city, "citizen-x", "elder")
            self.server.world.touch("civs")
        self.war()
        self.server.world.buildings[self.center_key]["hp"] = 1
        self.hit()
        self.wait_for(lambda: self.city.leader == self.attacker_id)
        self.assertNotIn(self.defender_id, self.city.members)
        self.assertFalse(self.server.territory_ok(self.defender_id, CITY_X, CITY_Y))
        # the new ruler appoints his own staff: the old posts are gone
        self.assertEqual(self.city.roles, {})
        self.assertFalse(self.city.may("citizen-x", "build"))

    def test_the_city_keeps_its_buildings(self):
        with self.server.world.lock:
            chest_key = self.server.world.place_building(CITY_TILE[0] + 3,
                                                         CITY_TILE[1],
                                                         "chest", self.defender_id,
                                                         1, 1)
        self.war()
        self.server.world.buildings[self.center_key]["hp"] = 1
        self.hit()
        self.wait_for(lambda: self.city.leader == self.attacker_id)
        self.assertIn(chest_key, self.server.world.buildings)

    def test_without_a_country_you_can_only_sack_the_city(self):
        """A lone wolf cannot hold land: he loots the fund and the city survives.

        Even a player who leads a city of his own needs a country to keep the
        next one - countries are what holds land together.
        """
        with self.server.world.lock:
            civs = self.server.world.civs
            civs.countries.clear()
            civs.cities["Target"].storage["gold_ingot"] = 4
            self.server.world.touch("civs")
        self.server.world.buildings[self.center_key]["hp"] = 1
        self.attacker.clear()
        self.hit()
        keys = self.keys(self.attacker, 1.0)
        self.assertIn("notify.city_sacked", keys)
        self.assertEqual(self.city.leader, self.defender_id)
        self.assertEqual(self.attacker_p["inventory"].get("gold_ingot"), 4)
        self.assertEqual(self.city.storage.get("gold_ingot", 0), 0)


class VictoryTest(B10BaseTest):
    """Two ways to win: hold every city, or build a wonder."""

    def setUp(self):
        super().setUp()
        self.one, self.one_id, self.one_p = self.join("One")
        self.two, self.two_id, self.two_p = self.join("Two")
        self.place(self.one_p)
        self.place(self.two_p, CITY_X + 600, CITY_Y + 600)

    def two_countries(self):
        with self.server.world.lock:
            civs = self.server.world.civs
            civs.create_city("First", self.one_id, CITY_X, CITY_Y)
            civs.create_city("Second", self.two_id, CITY_X + 600, CITY_Y + 600)
            civs.create_country("Empire", self.one_id)
            civs.create_country("Tribe", self.two_id)
            civs.join_country("First", "Empire", self.one_id)
            civs.join_country("Second", "Tribe", self.two_id)
            self.server.world.touch("civs")

    def test_capturing_every_city_wins_the_game(self):
        self.two_countries()
        with self.server.world.lock:
            civs = self.server.world.civs
            civs.capture_city(civs.cities["Second"], self.one_id,
                              civs.countries["Empire"])
            civs.dissolve_country("Tribe")
            self.server.world.touch("civs")
        self.two.clear()
        self.assertTrue(self.server.check_capture_victory(self.one_id))
        self.assertIsNotNone(self.server.victory)
        self.assertEqual(self.server.victory["type"], "capture")
        self.assertEqual(self.server.victory["country"], "Empire")
        self.assertIn("notify.victory_capture", self.keys(self.two, 1.0))
        state = self.server._state_payload(full=True)
        self.assertIn("victory", state)
        self.assertEqual(state["victory"]["country"], "Empire")

    def test_one_city_alone_is_not_a_victory(self):
        with self.server.world.lock:
            civs = self.server.world.civs
            civs.create_city("First", self.one_id, CITY_X, CITY_Y)
            civs.create_country("Empire", self.one_id)
            civs.join_country("First", "Empire", self.one_id)
        self.assertFalse(self.server.check_capture_victory(self.one_id))
        self.assertIsNone(self.server.victory)

    def test_building_a_wonder_wins_the_game(self):
        with self.server.world.lock:
            civs = self.server.world.civs
            civs.create_city("First", self.one_id, CITY_X, CITY_Y)
            civs.create_country("Empire", self.one_id)
            civs.join_country("First", "Empire", self.one_id)
            civs.countries["Empire"].techs = list(TECHS)
        self.two.clear()
        self.assertTrue(self.server.declare_victory("wonder", self.one_id))
        self.assertEqual(self.server.victory["type"], "wonder")
        self.assertIn("notify.victory_wonder", self.keys(self.two, 1.0))

    def test_only_one_victory_per_game(self):
        with self.server.world.lock:
            self.server.world.civs.create_city("First", self.one_id, CITY_X, CITY_Y)
        self.assertTrue(self.server.declare_victory("wonder", self.one_id))
        self.assertFalse(self.server.declare_victory("wonder", self.two_id))

    def test_a_server_can_switch_the_goal_off(self):
        self.server.config["victory"] = False
        with self.server.world.lock:
            self.server.world.civs.create_city("First", self.one_id, CITY_X, CITY_Y)
        self.assertFalse(self.server.declare_victory("wonder", self.one_id))
        self.assertIsNone(self.server.victory)


class WonderTest(B10BaseTest):
    """The wonder: the peaceful victory, gated by the age."""

    def setUp(self):
        super().setUp()
        self.builder, self.builder_id, self.builder_p = self.join("Builder")
        self.place(self.builder_p)
        self.city = self.found_city("Capita", self.builder_id, country="Empire")
        self.builder_p["inventory"] = dict(get_cost("wonder"))
        self.builder_p["selected"] = None

    def research(self, techs):
        with self.server.world.lock:
            self.server.world.civs.countries["Empire"].techs = list(techs)
            self.server.world.touch("civs")

    def test_the_wonder_needs_a_late_age(self):
        self.research(["industrialization"])          # the tech, but still stone
        keys = self.build(self.builder, self.builder_p, "wonder")
        self.assertIn("notify.wonder_age", keys)
        self.assertIsNone(self.server.victory)
        self.assertFalse(any(b["type"] == "wonder" for b in
                             self.server.world.buildings.values()))

    def test_the_wonder_needs_the_tech(self):
        self.research(["agriculture"])
        keys = self.build(self.builder, self.builder_p, "wonder")
        self.assertIn("notify.build_fail_tech", keys)

    def test_the_wonder_needs_a_city(self):
        self.research(TECHS)
        with self.server.world.lock:
            self.server.world.civs.cities.clear()
            self.server.world.touch("civs")
        keys = self.build(self.builder, self.builder_p, "wonder")
        self.assertIn("notify.wonder_city", keys)

    def test_an_industrial_country_builds_it_and_wins(self):
        self.research(TECHS)
        keys = self.build(self.builder, self.builder_p, "wonder")
        self.assertIn("notify.built", keys)
        self.assertIn("notify.victory_wonder", self.keys(self.builder, 1.0))
        self.assertIsNotNone(self.server.victory)
        self.assertEqual(self.server.victory["country"], "Empire")
        wonders = [b for b in self.server.world.buildings.values()
                   if b["type"] == "wonder"]
        self.assertEqual(len(wonders), 1)
        self.assertEqual(self.builder_p.get("stats", {}).get("wonders_built"), 1)


class EpochTest(B10BaseTest):
    """Epochs follow the researched techs and travel to the client."""

    def test_ages_follow_the_researched_techs(self):
        self.assertEqual(age_of([]), "stone")
        self.assertEqual(age_of(["agriculture"]), "stone")
        self.assertEqual(age_of(["agriculture", "masonry"]), "bronze")
        self.assertEqual(age_of(["agriculture", "masonry", "military", "logistics"]),
                         "iron")
        self.assertEqual(age_of(["agriculture", "masonry", "military", "logistics",
                                 "industrialization", "medicine"]), "industrial")
        self.assertEqual(age_of(list(TECHS)), "electric")

    def test_the_state_carries_the_age_of_every_country(self):
        client, player_id, _player = self.join("Chief")
        with self.server.world.lock:
            civs = self.server.world.civs
            civs.create_city("Capita", player_id, CITY_X, CITY_Y)
            civs.create_country("Empire", player_id)
            civs.join_country("Capita", "Empire", player_id)
            civs.countries["Empire"].techs = ["agriculture", "masonry"]
            self.server.world.touch("civs")
        payload = self.server._state_payload(full=True)
        self.assertEqual(payload["civs"]["countries"]["Empire"]["age"], "bronze")

    def test_the_research_menu_data_has_both_new_branches(self):
        client, player_id, _player = self.join("Chief")
        with self.server.world.lock:
            self.server.world.civs.create_country("Empire", player_id)
            self.server.world.touch("civs")
        available = self.server._state_payload(full=True)["civs"]["techs_available"]
        self.assertIn("medicine", available)
        self.assertIn("electricity", available)
        self.assertEqual(available["electricity"]["requires"], ["industrialization"])


class MedicineTest(B10BaseTest):
    """Medkits, bandages, hospitals and powered lamps (b10)."""

    def setUp(self):
        super().setUp()
        self.medic, self.medic_id, self.medic_p = self.join("Medic")
        self.place(self.medic_p)

    def use(self, item):
        self.medic.clear()
        self.medic.send({"type": "use", "item": item})
        self.medic.poll(0.5)
        return self.keys(self.medic, 0.3)

    def test_a_medkit_heals_and_is_used_up(self):
        self.medic_p["inventory"] = {"medkit": 1}
        self.medic_p["hp"] = 40
        keys = self.use("medkit")
        self.assertEqual(self.medic_p["hp"], 85)
        self.assertEqual(self.medic_p["inventory"].get("medkit", 0), 0)
        self.assertIn("notify.used_item", keys)

    def test_a_medkit_stops_poisoning(self):
        self.medic_p["inventory"] = {"medkit": 1}
        self.medic_p["hp"] = 60
        self.medic_p["poisoned"] = True
        self.medic_p["poison_until"] = time.time() + 30
        self.use("medkit")
        self.assertFalse(self.medic_p.get("poisoned"))

    def test_a_bandage_heals_less(self):
        self.medic_p["inventory"] = {"bandage": 1}
        self.medic_p["hp"] = 50
        self.use("bandage")
        self.assertEqual(self.medic_p["hp"], 65)

    def test_a_healthy_player_does_not_waste_medicine(self):
        self.medic_p["inventory"] = {"medkit": 1}
        self.medic_p["hp"] = 100
        keys = self.use("medkit")
        self.assertIn("notify.no_need", keys)
        self.assertEqual(self.medic_p["inventory"].get("medkit", 0), 1)

    def test_stone_is_not_medicine(self):
        self.medic_p["inventory"] = {"stone": 1}
        keys = self.use("stone")
        self.assertIn("notify.cannot_use", keys)

    def test_a_hospital_heals_players_around_it(self):
        gx, gy = CITY_TILE
        self.clear_nodes(gx, gy)
        self.server.world.place_building(gx + 1, gy + 1, "hospital",
                                         self.medic_id, 2, 2)
        self.assertEqual(self.server.hospital_heal(self.medic_p["x"],
                                                   self.medic_p["y"]), 6)
        self.assertEqual(self.server.hospital_heal(CITY_X + 2000, CITY_Y), 0)

    def test_lamps_need_a_generator(self):
        world = self.server.world
        self.clear_nodes(20, 20)
        world.place_building(20, 20, "lamp", self.medic_id, 1, 1)
        lamp_x = 20 * TILE_SIZE + TILE_SIZE // 2
        self.assertEqual([light for light in world.light_sources()
                          if light[0] == lamp_x], [])
        world.place_building(22, 22, "generator", self.medic_id, 2, 2)
        lit = [light for light in world.light_sources() if light[0] == lamp_x]
        self.assertEqual(len(lit), 1)
        self.assertEqual(lit[0][2], 220)


class WarriorRoleTest(B10BaseTest):
    """The warrior role is the one role with a perk: +10 % melee damage."""

    def setUp(self):
        super().setUp()
        self.warrior, self.warrior_id, self.warrior_p = self.join("Warrior")
        self.plain, self.plain_id, self.plain_p = self.join("Plain")
        self.victim, self.victim_id, self.victim_p = self.join("Victim")
        for player in (self.warrior_p, self.plain_p):
            self.place(player)
        self.place(self.victim_p, CITY_X + 2000, CITY_Y)
        # the city leader wears the "leader" role, so the warrior is a member
        self.city = self.found_city("Capita", self.plain_id)
        with self.server.world.lock:
            civs = self.server.world.civs
            civs.join_city("Capita", self.warrior_id)
            civs.set_role(self.city, self.warrior_id, "warrior")
            self.server.world.touch("civs")

    def hit(self, client, attacker):
        self.victim_p["hp"] = 100
        self.victim_p["armor"] = {}
        attacker["x"] = self.victim_p["x"] + 20
        attacker["y"] = self.victim_p["y"]
        attacker["inventory"] = {}
        attacker["selected"] = None
        client.clear()
        client.send({"type": "attack", "target_id": self.victim_id})
        self.wait_for(lambda: self.victim_p["hp"] < 100)
        return 100 - self.victim_p["hp"]

    def test_a_warrior_hits_harder_than_a_citizen(self):
        self.assertEqual(self.city.role_of(self.warrior_id), "warrior")
        self.assertEqual(self.city.role_of(self.plain_id), "leader")
        plain_damage = self.hit(self.plain, self.plain_p)
        warrior_damage = self.hit(self.warrior, self.warrior_p)
        self.assertEqual(plain_damage, 5)                  # bare fists deal 5
        self.assertEqual(warrior_damage, 6)                # +10 % for the warrior


class TreeTest(B10BaseTest):
    """The tech tree stays honest: everything it unlocks must exist."""

    def test_every_tech_unlocks_something_real(self):
        from shared.items import CRAFTING_RECIPES, ITEMS, SMELTING_RECIPES
        for code, data in TECHS.items():
            unlocks = data.get("unlocks", {})
            for structure in unlocks.get("structures", []):
                self.assertIn(structure, STRUCTURES, f"{code} unlocks a ghost building")
            for recipe in unlocks.get("recipes", []):
                self.assertTrue(recipe in CRAFTING_RECIPES            # what you craft
                                or recipe in SMELTING_RECIPES         # what you smelt
                                or recipe in ITEMS,                   # what you cook
                                f"{code} unlocks a ghost recipe")

    def test_requirements_point_at_real_techs(self):
        for code, data in TECHS.items():
            for required in data.get("requires", []):
                self.assertIn(required, TECHS, f"{code} requires a ghost tech")

    def test_the_wonder_is_expensive_and_strong(self):
        self.assertTrue(STRUCTURES["wonder"].get("wonder"))
        self.assertEqual(STRUCTURES["wonder"].get("age"), "industrial")
        self.assertGreaterEqual(STRUCTURES["wonder"]["hp"], 2000)
        self.assertGreaterEqual(get_cost("wonder").get("gold_ingot", 0), 50)

    def test_new_buildings_are_reachable(self):
        hospital = STRUCTURES["hospital"]
        self.assertEqual(hospital.get("tech"), "medicine")
        self.assertEqual(hospital.get("station"), "hospital")
        self.assertGreater(hospital.get("heal", 0), 0)
        generator = STRUCTURES["generator"]
        self.assertEqual(generator.get("tech"), "electricity")
        self.assertGreater(generator.get("power", 0), 0)
        self.assertTrue(STRUCTURES["lamp"].get("needs_power"))
        self.assertGreater(STRUCTURES["lamp"].get("light", 0), 100)
