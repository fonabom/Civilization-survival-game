"""The in-game loop: world, players, HUD, hotbar, build mode, pause menu."""

import math
import random
import time

import pygame

CAVE_DARKNESS = 200      # how dark it is underground without a light source

from client.camera import Camera
from client.config import HOTBAR_SIZE, Config
from client.i18n import t
from client.network import Network
from client.player import Player
from client.audio import Audio
from client.resources import ResourceManager
from client.keys import KeyMap
from client.onboarding import Onboarding
from client.settings import SCREEN_WIDTH, SCREEN_HEIGHT, TILE_SIZE
from client.waypoints import Waypoints
from client.ui import widgets as w
from client.ui.civ_menu import CivMenu
from client.ui.crafting_menu import CraftingMenu
from client.ui.help_menu import HelpMenu
from client.ui.keys_menu import KeysMenu
from client.ui.inventory_menu import InventoryMenu
from client.ui.research_menu import ResearchMenu
from client.ui.settings_menu import SettingsMenu
from client.ui.chest_menu import ChestMenu
from client.ui.trade_menu import TradeMenu
from client.ui.smelting_menu import SmeltingMenu
from client.ui.tasks_menu import TasksMenu
from client.world import World
from shared.biomes import COLORS as BIOME_COLORS
from shared.biomes import speed as biome_speed
from shared.items import (ITEMS, item_durability, item_food, item_range,
                         item_slot)
from shared.seasons import move_speed as season_move, tint as season_tint
from shared.speed import SWIM_SPEED, move_multiplier, terrain_speed
from shared.structures import (STRUCTURES, can_afford, get_light, get_size, get_speed,
                               get_station, is_market, is_storage)

INTERACT_RANGE_TILES = 8


