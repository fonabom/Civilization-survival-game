"""Registration, login, guests and progress persistence."""

import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server import server as server_module
from server.accounts import AccountStore

from tests.helpers import RawClient, free_port


class AccountStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = AccountStore(Path(self.tmp.name) / "accounts.json")

    def tearDown(self):
        self.tmp.cleanup()

    def test_register_then_login(self):
        ok, error, name = self.store.register("Alice", "hunter2")
        self.assertTrue(ok, error)
        self.assertEqual(name, "Alice")
        self.assertTrue(self.store.login("Alice", "hunter2")[0])

    def test_login_is_case_insensitive_on_the_name(self):
        self.store.register("Alice", "hunter2")
        ok, error, canonical = self.store.login("alice", "hunter2")
        self.assertTrue(ok, error)
        self.assertEqual(canonical, "Alice")

    def test_duplicate_registration_is_rejected(self):
        self.store.register("Alice", "hunter2")
        ok, error, _ = self.store.register("alice", "other")
        self.assertFalse(ok)
        self.assertEqual(error, "auth.name_taken")

    def test_wrong_password_and_unknown_user(self):
        self.store.register("Alice", "hunter2")
        ok, error, _ = self.store.login("Alice", "wrong")
        self.assertFalse(ok)
        self.assertEqual(error, "auth.bad_password")
        self.assertEqual(self.store.login("Nobody", "hunter2")[1], "auth.no_account")

    def test_short_password_and_bad_name(self):
        self.assertEqual(self.store.register("Al", "hunter2")[1], "auth.invalid_name")
        self.assertEqual(self.store.register("Alice", "12")[1], "auth.short_password")
        self.assertEqual(self.store.register("bad name!", "hunter2")[1], "auth.invalid_name")

    def test_passwords_are_salted_and_hashed(self):
        self.store.register("Alice", "hunter2")
        record = self.store.accounts["Alice"]
        self.assertNotIn("hunter2", str(record))
        self.assertTrue(record["salt"])
        self.assertNotEqual(record["salt"], record["password"])

    def test_progress_round_trip(self):
        self.store.register("Alice", "hunter2")
        self.assertTrue(self.store.set_progress("Alice", {"inventory": {"wood": 4}, "hp": 90}))
        loaded = self.store.get_progress("Alice")
        self.assertEqual(loaded["inventory"], {"wood": 4})
        self.assertEqual(loaded["hp"], 90)
        self.assertEqual(self.store.get_progress("Ghost"), None)

    def test_file_is_reloaded(self):
        self.store.register("Alice", "hunter2")
        fresh = AccountStore(self.store.path)
        self.assertTrue(fresh.login("Alice", "hunter2")[0])
        self.assertEqual(fresh.account_count(), 1)


class AuthFlowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.accounts_path = Path(cls.tmp.name) / "accounts.json"
        cls.port = free_port()
        cls.server = server_module.GameServer(host="127.0.0.1", port=cls.port,
                                              accounts_path=cls.accounts_path)
        threading.Thread(target=cls.server.run, daemon=True).start()
        time.sleep(0.6)

    @classmethod
    def tearDownClass(cls):
        cls.server.running = False
        time.sleep(0.3)
        cls.tmp.cleanup()

    def client(self):
        client = RawClient(self.port)
        self.addCleanup(client.close)
        return client

    def auth(self, client, kind, name, password="hunter2", seconds=0.9):
        client.poll(0.3)
        client.send({"type": kind, "username": name, "password": password})
        client.poll(seconds)
        return client.inbox

    def test_register_then_login_then_guest(self):
        client = self.client()
        messages = self.auth(client, "register", "Hero")
        self.assertIn("welcome", [m.get("type") for m in messages])
        self.assertIn("auth_ok", [m.get("type") for m in messages])
        client.close()
        time.sleep(0.3)

        again = self.client()
        messages = self.auth(again, "login", "Hero")
        self.assertIn("welcome", [m.get("type") for m in messages])
        self.assertTrue(next(m for m in messages if m.get("type") == "welcome")["account"])
        again.close()
        time.sleep(0.3)

        guest = self.client()
        welcome = guest.auth(name="G")
        self.assertIsNotNone(welcome)
        self.assertFalse(welcome["account"])

    def test_wrong_password_is_rejected(self):
        self.auth(self.client(), "register", "Guarded")
        time.sleep(0.2)
        messages = self.auth(self.client(), "login", "Guarded", password="nope")
        keys = [m.get("key") for m in messages if m.get("type") == "auth_error"]
        self.assertEqual(keys, ["auth.bad_password"])
        self.assertNotIn("welcome", [m.get("type") for m in messages])

    def test_registering_an_existing_name_is_rejected(self):
        self.auth(self.client(), "register", "Popular")
        time.sleep(0.2)
        messages = self.auth(self.client(), "register", "Popular")
        keys = [m.get("key") for m in messages if m.get("type") == "auth_error"]
        self.assertEqual(keys, ["auth.name_taken"])

    def test_progress_survives_a_reconnect(self):
        client = self.client()
        messages = self.auth(client, "register", "Keeper")
        pid = next(m["id"] for m in messages if m.get("type") == "welcome")
        self.server.world.players[pid]["inventory"]["wood"] = 42
        client.close()
        time.sleep(0.6)

        again = self.client()
        messages = self.auth(again, "login", "Keeper")
        welcome = next(m for m in messages if m.get("type") == "welcome")
        self.assertTrue(welcome["account"])
        self.assertTrue(welcome["restored"], "progress was not restored")
        inventories = [m["players"][welcome["id"]]["inventory"]
                       for m in again.inbox
                       if m.get("type") == "state"
                       and "inventory" in m.get("players", {}).get(welcome["id"], {})]
        self.assertTrue(inventories, "no packet carried the player's own inventory")
        self.assertEqual(inventories[-1]["wood"], 42)

    def test_second_login_is_refused_while_online(self):
        first = self.client()
        messages = self.auth(first, "register", "Twin")
        self.assertIn("welcome", [m.get("type") for m in messages])

        second = self.client()
        messages = self.auth(second, "login", "Twin")
        keys = [m.get("key") for m in messages if m.get("type") == "auth_error"]
        self.assertEqual(keys, ["auth.already_online"])
        self.assertNotIn("welcome", [m.get("type") for m in messages])

    def test_guests_are_never_written_to_the_database(self):
        client = self.client()
        welcome = client.auth(name="Ephemeral")
        self.server.world.players[welcome["id"]]["inventory"]["stone"] = 9
        client.close()
        time.sleep(0.5)
        self.assertFalse(self.server.accounts.exists("Ephemeral"))
        self.assertNotIn("ephemeral", {n.lower() for n in self.server.accounts.known_names()})

    def test_first_packet_must_be_auth(self):
        client = self.client()
        client.send({"type": "move", "dx": 1, "dy": 0})
        client.poll(0.6)
        types = [m.get("type") for m in client.inbox]
        self.assertIn("auth_required", types)
        self.assertNotIn("welcome", types)

    def test_hello_reports_the_build(self):
        client = self.client()
        client.poll(0.5)
        hello = next(m for m in client.inbox if m.get("type") == "hello")
        self.assertIn("build", hello)
        self.assertIsInstance(hello["build"], str)


class AccountsDisabledTest(unittest.TestCase):
    """--no-accounts: guests only, nothing written to disk."""

    def setUp(self):
        self.port = free_port()
        self.server = server_module.GameServer(host="127.0.0.1", port=self.port,
                                               accounts_path=None)
        threading.Thread(target=self.server.run, daemon=True).start()
        time.sleep(0.5)
        self.addCleanup(self._stop)

    def _stop(self):
        self.server.running = False
        time.sleep(0.2)

    def test_accounts_are_disabled_but_guests_work(self):
        self.assertIsNone(self.server.accounts)
        client = RawClient(self.port)
        self.addCleanup(client.close)
        client.send({"type": "register", "username": "Anyone", "password": "hunter2"})
        client.poll(0.6)
        keys = [m.get("key") for m in client.inbox if m.get("type") == "auth_error"]
        self.assertEqual(keys, ["auth.disabled"])

        guest = RawClient(self.port)
        self.addCleanup(guest.close)
        self.assertIsNotNone(guest.auth(name="JustVisiting"))


if __name__ == "__main__":
    unittest.main()
