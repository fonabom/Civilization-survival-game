"""b13: биомы, сезоны, музыка, обучение и удобства.

Здесь проверяется то, что легко сломать и трудно заметить:

* `shared/biomes.py` и `shared/seasons.py` — веса ресурсов, скорости, круг
  сезонов, наборы погоды, оттенки;
* сервер: генерация карты биомов, движение с учётом биома и сезона, счётчик
  дня, уведомления о сезонах, погода по сезону;
* клиент: музыка (файлы, настроения, громкость), привязки клавиш, цепочка
  первых шагов, точки на карте, сортировка инвентаря, каналы чата;
* меню F1 и «Управление» рисуются и не падают без звука и без окна.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pygame  # noqa: E402
from client import keys as client_keys  # noqa: E402
from client.config import Config  # noqa: E402
from shared import biomes as B  # noqa: E402
from shared import seasons as S  # noqa: E402


class BiomesTest(unittest.TestCase):
    def test_codes_and_names(self):
        self.assertEqual(len(B.BIOMES), 6)
        self.assertEqual(B.DEFAULT, B.MEADOW)
        self.assertEqual(B.name_key(B.CAVE), "biome.cave")
        for code in B.BIOMES:
            self.assertIn(code, B.COLORS)

    def test_encode_decode_roundtrip(self):
        grid = [[(x + y) % 6 for x in range(4)] for y in range(3)]
        text = B.encode([code for row in grid for code in row])
        self.assertEqual(len(text), 12)
        self.assertEqual(B.decode(text, 4), grid)
        # мусор не должен ронять игру
        self.assertEqual(B.decode("", 4), [])
        self.assertEqual(B.decode("9x3", 2), [[B.DEFAULT, B.DEFAULT], [3]])
        self.assertEqual(B.decode("9x3"), [B.DEFAULT, B.DEFAULT, 3])

    def test_speeds(self):
        self.assertLess(B.speed(B.SWAMP), 1.0)
        self.assertLess(B.speed(B.SNOW), 1.0)
        self.assertLess(B.speed(B.FOREST), 1.0)
        self.assertGreater(B.speed(B.DESERT), 1.0)
        self.assertEqual(B.speed(B.MEADOW), 1.0)
        for code in B.BIOMES:
            self.assertGreaterEqual(B.speed(code), 0.5)
            self.assertLessEqual(B.speed(code), 1.2)

    def test_weights(self):
        self.assertGreater(B.TREE_WEIGHT[B.FOREST], B.TREE_WEIGHT[B.MEADOW])
        self.assertGreater(B.TREE_WEIGHT[B.MEADOW], B.TREE_WEIGHT[B.SNOW])
        self.assertGreater(B.MUSHROOM_WEIGHT[B.SWAMP], 0)
        self.assertGreaterEqual(B.ORE_WEIGHT[B.CAVE], B.ORE_WEIGHT[B.MEADOW])
        self.assertGreater(B.ANIMAL_WEIGHT["sheep"][B.MEADOW],
                           B.ANIMAL_WEIGHT["sheep"][B.SNOW])
        self.assertGreater(B.ANIMAL_WEIGHT["bear"][B.FOREST],
                           B.ANIMAL_WEIGHT["bear"][B.MEADOW])


class SeasonsTest(unittest.TestCase):
    def test_order_and_cycle(self):
        self.assertEqual(S.ORDER, ("spring", "summer", "autumn", "winter"))
        days = [(day, S.season_of(day, 3)) for day in range(1, 13)]
        self.assertEqual(days[0], (1, "spring"))
        self.assertEqual(days[3], (4, "summer"))
        self.assertEqual(days[6], (7, "autumn"))
        self.assertEqual(days[9], (10, "winter"))
        self.assertEqual(S.season_of(13, 3), "spring")        # круг замкнулся

    def test_disabled_seasons_do_not_matter(self):
        self.assertEqual(S.season_of(10, 3, enabled=False), "summer")
        self.assertEqual(S.move_speed("winter", False), 1.0)
        self.assertEqual(S.regrowth("winter", False), 1.0)
        self.assertIsNone(S.tint("winter", enabled=False))
        self.assertEqual(S.weather_bag("winter", enabled=False),
                         ("clear", "clear", "clear", "rain", "fog"))

    def test_winter_is_slow_and_dark(self):
        self.assertLess(S.move_speed("winter"), 1.0)
        self.assertGreater(S.regrowth("spring"), 1.0)
        self.assertGreater(S.forage_bonus("autumn"), S.forage_bonus("summer"))
        self.assertLess(S.forage_bonus("winter"), S.forage_bonus("summer"))
        tint = S.tint("winter")
        self.assertIsNotNone(tint)
        self.assertEqual(len(tint), 4)
        self.assertGreater(tint[2], tint[0])          # синий оттенок


class KeyMapTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.config = Config(Path(self.tmp.name) / "config.json")

    def tearDown(self):
        self.tmp.cleanup()

    def test_defaults(self):
        keys = client_keys.KeyMap(self.config)
        self.assertEqual(keys.name("up"), "w")
        self.assertEqual(keys.key("inventory"), pygame.K_i)
        self.assertEqual(keys.label("help"), "F1")

    def test_rebind_and_persist(self):
        keys = client_keys.KeyMap(self.config)
        self.assertEqual(keys.bind("inventory", "tab"), True)
        self.assertEqual(keys.name("inventory"), "tab")
        again = client_keys.KeyMap(self.config)
        self.assertEqual(again.name("inventory"), "tab")

    def test_conflict_is_refused(self):
        keys = client_keys.KeyMap(self.config)
        self.assertFalse(keys.bind("inventory", "w"))
        self.assertEqual(keys.conflict("inventory", "w"), "up")
        self.assertEqual(keys.name("inventory"), "i")

    def test_bind_keycode_and_swap(self):
        keys = client_keys.KeyMap(self.config)
        self.assertEqual(keys.bind_keycode("inventory", pygame.K_TAB), "")
        self.assertEqual(keys.name("inventory"), "tab")
        self.assertEqual(keys.bind_keycode("inventory", pygame.K_w), "up")
        keys.swap("inventory", "up")
        self.assertEqual(keys.name("inventory"), "w")
        self.assertEqual(keys.name("up"), "tab")
        self.assertEqual(keys.bind_keycode("craft", pygame.K_LSHIFT), "forbidden")

    def test_reset(self):
        keys = client_keys.KeyMap(self.config)
        keys.bind("craft", "z")
        keys.reset()
        self.assertEqual(keys.name("craft"), "c")

    def test_matches_and_rows(self):
        keys = client_keys.KeyMap(self.config)

        class Event:
            key = pygame.K_i

        self.assertTrue(keys.matches(Event(), "inventory"))
        self.assertFalse(keys.matches(Event(), "craft"))
        rows = keys.rows()
        self.assertEqual(len(rows), len(client_keys.ACTIONS))
        self.assertTrue(all(len(row) == 3 for row in rows))


class AudioMusicTest(unittest.TestCase):
    def setUp(self):
        pygame.mixer.quit()
        try:
            pygame.mixer.init(frequency=22050, size=-16, channels=1, buffer=512)
        except pygame.error:
            pass

    def test_builtin_tracks_exist(self):
        from client.audio import Audio
        audio = Audio(volume=0.5)
        found = {mood: [path.name for path in paths]
                 for mood, paths in audio.music.items()}
        self.assertIn("day_calm.wav", found.get("day", []))
        self.assertIn("night_calm.wav", found.get("night", []))

    def test_play_music_does_not_crash(self):
        from client.audio import Audio
        audio = Audio(volume=0.5)
        audio.play_music("day")
        audio.set_music_volume(0.1)
        audio.play_music("night")
        audio.set_music_enabled(False)
        self.assertEqual(audio.music_mood, "")
        audio.set_volume(0.2)

    def test_music_can_be_switched_off(self):
        from client.audio import Audio
        audio = Audio(volume=0.5, music_enabled=False)
        audio.play_music("day")
        self.assertEqual(audio.music_mood, "")


class SeasonAndBiomeServerTest(unittest.TestCase):
    """Правила сервера: биом и сезон влияют на скорость ровно так же, как на клиенте."""

    def setUp(self):
        from server.world_state import WorldState
        self.world = WorldState(seed=7)

    def test_biome_map_is_generated(self):
        mix = {}
        for row in self.world.biomes:
            for code in row:
                mix[code] = mix.get(code, 0) + 1
        total = sum(mix.values())
        self.assertEqual(total, self.world.width * self.world.height)
        self.assertGreaterEqual(len(mix), 4)
        # ни один биом не должен занимать почти всю карту
        self.assertTrue(all(count / total < 0.5 for count in mix.values()), mix)

    def test_biome_string_roundtrip(self):
        text = self.world.biome_string()
        self.assertEqual(len(text), self.world.width * self.world.height)
        self.assertEqual(B.decode(text, self.world.width)[0][0], self.world.biomes[0][0])

    def test_move_factor_uses_biome_and_season(self):
        self.world.season_enabled = True
        self.world.season = "summer"
        # найдём по одному тайлу каждого биома
        spots = {}
        for gy in range(0, self.world.height, 3):
            for gx in range(0, self.world.width, 3):
                code = self.world.biomes[gy][gx]
                if code not in spots and self.world.passable(gx, gy):
                    spots[code] = (gx, gy)
        self.assertIn(B.SWAMP, spots)
        self.assertIn(B.MEADOW, spots)
        swamp = self.world.move_factor(spots[B.SWAMP][0] * 32 + 16,
                                       spots[B.SWAMP][1] * 32 + 16)
        meadow = self.world.move_factor(spots[B.MEADOW][0] * 32 + 16,
                                        spots[B.MEADOW][1] * 32 + 16)
        self.assertLess(swamp, meadow)
        self.world.season = "winter"
        winter = self.world.move_factor(spots[B.MEADOW][0] * 32 + 16,
                                        spots[B.MEADOW][1] * 32 + 16)
        self.assertLess(winter, meadow)

    def test_seasons_off(self):
        self.world.season_enabled = False
        meadow = None
        for gy in range(0, self.world.height, 3):
            for gx in range(0, self.world.width, 3):
                if self.world.biomes[gy][gx] == B.MEADOW and self.world.passable(gx, gy):
                    meadow = (gx, gy)
                    break
            if meadow:
                break
        self.world.season = "winter"
        self.assertEqual(self.world.move_factor(meadow[0] * 32 + 16, meadow[1] * 32 + 16),
                         1.0)


class ClientB13Test(unittest.TestCase):
    """Клиент: обучение, точки, сортировка, каналы чата — на живом объекте Game."""

    @classmethod
    def setUpClass(cls):
        pygame.init()
        from client.settings import SCREEN_HEIGHT, SCREEN_WIDTH
        cls.screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))

    def setUp(self):
        from client.game import Game
        self.tmp = tempfile.TemporaryDirectory()
        self.config = Config(Path(self.tmp.name) / "config.json")
        self.game = Game(self.screen, "127.0.0.1", 59999, name="Tester",
                         mode="guest", password="", config=self.config)

    def tearDown(self):
        self.tmp.cleanup()

    def test_components_exist(self):
        self.assertTrue(hasattr(self.game, "keys"))
        self.assertTrue(hasattr(self.game, "onboarding"))
        self.assertTrue(hasattr(self.game, "waypoints"))
        self.assertTrue(hasattr(self.game, "help_menu"))
        self.assertTrue(hasattr(self.game, "keys_menu"))

    def test_music_mood(self):
        self.game.season = "summer"
        self.game.world_time = 0.25
        self.assertEqual(self.game.music_mood(), "day")
        self.game.world_time = 0.95
        self.assertIn(self.game.music_mood(), ("night", "battle", "cave"))

    def test_onboarding_progress_and_panel(self):
        onboarding = self.game.onboarding
        self.assertEqual(onboarding.progress()[1], 10)
        self.assertEqual(onboarding.current(), "look")
        onboarding.mark("look")
        self.assertEqual(onboarding.current(), "wood")
        rows = onboarding.order()
        self.assertEqual(rows[0][3], "done")
        self.assertEqual(rows[1][3], "current")
        onboarding.panel_open = True
        self.game.draw_quest_panel()               # не должно падать
        self.game.draw()                           # и полный кадр тоже

    def test_onboarding_reset(self):
        self.game.onboarding.mark("look")
        self.game.onboarding.reset()
        self.assertEqual(self.game.onboarding.current(), "look")
        self.assertEqual(self.game.onboarding.progress()[0], 0)

    def test_waypoints_live_in_their_own_file(self):
        waypoints = self.game.waypoints
        waypoints.items = []
        waypoints.add(100, 200, "дом")
        self.assertEqual(len(waypoints.items), 1)
        waypoint, distance = waypoints.nearest(140, 200)
        self.assertEqual(waypoint["name"], "дом")
        self.assertAlmostEqual(distance, 40, places=3)
        self.game.draw_waypoint_compass()          # без игрока не падает
        self.assertEqual(waypoints.remove_nearest(140, 200, radius=200)["name"], "дом")
        self.assertTrue(not waypoints.items)

    def _fake_inventory(self, items):
        """Инвентарь клиента — это инвентарь игрока (`Game.inventory` только читает)."""
        from client.player import Player
        player = Player(1, "Tester")
        player.inventory = dict(items)
        self.game.players = {1: player}
        self.game.my_id = 1
        return player

    def test_inventory_sorting(self):
        self._fake_inventory({"wood": 5, "axe": 1, "berry": 3, "stone": 40})
        modes = []
        for _ in range(3):
            modes.append(self.game.cycle_inventory_sort())
        self.assertEqual(sorted(modes), ["category", "count", "name"])
        self.game.inventory_sort = "count"
        self.assertEqual(self.game.sorted_inventory()[0][0], "stone")
        self.game.inventory_sort = "category"
        items = {item for item, _count in self.game.sorted_inventory()}
        self.assertEqual(items, {"wood", "axe", "berry", "stone"})

    def test_hotbar_autofill(self):
        self._fake_inventory({"wood": 5, "axe": 1, "berry": 3, "stone": 40})
        self.game.autofill_hotbar()
        self.assertIn("axe", self.game.hotbar)
        self.assertIn("berry", self.game.hotbar)
        self.assertIsNone(self.game.hotbar[-1])

    def test_chat_channels(self):
        # серверные команды уходят как есть
        sent = []
        self.game.net.send_dict = lambda message: sent.append(message)
        self.game.send_chat("/who")
        self.assertEqual(sent[-1]["channel"], "global")
        self.game.send_chat("/l")
        self.assertEqual(self.game.chat_channel, "local")
        self.game.send_chat("привет")
        self.assertEqual(sent[-1]["channel"], "local")
        self.game.send_chat("/c")
        self.assertEqual(self.game.chat_channel, "country")
        self.game.send_chat("/w Bob привет лично")
        self.assertEqual(sent[-1]["channel"], "whisper")
        self.assertEqual(sent[-1]["to"], "Bob")
        labels = [line for line in self.game.chat_messages]
        self.assertTrue(any("привет" in line for line in labels))
        self.assertEqual(len(self.game.chat_colours), len(self.game.chat_messages))

    def test_chat_message_from_server(self):
        self.game.handle_message({"type": "chat", "id": "server", "msg": "pong"})
        self.assertIn("pong", self.game.chat_messages[-1])
        self.game.handle_message({"type": "chat", "id": 2, "name": "Bob", "msg": "hi",
                                  "channel": "local"})
        self.assertIn("Bob", self.game.chat_messages[-1])
        self.assertEqual(len(self.game.chat_colours), len(self.game.chat_messages))

    def test_help_menu_pages_draw(self):
        for page, _label in self.game.help_menu.tabs.items():
            self.game.help_menu.open(page)
            self.assertTrue(self.game.help_menu._lines())
            self.game.help_menu.draw(self.screen)
        self.game.help_menu.close()

    def test_keys_menu_draw_and_rebind(self):
        menu = self.game.keys_menu
        menu.open()
        self.game.config.data["language"] = "en"
        menu.draw(self.screen)
        self.game.keys.bind("trade", "u")
        self.assertEqual(self.game.keys.name("trade"), "u")
        menu.close()

    def test_season_visuals_do_not_crash(self):
        for season in S.ORDER:
            self.game.season = season
            self.game.day = 3
            self.game.world_time = 0.9
            self.game.draw()
        self.game.season = "winter"
        self.game._snow = []
        self.game.draw()
        self.game.draw()
        self.assertTrue(len(self.game._snow) > 0)

    def test_minimap_title_has_season_and_day(self):
        from client.i18n import set_language, t
        set_language("ru")
        self.game.day = 5
        self.game.season = "winter"
        self.game.rules = {"seasons": True}
        self.game.draw_minimap()
        self.assertEqual(t("season.winter"), "зима")
        set_language("en")


class LocaleKeysTest(unittest.TestCase):
    def test_b13_keys_are_present_in_all_languages(self):
        wanted = [
            "biome.meadow", "biome.forest", "biome.desert", "biome.snow", "biome.swamp",
            "biome.cave", "season.spring", "season.summer", "season.autumn",
            "season.winter", "hud.day", "settings.music", "settings.music_volume",
            "settings.keys", "settings.quest_reset", "help.title", "help.tab_quests",
            "help.tab_keys", "help.tab_world", "help.tab_civ", "help.world_biomes.text",
            "help.civ_war.text", "keys.up", "keys.help", "keys.title", "keys.waiting",
            "quest.look.title", "quest.winter.hint", "quest.all_done", "quest.panel_title",
            "waypoint.default", "waypoint.distance", "inv.sort_category", "inv.sort_count",
            "inv.sort_name", "inv.sort_keys", "chat.channel_local", "chat.channel_country",
            "chat.channel_whisper", "chat.placeholder_channel", "chat.whisper_usage",
            "ui.close", "notify.chat_no_country", "notify.season_winter",
            "notify.season_cold", "notify.season_forage",
        ]
        for language in ("en", "pl", "ru"):
            path = ROOT / "locales" / f"{language}.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            for key in wanted:
                self.assertIn(key, data, f"{language}: нет ключа {key}")
                self.assertTrue(str(data[key]).strip(), f"{language}: пустой {key}")

    def test_languages_have_the_same_keys(self):
        sets = []
        for language in ("en", "pl", "ru"):
            data = json.loads((ROOT / "locales" / f"{language}.json").read_text(
                encoding="utf-8"))
            sets.append(set(data))
        self.assertEqual(sets[0], sets[1])
        self.assertEqual(sets[1], sets[2])

    def test_placeholders_match(self):
        files = {language: json.loads((ROOT / "locales" / f"{language}.json").read_text(
            encoding="utf-8")) for language in ("en", "pl", "ru")}
        for key, text in files["ru"].items():
            for language, data in files.items():
                english = str(data.get(key, ""))
                for placeholder in ("{n}", "{name}", "{channel}", "{done}", "{total}",
                                    "{hotkey}", "{mode}", "{day}", "{season}"):
                    if placeholder in str(text):
                        self.assertIn(placeholder, english,
                                      f"{language}: в {key} нет {placeholder}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