class Game:
    def __init__(self, screen, host="127.0.0.1", port=5555, name="Player",
                 mode="guest", password="", config=None):
        self.screen = screen
        self.config = config or Config()
        self.player_name = name or "Player"
        self.session_mode = mode
        self.password = password

        self.resources = ResourceManager(self.config.get("resource_pack"))
        self.audio = Audio(self.resources, volume=self.config.get("sound_volume", 0.7),
                           music_enabled=bool(self.config.get("music", True)),
                           music_volume=float(self.config.get("music_volume", 0.45)),
                           enabled=self.config.get("sound", True))
        self.world = World(self.resources)
        self.camera = Camera()
        self.net = Network(host, port, name=self.player_name, auth={
            "type": "login" if mode == "login" else
                    ("register" if mode == "register" else "guest"),
            "username": self.player_name, "password": self.password, "name": self.player_name,
        })
        self.players = {}
        self.my_id = None
        self.server_build = None
        self.auth_state = "connecting"       # connecting | ok | error
        self.auth_error = ""
        self.exit_to_menu = False
        self.quit_game = False

        # UI components
        self.crafting_menu = CraftingMenu(self)
        self.civ_menu = CivMenu(self)
        self.smelting_menu = SmeltingMenu(self)
        self.inventory_menu = InventoryMenu(self)
        self.research_menu = ResearchMenu(self)
        self.chest_menu = ChestMenu(self)
        self.trade_menu = TradeMenu(self)
        self.tasks_menu = TasksMenu(self)
        self.settings_menu = SettingsMenu(game=self, config=self.config,
                                          on_change=self._on_settings_changed)
        # b13: rebindable keys, first-minutes quests, waypoints, F1 help
        self.keys = KeyMap(self.config)
        self.keys_menu = KeysMenu(game=self, config=self.config,
                                  on_change=self._on_settings_changed)
        self.help_menu = HelpMenu(self)
        self.onboarding = Onboarding(self)
        self.waypoints = Waypoints(host, port, game=self)
        self.inventory_sort = str(self.config.get("inventory_sort", "category"))
        self.paused = False

        # Chat and notifications
        self.chat_messages = []
        self.chat_colours = []          # b13: цвет строки зависит от канала
        self.chat_input = ""
        self.chat_active = False
        self.chat_channel = str(self.config.get("chat_channel", "global"))
        self.notifications = []

        # Hotbar (what the player holds)
        self.hotbar = list(self.config.get("hotbar"))[:HOTBAR_SIZE]
        self.hotbar += [None] * (HOTBAR_SIZE - len(self.hotbar))
        self.hotbar_index = 0

        # --- b8: world clock, animals, tasks, effects ------------------------
        self.animals = {}
        self.civ_state = {}            # b13: пусто, пока не пришло состояние
        self.trades = []
        self.victory = None            # {"type", "country", "player"} after a win
        self.victory_seen = 0.0        # when we heard about it (for the banner)
        self.world_time = 0.25
        self.season = "summer"
        self.day = 1
        self._snow = []                 # b13: падающий снег зимой
        self._last_music_check = 0.0
        self.weather = "clear"
        self.rules = {}                 # movement rules of the server (b11)
        self.lights = []
        self.stats = {}
        self.tasks = {}
        self.minimap_open = False
        self.damage_numbers = []
        self.death_banner = 0
        self.hints_shown = set()
        self.hint_timer = 0
        self.ping = 0
        self._last_ping_sent = 0.0
        self._last_hp = None
        self._step_timer = 0.0
        self._night_flag = False

        # Build mode
        self.build_target = None
        self.build_hint_timer = 0

        self.clock = pygame.time.Clock()
        self.apply_display_settings()
        self._sync_selected_item(initial=True)

    # ------------------------------------------------------------------ display
    def apply_display_settings(self):
        flags = pygame.FULLSCREEN if self.config.get("fullscreen") else 0
        surface = pygame.display.get_surface()
        if surface is not None and surface.get_flags() & pygame.FULLSCREEN != flags & pygame.FULLSCREEN:
            self.screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT), flags)
        elif surface is None:
            self.screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT), flags)
        else:
            self.screen = surface

    def _on_settings_changed(self, kind):
        if kind == "pack":
            self.world.set_textures(self.resources)

    # ------------------------------------------------------------------ helpers
    @property
    def me(self):
        return self.players.get(self.my_id)

    @property
    def inventory(self) -> dict:
        player = self.me
        return getattr(player, "inventory", {}) if player else {}

    def held_item(self):
        item = self.hotbar[self.hotbar_index]
        if item and self.inventory.get(item, 0) > 0:
            return item
        return None

    QUIET_KEYS = {"notify.built_other", "notify.gathered_other", "notify.task_other",
                  "notify.chests_used", "notify.tech_other"}

    def quiet_notification(self, key) -> bool:
        """Settings -> "quiet build messages": drop the noisy broadcasts."""
        if not self.config.get("quiet_notifications", False):
            return False
        return key in self.QUIET_KEYS

    def on_victory(self, payload):
        """Somebody won the game: banner + a line in the chat."""
        self.victory = dict(payload or {})
        self.victory_seen = time.time()
        self.chat_messages.append(t("victory.chat",
                                    country=self.victory.get("country", "?")))
        self.audio.play("task")

    def _localize_args(self, args: dict) -> dict:
        out = {}
        for key, value in (args or {}).items():
            if isinstance(value, str) and "." in value:
                prefix = value.split(".", 1)[0]
                if prefix in ("item", "structure", "tech", "station", "resource",
                              "task", "animal", "weather", "city", "country"):
                    out[key] = t(value)
                    continue
            out[key] = value
        return out

    def _sound_for_key(self, key, args):
        """Map server notifications to sounds (kept in one place, easy to tune)."""
        table = {
            "notify.hit": "hit", "notify.you_hit": "hurt", "notify.blocked": "hit",
            "notify.bitten": "hurt", "notify.gathered": "chop", "notify.crafted": "craft",
            "notify.built": "build", "notify.building_destroyed": "break",
            "notify.building_lost": "break", "notify.ate": "eat", "notify.poisoned": "hurt",
            "notify.tool_broke": "break", "notify.animal_killed": "hit",
            "notify.task_done": "task", "notify.defeated": "death",
            "notify.respawn": "pickup", "notify.stored": "pickup", "notify.taken": "pickup",
            "notify.chest_full": "hit", "notify.tamed": "pickup",
        }
        sound = table.get(key)
        if sound:
            self.audio.play(sound)

    def add_damage_number(self, x, y, amount, color=(250, 220, 120)):
        self.damage_numbers.append({"x": x, "y": y, "text": str(amount), "ttl": 60,
                                    "color": color})

    def durability_for(self, item: str, maximum: int) -> int:
        me = self.me
        if me is None:
            return maximum
        return int(getattr(me, "durability", {}).get(item, maximum))

    def hours(self) -> int:
        return int(self.world_time * 24)

    def is_night(self) -> bool:
        hours = self.hours()
        return hours < 6 or hours >= 21

    def nearest_animal(self, max_distance=90):
        me = self.me
        if me is None:
            return None, None
        best, best_id, best_distance = None, None, max_distance
        for aid, animal in self.animals.items():
            if animal.get("owner") == self.my_id:
                continue
            distance = ((animal["x"] - me.x) ** 2 + (animal["y"] - me.y) ** 2) ** 0.5
            if distance < best_distance:
                best, best_id, best_distance = animal, aid, distance
        return best, best_id

    def notify(self, text, color=None):
        self.notifications.append({"text": text, "ttl": 180, "color": color})

    # ------------------------------------------------------------------- update
    def update(self):
        self.clock.tick(60)
        now = time.time()
        if now - self._last_ping_sent > 2.0 and self.net.connected:
            self._last_ping_sent = now
            self.net.send_dict({"type": "ping", "t": now})

        for entry in list(self.damage_numbers):
            entry["ttl"] -= 1
            entry["y"] -= 0.6
        self.damage_numbers = [e for e in self.damage_numbers if e["ttl"] > 0]
        if self.death_banner > 0:
            self.death_banner -= 1

        # footsteps
        if self.me is not None:
            self._step_timer -= 1
            if self._step_timer <= 0:
                if any(self.keys.pressed(action)
                       for action in ("up", "down", "left", "right")):
                    self.audio.play("step", 0.5)
                    self._step_timer = 14

        # night falls -> a quiet chime, once per change
        if self.is_night() != self._night_flag:
            self._night_flag = self.is_night()
            if self._night_flag:
                self.audio.play("night")
        self._tick_music(now)
        self.onboarding.tick()
        self.keys_menu.update()
        self._tutorial_tick()
        for entry in self.notifications:
            entry["ttl"] -= 1
        self.notifications = [entry for entry in self.notifications if entry["ttl"] > 0]
        if self.build_hint_timer > 0:
            self.build_hint_timer -= 1

        for message in self.net.receive():
            self.handle_message(message)

        self.handle_input()

        for player in self.players.values():
            player.update()

        target = self.me or (next(iter(self.players.values())) if self.players else None)
        if target is not None:
            self.camera.update(target, SCREEN_WIDTH, SCREEN_HEIGHT,
                               world_width=self.world.width * TILE_SIZE,
                               world_height=self.world.height * TILE_SIZE)

    def music_mood(self) -> str:
        """Which track fits right now: cave, night, battle or a calm day.

        b13: the file name decides the mood (`calm_day.wav`, `night_*.ogg`), so
        a resource pack can simply add its own tracks with these names.
        """
        if self.in_cave():
            return "cave"
        if self._in_danger():
            return "battle"
        return "night" if self.is_night() else "day"

    def _in_danger(self) -> bool:
        me = self.me
        if me is None:
            return False
        if getattr(me, "hp", 100) < 35:
            return True
        for animal in self.animals.values():
            if not animal.get("hostile"):
                continue
            if ((animal["x"] - me.x) ** 2 + (animal["y"] - me.y) ** 2) ** 0.5 < 320:
                return True
        return False

    def _tick_music(self, now):
        """Called every frame; the player itself keeps a track playing."""
        if now - self._last_music_check < 1.0:
            return
        self._last_music_check = now
        self.audio.play_music(self.music_mood())

    def _tutorial_tick(self):
        """First-minutes hints: what to do next, shown once each."""
        if not self.config.get("tutorial", True):
            return
        hints = []
        if not self.players:
            return
        # b13: the first steps live in the onboarding chain now, so these hints
        # only point out things the chain does not cover
        if self.me is not None and self.me.hunger < 40 and "eat" not in self.hints_shown:
            hints.append(("eat", "hint.eat"))
        elif "night" not in self.hints_shown and self.is_night():
            hints.append(("night", "hint.night"))
        elif "fish" not in self.hints_shown and "fishing_rod" in self.inventory \
                and self.water_near():
            hints.append(("fish", "hint.fish"))
        elif "trade" not in self.hints_shown and self.market_near():
            hints.append(("trade", "hint.trade"))
        if hints and self.hint_timer <= 0:
            code, key = hints[0]
            self.hints_shown.add(code)
            self.notify(t(key), w.WARN)
            self.hint_timer = 240
        if self.hint_timer > 0:
            self.hint_timer -= 1

    def handle_message(self, message):
        kind = message.get("type")

        if kind == "hello":
            self.server_build = message.get("build")
            if self.server_build and self.server_build != self._build():
                self.notify(t("app.build_mismatch", server=self.server_build,
                              client=self._build()), w.WARN)

        elif kind == "auth_required":
            self.net.send_dict({"type": "guest", "name": self.player_name})

        elif kind == "auth_error":
            self.auth_state = "error"
            self.auth_error = t(message.get("key", "auth.no_account"))
            self.notify(self.auth_error, w.BAD)

        elif kind == "welcome":
            self.auth_state = "ok"
            self.my_id = message["id"]
            self.server_build = message.get("build", self.server_build)
            if message.get("name"):
                self.player_name = message["name"]
            if "terrain" in message:
                self.world.set_terrain(message["terrain"], message.get("world"))
            if "biomes" in message:
                self.world.set_biomes(message["biomes"], message.get("world"))
            if "season" in message:
                self.season = message["season"]
            if "day" in message:
                self.day = int(message.get("day", 1))
            if isinstance(message.get("rules"), dict):
                self.rules = dict(message["rules"])
            player = Player(self.my_id, self.player_name)
            if self.hotbar_index is not None and self.hotbar[self.hotbar_index]:
                player.selected = self.hotbar[self.hotbar_index]
            self.players[self.my_id] = player
            print(f"[client] connected as {self.my_id} ({self.player_name})")

        elif kind == "notification":
            if self.quiet_notification(message.get("key")):
                return
            text = t(message["key"], **self._localize_args(message.get("args")))
            self.notify(text)
            self._sound_for_key(message.get("key"), message.get("args") or {})

        elif kind == "tasks":
            was = dict(self.tasks or {})
            self.tasks = dict(message.get("tasks") or {})
            self.stats = dict(message.get("stats") or {})
            new_tasks = [code for code in self.tasks if code not in was]
            if new_tasks and was:
                self.audio.play("task")

        elif kind == "chest":
            self.chest_menu.open(message.get("x", 0), message.get("y", 0),
                                 message.get("items") or {})

        elif kind == "trades":
            self.trades = list(message.get("offers") or [])

        elif kind == "victory":
            self.on_victory(message)

        elif kind == "pong":
            if message.get("t") is not None:
                self.ping = max(0, int((time.time() - float(message["t"])) * 1000))

        elif kind == "chat":
            author = message.get("name") or (f"Player {message.get('id')}"
                                             if message.get("id") != "server" else "server")
            self.add_chat_line(author, message.get("msg", ""),
                               message.get("channel") or "global",
                               to=message.get("to") or "")

        elif kind == "player_left":
            self.players.pop(message.get("id"), None)

        elif kind == "state":
            payload = message.get("players", {})
            for pid, data in payload.items():
                if pid not in self.players:
                    self.players[pid] = Player(pid, data.get("name"))
                player = self.players[pid]
                player.update_from_server(data)
                if "selected" in data:
                    player.selected = data["selected"]
                if pid == self.my_id and "inventory" in data:
                    player.inventory = data["inventory"]
                    self._autofill_hotbar()
            me = self.players.get(self.my_id)
            if me is not None:
                if self._last_hp is not None and me.hp < self._last_hp - 0.5:
                    self.audio.play("hurt")
                    self.damage_numbers.append(
                        {"x": me.x, "y": me.y - 20, "text": f"-{int(self._last_hp - me.hp)}",
                         "ttl": 60, "color": (240, 90, 90)})
                self._last_hp = me.hp
            if not message.get("partial"):
                for pid in [pid for pid in self.players if pid not in payload]:
                    del self.players[pid]
            if "resources" in message:
                self.world.resources = message["resources"]
            if "buildings" in message:
                self.world.buildings = message["buildings"]
            if "civs" in message:
                self.civ_state = message["civs"]
            if "animals" in message:
                self.animals = message["animals"]
            if "time" in message:
                self.world_time = float(message["time"])
                if "season" in message:
                    self.season = message["season"]
                if "day" in message:
                    self.day = int(message.get("day", self.day))
            if "weather" in message:
                if message["weather"] != self.weather:
                    self.weather = message["weather"]
                    if self.weather in ("rain", "fog"):
                        self.audio.play("rain")
            if "lights" in message:
                self.lights = [tuple(entry) for entry in message["lights"]]
            if "trades" in message:
                self.trades = list(message["trades"] or [])
            if message.get("victory") and self.victory is None:
                self.on_victory(message["victory"])
            if "tasks" in message and "stats" in message:
                self.tasks = dict(message["tasks"])
                self.stats = dict(message["stats"])

    # -------------------------------------------------------------------- input
    def handle_input(self):
        keys = pygame.key.get_pressed()
        if self.chat_active or self.paused or self._any_menu_open():
            return

        dx = dy = 0
        speed = 4
        if self.keys.pressed("up"):
            dy = -speed
        if keys[pygame.K_s]:
            dy = speed
        if keys[pygame.K_a]:
            dx = -speed
        if keys[pygame.K_d]:
            dx = speed
        if dx or dy:
            self.net.send_move(dx, dy)          # the server scales this itself
            player = self.me
            if player is not None:
                # b11: predict the very same step the server will make
                # (water slows you down, roads and bridges speed you up) -
                # otherwise every step in water would rubber-band us back
                step = self.move_step_factor(player.x, player.y)
                player.x += dx * step
                player.y += dy * step
                player.target_x, player.target_y = player.x, player.y

    def move_step_factor(self, x, y) -> float:
        """How much of a movement request really happens here (b11).

        The client mirrors the server's rules (`shared/speed.py`): water is slow,
        a bridge or a road is fast, rain slows everybody down a little.
        """
        gx, gy = int(x // TILE_SIZE), int(y // TILE_SIZE)
        tile = self.world.tile(gx, gy)
        rules = self.rules or {}
        swim = bool(rules.get("swim", True))
        swim_speed = float(rules.get("swim_speed", SWIM_SPEED) or SWIM_SPEED)
        if terrain_speed(tile, swim, swim_speed) <= 0:
            return 0.0                     # that tile cannot be entered at all
        factor = move_multiplier(tile, self.weather, swim=swim, swim_speed=swim_speed,
                                 weather_enabled=bool(rules.get("weather", True)))
        if factor <= 0:
            return factor
        # a bridge or a road carries you at its own speed on both sides (b11)
        building = self.world.building_at(gx, gy) if hasattr(self.world, "building_at") else None
        if building is not None:
            speed = get_speed(building.get("type", ""))
            if speed:
                return float(speed)
        # b13: the biome and the season slow you down exactly like on the server
        factor *= biome_speed(self.world.biome(gx, gy))
        return factor * season_move(self.season, bool(rules.get("seasons", True)))

    def _any_menu_open(self):
        return any(menu.visible for menu in self._menu_list())

    def _menu_list(self):
        return (self.crafting_menu, self.civ_menu, self.smelting_menu,
                self.inventory_menu, self.research_menu, self.chest_menu,
                self.tasks_menu, self.trade_menu, self.settings_menu,
                self.help_menu)

    # -------------------------------------------------------------------- draw
    def draw(self):
        self.screen.fill((0, 0, 0))
        self.world.draw(self.screen, self.camera)
        self.draw_animals()
        for player in self.players.values():
            player.draw(self.screen, self.camera, is_me=(player.id == self.my_id),
                        resources=self.resources,
                        in_water=self.world.is_water(int(player.x // TILE_SIZE),
                                                     int(player.y // TILE_SIZE)))
        if self.build_target:
            self._draw_build_ghost()
        self.draw_night()
        self.draw_season()
        self.draw_weather()
        self.draw_damage_numbers()
        if self.minimap_open:
            self.draw_minimap()

        self.draw_hud()
        self.draw_chat()
        # notifications sit under the panels so they never cover a menu
        self.draw_notifications()
        # ... and the victory banner sits above them: a won game matters more
        self.draw_victory_banner()
        for menu in self._menu_list():
            menu.draw(self.screen)
        self.keys_menu.draw(self.screen)
        if pygame.key.get_pressed()[pygame.K_TAB]:
            self.draw_player_list()
        if self.paused:
            self.draw_pause()

    # ---------------------------------------------------------------- HUD parts
    def draw_animals(self):
        """Animals with a small health bar; pets get a green outline."""
        for animal in self.animals.values():
            ax = int(animal["x"] - self.camera.x)
            ay = int(animal["y"] - self.camera.y)
            if not (-64 < ax < SCREEN_WIDTH + 64 and -64 < ay < SCREEN_HEIGHT + 64):
                continue
            icon = self.resources.get(animal["type"])
            if icon is not None:
                self.screen.blit(icon, (ax - TILE_SIZE // 2, ay - TILE_SIZE // 2))
            else:
                pygame.draw.circle(self.screen, (200, 200, 200), (ax, ay), 10)
            if animal.get("owner") == self.my_id:
                pygame.draw.circle(self.screen, (90, 220, 120), (ax, ay), 16, 2)
            max_hp = animal.get("max_hp") or 1
            if animal.get("hp", max_hp) < max_hp:
                bar = pygame.Rect(ax - 16, ay - 24, 32, 4)
                pygame.draw.rect(self.screen, (60, 20, 20), bar)
                pygame.draw.rect(self.screen, (220, 80, 80),
                                 (bar.x, bar.y, int(bar.width * animal["hp"] / max_hp), 4))

    def in_cave(self) -> bool:
        me = self.me
        if me is None:
            return False
        return self.world.is_cave(int(me.x // TILE_SIZE), int(me.y // TILE_SIZE))

    def draw_night(self):
        """Darkness (night or a cave) with holes around torches and campfires."""
        darkness = self.night_alpha()
        if self.in_cave():
            darkness = max(darkness, CAVE_DARKNESS)
        if darkness <= 4:
            return
        overlay = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT))
        overlay.fill((10, 14, 40))
        overlay.set_alpha(darkness)
        if self.lights:
            mask = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
            mask.fill((0, 0, 0, darkness))
            for lx, ly, radius in self.lights:
                screen_x = int(lx - self.camera.x)
                screen_y = int(ly - self.camera.y)
                if not (-radius < screen_x < SCREEN_WIDTH + radius and
                        -radius < screen_y < SCREEN_HEIGHT + radius):
                    continue
                for step in range(4, 0, -1):
                    value = int(255 * (1 - step / 5))
                    pygame.draw.circle(mask, (0, 0, 0, value), (screen_x, screen_y),
                                       int(radius * step / 4))
            overlay = mask
        self.screen.blit(overlay, (0, 0))

    def night_alpha(self) -> int:
        """0 during the day, up to 170 at midnight."""
        hours = self.hours()
        if 8 <= hours < 19:
            return 0
        if 19 <= hours < 21:
            return int(170 * (hours - 19) / 2)
        if hours >= 21:
            return 170
        if hours < 5:
            return 170
        return int(170 * (1 - (hours - 5) / 3))

    def draw_season(self):
        """A light seasonal tint plus falling snow in winter (b13)."""
        rules = self.rules or {}
        if not rules.get("seasons", True):
            return
        colour = season_tint(self.season, True)
        if colour:
            overlay = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT))
            overlay.fill(colour[:3])
            overlay.set_alpha(colour[3])
            self.screen.blit(overlay, (0, 0))
        if self.season != "winter":
            self._snow = []
            return
        # snow: a handful of flakes that fall and drift
        if len(self._snow) < 90:
            self._snow.extend((random.randint(0, SCREEN_WIDTH), random.randint(-40, 0),
                               random.choice((0.6, 1.0, 1.5)))
                              for _ in range(90 - len(self._snow)))
        flakes = []
        for x, y, speed in self._snow:
            y += speed
            x += 0.3
            if y > SCREEN_HEIGHT:
                y, x = -6, random.randint(0, SCREEN_WIDTH)
            if x > SCREEN_WIDTH:
                x = 0
            flakes.append((x, y, speed))
            pygame.draw.rect(self.screen, (240, 246, 255),
                             (int(x), int(y), 2, 2))
        self._snow = flakes

    def draw_weather(self):
        if self.weather not in ("rain", "fog"):
            return
        if self.weather == "fog":
            fog = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT))
            fog.fill((200, 200, 205))
            fog.set_alpha(70)
            self.screen.blit(fog, (0, 0))
            return
        tint = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT))
        tint.fill((40, 60, 90))
        tint.set_alpha(40)
        self.screen.blit(tint, (0, 0))
        drop = pygame.Surface((2, 12), pygame.SRCALPHA)
        drop.fill((190, 205, 235, 150))
        offset = int(time.time() * 300) % 40
        for x in range(0, SCREEN_WIDTH, 46):
            for y in range(-40 + offset, SCREEN_HEIGHT, 40):
                self.screen.blit(drop, (x + (y % 7) * 3, y))

    def draw_damage_numbers(self):
        for entry in self.damage_numbers:
            x = int(entry["x"] - self.camera.x)
            y = int(entry["y"] - self.camera.y)
            alpha = min(255, entry["ttl"] * 5)
            label = w.font(18, bold=True).render(entry["text"], True, entry["color"])
            label.set_alpha(alpha)
            self.screen.blit(label, (x - label.get_width() // 2, y))

    def draw_minimap(self):
        """Small map of what we know: terrain, buildings, players, animals."""
        size = 200
        panel = pygame.Rect(SCREEN_WIDTH - size - 18, 84, size, size)
        pygame.draw.rect(self.screen, (18, 20, 26), panel, border_radius=6)
        pygame.draw.rect(self.screen, w.BORDER, panel, 2, border_radius=6)
        scale = size / max(self.world.width, self.world.height)
        for y in range(0, self.world.height, 2):
            for x in range(0, self.world.width, 2):
                tile = self.world.tiles[y][x]
                if tile == 0:
                    color = BIOME_COLORS.get(self.world.biome(x, y), (46, 120, 52))
                    color = tuple(max(0, channel - 24) for channel in color)
                else:
                    color = {1: (110, 110, 116), 2: (46, 92, 168),
                             3: (48, 44, 40)}.get(tile, (110, 110, 116))
                pygame.draw.rect(self.screen, color,
                                 (panel.x + x * scale, panel.y + y * scale,
                                  max(1, scale * 2), max(1, scale * 2)))
        for waypoint in self.waypoints.items:          # b13: свои точки на карте
            wx = panel.x + waypoint["x"] / TILE_SIZE * scale
            wy = panel.y + waypoint["y"] / TILE_SIZE * scale
            pygame.draw.rect(self.screen, (255, 215, 90),
                             (wx - 2, wy - 2, 5, 5))
        for building in self.world.buildings.values():
            color = (200, 180, 90) if building.get("owner") == self.my_id else (170, 90, 90)
            pygame.draw.rect(self.screen, color,
                             (panel.x + building["x"] * scale, panel.y + building["y"] * scale,
                              max(2, scale * 2), max(2, scale * 2)))
        for pid, player in self.players.items():
            color = (120, 200, 255) if pid == self.my_id else (250, 120, 120)
            pygame.draw.circle(self.screen, color,
                               (int(panel.x + player.x / TILE_SIZE * scale),
                                int(panel.y + player.y / TILE_SIZE * scale)), 3)
        for animal in self.animals.values():
            if animal.get("owner") == self.my_id:
                pygame.draw.circle(self.screen, (120, 240, 150),
                                   (int(panel.x + animal["x"] / TILE_SIZE * scale),
                                    int(panel.y + animal["y"] / TILE_SIZE * scale)), 2)
        if self.civ_state:
            for city in (self.civ_state.get("cities") or {}).values():
                pygame.draw.circle(self.screen, (250, 220, 120),
                                   (int(panel.x + city.get("x", 0) / TILE_SIZE * scale),
                                    int(panel.y + city.get("y", 0) / TILE_SIZE * scale)), 4, 2)
        season_name = t("season." + self.season) if self.season else ""
        title = (f"{t('hud.day', day=self.day)}  {season_name}  |  "
                 f"{self.hours():02d}:00  {t('weather.' + self.weather)}  {self.ping} ms")
        w.text(self.screen, title, (panel.centerx, panel.y - 14), size=14,
               centered_in=pygame.Rect(panel.x, panel.y - 26, panel.width, 18))

    def draw_hud(self):
        self.draw_connection_status()
        self.draw_civ_summary()
        self.draw_quest_panel()
        self.draw_waypoint_compass()
        self.draw_hotbar()
        if self.config.get("show_debug"):
            fps = int(self.clock.get_fps())
            w.text(self.screen, t("hud.fps", fps=fps) + f"  |  {self._build()}",
                   (12, SCREEN_HEIGHT - 22), size=14, color=w.TEXT_DIM)

    def draw_quest_panel(self):
        """The first-minutes chain, compact, in the top-left corner (b13)."""
        onboarding = self.onboarding
        if not self.config.get("tutorial", True) and not onboarding.panel_open:
            return
        rows = onboarding.order()
        code = onboarding.current()
        if code is None and not onboarding.panel_open:
            return
        done, total = onboarding.progress()
        lines = []
        if onboarding.panel_open:
            for index, (step, title_key, _hint, state) in enumerate(rows, start=1):
                mark = "[x]" if state == "done" else ("[>]" if state == "current" else "[ ]")
                colour = (w.GOOD if state == "done" else
                          (w.ACCENT if state == "current" else w.TEXT_DIM))
                lines.append((f"{mark} {index}. {t(title_key)}", colour))
        else:
            step, title_key, hint_key, _state = next(row for row in rows if row[0] == code)
            lines.append((f"[>] {t(title_key)}", w.ACCENT))
            lines.append((t(hint_key), w.TEXT_DIM))
        header = t("quest.panel_title", done=done, total=total)
        width = max([w.font(17).size(header)[0] + 24] +
                    [w.font(16).size(text)[0] + 30 for text, _colour in lines]) + 8
        height = 30 + sum(20 for _line in lines)
        rect = pygame.Rect(10, 46, min(width, 460), height)
        surface = pygame.Surface(rect.size, pygame.SRCALPHA)
        surface.fill((18, 20, 28, 200))
        self.screen.blit(surface, rect.topleft)
        pygame.draw.rect(self.screen, (70, 90, 130), rect, 2, border_radius=6)
        w.text(self.screen, header, (rect.x + 10, rect.y + 6), size=17, color=w.TEXT,
               bold=True)
        y = rect.y + 28
        for text, colour in lines:
            w.text(self.screen, text, (rect.x + 12, y), size=16, color=colour)
            y += 20
        if not onboarding.panel_open:
            hint = t("quest.panel_more", hotkey=self.keys.label("help"))
            w.text(self.screen, hint, (rect.x, rect.bottom + 4), size=14, color=w.TEXT_DIM)

    def draw_waypoint_compass(self):
        """Distance and direction to the nearest mark (b13)."""
        me = self.me
        if me is None or not self.waypoints.items:
            return
        waypoint, distance = self.waypoints.nearest(me.x, me.y)
        if waypoint is None:
            return
        # внизу справа: сверху уже стоят города, страны и недавние события
        rect = pygame.Rect(SCREEN_WIDTH - 258, SCREEN_HEIGHT - 122, 246, 46)
        surface = pygame.Surface(rect.size, pygame.SRCALPHA)
        surface.fill((18, 20, 28, 190))
        self.screen.blit(surface, rect.topleft)
        pygame.draw.rect(self.screen, (150, 130, 60), rect, 2, border_radius=6)
        name = waypoint.get("name") or t("waypoint.unnamed")
        w.text(self.screen, name, (rect.x + 34, rect.y + 5), size=16,
               color=(255, 225, 130))
        w.text(self.screen, t("waypoint.distance",
                              n=int(distance / TILE_SIZE)), (rect.x + 34, rect.y + 24),
               size=14, color=w.TEXT_DIM)
        angle = math.atan2(waypoint["y"] - me.y, waypoint["x"] - me.x)
        centre = (rect.x + 18, rect.centery)
        tip = (centre[0] + int(11 * math.cos(angle)), centre[1] + int(11 * math.sin(angle)))
        left = (centre[0] + int(9 * math.cos(angle + 2.5)),
                centre[1] + int(9 * math.sin(angle + 2.5)))
        right = (centre[0] + int(9 * math.cos(angle - 2.5)),
                 centre[1] + int(9 * math.sin(angle - 2.5)))
        pygame.draw.polygon(self.screen, (255, 215, 90), (tip, left, right))

    def draw_connection_status(self):
        status = self.net.status
        color = w.GOOD if self.net.connected else w.WARN
        if self.auth_state == "error":
            status, color = self.auth_error, w.BAD
        label = w.font(14).render(status, True, w.TEXT)
        rect = pygame.Rect(10, 10, label.get_width() + 18, label.get_height() + 10)
        surface = pygame.Surface(rect.size, pygame.SRCALPHA)
        surface.fill((20, 22, 30, 220))
        self.screen.blit(surface, rect.topleft)
        pygame.draw.rect(self.screen, color, rect, 2, border_radius=5)
        self.screen.blit(label, (rect.x + 9, rect.y + 5))

        if self.auth_state == "error":
            hint = w.font(15).render(t("pause.menu"), True, w.TEXT_DIM)
            self.screen.blit(hint, (rect.x, rect.bottom + 6))

    def draw_victory_banner(self):
        """Golden banner for ~25 s after the game was won (b10)."""
        if not self.victory or time.time() - self.victory_seen > 25:
            return
        key = "victory.wonder" if self.victory.get("type") == "wonder" else "victory.capture"
        text = t(key, country=self.victory.get("country", "?"),
                 name=self.victory.get("player", "?"))
        rect = pygame.Rect(0, 0, SCREEN_WIDTH - 160, 58)
        rect.center = (SCREEN_WIDTH // 2, 96)
        pygame.draw.rect(self.screen, (70, 58, 22), rect, border_radius=8)
        pygame.draw.rect(self.screen, (255, 215, 0), rect, 3, border_radius=8)
        w.text(self.screen, text, rect.center, size=24, bold=True,
               color=(255, 230, 140), centered_in=rect)

    def draw_civ_summary(self):
        civ_state = getattr(self, "civ_state", None)
        if not civ_state:
            return
        x = SCREEN_WIDTH - 210
        y = 12
        w.text(self.screen, t("hud.cities"), (x, y), size=15, color=(255, 215, 0), bold=True)
        y += 20
        cities = civ_state.get("cities", {})
        if cities:
            for name, data in list(cities.items())[:6]:
                w.text(self.screen, f"- {name} [{data.get('tier', 1)}]", (x, y), size=14)
                y += 18
        else:
            w.text(self.screen, t("hud.none"), (x, y), size=14, color=w.TEXT_DIM)
            y += 18
        y += 8
        w.text(self.screen, t("hud.countries"), (x, y), size=15, color=(255, 215, 0), bold=True)
        y += 20
        countries = civ_state.get("countries", {})
        if countries:
            for name, data in list(countries.items())[:6]:
                techs = len(data.get("techs", []))
                age = data.get("age") or "stone"
                w.text(self.screen, f"- {name} [{t('age.' + age)} {techs}t]",
                       (x, y), size=14)
                y += 18
        else:
            w.text(self.screen, t("hud.none"), (x, y), size=14, color=w.TEXT_DIM)

    def draw_hotbar(self):
        slot = 52
        gap = 6
        total = HOTBAR_SIZE * slot + (HOTBAR_SIZE - 1) * gap
        start_x = SCREEN_WIDTH // 2 - total // 2
        y = SCREEN_HEIGHT - slot - 14
        for index in range(HOTBAR_SIZE):
            rect = pygame.Rect(start_x + index * (slot + gap), y, slot, slot)
            selected = index == self.hotbar_index
            pygame.draw.rect(self.screen, (46, 50, 64) if not selected else (70, 82, 108),
                             rect, border_radius=6)
            pygame.draw.rect(self.screen, w.ACCENT if selected else w.BORDER, rect,
                             3 if selected else 1, border_radius=6)
            item = self.hotbar[index]
            if item:
                icon = self.resources.get(item)
                if icon:
                    self.screen.blit(pygame.transform.smoothscale(icon, (36, 36)),
                                     (rect.centerx - 18, rect.centery - 20))
                else:
                    w.text(self.screen, item[:2].upper(), (rect.centerx - 10, rect.centery - 12),
                           size=18, color=w.TEXT)
                count = self.inventory.get(item, 0)
                w.text(self.screen, str(count), (rect.right - 16, rect.bottom - 18),
                       size=14, color=w.TEXT if count else w.BAD)
                maximum = item_durability(item)
                if maximum:
                    left = self.durability_for(item, maximum)
                    bar = pygame.Rect(rect.x + 6, rect.bottom - 9, rect.width - 12, 4)
                    pygame.draw.rect(self.screen, (60, 34, 34), bar, border_radius=2)
                    color = w.GOOD if left / maximum > 0.5 else (
                        w.WARN if left / maximum > 0.2 else w.BAD)
                    pygame.draw.rect(self.screen, color,
                                     (bar.x, bar.y, int(bar.width * left / maximum), 4),
                                     border_radius=2)
            w.text(self.screen, str(index + 1), (rect.x + 4, rect.y + 2), size=12,
                   color=w.TEXT_DIM)

        held = self.held_item()
        label = t("hud.in_hand", item=t(f"item.{held}")) if held else t("hud.empty_hand")
        w.text(self.screen, label, (SCREEN_WIDTH // 2, y - 24), size=16, color=w.TEXT,
               centered_in=pygame.Rect(SCREEN_WIDTH // 2 - 200, y - 34, 400, 20))

        player = self.me
        if player is not None:
            bar = pygame.Rect(SCREEN_WIDTH // 2 - 100, y - 52, 200, 14)
            pygame.draw.rect(self.screen, (60, 20, 20), bar, border_radius=5)
            pygame.draw.rect(self.screen, (70, 190, 90),
                             (bar.x, bar.y, int(bar.width * max(0, player.hp) / 100), bar.height),
                             border_radius=5)
            w.text(self.screen, f"{t('hud.hp')} {player.hp}/100",
                   (bar.centerx, bar.centery), size=13, centered_in=bar)

        player = self.me
        if player is not None:
            hunger_bar = pygame.Rect(SCREEN_WIDTH // 2 - 100, y - 36, 200, 10)
            pygame.draw.rect(self.screen, (64, 50, 20), hunger_bar, border_radius=4)
            pygame.draw.rect(self.screen, (230, 180, 60),
                             (hunger_bar.x, hunger_bar.y,
                              int(hunger_bar.width * max(0.0, min(100.0, player.hunger)) / 100),
                              hunger_bar.height), border_radius=4)
            w.text(self.screen, f"{t('hud.hunger')} {int(player.hunger)}%",
                   (hunger_bar.centerx, hunger_bar.centery - 12), size=12,
                   color=w.TEXT_DIM, centered_in=pygame.Rect(hunger_bar.x, hunger_bar.y - 16,
                                                             hunger_bar.width, 14))
            extras = []
            if player.armor:
                extras.append(t("hud.armor", n=int(player.armor)))
            if player.pets:
                extras.append(t("hud.pets", n=int(player.pets)))
            if extras:
                w.text(self.screen, "  ".join(extras),
                       (SCREEN_WIDTH // 2 + 120, y - 48), size=13, color=w.TEXT_DIM)
            season_name = t("season." + self.season) if self.season else ""
            clock = (f"{t('hud.day', day=self.day)} {season_name}  "
                     f"{self.hours():02d}:00 {t('weather.' + self.weather)}")
            w.text(self.screen, clock, (SCREEN_WIDTH // 2 - 220, y - 48), size=13,
                   color=w.TEXT_DIM)
            if self.ping:
                w.text(self.screen, f"{self.ping} ms", (SCREEN_WIDTH // 2 - 220, y - 30),
                       size=12, color=w.TEXT_DIM)

        if self.death_banner > 0:
            banner = pygame.Rect(0, SCREEN_HEIGHT // 3, SCREEN_WIDTH, 64)
            surface = pygame.Surface(banner.size, pygame.SRCALPHA)
            surface.fill((120, 20, 20, 180))
            self.screen.blit(surface, banner.topleft)
            w.text(self.screen, t("hud.died"), banner.center, size=26, bold=True,
                   centered_in=banner)

        if self.build_target:
            w.text(self.screen, t("hud.build_mode", name=t(f"structure.{self.build_target}")),
                   (SCREEN_WIDTH // 2, y - 74), size=16, color=w.WARN,
                   centered_in=pygame.Rect(SCREEN_WIDTH // 2 - 300, y - 84, 600, 20))

    def draw_notifications(self):
        if not self.notifications:
            return
        y = 80
        for entry in self.notifications[-6:]:
            color = entry.get("color") or w.TEXT
            label = w.font(17).render(entry["text"], True, color)
            surface = pygame.Surface((label.get_width() + 20, label.get_height() + 8),
                                     pygame.SRCALPHA)
            surface.fill((18, 20, 28, 200))
            x = SCREEN_WIDTH // 2 - surface.get_width() // 2
            self.screen.blit(surface, (x, y))
            self.screen.blit(label, (x + 10, y + 4))
            y += surface.get_height() + 4

    # --------------------------------------------------------------- b13: чат
    CHAT_COLOURS = {
        "global": (235, 235, 235),
        "local": (170, 235, 180),
        "country": (240, 210, 130),
        "whisper": (240, 170, 225),
        "server": (170, 200, 255),
    }

    def add_chat_line(self, author, text, channel="global", to=""):
        """One line of chat with the channel label in front (b13)."""
        channel = channel if channel in self.CHAT_COLOURS else "global"
        label_key = "chat.channel_server" if author == "server" else \
            f"chat.channel_{channel}"
        label = t(label_key)
        prefix = f"[{label}] " if label_key != "chat.channel_global" else ""
        if channel == "whisper" and to and author != "server":
            prefix += f"-> {to} "
        self.chat_messages.append(f"{prefix}{author}: {text}")
        self.chat_messages = self.chat_messages[-40:]
        colour = self.CHAT_COLOURS["server"] if author == "server" else \
            self.CHAT_COLOURS[channel]
        self.chat_colours.append(colour)
        self.chat_colours = self.chat_colours[-40:]

    def send_chat(self, text):
        """Send a message; `/g`, `/l`, `/c`, `/w <имя> <текст>` choose the channel.

        A bare `/g`, `/l` or `/c` switches the channel used from now on (and is
        remembered in config.json), so a player does not have to type a prefix
        every time. Unknown commands such as `/who` still go to the server.
        """
        text = text.strip()
        if not text:
            return None
        lowered = text.lower()
        shortcuts = {"g": "global", "l": "local", "c": "country"}
        if len(lowered) >= 2 and lowered[0] == "/" and lowered[1] in shortcuts and \
                (len(lowered) == 2 or lowered[2] == " "):
            body = text[2:].strip()
            if not body:                       # голый /g, /l или /c — сменить канал
                self.chat_channel = shortcuts[lowered[1]]
                self.config.set("chat_channel", self.chat_channel)
                self.config.save()
                self.notify(t("chat.channel_now",
                              channel=t(f"chat.channel_{self.chat_channel}")), w.ACCENT)
                return self.chat_channel
            channel = shortcuts[lowered[1]]     # /g текст — разовое сообщение
            self.net.send_dict({"type": "chat", "text": body, "channel": channel})
            self.add_chat_line(self.player_name, body, channel)
            return channel
        if lowered.startswith("/w "):
            parts = text.split(" ", 2)
            if len(parts) < 3:
                self.notify(t("chat.whisper_usage"), w.WARN)
                return None
            who, message = parts[1], parts[2]
            self.net.send_dict({"type": "chat", "text": message, "channel": "whisper",
                                "to": who})
            self.add_chat_line(self.player_name, message, "whisper", to=who)
            return "whisper"
        channel = self.chat_channel
        # a server command (`/who`, `/city`, ...) always goes out as a normal
        # message: the server answers it before anybody sees the text
        self.net.send_dict({"type": "chat", "text": text, "channel": channel})
        self.add_chat_line(self.player_name, text, channel)
        return channel

    def draw_chat(self):
        if not self.chat_messages and not self.chat_active:
            return
        y = SCREEN_HEIGHT - 210
        colours = self.chat_colours[-len(self.chat_messages[-8:]):]
        for index, message in enumerate(self.chat_messages[-8:]):
            colour = colours[index] if index < len(colours) else (235, 235, 235)
            label = w.font(15).render(message, True, colour)
            surface = pygame.Surface((label.get_width() + 12, label.get_height() + 4),
                                     pygame.SRCALPHA)
            surface.fill((0, 0, 0, 120))
            self.screen.blit(surface, (10, y))
            self.screen.blit(label, (16, y + 2))
            y += label.get_height() + 6
        if self.chat_active:
            rect = pygame.Rect(10, SCREEN_HEIGHT - 34, 460, 26)
            pygame.draw.rect(self.screen, (0, 0, 0), rect)
            pygame.draw.rect(self.screen, w.ACCENT, rect, 2)
            value = self.chat_input or t("chat.placeholder_channel",
                                         channel=t(f"chat.channel_{self.chat_channel}"))
            color = w.TEXT if self.chat_input else w.TEXT_DIM
            self.screen.blit(w.font(16).render(value, True, color), (16, rect.y + 4))

    def draw_player_list(self):
        overlay = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 150))
        self.screen.blit(overlay, (0, 0))
        rect = pygame.Rect(100, 100, SCREEN_WIDTH - 200, SCREEN_HEIGHT - 200)
        top = w.panel(self.screen, rect, f"{t('hud.players_online')}: {len(self.players)}")
        y = top + 6
        for label_key, x in (("ID", 4), ("Name", 90), ("HP", 360), ("Hand", 460)):
            w.text(self.screen, label_key, (rect.x + 20 + x, y), size=16, color=w.TEXT_DIM)
        y += 26
        pygame.draw.line(self.screen, w.BORDER, (rect.x + 12, y), (rect.right - 12, y))
        y += 8
        for pid, player in self.players.items():
            suffix = " (you)" if pid == self.my_id else ""
            w.text(self.screen, str(pid), (rect.x + 24, y), size=16)
            w.text(self.screen, f"{player.name}{suffix}", (rect.x + 110, y), size=16)
            w.text(self.screen, f"{player.hp}", (rect.x + 380, y), size=16)
            hand = t(f"item.{player.selected}") if player.selected else "-"
            w.text(self.screen, hand, (rect.x + 480, y), size=16, color=w.TEXT_DIM)
            y += 26

    def draw_pause(self):
        overlay = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 150))
        self.screen.blit(overlay, (0, 0))
        panel = pygame.Rect(SCREEN_WIDTH // 2 - 190, SCREEN_HEIGHT // 2 - 170, 380, 340)
        w.panel(self.screen, panel, t("pause.title"))
        mouse = pygame.mouse.get_pos()
        buttons = [
            (self.pause_resume, t("pause.resume"), (50, 110, 60), (65, 145, 78)),
            (self.pause_settings, t("pause.settings"), (60, 80, 140), (75, 100, 175)),
            (self.pause_menu, t("pause.menu"), (105, 55, 55), (140, 70, 70)),
        ]
        for rect, label, base, hover in buttons:
            w.button(self.screen, rect, label, base_color=base, hover_color=hover,
                     mouse_pos=mouse)

    def _draw_light_preview(self, tile_x, tile_y):
        """While placing a light source, show how far it will shine."""
        radius = get_light(self.build_target) if self.build_target else 0
        if not radius:
            return
        centre = (int(tile_x * TILE_SIZE + TILE_SIZE / 2 - self.camera.x),
                  int(tile_y * TILE_SIZE + TILE_SIZE / 2 - self.camera.y))
        halo = pygame.Surface((radius * 2, radius * 2), pygame.SRCALPHA)
        pygame.draw.circle(halo, (255, 220, 130, 46), (radius, radius), radius)
        pygame.draw.circle(halo, (255, 220, 130, 90), (radius, radius), 3)
        self.screen.blit(halo, (centre[0] - radius, centre[1] - radius))

    def _draw_build_ghost(self):
        mouse = pygame.mouse.get_pos()
        gx = int((mouse[0] + self.camera.x) // TILE_SIZE)
        gy = int((mouse[1] + self.camera.y) // TILE_SIZE)
        w_tiles, h_tiles = get_size(self.build_target)
        okay = self.can_build_here(gx, gy)
        color = (90, 220, 120) if okay else (230, 90, 90)
        rect = pygame.Rect(int(gx * TILE_SIZE - self.camera.x), int(gy * TILE_SIZE - self.camera.y),
                           TILE_SIZE * w_tiles, TILE_SIZE * h_tiles)
        surface = pygame.Surface(rect.size, pygame.SRCALPHA)
        surface.fill((*color, 70))
        self.screen.blit(surface, rect.topleft)
        pygame.draw.rect(self.screen, color, rect, 2)
        if not self.is_night():
            self._draw_light_preview(gx, gy)
        icon = self.resources.get(self.build_target)
        if icon:
            icon = pygame.transform.smoothscale(icon, rect.size)
            icon.set_alpha(170)
            self.screen.blit(icon, rect.topleft)
        if not okay:
            w.text(self.screen, t("hud.build_bad"), (rect.centerx, rect.y - 18), size=15,
                   color=w.BAD, centered_in=pygame.Rect(rect.centerx - 100, rect.y - 26, 200, 16))

    # -------------------------------------------------------------- b8 actions
    def use_action(self):
        """E: gather, or cast a line when a fishing rod is in hand."""
        if self.held_item() == "fishing_rod" or \
                ("fishing_rod" in self.inventory and self.water_near()):
            self.net.send_dict({"type": "fish"})
            self.audio.play("pickup")
            return
        self.net.send_dict({"type": "gather"})

    def market_near(self, tiles=3) -> bool:
        """A market building close enough to trade at (b9)."""
        me = self.me
        if me is None:
            return False
        for building in self.world.buildings.values():
            if building.get("type") != "market":
                continue
            bx = building["x"] * TILE_SIZE + TILE_SIZE * building.get("w", 1) / 2
            by = building["y"] * TILE_SIZE + TILE_SIZE * building.get("h", 1) / 2
            if max(abs(bx - me.x), abs(by - me.y)) / TILE_SIZE <= tiles:
                return True
        return False

    def water_near(self, tiles=2) -> bool:
        """Is there water within a couple of tiles? (for the fishing affordance)"""
        me = self.me
        if me is None:
            return False
        gx, gy = int(me.x // TILE_SIZE), int(me.y // TILE_SIZE)
        for dy in range(-tiles, tiles + 1):
            for dx in range(-tiles, tiles + 1):
                if self.world.is_water(gx + dx, gy + dy):
                    return True
        return False

    def use_medkit(self):
        """H: use a medkit (or a bandage) - they heal, and cure poisoning."""
        for item in ("medkit", "bandage"):
            if self.inventory.get(item, 0) > 0:
                self.net.send_dict({"type": "use", "item": item})
                return
        self.notify(t("notify.cannot_use"), w.WARN)

    def build_menu(self):
        """B: open the crafting screen right on the Buildings tab."""
        menu = self.crafting_menu
        if not menu.visible:
            menu.toggle()
        menu.tab = "buildings"

    def eat_best_food(self):
        """Eat the most filling food in the inventory (or the one in hand)."""
        held = self.held_item()
        candidates = []
        for item, count in self.inventory.items():
            if count <= 0:
                continue
            food = item_food(item)
            if food:
                candidates.append((food.get("hunger", 0) + food.get("heal", 0), item))
        if not candidates:
            self.notify(t("notify.cannot_eat"), w.WARN)
            return
        held_food = item_food(held) if held else None
        item = held if held_food else max(candidates)[1]
        self.net.send_dict({"type": "eat", "item": item})
        self.audio.play("eat")

    def equip_best_armor(self):
        """Put on the best armor piece we are carrying (G)."""
        for item, count in sorted(self.inventory.items(),
                                  key=lambda entry: -entry[1]):
            if count > 0 and item.startswith(("iron_", "leather_")) and \
                    item.split("_", 1)[1] in ("helmet", "chestplate", "leggings",
                                              "boots"):
                self.net.send_dict({"type": "equip", "item": item})
                return
        self.notify(t("notify.cannot_equip"), w.WARN)

    def tame_at_cursor(self):
        mouse = pygame.mouse.get_pos()
        animal_id, _animal = self.animal_at(mouse)
        if animal_id is None:
            _animal, animal_id = self.nearest_animal(70)
        if animal_id is None:
            self.notify(t("notify.no_animal"), w.WARN)
            return
        self.net.send_dict({"type": "tame", "animal_id": animal_id})

    def repair_at_cursor(self):
        mouse = pygame.mouse.get_pos()
        building = self.building_at(mouse)
        if building is None:
            self.notify(t("notify.no_building"), w.WARN)
            return
        self.net.send_dict({"type": "repair", "x": building["x"], "y": building["y"],
                            "units": 10})

    # ------------------------------------------------------------------ events
    def handle_event(self, event):
        if self.keys_menu.visible:
            if self.keys_menu.handle_event(event):
                return
        if self.help_menu.handle_event(event):
            return
        if self.settings_menu.handle_event(event):
            return
        if self.paused:
            self._handle_pause_event(event)
            return

        if event.type == pygame.MOUSEBUTTONDOWN:
            if self.trade_menu.visible and event.button in (4, 5):
                self.trade_menu.handle_wheel(event)
                return
            if event.button == 4 and not self._any_menu_open():      # wheel up
                self.select_hotbar(self.hotbar_index - 1)
                return
            if event.button == 5 and not self._any_menu_open():      # wheel down
                self.select_hotbar(self.hotbar_index + 1)
                return

            consumed = False
            for menu in self._menu_list():
                if menu.visible and not isinstance(menu, SettingsMenu):
                    menu.handle_click(event)
                    consumed = True
            if consumed:
                return

            if event.button == 1:
                if self.build_target:
                    self._place_building(event.pos)
                else:
                    self.left_click(event.pos)
            elif event.button == 3:
                if self.build_target:
                    self.cancel_build()
                else:
                    self.right_click(event.pos)

        if event.type == pygame.KEYDOWN:
            self._handle_key(event)

    def _handle_key(self, event):
        if self.chat_active:
            if event.key == pygame.K_RETURN:
                if self.chat_input:
                    self.send_chat(self.chat_input)
                    self.chat_input = ""
                self.chat_active = False
            elif event.key == pygame.K_ESCAPE:
                self.chat_input = ""
                self.chat_active = False
            elif event.key == pygame.K_BACKSPACE:
                self.chat_input = self.chat_input[:-1]
            elif getattr(event, "unicode", "") and event.unicode.isprintable():
                self.chat_input += event.unicode
            return

        if self.civ_menu.visible and self.civ_menu.active_input:
            self.civ_menu.handle_input(event)
            return

        if pygame.K_1 <= event.key <= pygame.K_9:
            self.select_hotbar(event.key - pygame.K_1)
            return

        keys = self.keys
        shifted = bool(getattr(event, "mod", 0) & pygame.KMOD_SHIFT)

        if keys.matches(event, "up") or keys.matches(event, "down") or \
                keys.matches(event, "left") or keys.matches(event, "right"):
            return                                  # movement is handled by polling

        if keys.matches(event, "pause"):
            if self.build_target:
                self.cancel_build()
            elif self._any_menu_open():
                for menu in self._menu_list():
                    menu.visible = False
                self.keys_menu.close()
            else:
                self.open_pause()
        elif keys.matches(event, "chat"):
            self.chat_active = True
        elif keys.matches(event, "craft"):
            self.crafting_menu.toggle()
        elif keys.matches(event, "inventory"):
            self.inventory_menu.toggle()
        elif keys.matches(event, "civ"):
            self.civ_menu.toggle()
        elif keys.matches(event, "interact"):
            self.interact_at_cursor()
        elif keys.matches(event, "use"):
            self.use_action()
        elif keys.matches(event, "medkit"):
            self.use_medkit()
        elif keys.matches(event, "build"):
            self.build_menu()
        elif keys.matches(event, "eat"):
            self.eat_best_food()
        elif keys.matches(event, "tasks"):
            self.tasks_menu.toggle()
        elif keys.matches(event, "trade"):
            self.trade_menu.toggle()
        elif keys.matches(event, "minimap"):
            self.minimap_open = not self.minimap_open
        elif keys.matches(event, "tame"):
            self.tame_at_cursor()
        elif keys.matches(event, "repair"):
            self.repair_at_cursor()
        elif keys.matches(event, "armor"):
            self.equip_best_armor()
        elif keys.matches(event, "help"):
            self.help_menu.toggle()
        elif keys.matches(event, "waypoint"):
            if shifted:
                self.remove_nearest_waypoint()
            else:
                self.add_waypoint()
        elif keys.matches(event, "sort"):
            if shifted:
                self.autofill_hotbar()
            else:
                self.cycle_inventory_sort()
        elif event.key == pygame.K_F11:
            self.config.set("fullscreen", not self.config.get("fullscreen"))
            self.config.save()
            self.apply_display_settings()

    # ------------------------------------------------------------- b13 helpers
    def add_waypoint(self, name="", silent=False):
        """P: put a mark where the player stands right now."""
        me = self.me
        if me is None:
            return None
        if not name:
            index = len(self.waypoints.items) + 1
            name = t("waypoint.default", n=index)
        waypoint = self.waypoints.add(me.x, me.y, name)
        self.audio.play("pickup")
        if not silent:
            self.notify(t("waypoint.added", name=name), w.GOOD)
        return waypoint

    def remove_nearest_waypoint(self):
        """Shift+P: delete the mark you are standing next to."""
        me = self.me
        if me is None:
            return None
        removed = self.waypoints.remove_nearest(me.x, me.y, radius=6 * TILE_SIZE)
        if not removed:
            self.notify(t("waypoint.none_nearby"), w.WARN)
            return None
        self.notify(t("waypoint.removed", name=removed.get("name") or "?"), w.WARN)
        return removed

    def cycle_inventory_sort(self):
        """O: how the pack is ordered (by category, by count, by name)."""
        order = ("category", "count", "name")
        index = order.index(self.inventory_sort) if self.inventory_sort in order else 0
        self.inventory_sort = order[(index + 1) % len(order)]
        self.config.set("inventory_sort", self.inventory_sort)
        self.config.save()
        self.notify(t("inv.sort_label", mode=t(f"inv.sort_{self.inventory_sort}")),
                    w.ACCENT)
        return self.inventory_sort

    def autofill_hotbar(self):
        """Shift+O: put tools and food into the hotbar, count each item once."""
        ordered = self.sorted_inventory()
        tools = [item for item, count in ordered
                 if ITEMS.get(item, {}).get("type") in ("tool", "weapon")
                 or item_slot(item)]
        food = [item for item, count in ordered if item_food(item)]
        blocks = [item for item, count in ordered
                  if ITEMS.get(item, {}).get("type") == "block"]
        rest = [item for item, _count in ordered
                if item not in tools and item not in food and item not in blocks]
        wanted = (tools + food + blocks + rest)[:HOTBAR_SIZE]
        for index in range(HOTBAR_SIZE):
            self.hotbar[index] = wanted[index] if index < len(wanted) else None
        self.config.set("hotbar", self.hotbar)
        self.config.save()
        self.notify(t("inv.hotbar_filled", n=len(wanted)), w.GOOD)
        return wanted

    def sorted_inventory(self):
        """The pack in the order the player chose (b13), without empty stacks."""
        inventory = self.inventory or {}
        mode = self.inventory_sort
        pairs = [(item, count) for item, count in inventory.items() if count > 0]

        def category(item):
            return ITEMS.get(item, {}).get("category", "z")

        if mode == "count":
            return sorted(pairs, key=lambda pair: (-pair[1], pair[0]))
        if mode == "name":
            return sorted(pairs, key=lambda pair: (t(f"item.{pair[0]}"), pair[0]))
        return sorted(pairs, key=lambda pair: (category(pair[0]), pair[0]))

    # ------------------------------------------------------------------ pause
    def open_pause(self):
        self.paused = True
        panel = pygame.Rect(SCREEN_WIDTH // 2 - 190, SCREEN_HEIGHT // 2 - 170, 380, 340)
        self.pause_resume = pygame.Rect(panel.x + 40, panel.y + 70, 300, 52)
        self.pause_settings = pygame.Rect(panel.x + 40, panel.y + 136, 300, 52)
        self.pause_menu = pygame.Rect(panel.x + 40, panel.y + 202, 300, 52)

    def _handle_pause_event(self, event):
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self.paused = False
            return
        if event.type == pygame.MOUSEBUTTONDOWN:
            if self.pause_resume.collidepoint(event.pos):
                self.paused = False
            elif self.pause_settings.collidepoint(event.pos):
                self.settings_menu.open()
            elif self.pause_menu.collidepoint(event.pos):
                self.exit_to_menu = True

    # ------------------------------------------------------------- hotbar logic
    def select_hotbar(self, index):
        index %= HOTBAR_SIZE
        self.hotbar_index = index
        item = self.hotbar[index]
        if item is None:
            self.net.send_dict({"type": "select_item", "item": None})
            return
        if self.inventory.get(item, 0) <= 0:
            self.notify(t("notify.no_such_item"), w.WARN)
            return
        self.net.send_dict({"type": "select_item", "item": item})
        me = self.me
        if me is not None:
            me.selected = item

    def set_hotbar_item(self, index, item):
        """Used by the inventory screen: put an item into a hotbar slot."""
        if 0 <= index < HOTBAR_SIZE:
            self.hotbar[index] = item
            self.config.set("hotbar", self.hotbar)
            self.config.save()

    def _autofill_hotbar(self):
        """Make sure everything the player owns is reachable with 1..9."""
        inventory = self.inventory
        changed = False
        for item, count in inventory.items():
            if count <= 0 or item in self.hotbar:
                continue
            try:
                slot = self.hotbar.index(None)
            except ValueError:
                break
            self.hotbar[slot] = item
            changed = True
        for index, item in enumerate(self.hotbar):
            if item and inventory.get(item, 0) <= 0:
                self.hotbar[index] = None      # drop items we no longer have
                changed = True
        if changed:
            self.config.set("hotbar", self.hotbar)
            self.config.save()
            self._sync_selected_item()

    def _sync_selected_item(self, initial=False):
        item = self.held_item()
        if initial and item is None:
            return
        self.net.send_dict({"type": "select_item", "item": item})

    # --------------------------------------------------------------- interactions
    def animal_at(self, screen_pos):
        wx, wy = screen_pos[0] + self.camera.x, screen_pos[1] + self.camera.y
        for aid, animal in self.animals.items():
            if abs(animal["x"] - wx) < 24 and abs(animal["y"] - wy) < 24:
                return aid, animal
        return None, None

    def left_click(self, pos):
        wx, wy = pos[0] + self.camera.x, pos[1] + self.camera.y
        # 1. an animal under the cursor
        animal_id, _animal = self.animal_at(pos)
        if animal_id is not None:
            self.net.send_dict({"type": "attack_animal", "animal_id": animal_id})
            self.audio.play("hit")
            return
        # 2. a player under the cursor (only if the weapon can reach)
        for pid, player in self.players.items():
            if pid == self.my_id:
                continue
            if abs(player.x - wx) < TILE_SIZE and abs(player.y - wy) < TILE_SIZE:
                me = self.me
                reach = item_range(self.held_item()) if self.held_item() else 34
                if me is not None and reach:
                    distance = ((player.x - me.x) ** 2 + (player.y - me.y) ** 2) ** 0.5
                    if distance > reach:
                        self.notify(t("notify.out_of_range"), w.WARN)
                        return
                self.net.send_dict({"type": "attack", "target_id": pid})
                return
        # 3. a foreign building under the cursor
        building = self.building_at(pos)
        if building is not None and building.get("owner") != self.my_id:
            self.net.send_dict({"type": "attack_building", "x": building["x"],
                                "y": building["y"]})
            return
        self.net.send_dict({"type": "gather"})
        self.audio.play("chop")

    def right_click(self, pos):
        building = self.building_at(pos)
        if building is None:
            animal_id, animal = self.animal_at(pos)
            if animal_id is not None:
                self.net.send_dict({"type": "tame", "animal_id": animal_id})
            return
        kind = building["type"]
        if kind == "door":
            self.net.send_dict({"type": "toggle_door", "x": building["x"],
                                "y": building["y"]})
            return
        if is_storage(kind):
            self.net.send_dict({"type": "chest_take", "x": building["x"],
                                "y": building["y"], "item": "__open__", "count": 0})
            self.chest_menu.open(building["x"], building["y"], building.get("items", {}))
            return
        if is_market(kind):
            self.trade_menu.toggle()
            return
        if building.get("owner") == self.my_id:
            self.net.send_dict({"type": "repair", "x": building["x"], "y": building["y"],
                                "units": 10})
            return
        if kind == "town_center":
            self.research_menu.open("city")
        elif kind == "research_table":
            self.research_menu.open("country")
        elif kind == "furnace":
            self.smelting_menu.toggle()
        elif kind == "crafting_table" or get_station(kind) == "crafting_table":
            self.crafting_menu.toggle()
        elif get_station(kind) == "advanced_workbench":
            self.crafting_menu.toggle()

    def interact_at_cursor(self):
        """F: interact with whatever building is under the mouse."""
        pos = pygame.mouse.get_pos()
        if self.building_at(pos) is not None:
            self.right_click(pos)

    def building_at(self, screen_pos):
        wx, wy = screen_pos[0] + self.camera.x, screen_pos[1] + self.camera.y
        for building in self.world.buildings.values():
            rect = pygame.Rect(building["x"] * TILE_SIZE, building["y"] * TILE_SIZE,
                               TILE_SIZE * building.get("w", 1), TILE_SIZE * building.get("h", 1))
            if rect.collidepoint(wx, wy):
                return building
        return None

    # ------------------------------------------------------------ build system
    def enter_build_mode(self, structure):
        if structure not in STRUCTURES:
            return
        self.build_target = structure
        self.build_hint_timer = 240
        for menu in self._menu_list():
            menu.visible = False
        self.inventory_menu.visible = False

    def cancel_build(self):
        if self.build_target:
            self.notify(t("build.cancelled"), w.WARN)
        self.build_target = None

    def can_build_here(self, gx, gy) -> bool:
        """Client-side prediction; the server has the final word."""
        if not self.build_target:
            return False
        width, height = get_size(self.build_target)
        world = self.world
        if gx < 0 or gy < 0 or gx + width > world.width or gy + height > world.height:
            return False
        for dx in range(width):
            for dy in range(height):
                # the same rule as the server (b11): rock never, water only for
                # a bridge - this used to refuse a bridge on water and made the
                # player see "you cannot build here" while the server was happy
                if world.blocks_building(gx + dx, gy + dy, self.build_target):
                    return False
                for building in world.buildings.values():
                    bx, by = building["x"], building["y"]
                    if bx <= gx + dx < bx + building.get("w", 1) and \
                       by <= gy + dy < by + building.get("h", 1):
                        return False
        if not can_afford(self.build_target, self.inventory):
            return False
        me = self.me
        if me is not None:
            distance = max(abs(gx * TILE_SIZE + TILE_SIZE / 2 - me.x),
                           abs(gy * TILE_SIZE + TILE_SIZE / 2 - me.y)) / TILE_SIZE
            if distance > INTERACT_RANGE_TILES:
                return False
        return True

    def _place_building(self, screen_pos):
        gx = int((screen_pos[0] + self.camera.x) // TILE_SIZE)
        gy = int((screen_pos[1] + self.camera.y) // TILE_SIZE)
        self.net.send_dict({"type": "build", "structure": self.build_target,
                            "x": gx, "y": gy})
        # keep a hint until the server answers
        if not self.can_build_here(gx, gy):
            self.notify(t("hud.build_bad"), w.WARN)

    # ------------------------------------------------------------------- build
    def _build(self):
        try:
            from shared.build import BUILD
            return BUILD
        except Exception:
            return "b?"
