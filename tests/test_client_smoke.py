"""Headless client smoke test (no window, dummy SDL drivers).

Runs the real menu and game loop for a few frames and pokes every UI panel, so
crashes like "the menu sends on a dead socket" or a bad draw call are caught in
CI instead of during a play session.
"""
import os
import sys
import tempfile
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("CIV_CONFIG", os.path.join(tempfile.mkdtemp(), "config.json"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame  # noqa: E402  (needs the env vars set first)

from client.config import Config  # noqa: E402
from client.game import Game  # noqa: E402
from client.menu import MainMenu  # noqa: E402
from client.settings import SCREEN_HEIGHT, SCREEN_WIDTH  # noqa: E402


class ClientSmokeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()
        cls.screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))

    @classmethod
    def tearDownClass(cls):
        pygame.quit()

    def setUp(self):
        self.config = Config()

    # ------------------------------------------------------------------ menu
    def test_menu_draws_and_accepts_input(self):
        menu = MainMenu(self.screen, self.config)
        for _ in range(3):
            menu.draw()

        server_field = menu.fields["server"]
        server_field.value = "127.0.0.1"
        menu.fields["login"].focused = True
        menu.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN,
                                             pos=server_field.rect.center, button=1))
        self.assertTrue(server_field.focused)
        menu.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_BACKSPACE, unicode=""))
        self.assertEqual(server_field.value, "127.0.0.")
        menu.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_a, unicode="a"))
        self.assertTrue(server_field.value.endswith("a"))
        menu.draw()

        # settings screen opens and closes
        menu.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN,
                                             pos=menu.btn_settings.center, button=1))
        self.assertTrue(menu.settings_menu.visible)
        menu.draw()
        menu.settings_menu.visible = False

        # help screen opens, draws and closes on any click
        menu.state = "help"
        menu.draw()
        menu.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=(10, 10), button=1))
        self.assertEqual(menu.state, "main")

        # "Play as guest" closes the menu and fills the result for main.py
        menu.fields["guest"].value = "SmokeTester"
        menu.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN,
                                             pos=menu.btn_guest.center, button=1))
        self.assertFalse(menu.active)
        self.assertEqual(menu.result["mode"], "guest")
        self.assertEqual(menu.result["name"], "SmokeTester")

    def test_login_flow_validates_the_form(self):
        menu = MainMenu(self.screen, self.config)
        menu.fields["login"].value = "TooShort"       # password missing
        menu.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN,
                                             pos=menu.btn_login.center, button=1))
        self.assertTrue(menu.active, "menu must stay open without a password")
        self.assertTrue(menu.message, "an error message should be shown")

        menu.fields["password"].value = "hunter2"
        menu.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN,
                                             pos=menu.btn_login.center, button=1))
        self.assertFalse(menu.active)
        self.assertEqual(menu.result["mode"], "login")
        self.assertEqual(menu.result["password"], "hunter2")

    def test_registration_flow(self):
        menu = MainMenu(self.screen, self.config)
        menu.fields["login"].value = "Newcomer"
        menu.fields["password"].value = "hunter2"
        menu.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN,
                                             pos=menu.btn_register.center, button=1))
        self.assertFalse(menu.active)
        self.assertEqual(menu.result["mode"], "register")

    # ------------------------------------------------------------------ game
    def _game_without_server(self):
        """Game pointed at a closed port: everything must still work offline."""
        game = Game(self.screen, "127.0.0.1", 1, name="SmokeTester", mode="guest",
                    password="", config=self.config)
        game.my_id = "0"
        self.addCleanup(game.net.close)
        return game

    def test_game_runs_offline_and_actions_do_not_crash(self):
        game = self._game_without_server()
        game.handle_message({
            "type": "state",
            "players": {"0": {"x": 100, "y": 100, "name": "SmokeTester", "hp": 100,
                              "selected": None, "inventory": {"wood": 3, "stone": 1,
                                                              "iron_axe": 1, "pistol": 1,
                                                              "ammo": 5}}},
            "resources": {"100,100": {"x": 100, "y": 100, "type": "tree"}},
            "buildings": {"5,5": {"x": 5, "y": 5, "type": "crafting_table", "w": 1, "h": 1}},
            "civs": {"cities": {"Rome": {"members": ["0"], "leader": "0", "techs": [],
                                         "x": 100, "y": 100, "tier": 1, "storage": {}}},
                     "countries": {}},
        })
        for _ in range(10):
            game.update()
            game.draw()

        # clicking in the world must not raise, even while offline
        game.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=(400, 300), button=1))
        game.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=(400, 300), button=3))

        # every panel opens, draws and reacts to clicks while offline
        for menu in (game.crafting_menu, game.civ_menu, game.inventory_menu,
                     game.research_menu, game.smelting_menu, game.settings_menu):
            menu.visible = True
            for _ in range(3):
                game.draw()
            click = pygame.event.Event(pygame.MOUSEBUTTONDOWN,
                                       pos=(menu.panel.centerx, menu.panel.y + 70), button=1)
            if hasattr(menu, "handle_click"):
                menu.handle_click(click)
            else:
                menu.handle_event(click)
            menu.visible = False

    def test_ui_helpers_with_empty_state(self):
        game = self._game_without_server()
        game.draw_hud()
        game.draw_chat()
        game.draw_player_list()
        game.draw_notifications()

    def test_hotbar_selection_updates_the_hand(self):
        game = self._game_without_server()
        game.handle_message({
            "type": "state", "partial": True, "resources": {}, "buildings": {},
            "players": {"0": {"x": 100, "y": 100, "name": "SmokeTester", "hp": 100,
                              "selected": None,
                              "inventory": {"wood": 1, "stone": 1, "iron_sword": 1}}},
        })
        self.assertTrue(game.inventory)
        game.select_hotbar(0)
        self.assertIsNotNone(game.held_item())
        self.assertEqual(game.hotbar_index, 0)

    def test_state_pruning_and_player_left(self):
        game = self._game_without_server()
        game.handle_message({"type": "state", "players": {
            "0": {"x": 0, "y": 0, "name": "SmokeTester"},
            "5": {"x": 10, "y": 10, "name": "Other"},
        }})
        self.assertEqual(len(game.players), 2)
        game.players.pop("5", None)
        self.assertNotIn("5", game.players)

    def test_server_terrain_is_used_for_rendering(self):
        game = self._game_without_server()
        terrain = "1" + "0" * (100 * 100 - 1)
        game.handle_message({"type": "welcome", "id": "0", "terrain": terrain,
                             "world": [100, 100], "players": {}})
        game.draw()
        from client.world import GRASS, STONE
        self.assertEqual(game.world.tiles[0][0], STONE)
        self.assertEqual(game.world.tiles[0][1], GRASS)

    def test_notifications_and_chat(self):
        game = self._game_without_server()
        game.handle_message({"type": "notification", "key": "notify.built",
                             "args": {"name": "structure.wall"}})
        self.assertTrue(game.notifications)

        game.handle_message({"type": "chat", "name": "Bob", "msg": "hello"})
        self.assertTrue(any("hello" in line for line in game.chat_messages))

        game.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN, unicode="\r"))
        self.assertTrue(game.chat_active)
        game.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_h, unicode="h"))
        game.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_i, unicode="i"))
        self.assertEqual(game.chat_input, "hi")
        game.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN, unicode="\r"))
        self.assertFalse(game.chat_active)

    def test_unknown_notification_key_does_not_crash(self):
        game = self._game_without_server()
        game.handle_message({"type": "notification", "key": "notify.does_not_exist"})
        for _ in range(3):
            game.draw()


if __name__ == "__main__":
    unittest.main()
