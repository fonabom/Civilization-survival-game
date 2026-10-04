"""Authoritative game server.

Run with `python run_server.py` (options: --port, --save, --accounts).

The world lives in memory (restarting the server starts a fresh world unless
--save is given), while player accounts and their progress are always kept in
`server_data/accounts.json`.

Notifications are sent as translation keys + arguments, e.g.
    {"type": "notification", "key": "notify.gathered", "args": {"n": 3, "item": "item.wood"}}
so every player sees them in their own language.
"""

import argparse
import os
import random
import re
import signal
import socket
import threading
from pathlib import Path
import time

from server.accounts import DEFAULT_ACCOUNTS_PATH, AccountStore
from shared import tasks as task_module
from shared.roles import MAX_TAX, ROLE_ORDER, WARRIOR_DAMAGE_BONUS
from shared.techs import (TECHS, MAX_CITY_TIER, age_at_least, age_of, tech_cost,
                          tech_requires, tier_cost)
from server.persistence import WorldStore
from server.world_state import (ANIMAL_AGGRO_RANGE, ANIMAL_ATTACK_COOLDOWN,
                                ANIMAL_IDLE, ANIMAL_TYPES, CAVE_YIELD_BONUS,
                                PACK_ALERT_RANGE, TILE_SIZE, WorldState)
from shared.build import BUILD
from shared.protocol import Protocol, encode
from shared.items import (CRAFTING_RECIPES, ITEMS, RESOURCE_YIELD, SMELTING_RECIPES,
                          craftable_amount, is_food, item_ammo, item_armor_points,
                          item_block, item_cooldown, item_damage, item_durability,
                          item_efficiency, item_food, item_poison, item_range, item_slot,
                          item_targets, pay_for_craft, recipe_station)
from shared.structures import (REPAIR_PER_UNIT, STATION_RANGE, STRUCTURES,
                               can_afford as can_build, get_age as structure_age,
                               get_cost, get_heal, get_hp, get_power, get_size,
                               get_station, get_storage, get_tech, is_market,
                               is_storage, is_walkable, is_wonder, missing_for,
                               needs_power, pay_for)

HOST = os.environ.get("CIV_HOST", "0.0.0.0")
PORT = int(os.environ.get("CIV_PORT", "5555"))
MAX_MOVE_STEP = 12            # px per move packet
POISON_SECONDS = 8            # how long bad food keeps hurting (b10)
HOSPITAL_TICK = 5.0           # seconds between hospital heals (b10)
FISH_REACH = 2               # tiles: how far from the shore you may cast
FISH_COOLDOWN = 2.5          # seconds between two catches
# rain slows walking down (b9), fog keeps the speed but hides the light;
# b11 moved the numbers into shared/speed.py so the client predicts the same
from shared.seasons import (forage_bonus as season_forage, regrowth as season_regrowth,
                            season_of, weather_bag)
from shared.speed import SWIM_SPEED, WEATHER_SPEED
MAX_BUILD_DISTANCE = 8        # tiles, how far from the player you may build
STATE_RATE = 15               # world broadcasts per second
RESOURCE_REGEN_INTERVAL = 60
DRILL_INTERVAL = 5
PUMP_INTERVAL = 12
SAVE_INTERVAL = 60
MAX_NAME_LENGTH = 16
AUTH_TIMEOUT = 30             # seconds to log in after connecting
MAX_CRAFT_COUNT = 64
MAX_CHAT_LENGTH = 200

NAME_RE = re.compile(r"^[A-Za-z0-9_ ]{2,16}$")

# Defaults for server_config.json (see CONFIG_FILE). Players can change them
# without touching the code - that is what everybody asks for first.
DEFAULT_CONFIG = {
    "pvp": True,                 # players can hurt each other
    "day_length": 600,           # seconds for a full day+night
    "hunger_rate": 1.0,          # 1.0 = normal, 0 = hunger off
    "resource_rate": 1.0,        # extra resources per gather
    "durability": True,          # tools wear out
    "tasks": True,               # tasks / achievements and their rewards
    "seasons": True,             # b13: spring -> summer -> autumn -> winter
    "days_per_season": 3,        # in-game days in one season
    "weather": True,             # rain and fog, with their effects
    "chat_radius": 12,           # tiles you can hear a local message from (b13)
    "swim": True,                # players may wade into water (slowly)
    "swim_speed": 0.4,           # how fast they move there (0.4 = wading)
    "taxes": True,               # city leaders may tax the gathered resources
    "victory": True,             # a game goal: capture every city or build a wonder
    "animals": True,             # animals live in the world
    "wolves": True,              # wolves hunt players at night
    "animal_respawn": 45,        # seconds between animal top-ups
    "start_kit": {"wood": 5, "stone": 5},
    "max_players": 24,
    "save_interval": 60,
}
CONFIG_FILE = "server_config.json"


def load_config(path=None) -> dict:
    """server_config.json next to the game, merged over DEFAULT_CONFIG."""
    import json as _json
    config = dict(DEFAULT_CONFIG)
    candidates = [Path(path)] if path else [Path(CONFIG_FILE),
                                            Path(__file__).resolve().parent.parent / CONFIG_FILE]
    for candidate in candidates:
        try:
            if candidate and candidate.is_file():
                config.update(_json.loads(candidate.read_text(encoding="utf-8")))
                print(f"[config] loaded {candidate}")
                break
        except (OSError, ValueError) as exc:
            print(f"[config] {candidate} is broken ({exc}); using defaults")
    return config


def local_ip() -> str:
    """Best-effort LAN address of this machine."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


class GameServer:
    def __init__(self, host: str = HOST, port: int = PORT, world: WorldState = None,
                 save_path=None, accounts_path=DEFAULT_ACCOUNTS_PATH, config=None):
        self.config = config if config is not None else load_config()
        self.host = host
        self.port = port
        self.world = world or WorldState()
        self.store = WorldStore(save_path)
        self.accounts = AccountStore(accounts_path) if accounts_path else None
        self.clients = {}                 # player_id -> socket
        self.clients_lock = threading.Lock()
        self.sent_rev = {"resources": 0, "buildings": 0, "civs": 0, "animals": 0,
                         "trades": 0}
        self.sent_inv_rev = {}            # player_id -> last inventory revision sent
        self.player_counter = 0
        self.running = True
        self.last_save = time.time()
        self.world_time = 0.25          # 0..1, 0.25 = morning
        self.day = 1                    # 1-based in-game day (b13 seasons)
        self.seasons_on = bool(self.config.get("seasons", True))
        self.days_per_season = max(1, int(self.config.get("days_per_season", 3) or 3))
        self.weather = "clear"
        self.weather_until = 0.0
        self.victory = None          # {"type", "country", "player", "at"} after a win
        self.tax_carry = {}          # (player, city, item) -> part of a unit not yet taxed
        self.last_animal_topup = time.time()
        # b11: water is walkable (slowly) unless the server says otherwise
        self.world.swim = bool(self.config.get("swim", True))
        self.world.swim_speed = float(self.config.get("swim_speed", SWIM_SPEED) or SWIM_SPEED)
        # b13: the world knows the season, so movement and growth can follow it
        self.world.season_enabled = self.seasons_on
        self.world.season = season_of(self.day, self.days_per_season, self.seasons_on)
        self.loaded_save = self.store.load(self.world)

    # ------------------------------------------------------------------ socket
    def _send(self, conn, message: dict) -> bool:
        try:
            conn.sendall(encode(message))
            return True
        except (OSError, ValueError):
            return False

    def broadcast(self, message: dict, exclude_id=None):
        payload = encode(message)
        with self.clients_lock:
            targets = [(pid, conn) for pid, conn in self.clients.items() if pid != exclude_id]
        for _pid, conn in targets:
            try:
                conn.sendall(payload)
            except OSError:
                pass  # the owning thread cleans up

    def notify(self, conn, key: str, **args):
        """Send a translated notification: notify(conn, "notify.gathered", n=2, item="item.wood")."""
        self._send(conn, {"type": "notification", "key": key, "args": args})

    def notify_saved(self, conn, **args):
        self.notify(conn, "notify.saved", **args)

    # ------------------------------------------------------------------- state
    def _players_payload(self) -> dict:
        with self.world.lock:
            return {
                pid: {"x": p["x"], "y": p["y"], "name": p.get("name", f"Player {pid}"),
                      "hp": int(p.get("hp", 100)), "hunger": int(p.get("hunger", 100)),
                      "armor": self.armor_points(p),
                      "armor_items": dict(p.get("armor", {})),
                      "selected": p.get("selected"),
                      "pets": len(p.get("pets", []))}
                for pid, p in self.world.players.items()
            }

    def light_sources(self) -> list:
        """Torch/campfire lights, dimmed by fog (b9 weather)."""
        lights = self.world.light_sources()
        if self.config.get("weather", True) and self.weather == "fog":
            lights = [(x, y, int(radius * 0.55)) for x, y, radius in lights]
        return lights

    def _state_payload(self, full: bool = False) -> dict:
        msg = {"type": "state", "players": self._players_payload()}
        if full or self.sent_rev["resources"] != self.world.rev["resources"]:
            with self.world.lock:
                msg["resources"] = dict(self.world.resources)
            self.sent_rev["resources"] = self.world.rev["resources"]
        if full or self.sent_rev["buildings"] != self.world.rev["buildings"]:
            with self.world.lock:
                msg["buildings"] = {k: dict(v) for k, v in self.world.buildings.items()}
            self.sent_rev["buildings"] = self.world.rev["buildings"]
        if full or self.sent_rev["civs"] != self.world.rev["civs"]:
            msg["civs"] = self.world.civs.get_state()
            researched = {}
            for name, country in self.world.civs.countries.items():
                for tech in getattr(country, "techs", []):
                    researched.setdefault(tech, []).append(name)
            msg["civs"]["techs_available"] = {
                code: {"cost": tech_cost(code), "requires": tech_requires(code),
                       "unlocks": TECHS[code].get("unlocks", {}),
                       "researched": code in researched,
                       "researched_by": researched.get(code, [])}
                for code in TECHS}
            msg["civs"]["tier_costs"] = {str(tier): tier_cost(tier)
                                         for tier in range(2, MAX_CITY_TIER + 1)}
            # b10: what age every country is in (menu + wonder requirement)
            for name, country in msg["civs"]["countries"].items():
                country["age"] = age_of(country.get("techs", []))
            self.sent_rev["civs"] = self.world.rev["civs"]
        if full or self.sent_rev["animals"] != self.world.rev.get("animals", 0):
            msg["animals"] = self.world.animal_payload()
            self.sent_rev["animals"] = self.world.rev.get("animals", 0)
        if full or self.sent_rev["trades"] != self.world.rev.get("trades", 0):
            msg["trades"] = self.world.trade_payload()
            self.sent_rev["trades"] = self.world.rev.get("trades", 0)
        msg["time"] = round(self.world_time, 4)
        msg["weather"] = self.weather
        msg["season"] = self.world.season if self.seasons_on else "summer"
        msg["day"] = self.day
        msg["lights"] = self.light_sources()
        if self.victory is not None:
            msg["victory"] = dict(self.victory)
        return msg

    def broadcast_state(self):
        payload = self._state_payload()
        if "buildings" in payload:
            payload = self._state_payload_for_everyone(payload)
            return
        self.broadcast(payload)

        with self.world.lock:
            pending = [(pid, dict(p)) for pid, p in self.world.players.items()
                       if self.sent_inv_rev.get(pid) != p.get("rev", 0)]
        for pid, player in pending:
            with self.clients_lock:
                conn = self.clients.get(pid)
            if conn is None:
                continue
            self._send(conn, {
                "type": "state",
                "partial": True,
                "players": {pid: {"x": player["x"], "y": player["y"],
                                  "name": player.get("name", f"Player {pid}"),
                                  "hp": int(player.get("hp", 100)),
                                  "hunger": int(player.get("hunger", 100)),
                                  "armor": self.armor_points(player),
                                  "selected": player.get("selected"),
                                  "durability": dict(player.get("durability", {})),
                                  "stats": dict(player.get("stats", {})),
                                  "tasks": dict(player.get("tasks", {})),
                                  "inventory": dict(player.get("inventory", {}))}},
            })
            self.sent_inv_rev[pid] = player.get("rev", 0)

    def _state_payload_for_everyone(self, payload: dict) -> dict:
        """Send the same state to everybody, but hide other people's chests.

        Chest contents are personal (or shared inside a city); the owner still
        gets them in the `chest` packet when the screen is open.
        """
        buildings = payload["buildings"]
        with self.world.lock:
            owners = {key: building.get("owner")
                      for key, building in buildings.items()}
            recipients = list(self.clients.items())
        for pid, conn in recipients:
            private = None
            for key, building in buildings.items():
                if "items" not in building:
                    continue
                if owners.get(key) == pid or self.same_city(pid, owners.get(key)):
                    continue
                if private is None:
                    private = {name: dict(value) for name, value in buildings.items()}
                private[key].pop("items", None)
            self._send(conn, payload if private is None
                       else {**payload, "buildings": private})

    # ------------------------------------------------------------------- login
    def handle_client(self, conn, player_id):
        proto = Protocol()
        conn.settimeout(1.0)
        self._send(conn, {"type": "hello", "build": BUILD})

        session = None
        deadline = time.time() + AUTH_TIMEOUT
        try:
            while session is None and time.time() < deadline and self.running:
                try:
                    data = conn.recv(4096)
                except socket.timeout:
                    continue
                if not data:
                    return
                for message in proto.receive(data):
                    session = self.authenticate(conn, message)
                    if session is not None:
                        break
            if session is None:
                self._send(conn, {"type": "auth_error", "key": "auth.timeout"})
                return

            self.start_session(conn, player_id, session)
            while self.running:
                try:
                    data = conn.recv(4096)
                except socket.timeout:
                    continue
                if not data:
                    break
                for message in proto.receive(data):
                    try:
                        self.dispatch(conn, player_id, message)
                    except Exception as exc:              # never kill the session
                        print(f"[warn] bad packet from {player_id}: {message!r} -> {exc!r}")
                        self.notify(conn, "notify.bad_packet")
        except (ConnectionResetError, ConnectionAbortedError, OSError):
            pass
        finally:
            self.close_session(conn, player_id)

    # -- authentication -----------------------------------------------------
    def authenticate(self, conn, message: dict):
        """Turn the first message into a session dict, or None to keep waiting."""
        kind = message.get("type")
        if kind in ("register", "login") and self.accounts is None:
            self._send(conn, {"type": "auth_error", "key": "auth.disabled"})
            return None
        if kind == "register":
            ok, error, username = self.accounts.register(message.get("username", ""),
                                                         message.get("password", ""))
            if not ok:
                self._send(conn, {"type": "auth_error", "key": error})
                return None
            self._send(conn, {"type": "auth_ok", "kind": "registered",
                              "name": username, "account": True})
            return {"name": username, "account": username}

        if kind == "login":
            ok, error, username = self.accounts.login(message.get("username", ""),
                                                      message.get("password", ""))
            if not ok:
                self._send(conn, {"type": "auth_error", "key": error})
                return None
            if self.account_online(username):
                self._send(conn, {"type": "auth_error", "key": "auth.already_online"})
                return None
            self._send(conn, {"type": "auth_ok", "kind": "logged_in",
                              "name": username, "account": True})
            return {"name": username, "account": username}

        if kind in ("guest", "hello"):
            name = str(message.get("name") or message.get("username") or "Player").strip()
            if not NAME_RE.match(name) or name.lower() in self.taken_names():
                name = f"Guest{self.player_counter}"
            self._send(conn, {"type": "auth_ok", "kind": "guest",
                              "name": name, "account": False})
            return {"name": name, "account": None}

        # Anything else before auth: tell the client what the server expects
        self._send(conn, {"type": "auth_required", "build": BUILD})
        return None

    def account_online(self, username: str) -> bool:
        with self.world.lock:
            for player in self.world.players.values():
                if player.get("account") and player["account"].lower() == username.lower():
                    return True
        return False

    def taken_names(self) -> set:
        with self.world.lock:
            return {p.get("name", "").lower() for p in self.world.players.values()}

    # -- session ------------------------------------------------------------
    def start_session(self, conn, player_id, session):
        with self.clients_lock:
            self.clients[player_id] = conn
        self.sent_inv_rev[player_id] = -1

        name, account = session["name"], session["account"]
        self.world.add_player(player_id, name, account=account)

        restored = False
        if account and self.accounts is not None:
            progress = self.accounts.get_progress(account)
            if progress:
                with self.world.lock:
                    player = self.world.players[player_id]
                    if isinstance(progress.get("inventory"), dict):
                        player["inventory"] = dict(progress["inventory"])
                    player["hp"] = int(progress.get("hp", 100) or 100)
                    player["hunger"] = int(progress.get("hunger", 100) or 100)
                    if "x" in progress and "y" in progress:
                        player["x"], player["y"] = progress["x"], progress["y"]
                    player["selected"] = progress.get("selected")
                    player["armor"] = dict(progress.get("armor") or {})
                    player["durability"] = dict(progress.get("durability") or {})
                    player["stats"] = dict(progress.get("stats") or {})
                    player["tasks"] = dict(progress.get("tasks") or {})
                restored = True
                self.world.touch_inventory(player_id)

        if not restored:
            self._give_start_kit(player_id)
        self._deliver_payments(conn, player_id, name)
        self.world.touch_inventory(player_id)

        self._send(conn, {
            "type": "welcome",
            "id": player_id,
            "build": BUILD,
            "name": name,
            "account": bool(account),
            "restored": restored,
            "terrain": self.world.terrain_string(),
            "biomes": self.world.biome_string(),
            "world": [self.world.width, self.world.height],
            "day": self.day,
            "season": self.world.season if self.seasons_on else "summer",
            # b11: the movement rules the server uses, so the client predicts
            # its own steps with exactly the same numbers
            "rules": {"swim": bool(self.config.get("swim", True)),
                      "swim_speed": float(self.world.swim_speed),
                      "weather": bool(self.config.get("weather", True)),
                      "seasons": bool(self.seasons_on),
                      "days_per_season": self.days_per_season},
            "players": self._players_payload(),
        })
        self._send(conn, self._state_payload(full=True))
        self.sent_inv_rev[player_id] = -2
        self.send_tasks(conn, player_id)

        self.notify(conn, "auth.welcome_back" if restored else
                    ("auth.welcome" if account else "auth.guest"), name=name)
        self.broadcast({"type": "notification", "key": "notify.player_joined",
                        "args": {"name": name}}, exclude_id=player_id)

    def close_session(self, conn, player_id):
        with self.clients_lock:
            self.clients.pop(player_id, None)
        with self.world.lock:
            player = self.world.players.get(player_id)
            leaver = (player or {}).get("name", f"Player {player_id}")
            account = (player or {}).get("account")
            if account and player is not None and self.accounts is not None:
                self.accounts.set_progress(account, {
                    "inventory": dict(player.get("inventory", {})),
                    "x": player["x"], "y": player["y"],
                    "hp": player.get("hp", 100),
                    "hunger": player.get("hunger", 100),
                    "selected": player.get("selected"),
                    "armor": dict(player.get("armor", {})),
                    "durability": dict(player.get("durability", {})),
                    "stats": dict(player.get("stats", {})),
                    "tasks": dict(player.get("tasks", {})),
                })
            if self.running:
                self.world.remove_player(player_id)
        self.sent_inv_rev.pop(player_id, None)
        try:
            conn.close()
        except OSError:
            pass
        self.world.touch("civs")
        self.broadcast({"type": "notification", "key": "notify.player_left",
                        "args": {"name": leaver}})
        self.broadcast({"type": "player_left", "id": player_id})

    # ---------------------------------------------------------------- routing
    def dispatch(self, conn, player_id, msg: dict):
        handler = {
            "move": self.on_move,
            "chat": self.on_chat,
            "gather": self.on_gather,
            "build": self.on_build,
            "craft": self.on_craft,
            "smelt": self.on_smelt,
            "research": self.on_research,
            "attack": self.on_attack,
            "select_item": self.on_select_item,
            "create_city": self.on_create_city,
            "create_country": self.on_create_country,
            "join_city": self.on_join_city,
            "join_country": self.on_join_country,
            "eat": self.on_eat,
            "equip": self.on_equip,
            "attack_animal": self.on_attack_animal,
            "tame": self.on_tame,
            "attack_building": self.on_attack_building,
            "repair": self.on_repair,
            "toggle_door": self.on_toggle_door,
            "chest_put": self.on_chest_put,
            "chest_take": self.on_chest_take,
            "fish": self.on_fish,
            "diplomacy": self.on_diplomacy,
            "use": self.on_use,
            "set_role": self.on_set_role,
            "set_tax": self.on_set_tax,
            "trade_post": self.on_trade_post,
            "trade_take": self.on_trade_take,
            "trade_cancel": self.on_trade_cancel,
            "ping": lambda c, p, m: self._send(c, {"type": "pong", "t": m.get("t")}),
        }.get(msg.get("type"))
        if handler:
            handler(conn, player_id, msg)

    # ---------------------------------------------------------------- actions
    def _deliver_payments(self, conn, player_id, name):
        """Goods sold while the player was offline (market) land in the bag."""
        owed = self.world.take_payments(name)
        if not owed:
            return
        with self.world.lock:
            player = self.world.players.get(player_id)
            if player is None:
                return
            inventory = player.setdefault("inventory", {})
            for payment in owed:
                for item, amount in payment.items():
                    inventory[item] = inventory.get(item, 0) + int(amount)
            player["rev"] = player.get("rev", 0) + 1
        self.notify(conn, "notify.payments_arrived", n=len(owed))

    def _give_start_kit(self, player_id):
        """Items every fresh player gets (server_config.json -> start_kit)."""
        kit = self.config.get("start_kit") or {}
        if not isinstance(kit, dict) or not kit:
            return
        with self.world.lock:
            player = self.world.players.get(player_id)
            if player is None:
                return
            inventory = {}
            for item, amount in kit.items():
                try:
                    amount = int(amount)
                except (TypeError, ValueError):
                    continue
                if item not in ITEMS or amount <= 0:
                    continue
                inventory[item] = amount
                durability = item_durability(item)
                if durability:
                    player.setdefault("durability", {})[item] = durability
            player["inventory"] = inventory

    def weather_speed(self) -> float:
        """Rain slows everybody down a little (config switch `weather`)."""
        if not self.config.get("weather", True):
            return 1.0
        return WEATHER_SPEED.get(self.weather, 1.0)

    def on_move(self, conn, player_id, msg):
        multiplier = self.weather_speed()
        dx = max(-MAX_MOVE_STEP, min(MAX_MOVE_STEP, float(msg.get("dx", 0) or 0))) * multiplier
        dy = max(-MAX_MOVE_STEP, min(MAX_MOVE_STEP, float(msg.get("dy", 0) or 0))) * multiplier
        moved = self.world.move_player(player_id, dx, dy)
        if moved and self.world.swim:
            # b11: tell a swimmer (once) that water is slow, but harmless
            with self.world.lock:
                player = self.world.players.get(player_id)
                if player is not None and not player.get("swim_hint") and \
                        self.world.in_water(player["x"], player["y"]):
                    player["swim_hint"] = True
                    self.notify(conn, "notify.swim_hint", n=int(SWIM_SPEED * 100))

    def on_select_item(self, conn, player_id, msg):
        item = msg.get("item")
        with self.world.lock:
            player = self.world.players.get(player_id)
            if player is None:
                return
            inventory = player.setdefault("inventory", {})
            if item in (None, "", "none"):
                player["selected"] = None
                player["rev"] = player.get("rev", 0) + 1
                self.notify(conn, "hud.empty_hand")
                return
            if inventory.get(item, 0) <= 0:
                self.notify(conn, "notify.no_such_item")
                return
            player["selected"] = item
            player["rev"] = player.get("rev", 0) + 1
        self.notify(conn, "notify.item_in_hand", item=f"item.{item}")

    def held_item(self, player) -> str:
        item = player.get("selected")
        inventory = player.get("inventory", {})
        if item and inventory.get(item, 0) > 0:
            return item
        return None

    def on_chat(self, conn, player_id, msg):
        text = str(msg.get("text", ""))[:MAX_CHAT_LENGTH]
        if text == "/wipe":
            self.world.reset()
            self.broadcast({"type": "notification", "key": "notify.world_wiped"})
            self.broadcast(self._state_payload(full=True))
            self.save_world(quiet=True)
            return
        if text == "/regen":
            self.world.regenerate_resources()
            self.broadcast({"type": "notification", "key": "notify.world_regen"})
            return
        if text == "/save":
            ok = self.save_world(quiet=True)
            self.notify(conn, "notify.saved" if ok else "notify.save_disabled")
            return
        if text == "/help":
            self._send(conn, {"type": "chat", "id": "server",
                              "msg": "/who /where /time /msg <name> <text> /city "
                                     "/role <name> <role> /tax <0-40> /trade /war "
                                     "/peace /ally <country> /save /wipe /regen /help "
                                     "| chat: /g /l /c /w <name> <text>"})
            return
        if text in ("/who", "/online"):
            with self.world.lock:
                names = [f"{p.get('name')} ({int(p.get('hp', 100))}hp)" 
                         for p in self.world.players.values()]
            self._send(conn, {"type": "chat", "id": "server",
                              "msg": f"online ({len(names)}): " + ", ".join(names)})
            return
        if text == "/where":
            x, y = self.world.player_pos(player_id)
            self._send(conn, {"type": "chat", "id": "server",
                              "msg": f"{self.player_name(player_id)}: "
                                     f"tile {int(x // TILE_SIZE)},{int(y // TILE_SIZE)}"})
            return
        if text in ("/time", "/day"):
            day = int(self.world_time * 24)
            phase = "night" if (day < 6 or day >= 21) else "day"
            self._send(conn, {"type": "chat", "id": "server",
                              "msg": f"{day:02d}:00 ({phase}), weather: {self.weather}"})
            return
        if text.startswith("/war ") or text.startswith("/peace ") or \
                text.startswith("/ally "):
            action, _, target = text[1:].partition(" ")
            self.on_diplomacy(conn, player_id, {"target": target.strip(), "action": action})
            return
        if text.startswith("/role "):
            parts = text.split(" ", 2)
            if len(parts) == 3:
                self.on_set_role(conn, player_id, {"target": parts[1], "role": parts[2]})
            else:
                self.notify(conn, "notify.role_usage")
            return
        if text.startswith("/tax"):
            value = text[4:].strip()
            self.on_set_tax(conn, player_id, {"value": value or 0})
            return
        if text == "/city":
            with self.world.lock:
                city = self.world.civs.find_city_of(player_id)
                if city is None:
                    self._send(conn, {"type": "chat", "id": "server",
                                      "msg": "you are not in a city"})
                    return
                roles = ", ".join(f"{self.world.players.get(pid, {}).get('name', pid)}:"
                                  f"{city.role_of(pid)}" for pid in city.members)
                msg = (f"{city.name}: tier {city.tier}, tax {city.tax}%, "
                       f"fund wood {city.storage.get('wood', 0)} "
                       f"stone {city.storage.get('stone', 0)} | {roles}")
            self._send(conn, {"type": "chat", "id": "server", "msg": msg})
            return
        if text.startswith("/trade"):
            with self.world.lock:
                offers = self.world.trade_payload()
            lines = [f"{o['id']}: {o['give_count']}x {o['give_item']} -> "
                     f"{o['want_count']}x {o['want_item']} ({o['owner_name']})"
                     for o in offers[:8]]
            self._send(conn, {"type": "chat", "id": "server",
                              "msg": "; ".join(lines) or "no offers on the market"})
            return
        if text.startswith("/msg "):
            parts = text.split(" ", 2)
            if len(parts) == 3:
                who, message = parts[1], parts[2][:MAX_CHAT_LENGTH]
                with self.world.lock:
                    target = next((pid for pid, pl in self.world.players.items()
                                   if pl.get("name", "").lower() == who.lower()), None)
                with self.clients_lock:
                    target_conn = self.clients.get(target) if target else None
                if target_conn:
                    sender = self.player_name(player_id)
                    self.notify(target_conn, "notify.whisper", name=sender, text=message)
                    self.notify(conn, "notify.whisper_sent", name=who, text=message)
                else:
                    self.notify(conn, "notify.no_such_player", name=who)
                return
        # b13: chat channels. The player may send to everybody, to the people
        # nearby, to his own country or to one person. Everything else (the
        # commands above) keeps working exactly as before.
        channel = str(msg.get("channel") or "global").lower()
        target = msg.get("to") or ""
        with self.world.lock:
            sender = dict(self.world.players.get(player_id, {}))
            name = sender.get("name", f"Player {player_id}")
        payload = {"type": "chat", "id": player_id, "name": name, "msg": text,
                   "channel": channel}
        if channel == "local":
            radius = float(self.config.get("chat_radius", 12)) * TILE_SIZE
            with self.world.lock:
                listeners = [(pid, dict(p)) for pid, p in self.world.players.items()
                             if self._within(p, sender, radius)]
            for pid, _player in listeners:
                if pid == player_id:
                    self._send(conn, payload)
                    continue
                with self.clients_lock:
                    peer = self.clients.get(pid)
                if peer is not None:
                    self._send(peer, payload)
            return
        if channel == "country":
            with self.world.lock:
                country = self.world.civs.find_country_of(player_id)
                members = country.members() if country is not None else [player_id]
                country_name = country.name if country is not None else ""
            payload["country"] = country_name
            if not country_name:
                self.notify(conn, "notify.chat_no_country")
                return
            for pid in members:
                with self.clients_lock:
                    peer = self.clients.get(pid)
                if peer is not None:
                    self._send(peer, payload)
            return
        if channel == "whisper":
            with self.world.lock:
                target_id = next((pid for pid, player in self.world.players.items()
                                  if str(player.get("name", "")).lower() == str(target).lower()),
                                 None)
            with self.clients_lock:
                peer = self.clients.get(target_id) if target_id else None
            payload["to"] = target
            if peer is None:
                self.notify(conn, "notify.no_such_player", name=target)
                return
            self._send(peer, payload)
            self._send(conn, payload)
            return
        self.broadcast({"type": "chat", "id": player_id, "name": name, "msg": text,
                        "channel": "global"})

    @staticmethod
    def _within(player, other, radius: float) -> bool:
        """Is `player` close enough to hear `other`? (b13, local chat)"""
        if not player or not other:
            return False
        return ((player.get("x", 0) - other.get("x", 0)) ** 2 +
                (player.get("y", 0) - other.get("y", 0)) ** 2) ** 0.5 <= radius

    def on_gather(self, conn, player_id, msg):
        px, py = self.world.player_pos(player_id)
        if px is None:
            return
        with self.world.lock:
            player = self.world.players[player_id]
            inventory = player.setdefault("inventory", {})
            held = self.held_item(player)
            target_key = target = None
            for key, res in list(self.world.resources.items()):
                if ((px - res["x"]) ** 2 + (py - res["y"]) ** 2) ** 0.5 < 50:
                    target_key, target = key, res
                    break

            if target is not None:
                rtype = target["type"]
                amount = 1
                # the item in hand decides how much you get
                if held and rtype in item_targets(held):
                    amount = item_efficiency(held)
                item, base = RESOURCE_YIELD.get(rtype, (rtype, 1))
                total = int((amount * base) * float(self.config.get("resource_rate", 1.0)) or 1)
                # caves are richer: mining/foraging inside pays double
                cave_bonus = self.world.in_cave(px, py)
                if cave_bonus:
                    total *= int(self.config.get("cave_bonus", CAVE_YIELD_BONUS) or 1)
                if rtype in ("bush", "mushroom"):
                    bonus = season_forage(self.world.season, self.seasons_on)
                    extra = int(total * (bonus - 1.0))
                    if extra > 0:
                        total += extra
                        self.notify(conn, "notify.season_forage", n=extra)
                inventory[item] = inventory.get(item, 0) + total
                del self.world.resources[target_key]
                self.world.touch("resources")
                player["rev"] = player.get("rev", 0) + 1
                broken = self.wear_tool(player, held)
                if broken:
                    self.notify(conn, "notify.tool_broke", item=f"item.{broken}")
                self.bump_stat(player, "wood_gathered" if item == "wood" else
                               ("stone_gathered" if item == "stone" else "ore_gathered"),
                               total)
                if item == "gold_ore":
                    self.bump_stat(player, "gold_mined", total)
                # apples drop from trees now and then
                if rtype == "tree" and random.random() < 0.18:
                    inventory["apple"] = inventory.get("apple", 0) + 1
                    self.notify(conn, "notify.gathered", n=1, item="item.apple")
                self.notify(conn, "notify.gathered", n=total, item=f"item.{item}")
                if cave_bonus:
                    self.notify(conn, "notify.cave_bonus")
                taxed, tax_city = self.take_tax(player_id, px, py, item, total)
                if taxed:
                    self.notify(conn, "notify.tax_paid", n=taxed, item=f"item.{item}",
                                city=tax_city)
                self.check_tasks(conn, player_id)
                return
            feedback = self._harvest_farm(px, py, inventory)
            if feedback == "__ok__":
                player["rev"] = player.get("rev", 0) + 1
                self.notify(conn, "notify.farm_harvest")
                self.bump_stat(player, "food_grown", 1)
            elif feedback is None:
                self.notify(conn, "notify.nothing_gather")
            else:
                self.notify(conn, "notify.farm_growing", n=feedback)
        return

    def take_tax(self, player_id, px, py, item, amount) -> tuple:
        """A city takes its share of everything gathered on its land (b10).

        Only members of the city pay, and only inside its territory: the tax is
        the price of building and repairing inside the walls. A single log is
        worth less than any tax, so the fraction that was not taken yet stays on
        the books and is collected on the next gather (otherwise a 40 % tax on
        wood would quietly take nothing at all).
        """
        if not amount or not self.config.get("taxes", True):
            return 0, ""
        with self.world.lock:
            city = self.world.civs.city_at(px, py)
            if city is None or city.tax <= 0 or player_id not in city.members:
                return 0, ""
            book = (player_id, city.name, item)
            owed = self.tax_carry.get(book, 0.0) + amount * city.tax / 100.0
            share = min(int(owed), amount)
            self.tax_carry[book] = owed - int(owed)
            if share <= 0:
                return 0, ""
            city.storage[item] = city.storage.get(item, 0) + share
            player = self.world.players.get(player_id)
            if player is not None:
                inventory = player.setdefault("inventory", {})
                inventory[item] = max(0, inventory.get(item, 0) - share)
                if inventory[item] <= 0:
                    inventory.pop(item, None)
                player["rev"] = player.get("rev", 0) + 1
            self.world.touch("civs")
            return share, city.name

    def on_use(self, conn, player_id, msg):
        """Use a consumable: medkits and bandages heal (b10, key H)."""
        from shared.items import cures_poison, item_heal, is_consumable
        item = msg.get("item")
        with self.world.lock:
            player = self.world.players.get(player_id)
            if player is None:
                return
            inventory = player.setdefault("inventory", {})
            if not item:
                item = player.get("selected")
            if not is_consumable(item) or inventory.get(item, 0) <= 0:
                self.notify(conn, "notify.cannot_use")
                return
            if player.get("hp", 100) >= 100 and not (cures_poison(item)
                                                     and player.get("poisoned")):
                self.notify(conn, "notify.no_need")
                return
            heal = item_heal(item)
            inventory[item] -= 1
            if inventory.get(item, 0) <= 0:
                inventory.pop(item, None)
            player["hp"] = min(100, int(player.get("hp", 100)) + heal)
            if cures_poison(item):
                player["poisoned"] = False
                player["hunger"] = max(0.0, player.get("hunger", 100))
            if player.get("selected") == item and inventory.get(item, 0) <= 0:
                player["selected"] = None
            player["rev"] = player.get("rev", 0) + 1
            hp = int(player["hp"])
        self.notify(conn, "notify.used_item", item=f"item.{item}", hp=hp)
        self.bump_stat(player, "items_used", 1)
        self.check_tasks(conn, player_id)

    def on_set_role(self, conn, player_id, msg):
        """City leader: give a member a role (b10)."""
        target = str(msg.get("target", "")).strip()
        role = str(msg.get("role", "")).strip().lower()
        with self.world.lock:
            city = self.world.civs.find_city_led_by(player_id)
            if city is None:
                self.notify(conn, "notify.only_city_leader")
                return
            if role not in ROLE_ORDER or role == "leader":
                self.notify(conn, "notify.role_unknown")
                return
            target_id = next((pid for pid, p in self.world.players.items()
                              if str(p.get("name", "")).lower() == target.lower()), None)
            if target_id is None:
                target_id = next((pid for pid in city.members
                                  if self.world.players.get(pid, {}).get("name", "")
                                  .lower() == target.lower()), None)
            if target_id is None or target_id not in city.members:
                self.notify(conn, "notify.role_not_member", name=target or "?")
                return
            if not self.world.civs.set_role(city, target_id, role):
                self.notify(conn, "notify.role_failed")
                return
            self.world.touch("civs")
            name = self.world.players.get(target_id, {}).get("name", target)
        self.notify(conn, "notify.role_set", name=name, role=f"role.{role}")
        with self.clients_lock:
            target_conn = self.clients.get(target_id)
        if target_conn is not None:
            self.notify(target_conn, "notify.role_given", role=f"role.{role}",
                        city=city.name)

    def on_set_tax(self, conn, player_id, msg):
        """City leader: the share of gathered resources that goes to the fund."""
        try:
            value = int(msg.get("value", 0))
        except (TypeError, ValueError):
            value = 0
        with self.world.lock:
            city = self.world.civs.find_city_led_by(player_id)
            if city is None:
                self.notify(conn, "notify.only_city_leader")
                return
            if not self.config.get("taxes", True):
                self.notify(conn, "notify.taxes_off")
                return
            tax = self.world.civs.set_tax(city, value)
            self.world.touch("civs")
        self.notify(conn, "notify.tax_set", n=tax, city=city.name)

    def on_fish(self, conn, player_id, msg):
        """Cast a line: needs a fishing rod and water within one tile."""
        now = time.time()
        with self.world.lock:
            player = self.world.players.get(player_id)
            if player is None:
                return
            inventory = player.setdefault("inventory", {})
            held = self.held_item(player)
            rod = held if held == "fishing_rod" else (
                "fishing_rod" if inventory.get("fishing_rod", 0) > 0 else None)
            if rod is None:
                self.notify(conn, "notify.need_rod")
                return
            if now - player.get("last_fish", 0) < FISH_COOLDOWN:
                self.notify(conn, "notify.fishing_wait")
                return
            if self.world.nearest_water(player["x"], player["y"], FISH_REACH) is None:
                self.notify(conn, "notify.no_water")
                return
            player["last_fish"] = now
            caught = 1 + (1 if random.random() < 0.25 else 0)
            inventory["fish"] = inventory.get("fish", 0) + caught
            player["rev"] = player.get("rev", 0) + 1
            self.bump_stat(player, "fish_caught", caught)
            broken = self.wear_tool(player, rod)
        self.notify(conn, "notify.fish_caught", n=caught)
        if broken:
            self.notify(conn, "notify.tool_broke", item=f"item.{broken}")
        self.check_tasks(conn, player_id)

    def _harvest_farm(self, px, py, inventory):
        for b_data in self.world.buildings.values():
            if b_data["type"] != "farm":
                continue
            bx, by = b_data["x"] * TILE_SIZE + 16, b_data["y"] * TILE_SIZE + 16
            if ((px - bx) ** 2 + (py - by) ** 2) ** 0.5 > 64:
                continue
            now = time.time()
            last = b_data.get("last_harvest", 0)
            growth = self.farm_growth_seconds()
            if now - last > growth:
                b_data["last_harvest"] = now
                inventory["wheat"] = inventory.get("wheat", 0) + 1
                return "__ok__"
            return int(growth - (now - last))
        return None

    def on_build(self, conn, player_id, msg):
        structure = msg.get("structure")
        if structure not in STRUCTURES:
            self.notify(conn, "notify.build_fail_unknown")
            return

        with self.world.lock:
            player = self.world.players.get(player_id)
            if player is None:
                return
            inventory = player.setdefault("inventory", {})

            px0, py0 = player["x"], player["y"]

            # whose land is this and may this player build on it (b10)
            blocker = self.territory_blocker(player_id, px0, py0)
            if blocker is not None:
                # b11: name the city that really refused, not the one we happen
                # to stand in
                if player_id in blocker.members:
                    self.notify(conn, "notify.build_fail_role", city=blocker.name)
                else:
                    self.notify(conn, "notify.build_fail_territory")
                return

            fund_city = self.city_fund(player_id, px0, py0)
            pool = dict(inventory)
            if fund_city is not None:
                for res, amount in fund_city.storage.items():
                    pool[res] = pool.get(res, 0) + amount
            if not can_build(structure, pool):
                missing = ", ".join(f"{res} x{amount}"
                                    for res, amount in missing_for(structure, pool).items())
                self.notify(conn, "notify.build_fail_resources")
                self.notify(conn, "notify.tech_need", cost=missing)
                return

            tech = get_tech(structure)
            if tech and not self.country_has_tech(player_id, tech):
                self.notify(conn, "notify.build_fail_tech", tech=f"tech.{tech}")
                return

            # target tile: either given by the client or the player's own tile
            if "x" in msg and "y" in msg:
                gx, gy = int(msg["x"]), int(msg["y"])
            else:
                gx, gy = int(player["x"] // TILE_SIZE), int(player["y"] // TILE_SIZE)

            px, py = player["x"], player["y"]
            distance = max(abs(gx * TILE_SIZE + TILE_SIZE / 2 - px),
                           abs(gy * TILE_SIZE + TILE_SIZE / 2 - py)) / TILE_SIZE
            if distance > MAX_BUILD_DISTANCE:
                self.notify(conn, "notify.build_fail_range")
                return

            w, h = get_size(structure)
            # b11: the building must stand where this player may build. Only the
            # player's own tile was checked before, so an outsider could stand
            # outside the walls (the build range is 8 tiles) and drop a tower
            # inside somebody's city.
            for tx in range(gx, gx + w):
                for ty in range(gy, gy + h):
                    blocker = self.territory_blocker(
                        player_id, tx * TILE_SIZE + TILE_SIZE / 2,
                        ty * TILE_SIZE + TILE_SIZE / 2)
                    if blocker is None:
                        continue
                    if player_id in blocker.members:
                        self.notify(conn, "notify.build_fail_role", city=blocker.name)
                    else:
                        self.notify(conn, "notify.build_fail_territory")
                    return
            if not self.world.can_place(gx, gy, w, h, structure):
                self.notify(conn, "notify.build_fail_space")
                return

            for pid, other in self.world.players.items():
                if pid == player_id:
                    continue
                if gx * TILE_SIZE <= other["x"] <= (gx + w) * TILE_SIZE and \
                   gy * TILE_SIZE <= other["y"] <= (gy + h) * TILE_SIZE:
                    self.notify(conn, "notify.build_fail_player")
                    return

            # b10: the wonder needs an age, a city and a leader
            if is_wonder(structure):
                country = self.world.civs.find_country_of(player_id)
                needed = structure_age(structure)
                if self.world.civs.find_city_led_by(player_id) is None:
                    self.notify(conn, "notify.wonder_city")
                    return
                if needed and not age_at_least(getattr(country, "techs", []), needed):
                    self.notify(conn, "notify.wonder_age", age=f"age.{needed}")
                    return

            if structure == "town_center" and not self.leads_city(player_id):
                self.notify(conn, "notify.build_fail_city")
                return

            from_fund = self.pay_for_build(structure, player, fund_city)
            self.world.place_building(gx, gy, structure, player_id, w, h)
            if not is_walkable(structure):
                self._push_out(player_id, gx, gy, w, h)
            player["rev"] = player.get("rev", 0) + 1
            self.bump_stat(player, "blocks_built", 1)
            if structure in ("torch", "campfire"):
                self.bump_stat(player, "torches_placed", 1)
            if structure == "town_center":
                self.bump_stat(player, "town_centers", 1)
            if is_storage(structure):
                self.bump_stat(player, "storages_built", 1)
            name = self.player_name(player_id)
            self.notify(conn, "notify.built", name=f"structure.{structure}")
            if from_fund:
                self.notify(conn, "notify.fund_used", city=fund_city.name,
                            n=sum(from_fund.values()))
            self.broadcast({"type": "notification", "key": "notify.built_other",
                            "args": {"name": name, "structure": f"structure.{structure}"}},
                           exclude_id=player_id)
            if structure == "wonder":
                self.bump_stat(player, "wonders_built", 1)
                self.world.touch("civs")
                self.declare_victory("wonder", player_id)

    def on_craft(self, conn, player_id, msg):
        item = msg.get("item")
        if item not in CRAFTING_RECIPES:
            self.notify(conn, "craft.unknown")
            return
        count = max(1, min(MAX_CRAFT_COUNT, int(msg.get("count", 1) or 1)))

        with self.world.lock:
            player = self.world.players.get(player_id)
            if player is None:
                return
            inventory = player.setdefault("inventory", {})

            station = recipe_station(item)
            if station and not self.near_building(player["x"], player["y"], station,
                                                  STATION_RANGE):
                self.notify(conn, "craft.station_missing",
                            station=f"station.{station}")
                return

            unlocked = self.unlocked_recipes(player_id)
            if unlocked and item not in unlocked and item not in ("axe", "pickaxe", "sword"):
                self.notify(conn, "craft.no_tech", tech="")
                return

            made = craftable_amount(item, inventory)
            if made <= 0:
                self.notify(conn, "craft.missing")
                return
            count = min(count, made)
            produced = pay_for_craft(item, inventory, count)
            inventory[item] = inventory.get(item, 0) + produced
            player["rev"] = player.get("rev", 0) + 1
            self.bump_stat(player, "items_crafted", count)
            if item_durability(item):
                player.setdefault("durability", {})[item] = item_durability(item)
        self.notify(conn, "notify.crafted", item=f"item.{item}", n=produced)
        self.check_tasks(conn, player_id)

    def on_smelt(self, conn, player_id, msg):
        recipe = SMELTING_RECIPES.get(msg.get("action"))
        px, py = self.world.player_pos(player_id)
        if px is None:
            return
        if recipe is None:
            self.notify(conn, "craft.unknown")
            return
        if not self.near_building(px, py, "furnace", 64):
            self.notify(conn, "notify.smelt_no_furnace")
            return

        with self.world.lock:
            player = self.world.players[player_id]
            inventory = player.setdefault("inventory", {})
            fuel, ore, ingot = recipe["fuel"], recipe["input"], recipe["output"]
            if inventory.get(fuel, 0) < 1:
                self.notify(conn, "notify.smelt_need_coal")
                return
            if inventory.get(ore, 0) < 1:
                self.notify(conn, "notify.smelt_need_ore", item=f"item.{ore}")
                return
            multiplier = 2 if self.country_has_tech(player_id, "industrialization") else 1
            inventory[fuel] -= 1
            inventory[ore] -= 1
            inventory[ingot] = inventory.get(ingot, 0) + multiplier
            player["rev"] = player.get("rev", 0) + 1
            self.bump_stat(player, "items_smelted", 1)
            if ingot == "iron_ingot":
                self.bump_stat(player, "iron_smelted", multiplier)
        self.notify(conn, "notify.smelted", item=f"item.{ingot}", n=multiplier)
        self.check_tasks(conn, player_id)

    def on_research(self, conn, player_id, msg):
        """City tier upgrade (town center) or a country technology (research table)."""
        city_name = msg.get("city")
        with self.world.lock:
            target_city = None
            if city_name == "AUTO_FIND":
                target_city = self.world.civs.find_city_led_by(player_id)
            elif city_name in self.world.civs.cities:
                target_city = self.world.civs.cities[city_name]

            if target_city is not None:
                if target_city.leader != player_id:
                    self.notify(conn, "notify.only_city_leader")
                    return
                next_tier = target_city.tier + 1
                if next_tier > MAX_CITY_TIER:
                    self.notify(conn, "notify.tier_max")
                    return
                cost = tier_cost(next_tier)
                inventory = self.world.players[player_id]["inventory"]
                if any(inventory.get(res, 0) < amount for res, amount in cost.items()):
                    self.notify(conn, "notify.tier_need")
                    return
                for res, amount in cost.items():
                    inventory[res] -= amount
                    if inventory[res] <= 0:
                        inventory.pop(res)
                target_city.tier = next_tier
                self.world.touch("civs")
                self.world.players[player_id]["rev"] = \
                    self.world.players[player_id].get("rev", 0) + 1
                self.notify(conn, "notify.tier_up", tier=next_tier)
                self.broadcast({"type": "notification", "key": "notify.tier_other",
                                "args": {"name": target_city.name, "tier": next_tier}},
                               exclude_id=player_id)
                return

            if msg.get("scope") != "country":
                self.notify(conn, "notify.city_not_found")
                return

            country_name = msg.get("country")
            target_country = None
            if country_name == "AUTO_FIND":
                target_country = self.world.civs.find_country_led_by(player_id)
            elif country_name in self.world.civs.countries:
                target_country = self.world.civs.countries[country_name]

            if target_country is None:
                self.notify(conn, "notify.country_not_found")
                return
            if target_country.leader != player_id:
                self.notify(conn, "notify.only_country_leader")
                return

            tech = msg.get("tech", "")
            if tech not in TECHS:
                self.notify(conn, "notify.tech_unknown")
                return
            if tech in target_country.techs:
                self.notify(conn, "notify.tech_already")
                return
            missing_techs = [t for t in tech_requires(tech) if t not in target_country.techs]
            if missing_techs:
                self.notify(conn, "notify.tech_requires",
                            tech=f"tech.{missing_techs[0]}")
                return

            inventory = self.world.players[player_id]["inventory"]
            cost = tech_cost(tech)
            if any(inventory.get(res, 0) < amount for res, amount in cost.items()):
                missing = ", ".join(f"{res}:{amount}" for res, amount in cost.items())
                self.notify(conn, "notify.tech_need", cost=missing)
                return
            for res, amount in cost.items():
                inventory[res] -= amount
                if inventory[res] <= 0:
                    inventory.pop(res)
            target_country.techs.append(tech)
            self.world.touch("civs")
            self.world.players[player_id]["rev"] = \
                self.world.players[player_id].get("rev", 0) + 1
            self.bump_stat(self.world.players[player_id], "techs_researched", 1)
            country_name = target_country.name
        self.notify(conn, "notify.tech_done", tech=f"tech.{tech}")
        self.broadcast({"type": "notification", "key": "notify.tech_other",
                        "args": {"country": country_name, "tech": f"tech.{tech}"}},
                       exclude_id=player_id)
        self.check_tasks(conn, player_id)

    def on_attack(self, conn, player_id, msg):
        target_id = msg.get("target_id")
        with self.world.lock:
            attacker = self.world.players.get(player_id)
            target = self.world.players.get(target_id)
            if attacker is None or target is None:
                return
            if not self.config.get("pvp", True):
                self.notify(conn, "notify.pvp_off")
                return
            if not self.can_harm(player_id, target_id):
                self.notify(conn, "notify.at_peace")
                return
            distance = ((target["x"] - attacker["x"]) ** 2 +
                        (target["y"] - attacker["y"]) ** 2) ** 0.5
            inventory = attacker.setdefault("inventory", {})
            held = self.held_item(attacker)

            # the item in hand defines damage and reach
            damage, attack_range = 5, 40
            weapon = "fists"
            if held:
                weapon = held
                damage = item_damage(held) or 3
                attack_range = item_range(held)
                cooldown = item_cooldown(held)
                if cooldown and time.time() - attacker.get("last_shot", 0) < cooldown:
                    self.notify(conn, "notify.reloading")
                    return
                ammo = item_ammo(held)
                if ammo:
                    if inventory.get(ammo, 0) <= 0:
                        self.notify(conn, "notify.no_ammo", item=f"item.{ammo}")
                        return
                    inventory[ammo] -= 1
                    attacker["last_shot"] = time.time()
                    attacker["rev"] = attacker.get("rev", 0) + 1

            if distance > attack_range:
                self.notify(conn, "notify.out_of_range")
                return

            # b10: the warrior role of a city hits a little harder
            role_city = self.world.civs.find_city_of(player_id)
            if role_city is not None and role_city.role_of(player_id) == "warrior":
                damage = int(round(damage * WARRIOR_DAMAGE_BONUS))

            # shield blocks most of the damage
            blocked = False
            target_held = self.held_item(target)
            if target_held and item_block(target_held):
                blocked = True
                damage = int(damage * (1 - item_block(target_held)))

            damage = self.apply_armor(target, damage)
            target["hp"] = max(0, target.get("hp", 100) - damage)
            target_name = target.get("name", f"Player {target_id}")
            broken = self.wear_tool(attacker, held)
            if broken:
                self.notify(conn, "notify.tool_broke", item=f"item.{broken}")
            self.notify(conn, "notify.hit", name=target_name,
                        weapon=f"item.{weapon}" if weapon != "fists" else weapon,
                        damage=damage)

            with self.clients_lock:
                target_conn = self.clients.get(target_id)
            if target_conn:
                self.notify(target_conn, "notify.blocked" if blocked else "notify.you_hit",
                            damage=damage, hp=target["hp"])

            # pets defend their owner
            for pet_id in list(target.get("pets", [])):
                pet = self.world.animals.get(pet_id)
                if pet is not None:
                    pet["target"] = player_id

            if target["hp"] <= 0:
                self.kill_player(target_id, killer=player_id)

    def kill_player(self, player_id, killer=None):
        """Death: respawn at the nearest bed/barracks of the player's city."""
        with self.world.lock:
            player = self.world.players.get(player_id)
            if player is None:
                return
            player["hp"] = 100
            player["hunger"] = max(50, player.get("hunger", 100))
            player["x"], player["y"] = self.respawn_point(player_id)
            player["died_at"] = time.time()
            name = player.get("name", f"Player {player_id}")
            self.bump_stat(player, "deaths", 1)
        if killer is not None:
            with self.world.lock:
                slayer = self.world.players.get(killer)
                if slayer is not None:
                    self.bump_stat(slayer, "players_defeated", 1)
        self.broadcast({"type": "notification", "key": "notify.defeated",
                        "args": {"name": name,
                                 "killer": self.player_name(killer) if killer else ""}})
        with self.clients_lock:
            conn = self.clients.get(player_id)
        if conn:
            self.notify(conn, "notify.respawn")

    def respawn_point(self, player_id):
        """Nearest barracks of the player's city, else a random free tile."""
        with self.world.lock:
            city = self.world.civs.find_city_of(player_id)
            if city is not None:
                best = None
                for building in self.world.buildings.values():
                    if building["type"] != "barracks":
                        continue
                    in_country = True
                    for country in self.world.civs.countries.values():
                        if city in country.cities and country.leader != building.get("owner"):
                            members = {c.leader for c in country.cities}
                            in_country = building.get("owner") in members
                            break
                    if not in_country:
                        continue
                    distance = ((building["x"] * TILE_SIZE - city.x) ** 2 +
                                (building["y"] * TILE_SIZE - city.y) ** 2) ** 0.5
                    if best is None or distance < best[0]:
                        best = (distance, building)
                if best is not None:
                    building = best[1]
                    return (building["x"] * TILE_SIZE + TILE_SIZE // 2,
                            building["y"] * TILE_SIZE + TILE_SIZE // 2)
        return self.world.spawn_point()

    # ------------------------------------------------------- players: survival
    def armor_points(self, player) -> int:
        return sum(item_armor_points(item) for item in (player.get("armor") or {}).values())

    def apply_armor(self, player, damage: int) -> int:
        """Armor soaks part of the damage: 20 points = 75% reduction (capped)."""
        points = self.armor_points(player)
        if not points:
            return damage
        reduction = min(0.75, points * 0.04)
        return max(1, int(damage * (1 - reduction)))

    def wear_tool(self, player, item):
        """Tools and weapons lose durability; returns the item that just broke."""
        if not item or not self.config.get("durability", True):
            return None
        maximum = item_durability(item)
        if not maximum:
            return None
        broken = None
        with self.world.lock:
            durability = player.setdefault("durability", {})
            left = durability.get(item, maximum) - 1
            if left > 0:
                durability[item] = left
                player["rev"] = player.get("rev", 0) + 1
                return None
            durability.pop(item, None)
            broken = item
            inventory = player.get("inventory", {})
            inventory[item] = max(0, inventory.get(item, 0) - 1)
            if inventory.get(item, 0) <= 0:
                inventory.pop(item, None)
            if player.get("selected") == item and inventory.get(item, 0) <= 0:
                player["selected"] = None
            self.bump_stat(player, "tools_broken", 1)
        return broken

    def bump_stat(self, player, stat: str, amount=1):
        if player is None:
            return
        task_module.bump(player.setdefault("stats", {}), stat, amount)

    def check_tasks(self, conn=None, player_id=None):
        """Complete tasks/achievements whose target is reached, pay rewards."""
        if not self.config.get("tasks", True):
            return
        with self.world.lock:
            player = self.world.players.get(player_id)
            if player is None:
                return
            done = player.setdefault("tasks", {})
            finished = task_module.completed_now(player.get("stats", {}), done)
            rewards = []
            for code in finished:
                done[code] = True
                reward = dict(task_module.task_data(code).get("reward", {}))
                inventory = player.setdefault("inventory", {})
                for item, amount in reward.items():
                    inventory[item] = inventory.get(item, 0) + amount
                rewards.append((code, reward))
            if finished:
                player["rev"] = player.get("rev", 0) + 1
        for code, reward in rewards:
            with self.clients_lock:
                target_conn = conn or self.clients.get(player_id)
            if target_conn:
                self.notify(target_conn, "notify.task_done",
                            task=f"task.{code}", reward=", ".join(
                                f"{v}x" for v in reward.values()) or "-")
            self.broadcast({"type": "notification", "key": "notify.task_other",
                            "args": {"name": self.player_name(player_id),
                                     "task": f"task.{code}"}}, exclude_id=player_id)
        if rewards and conn:
            with self.world.lock:
                player = self.world.players.get(player_id)
                payload = self.tasks_payload(player)
            self._send(conn, {"type": "tasks", **payload})

    def tasks_payload(self, player) -> dict:
        return {"tasks": dict(player.get("tasks", {})),
                "stats": dict(player.get("stats", {}))}

    def send_tasks(self, conn, player_id):
        with self.world.lock:
            player = self.world.players.get(player_id)
            if player is None:
                return
            payload = self.tasks_payload(player)
        self._send(conn, {"type": "tasks", **payload})

    # ------------------------------------------------------- players: actions
    def on_eat(self, conn, player_id, msg):
        item = msg.get("item")
        with self.world.lock:
            player = self.world.players.get(player_id)
            if player is None:
                return
            inventory = player.setdefault("inventory", {})
            if not item:
                item = player.get("selected")
            if not is_food(item) or inventory.get(item, 0) <= 0:
                self.notify(conn, "notify.cannot_eat")
                return
            food = item_food(item)
            inventory[item] -= 1
            if inventory.get(item, 0) <= 0:
                inventory.pop(item, None)
            player["hunger"] = min(100, player.get("hunger", 100) + food.get("hunger", 0))
            healed = food.get("heal", 0)
            if healed:
                player["hp"] = min(100, player.get("hp", 100) + healed)
            poisoned = item_poison(item) and random.random() < item_poison(item)
            if poisoned:
                player["hp"] = max(1, player.get("hp", 100) - 8)
                # b10: it keeps hurting for a few seconds - a medkit stops it
                player["poisoned"] = True
                player["poison_until"] = time.time() + POISON_SECONDS
            if player.get("selected") == item and inventory.get(item, 0) <= 0:
                player["selected"] = None
            player["rev"] = player.get("rev", 0) + 1
            self.bump_stat(player, "food_eaten", 1)
            hunger, hp = player["hunger"], player["hp"]
        self.notify(conn, "notify.poisoned" if poisoned else "notify.ate",
                    item=f"item.{item}", hunger=int(hunger), hp=int(hp))
        self.check_tasks(conn, player_id)

    def on_equip(self, conn, player_id, msg):
        item = msg.get("item")
        with self.world.lock:
            player = self.world.players.get(player_id)
            if player is None:
                return
            inventory = player.setdefault("inventory", {})
            armor = player.setdefault("armor", {})
            slot = item_slot(item) if item else None
            if item and (slot is None or inventory.get(item, 0) <= 0):
                self.notify(conn, "notify.cannot_equip")
                return
            # take the piece off
            if item is None:
                old = armor.pop(str(msg.get("slot", "")), None)
            elif slot in armor:
                old = armor[slot]
                if old == item:
                    self.notify(conn, "notify.cannot_equip")
                    return
            else:
                old = None
            if item is not None:
                inventory[item] -= 1
                if inventory.get(item, 0) <= 0:
                    inventory.pop(item, None)
                armor[slot] = item
            if old:
                inventory[old] = inventory.get(old, 0) + 1
            player["rev"] = player.get("rev", 0) + 1
            points = self.armor_points(player)
        self.notify(conn, "notify.equipped" if item else "notify.unequipped",
                    item=f"item.{item}" if item else "-", armor=points)

    def on_attack_animal(self, conn, player_id, msg):
        animal_id = str(msg.get("animal_id"))
        with self.world.lock:
            attacker = self.world.players.get(player_id)
            animal = self.world.animals.get(animal_id)
            if attacker is None or animal is None:
                return
            held = self.held_item(attacker)
            damage = item_damage(held) if held else 5
            if held and item_ammo(held):
                inventory = attacker.setdefault("inventory", {})
                if inventory.get(item_ammo(held), 0) <= 0:
                    self.notify(conn, "notify.no_ammo", item=f"item.{item_ammo(held)}")
                    return
                inventory[item_ammo(held)] -= 1
                attacker["rev"] = attacker.get("rev", 0) + 1
            distance = ((animal["x"] - attacker["x"]) ** 2 +
                        (animal["y"] - attacker["y"]) ** 2) ** 0.5
            if distance > (item_range(held) if held else 40):
                self.notify(conn, "notify.out_of_range")
                return
            broken = self.wear_tool(attacker, held)
            if broken:
                self.notify(conn, "notify.tool_broke", item=f"item.{broken}")
            killed, drops = self.world.damage_animal(animal_id, damage, player_id)
            kind = animal["type"]
            if killed:
                inventory = attacker.setdefault("inventory", {})
                for drop, amount in drops.items():
                    inventory[drop] = inventory.get(drop, 0) + amount
                attacker["rev"] = attacker.get("rev", 0) + 1
                self.bump_stat(attacker, "animals_hunted", 1)
            else:
                # wounded animals run away from the attacker
                animal["target"] = None
                animal["scared_at"] = time.time()
        if killed:
            self.notify(conn, "notify.animal_killed", animal=f"item.{kind}",
                        drops=", ".join(f"{k} x{v}" for k, v in drops.items()))
            self.check_tasks(conn, player_id)
        else:
            self.notify(conn, "notify.animal_hit", damage=damage)

    def on_tame(self, conn, player_id, msg):
        animal_id = str(msg.get("animal_id"))
        with self.world.lock:
            player = self.world.players.get(player_id)
            animal = self.world.animals.get(animal_id)
            if player is None or animal is None:
                return
            if animal["type"] not in ("wolf", "sheep"):
                self.notify(conn, "notify.cannot_tame")
                return
            inventory = player.setdefault("inventory", {})
            if inventory.get("raw_meat", 0) <= 0:
                self.notify(conn, "notify.tame_need_meat")
                return
            distance = ((animal["x"] - player["x"]) ** 2 +
                        (animal["y"] - player["y"]) ** 2) ** 0.5
            if distance > 60:
                self.notify(conn, "notify.out_of_range")
                return
            inventory["raw_meat"] -= 1
            if inventory["raw_meat"] <= 0:
                inventory.pop("raw_meat")
            animal["owner"] = player_id
            animal["target"] = None
            if animal_id not in player.setdefault("pets", []):
                player["pets"].append(animal_id)
            player["rev"] = player.get("rev", 0) + 1
            self.bump_stat(player, "animals_tamed", 1)
        self.notify(conn, "notify.tamed", animal=f"item.{animal['type']}")
        self.check_tasks(conn, player_id)

    def on_attack_building(self, conn, player_id, msg):
        tile = (int(msg.get("x", 0)), int(msg.get("y", 0)))
        with self.world.lock:
            player = self.world.players.get(player_id)
            if player is None:
                return
            key, building = self.world.building_at(*tile)
            if building is None:
                self.notify(conn, "notify.no_building")
                return
            if building.get("owner") == player_id:
                self.notify(conn, "notify.own_building")
                return
            if not self.can_harm(player_id, building.get("owner")):
                self.notify(conn, "notify.at_peace")
                return
            distance = max(abs(tile[0] * TILE_SIZE + TILE_SIZE / 2 - player["x"]),
                           abs(tile[1] * TILE_SIZE + TILE_SIZE / 2 - player["y"])) / TILE_SIZE
            if distance > 3:
                self.notify(conn, "notify.out_of_range")
                return
            held = self.held_item(player)
            damage = (item_damage(held) if held else 5) * 3
            broken = self.wear_tool(player, held)
            if broken:
                self.notify(conn, "notify.tool_broke", item=f"item.{broken}")
            destroyed, broken = self.world.damage_building(key, damage)
            kind = broken["type"]
            hp_left = 0 if destroyed else broken.get("hp", 0)
        if destroyed:
            if kind == "town_center":
                self.notify(conn, "notify.city_center_down")
            else:
                self.notify(conn, "notify.building_destroyed", name=f"structure.{kind}")
            self.broadcast({"type": "notification", "key": "notify.building_lost",
                            "args": {"name": self.player_name(building.get("owner")),
                                     "structure": f"structure.{kind}"}},
                           exclude_id=player_id)
            self.bump_stat(player, "buildings_destroyed", 1)
            if kind == "town_center":
                self.on_town_center_fallen(conn, player_id, building)
        elif kind == "town_center":
            # b10: a siege in progress - the whole city is told about it
            self.notify(conn, "notify.siege_hit", hp=int(hp_left))
            self.warn_city_siege(building, player_id, hp_left)
        else:
            self.notify(conn, "notify.building_hit", name=f"structure.{kind}", hp=int(hp_left))

    # ------------------------------------------------------- b10: city capture
    def city_of_building(self, building):
        """The city a building belongs to (by territory, then by its owner)."""
        if building is None:
            return None
        cx = building["x"] * TILE_SIZE + TILE_SIZE // 2
        cy = building["y"] * TILE_SIZE + TILE_SIZE // 2
        with self.world.lock:
            city = self.world.civs.city_at(cx, cy)
            if city is None:
                city = self.world.civs.find_city_of(building.get("owner"))
            return city

    def warn_city_siege(self, building, attacker_id, hp_left):
        """Tell everybody in the city that its centre is being attacked."""
        city = self.city_of_building(building)
        if city is None:
            return
        attacker = self.player_name(attacker_id)
        with self.world.lock:
            members = list(city.members)
        payload = {"type": "notification", "key": "notify.under_siege",
                   "args": {"city": city.name, "name": attacker, "hp": int(hp_left)}}
        for pid in members:
            if pid == attacker_id:
                continue
            with self.clients_lock:
                target_conn = self.clients.get(pid)
            if target_conn is not None:
                self._send(target_conn, payload)

    def on_town_center_fallen(self, conn, attacker_id, building):
        """The town centre is gone: the city changes hands (b10).

        Only a country can hold a captured city: with one behind the attacker
        the city *joins him* (its leader is thrown out, its staff lose their
        posts, its fund is looted). Without a country a loner can only *sack*
        the city: he takes the fund and the city loses a tier, but it stays in
        the hands of its own leader.
        """
        city = self.city_of_building(building)
        if city is None:
            return
        with self.world.lock:
            attacker_country = self.world.civs.find_country_of(attacker_id)
            attacker = self.world.players.get(attacker_id, {})
            old_leader_name = self.world.players.get(city.leader, {}).get("name", "?")
            loot = dict(city.storage)
            inventory = attacker.setdefault("inventory", {})
            for item, amount in loot.items():
                inventory[item] = inventory.get(item, 0) + amount
            city.storage = {}
            info = None
            if attacker_country is None:
                city.tier = max(1, city.tier - 1)
            else:
                info = self.world.civs.capture_city(city, attacker_id, attacker_country)
            attacker["rev"] = attacker.get("rev", 0) + 1
            city_name = city.name
            self.world.touch("civs")
        looted = sum(loot.values())
        if info is None:
            self.notify(conn, "notify.city_sacked", name=city_name, n=looted)
            self.broadcast({"type": "notification", "key": "notify.city_sacked_news",
                            "args": {"city": city_name,
                                     "name": self.player_name(attacker_id)}},
                           exclude_id=attacker_id)
            self.check_capture_victory(attacker_id)
            return
        country_name = attacker_country.name if attacker_country else "-"
        self.notify(conn, "notify.city_captured", name=city_name, n=looted)
        self.broadcast({"type": "notification", "key": "notify.city_captured_news",
                        "args": {"city": city_name, "name": self.player_name(attacker_id),
                                 "country": country_name,
                                 "old": info.get("old_country") or "-",
                                 "old_leader": old_leader_name}},
                       exclude_id=attacker_id)
        self.bump_stat(attacker, "cities_captured", 1)
        old_country = info.get("old_country")
        if old_country:
            with self.world.lock:
                remaining = self.world.civs.countries.get(old_country)
                alive = bool(remaining and remaining.cities)
                if not alive:
                    self.world.civs.dissolve_country(old_country)
                    self.world.touch("civs")
            if not alive:
                self.broadcast({"type": "notification", "key": "notify.country_dissolved",
                                "args": {"country": old_country}})
        self.check_capture_victory(attacker_id)

    def check_capture_victory(self, attacker_id):
        with self.world.lock:
            winners = self.world.civs.countries_owning_everything()
            if not winners:
                return False
            country = winners[0]
            leader = country.leader
        return self.declare_victory("capture", leader, country=country.name)

    def declare_victory(self, reason: str, player_id, country: str = "") -> bool:
        """Somebody reached the game goal: capture every city or build a wonder."""
        if not self.config.get("victory", True) or self.victory is not None:
            return False
        with self.world.lock:
            if not country:
                found = self.world.civs.find_country_of(player_id)
                country = found.name if found else ""
            name = self.world.players.get(player_id, {}).get("name", "?")
            self.victory = {"type": reason, "country": country or name,
                            "player": name, "at": round(time.time(), 2)}
            for pid, player in self.world.players.items():
                in_country = self.world.civs.find_country_of(pid)
                if country and in_country is not None and in_country.name == country:
                    self.bump_stat(player, "victories", 1)
        key = "notify.victory_wonder" if reason == "wonder" else "notify.victory_capture"
        self.broadcast({"type": "notification", "key": key,
                        "args": {"country": country, "name": self.player_name(player_id)}})
        return True

    def on_repair(self, conn, player_id, msg):
        """Repair your own building: 1 resource restores REPAIR_PER_UNIT health."""
        tile = (int(msg.get("x", 0)), int(msg.get("y", 0)))
        with self.world.lock:
            player = self.world.players.get(player_id)
            if player is None:
                return
            key, building = self.world.building_at(*tile)
            if building is None:
                self.notify(conn, "notify.no_building")
                return
            if building.get("owner") != player_id:
                self.notify(conn, "notify.not_yours")
                return
            maximum = building.get("max_hp", get_hp(building["type"]))
            missing = maximum - building.get("hp", maximum)
            if missing <= 0:
                self.notify(conn, "notify.repair_full")
                return
            cost = get_cost(building["type"]) or {"wood": 1}
            resource = min(cost, key=lambda res: cost[res])
            inventory = player.setdefault("inventory", {})
            units = min(inventory.get(resource, 0),
                        max(1, (missing + REPAIR_PER_UNIT - 1) // REPAIR_PER_UNIT),
                        max(1, int(msg.get("units", 10) or 10)))
            if units <= 0:
                self.notify(conn, "notify.repair_need", item=f"item.{resource}")
                return
            inventory[resource] -= units
            if inventory.get(resource, 0) <= 0:
                inventory.pop(resource, None)
            building["hp"] = min(maximum, building.get("hp", 0) + units * REPAIR_PER_UNIT)
            hp = building["hp"]
            self.world.touch("buildings")
            player["rev"] = player.get("rev", 0) + 1
            self.bump_stat(player, "repairs", 1)
        self.notify(conn, "notify.repaired", name=f"structure.{building['type']}",
                    hp=int(hp), item=f"item.{resource}")

    def on_toggle_door(self, conn, player_id, msg):
        tile = (int(msg.get("x", 0)), int(msg.get("y", 0)))
        with self.world.lock:
            player = self.world.players.get(player_id)
            key, building = self.world.building_at(*tile)
            if player is None or building is None or building["type"] != "door":
                self.notify(conn, "notify.no_building")
                return
            same_city = self.same_city(player_id, building.get("owner"))
            if building.get("owner") != player_id and not same_city:
                self.notify(conn, "notify.not_yours")
                return
            distance = max(abs(tile[0] * TILE_SIZE - player["x"]),
                           abs(tile[1] * TILE_SIZE - player["y"])) / TILE_SIZE
            if distance > 2.5:
                self.notify(conn, "notify.out_of_range")
                return
            building["open"] = not building.get("open", False)
            state = building["open"]
            self.world.touch("buildings")
        self.notify(conn, "notify.door_open" if state else "notify.door_closed")

    def can_harm(self, player_id, other_id) -> bool:
        """Diplomacy (b9): countries at peace cannot hurt each other.

        Players without a country, and cities of the same country, keep the old
        rules - peace only applies between two different countries.
        """
        if other_id is None or player_id == other_id:
            return True
        mine = self.world.civs.find_country_of(player_id)
        theirs = self.world.civs.find_country_of(other_id)
        if mine is None or theirs is None:
            return True
        return self.world.civs.relation(mine, theirs) in ("war", "same")

    def on_diplomacy(self, conn, player_id, msg):
        """Country leader: declare war, make peace or offer an alliance."""
        target_name = str(msg.get("target", ""))
        action = str(msg.get("action", ""))
        with self.world.lock:
            country = self.world.civs.find_country_led_by(player_id)
            target = self.world.civs.countries.get(target_name)
            if country is None:
                self.notify(conn, "notify.only_country_leader")
                return
            if target is None or target.name == country.name:
                self.notify(conn, "notify.country_not_found")
                return
            if action not in ("war", "peace", "ally"):
                return
            self.world.civs.set_relation(country, target, action)
            self.world.touch("civs")
            relation = self.world.civs.relation(country, target)
        keys = {"war": "notify.declared_war", "peace": "notify.made_peace",
                "ally": "notify.ally_offer"}
        self.notify(conn, keys[action], country=target_name)
        self.broadcast({"type": "notification",
                        "key": f"notify.diplomacy_{action}",
                        "args": {"country": country.name, "other": target_name}},
                       exclude_id=player_id)
        if relation == "ally" and action == "ally":
            self.notify(conn, "notify.allied", country=target_name)

    def same_city(self, player_id, other_id) -> bool:
        with self.world.lock:
            mine = self.world.civs.find_city_of(player_id)
            theirs = self.world.civs.find_city_of(other_id)
            return bool(mine and theirs and mine.name == theirs.name)

    def on_chest_put(self, conn, player_id, msg):
        self._chest_move(conn, player_id, msg, to_chest=True)

    def on_chest_take(self, conn, player_id, msg):
        self._chest_move(conn, player_id, msg, to_chest=False)

    def _chest_move(self, conn, player_id, msg, to_chest: bool):
        tile = (int(msg.get("x", 0)), int(msg.get("y", 0)))
        item = msg.get("item")
        amount = max(1, min(1000, int(msg.get("count", 1) or 1)))
        with self.world.lock:
            player = self.world.players.get(player_id)
            key, building = self.world.building_at(*tile)
            if player is None or building is None or not is_storage(building["type"]):
                self.notify(conn, "notify.no_chest")
                return
            if building.get("owner") != player_id and not self.same_city(
                    player_id, building.get("owner")):
                self.notify(conn, "notify.not_yours")
                return
            distance = max(abs(tile[0] * TILE_SIZE - player["x"]),
                           abs(tile[1] * TILE_SIZE - player["y"])) / TILE_SIZE
            if distance > 2.5:
                self.notify(conn, "notify.out_of_range")
                return
            storage = building.setdefault("items", {})
            inventory = player.setdefault("inventory", {})
            slots = get_storage(building["type"])
            if to_chest:
                have = inventory.get(item, 0)
                if have <= 0:
                    self.notify(conn, "notify.no_such_item")
                    return
                if item not in storage and len(storage) >= slots:
                    self.notify(conn, "notify.chest_full")
                    return
                moved = min(amount, have)
                inventory[item] = have - moved
                if inventory[item] <= 0:
                    inventory.pop(item)
                storage[item] = storage.get(item, 0) + moved
                if player.get("selected") == item and inventory.get(item, 0) <= 0:
                    player["selected"] = None
            else:
                have = storage.get(item, 0)
                if have <= 0:
                    self.notify(conn, "notify.chest_empty")
                    return
                moved = min(amount, have)
                storage[item] = have - moved
                if storage[item] <= 0:
                    storage.pop(item)
                inventory[item] = inventory.get(item, 0) + moved
            player["rev"] = player.get("rev", 0) + 1
            self.world.touch("buildings")
            self.bump_stat(player, "chests_used" if to_chest else "chest_taken", 1)
            contents = dict(storage)
        self._send(conn, {"type": "chest", "x": tile[0], "y": tile[1], "items": contents})
        self.notify(conn, "notify.stored" if to_chest else "notify.taken",
                    n=moved, item=f"item.{item}")
        self.check_tasks(conn, player_id)

    # ----------------------------------------------------------- trade (b9)
    def market_near(self, x: float, y: float, tiles: int = 3):
        """A market building close enough to trade at."""
        with self.world.lock:
            for key, building in self.world.buildings.items():
                if not is_market(building["type"]):
                    continue
                bx = building["x"] * TILE_SIZE + TILE_SIZE * building.get("w", 1) / 2
                by = building["y"] * TILE_SIZE + TILE_SIZE * building.get("h", 1) / 2
                if max(abs(bx - x), abs(by - y)) / TILE_SIZE <= tiles:
                    return building
        return None

    def send_trades(self, conn=None):
        payload = {"type": "trades", "offers": self.world.trade_payload()}
        if conn is not None:
            self._send(conn, payload)
        else:
            self.broadcast(payload)

    def on_trade_post(self, conn, player_id, msg):
        """Put goods on the market: give X, ask for Y in return."""
        give_item = str(msg.get("give_item", ""))
        want_item = str(msg.get("want_item", ""))
        give_count = max(1, min(1000, int(msg.get("give_count", 1) or 1)))
        want_count = max(1, min(1000, int(msg.get("want_count", 1) or 1)))
        with self.world.lock:
            player = self.world.players.get(player_id)
            if player is None:
                return
            if self.market_near(player["x"], player["y"]) is None:
                self.notify(conn, "notify.no_market")
                return
            if give_item not in ITEMS or want_item not in ITEMS:
                self.notify(conn, "notify.no_such_item")
                return
            if give_item == want_item:
                self.notify(conn, "notify.trade_same")
                return
            inventory = player.setdefault("inventory", {})
            if inventory.get(give_item, 0) < give_count:
                self.notify(conn, "notify.trade_need", n=give_count, item=f"item.{give_item}")
                return
            if player.get("selected") == give_item and \
                    inventory.get(give_item, 0) - give_count <= 0:
                player["selected"] = None
            inventory[give_item] -= give_count
            if inventory.get(give_item, 0) <= 0:
                inventory.pop(give_item, None)
            city = self.world.civs.find_city_of(player_id)
            self.world.add_trade({
                "owner": player_id,
                "owner_name": player.get("name", "?"),
                "city": city.name if city else "",
                "x": player["x"], "y": player["y"],
                "give_item": give_item, "give_count": give_count,
                "want_item": want_item, "want_count": want_count,
            })
            player["rev"] = player.get("rev", 0) + 1
            self.bump_stat(player, "trades_posted", 1)
        self.notify(conn, "notify.trade_posted", n=give_count, item=f"item.{give_item}",
                    want=want_count, want_item=f"item.{want_item}")
        self.send_trades()

    def on_trade_take(self, conn, player_id, msg):
        """Accept somebody's offer: pay what they asked, take what they gave."""
        trade_id = str(msg.get("id", ""))
        with self.world.lock:
            player = self.world.players.get(player_id)
            offer = self.world.trades.get(trade_id)
            if player is None or offer is None:
                self.notify(conn, "notify.trade_gone")
                return
            if offer.get("owner") == player_id:
                self.notify(conn, "notify.trade_own")
                return
            if self.market_near(player["x"], player["y"]) is None:
                self.notify(conn, "notify.no_market")
                return
            inventory = player.setdefault("inventory", {})
            want_item, want_count = offer["want_item"], offer["want_count"]
            if inventory.get(want_item, 0) < want_count:
                self.notify(conn, "notify.trade_need", n=want_count, item=f"item.{want_item}")
                return
            inventory[want_item] -= want_count
            if inventory.get(want_item, 0) <= 0:
                inventory.pop(want_item, None)
            give_item, give_count = offer["give_item"], offer["give_count"]
            inventory[give_item] = inventory.get(give_item, 0) + give_count
            if player.get("selected") == want_item and inventory.get(want_item, 0) <= 0:
                player["selected"] = None
            self.world.drop_trade(trade_id)
            seller_id, seller_name = offer["owner"], offer.get("owner_name", "?")
            seller = self.world.players.get(seller_id)
            seller_city = self.world.civs.find_city_of(seller_id) if seller_id else None
            payment = {want_item: want_count}
            if seller is not None:
                seller.setdefault("inventory", {})[want_item] = \
                    seller["inventory"].get(want_item, 0) + want_count
                seller["rev"] = seller.get("rev", 0) + 1
                where = "inventory"
            elif seller_city is not None:
                seller_city.storage[want_item] = seller_city.storage.get(want_item, 0) + want_count
                where = "city"
                self.world.touch("civs")
            else:
                self.world.queue_payment(seller_name, payment)
                where = "mail"
            player["rev"] = player.get("rev", 0) + 1
            self.bump_stat(player, "trades_taken", 1)
        self.notify(conn, "notify.trade_done", n=give_count, item=f"item.{give_item}")
        self.notify(conn, "notify.trade_paid", n=want_count, item=f"item.{want_item}")
        if where != "inventory":
            self.broadcast({"type": "notification", "key": "notify.trade_pending",
                            "args": {"name": seller_name, "n": want_count,
                                     "item": f"item.{want_item}"}})
        self.send_trades()

    def on_trade_cancel(self, conn, player_id, msg):
        """Take an offer back and get the goods back into the inventory."""
        trade_id = str(msg.get("id", ""))
        with self.world.lock:
            player = self.world.players.get(player_id)
            offer = self.world.trades.get(trade_id)
            if player is None or offer is None:
                self.notify(conn, "notify.trade_gone")
                return
            if offer.get("owner") != player_id:
                self.notify(conn, "notify.trade_not_yours")
                return
            inventory = player.setdefault("inventory", {})
            give_item, give_count = offer["give_item"], offer["give_count"]
            inventory[give_item] = inventory.get(give_item, 0) + give_count
            self.world.drop_trade(trade_id)
            player["rev"] = player.get("rev", 0) + 1
        self.notify(conn, "notify.trade_cancelled", n=give_count, item=f"item.{give_item}")
        self.send_trades()

    # ------------------------------------------------------- tech / tiers
    def unlocked_recipes(self, player_id) -> set:
        """Recipes unlocked by the country's techs (plus the always-available ones)."""
        with self.world.lock:
            techs = []
            for country in self.world.civs.countries.values():
                if country.leader == player_id or any(
                        c.leader == player_id for c in country.cities):
                    techs.extend(country.techs)
        from shared.techs import unlocked_recipes as _unlocked
        return _unlocked(techs)

    def on_create_city(self, conn, player_id, msg):
        name = str(msg.get("name", "")).strip()[:24]
        if not name:
            self.notify(conn, "notify.city_name_taken")
            return
        if self.leads_city(player_id):
            self.notify(conn, "notify.city_already_lead")
            return
        px, py = self.world.player_pos(player_id)
        with self.world.lock:
            if self.world.civs.create_city(name, player_id, px, py):
                self.world.touch("civs")
                self.notify(conn, "notify.city_founded", name=name)
            else:
                self.notify(conn, "notify.city_name_taken")

    def on_join_city(self, conn, player_id, msg):
        name = str(msg.get("name", ""))
        with self.world.lock:
            if self.world.civs.join_city(name, player_id):
                self.world.touch("civs")
                self.notify(conn, "notify.joined_city", name=name)
            else:
                self.notify(conn, "notify.join_city_fail")

    def on_create_country(self, conn, player_id, msg):
        name = str(msg.get("name", "")).strip()[:24]
        if not name:
            self.notify(conn, "notify.country_name_taken")
            return
        with self.world.lock:
            if any(c.leader == player_id for c in self.world.civs.countries.values()):
                self.notify(conn, "notify.country_already_lead")
                return
            if self.world.civs.create_country(name, player_id):
                self.world.touch("civs")
                self.notify(conn, "notify.country_founded", name=name)
            else:
                self.notify(conn, "notify.country_name_taken")

    def on_join_country(self, conn, player_id, msg):
        country_name = str(msg.get("country", ""))
        city_name = str(msg.get("city", "") or "")
        with self.world.lock:
            if not city_name:
                city = self.world.civs.find_city_of(player_id)
                city_name = city.name if city else ""
            if not city_name:
                self.notify(conn, "notify.take_city_first")
                return
            if self.world.civs.join_country(city_name, country_name, player_id):
                self.world.touch("civs")
                self.notify(conn, "notify.joined_country", name=country_name)
            else:
                self.notify(conn, "notify.join_country_fail")

    # ---------------------------------------------------------------- helpers
    def _push_out(self, player_id, gx, gy, w, h):
        """Move a player standing inside a freshly built solid structure out of it."""
        with self.world.lock:
            player = self.world.players.get(player_id)
            if player is None:
                return
            for _ in range(4):
                gpx, gpy = int(player["x"] // TILE_SIZE), int(player["y"] // TILE_SIZE)
                if not (gx <= gpx < gx + w and gy <= gpy < gy + h):
                    return
                for nx, ny in ((gpx, gy - 1), (gpx, gy + h), (gx - 1, gpy), (gx + w, gpy)):
                    if not self.world.is_blocked_tile(nx, ny) and \
                            f"{nx},{ny}" not in self.world.occupied:
                        player["x"] = nx * TILE_SIZE + TILE_SIZE // 2
                        player["y"] = ny * TILE_SIZE + TILE_SIZE // 2
                        break
                else:
                    return

    def player_name(self, player_id) -> str:
        with self.world.lock:
            return self.world.players.get(player_id, {}).get("name", f"Player {player_id}")

    def leads_city(self, player_id) -> bool:
        with self.world.lock:
            return self.world.civs.find_city_led_by(player_id) is not None

    def country_has_tech(self, player_id, tech) -> bool:
        with self.world.lock:
            for country in self.world.civs.countries.values():
                member = country.leader == player_id or any(
                    c.leader == player_id for c in country.cities)
                if member and tech in country.techs:
                    return True
        return False

    def city_covering(self, x, y):
        """The city whose territory covers a point (b10)."""
        with self.world.lock:
            return self.world.civs.city_at(x, y)

    def player_city(self, player_id):
        with self.world.lock:
            return self.world.civs.find_city_of(player_id)

    def territory_ok(self, player_id, x, y) -> bool:
        """Inside somebody's city only its members with the right role build."""
        return self.territory_blocker(player_id, x, y) is None

    def territory_blocker(self, player_id, x, y):
        """The city that forbids building at this point (None when it is fine).

        b11: the caller used to take the *first* city covering the spot and name
        it in the message, so a player who stood in two overlapping territories
        was told about the city where he actually had the right to build.
        """
        with self.world.lock:
            for city in self.world.civs.cities.values():
                if ((x - city.x) ** 2 + (y - city.y) ** 2) ** 0.5 < city.get_radius():
                    if player_id not in city.members:
                        return city
                    # b10: a plain member ("citizen") needs a role to build here
                    if not city.may(player_id, "build"):
                        return city
        return None

    # ---------------------------------------------------------------- b10: fund
    def city_fund(self, player_id, px, py):
        """The city whose fund may pay for this build (build rights + taxes on)."""
        city = self.city_covering(px, py)
        if city is None or not self.config.get("taxes", True):
            return None
        if player_id not in city.members or not city.may(player_id, "build"):
            return None
        return city

    def pay_for_build(self, structure, player, city) -> dict:
        """Pay from the city fund first, then from the player's own inventory."""
        from_fund = {}
        for res, amount in get_cost(structure).items():
            if city is None:
                break
            available = min(city.storage.get(res, 0), amount)
            if available > 0:
                city.storage[res] = city.storage[res] - available
                from_fund[res] = available
        inventory = player.setdefault("inventory", {})
        for res, amount in get_cost(structure).items():
            left = amount - from_fund.get(res, 0)
            if left > 0:
                inventory[res] = inventory.get(res, 0) - left
        for res in list(get_cost(structure)):
            if inventory.get(res, 0) <= 0:
                inventory.pop(res, None)
        if city is not None and from_fund:
            self.world.touch("civs")
        return from_fund

    def near_building(self, x, y, building_type, radius) -> bool:
        """A building that *provides* the given station, or a building of that type."""
        with self.world.lock:
            for b in self.world.buildings.values():
                if b["type"] != building_type and get_station(b["type"]) != building_type:
                    continue
                bx = b["x"] * TILE_SIZE + TILE_SIZE // 2
                by = b["y"] * TILE_SIZE + TILE_SIZE // 2
                if ((x - bx) ** 2 + (y - by) ** 2) ** 0.5 < radius:
                    return True
        return False

    # ----------------------------------------------------------------- saving
    def save_world(self, quiet: bool = False) -> bool:
        if self.store.path is None:
            return False
        ok = self.store.save(self.world)
        if ok:
            self.last_save = time.time()
            if not quiet:
                print(f"[save] world written to {self.store.path}")
        return ok

    # ------------------------------------------------------------- game loop
    def game_loop(self):
        """Server heartbeat: world time, weather, hunger, animals, machines."""
        last_regen = time.time()
        last_hunger = time.time()
        last_animal = time.time()
        while self.running:
            now = time.time()
            save_interval = float(self.config.get("save_interval", SAVE_INTERVAL) or SAVE_INTERVAL)

            if self.store.path is not None and now - self.last_save > save_interval:
                self.save_world()

            self.tick_clock(now)
            self.tick_hunger(now - last_hunger)
            last_hunger = now
            self.tick_animals(now)

            if now - last_regen > RESOURCE_REGEN_INTERVAL:
                last_regen = now
                with self.world.lock:
                    total = len(self.world.resources)
                regrowth = season_regrowth(self.world.season, self.seasons_on)
                if total < 3000 and regrowth > 0 and \
                        random.random() < min(1.0, regrowth) and \
                        self.world.regenerate_resources():
                    self.broadcast({"type": "notification", "key": "notify.world_regen"})

            respawn = float(self.config.get("animal_respawn", 45) or 45)
            if self.config.get("animals", True) and now - last_animal > respawn:
                last_animal = now
                self.world.spawn_animals(initial=False, amount=2)

            self.tick_machines(now)
            time.sleep(0.5)

    # ------------------------------------------------------------ day & night
    def tick_clock(self, now):
        # a day is `day_length` seconds long; very small values are useful for
        # test worlds (and hurt nobody), so the floor is low on purpose (b13)
        length = max(20.0, float(self.config.get("day_length", 600) or 600))
        before = self.world_time
        self.world_time = (self.world_time + 0.5 / length) % 1.0
        if self.world_time < before:            # the sun came up again: a new day
            self.day += 1
            self.tick_season()
        day = int(self.world_time * 24)
        # night survival achievements
        if abs(self.world_time - 0.95) < 0.002:
            for player in self.world.players.values():
                self.bump_stat(player, "nights_survived", 1)
                self.bump_stat(player, "days_survived", 1)
        if now > self.weather_until:
            self.weather_until = now + random.randint(90, 300)
            self.weather = random.choice(weather_bag(self.world.season, self.seasons_on))
            if self.weather != "clear":
                self.broadcast({"type": "notification",
                                "key": f"notify.weather_{self.weather}"})
        # wolves only hunt when it is dark
        self.night = day < 6 or day >= 21

    def tick_season(self):
        """b13: a new in-game day may bring a new season."""
        season = season_of(self.day, self.days_per_season, self.seasons_on)
        if season == self.world.season:
            return
        self.world.season = season
        self.world.touch("resources")
        self.broadcast({"type": "notification", "key": f"notify.season_{season}"})
        if season == "winter":
            self.broadcast({"type": "notification", "key": "notify.season_cold"})

    def season(self) -> str:
        return self.world.season if self.seasons_on else "summer"

    def tick_hunger(self, elapsed):
        rate = float(self.config.get("hunger_rate", 1.0) or 0)
        if rate <= 0:
            return
        starving = []
        with self.world.lock:
            for pid, player in self.world.players.items():
                player["hunger"] = max(0.0, player.get("hunger", 100) - 0.06 * rate * elapsed)
                if player["hunger"] <= 0:
                    # starving: lose one hit point every couple of seconds
                    player["starve_timer"] = player.get("starve_timer", 0.0) + elapsed
                    while player["starve_timer"] >= 2.0:
                        player["starve_timer"] -= 2.0
                        player["hp"] = int(max(0, player.get("hp", 100) - 1))
                    if player["hp"] <= 0:
                        starving.append(pid)
                elif player["hunger"] > 70 and player.get("hp", 100) < 100:
                    # well fed: slowly heal
                    player["regen_timer"] = player.get("regen_timer", 0.0) + elapsed
                    if player["regen_timer"] >= 5.0:
                        player["regen_timer"] = 0.0
                        player["hp"] = min(100, int(player.get("hp", 100)) + 1)
                # b10: poisoned by bad food - a hospital or a medkit helps
                if player.get("poisoned"):
                    if time.time() >= player.get("poison_until", 0):
                        player["poisoned"] = False
                    else:
                        player["poison_timer"] = player.get("poison_timer", 0.0) + elapsed
                        while player["poison_timer"] >= 2.0:
                            player["poison_timer"] -= 2.0
                            player["hp"] = int(max(0, player.get("hp", 100) - 1))
                            if player["hp"] <= 0 and pid not in starving:
                                starving.append(pid)
                if player.get("hp", 100) < 100:
                    player["hospital_timer"] = player.get("hospital_timer", 0.0) + elapsed
                    if player["hospital_timer"] >= HOSPITAL_TICK:
                        heal = self.hospital_heal(player["x"], player["y"])
                        if heal:
                            player["hospital_timer"] = 0.0
                            player["hp"] = min(100, int(player.get("hp", 100)) + heal)
                        if player.get("poisoned"):
                            player["poison_until"] = min(player.get("poison_until", 0),
                                                         time.time() + 2)
        for pid in starving:
            self.kill_player(pid)

    def hospital_heal(self, x, y) -> int:
        """How much the hospitals around a spot heal per tick (b10)."""
        heal = 0
        with self.world.lock:
            for building in self.world.buildings.values():
                points = get_heal(building["type"])
                if points <= 0:
                    continue
                bx = building["x"] * TILE_SIZE + TILE_SIZE // 2
                by = building["y"] * TILE_SIZE + TILE_SIZE // 2
                if ((x - bx) ** 2 + (y - by) ** 2) ** 0.5 <= 140:
                    heal = max(heal, points)
        return heal

    # ------------------------------------------------------------- animals
    def alert_pack(self, wolf):
        """Wolves hunt in packs: everybody nearby joins in (b9)."""
        pack = wolf.get("pack")
        if not pack:
            return
        for other in self.world.animals.values():
            if other is wolf or other.get("pack") != pack or other.get("hostile") is False:
                continue
            if other.get("owner"):
                continue
            distance = ((other["x"] - wolf["x"]) ** 2 + (other["y"] - wolf["y"]) ** 2) ** 0.5
            if distance <= PACK_ALERT_RANGE:
                other["target"] = wolf.get("target")

    def tick_animals(self, now):
        if not self.config.get("animals", True):
            return
        with self.world.lock:
            animals = [(aid, dict(a)) for aid, a in self.world.animals.items()]
            players = {pid: dict(p) for pid, p in self.world.players.items()}
        for animal_id, animal in animals:
            kind = animal["type"]
            data = ANIMAL_TYPES.get(kind, {})
            speed = data.get("speed", 0.5) * 6
            target_id = animal.get("target") or animal.get("owner")
            target = players.get(target_id) if target_id else None

            # hunters vs pets: wolves hunt at night, bears do not care about
            # the clock at all (b9)
            hunts = bool(data.get("hostile")) and (
                kind == "bear" or (self.night and self.config.get("wolves", True)))
            if hunts and not animal.get("owner") and not target_id:
                nearest, best = None, ANIMAL_AGGRO_RANGE
                for pid, player in players.items():
                    distance = ((player["x"] - animal["x"]) ** 2 +
                                (player["y"] - animal["y"]) ** 2) ** 0.5
                    if distance < best:
                        nearest, best = pid, distance
                if nearest:
                    with self.world.lock:
                        live = self.world.animals.get(animal_id)
                        if live is not None:
                            live["target"] = nearest
                            if live.get("pack"):
                                self.alert_pack(live)      # the whole pack joins
                    target_id, target = nearest, players.get(nearest)

            if target is not None:
                distance = ((target["x"] - animal["x"]) ** 2 +
                            (target["y"] - animal["y"]) ** 2) ** 0.5
                attack_range = data.get("range", 34)
                if distance <= attack_range:
                    # bite (pets bite other players, wolves bite players)
                    if now - animal.get("last_attack", 0) > ANIMAL_ATTACK_COOLDOWN:
                        with self.world.lock:
                            live = self.world.animals.get(animal_id)
                            victim = self.world.players.get(target_id)
                            if live is not None:
                                live["last_attack"] = now
                            if victim is not None:
                                damage = data.get("damage", 5)
                                victim["hp"] = max(0, victim["hp"] - damage)
                                if victim["hp"] <= 0:
                                    self.kill_player(target_id, killer=None)
                        with self.clients_lock:
                            conn = self.clients.get(target_id)
                        if conn:
                            self.notify(conn, "notify.bitten",
                                        animal=f"item.{kind}", damage=damage)
                    continue
                # chase (pets keep the same distance, wolves close in)
                step = speed * (1.6 if data.get("hostile") and not animal.get("owner") else 1.0)
                dx = target["x"] - animal["x"]
                dy = target["y"] - animal["y"]
                length = max(1.0, (dx * dx + dy * dy) ** 0.5)
                follow = 30 if animal.get("owner") else 0
                if length - follow > 6:
                    moved = self.world.move_animal(animal_id, dx / length * step,
                                                   dy / length * step)
                    if not moved and animal.get("owner") is None:
                        with self.world.lock:
                            live = self.world.animals.get(animal_id)
                            if live is not None:
                                live["target"] = None
                continue

            # wander
            if now - animal.get("last_move", 0) < ANIMAL_IDLE:
                continue
            with self.world.lock:
                live = self.world.animals.get(animal_id)
                if live is None:
                    continue
                live["last_move"] = now
                heading = random.random() * 6.283
                step = speed * (2.5 if animal.get("scared_at") and
                                now - animal["scared_at"] < 4 else 1.2)
                import math
                moved = self.world.move_animal(animal_id, math.cos(heading) * step,
                                               math.sin(heading) * step)
                if not moved:
                    # bounce back towards home
                    dx = animal.get("home_x", animal["x"]) - animal["x"]
                    dy = animal.get("home_y", animal["y"]) - animal["y"]
                    length = max(1.0, (dx * dx + dy * dy) ** 0.5)
                    self.world.move_animal(animal_id, dx / length * step, dy / length * step)
                if random.random() < 0.15:
                    self.world.touch("animals")

    # ------------------------------------------------------------- machines
    def farm_growth_seconds(self) -> float:
        """Rain waters the fields, so crops come back faster (b9)."""
        base = 10.0
        if self.config.get("weather", True) and self.weather == "rain":
            return base / 2.0
        return base

    def tick_machines(self, now):
        with self.world.lock:
            drills = [(key, dict(b)) for key, b in self.world.buildings.items()
                      if b["type"] == "drill"]
            pumps = [(key, dict(b)) for key, b in self.world.buildings.items()
                     if b["type"] == "pump"]
        for key, b in drills:
            if now - b.get("last_drill", 0) < DRILL_INTERVAL:
                continue
            with self.world.lock:
                building = self.world.buildings.get(key)
                if building is not None:
                    building["last_drill"] = now
                dx, dy = b["x"] * TILE_SIZE, b["y"] * TILE_SIZE
                mined = None
                for rkey, res in list(self.world.resources.items()):
                    if dx <= res["x"] <= dx + TILE_SIZE and dy <= res["y"] <= dy + TILE_SIZE:
                        mined = res["type"]
                        del self.world.resources[rkey]
                        break
                if mined:
                    self.world.touch("resources")
                    self.give_to_owner(b, RESOURCE_YIELD.get(mined, (mined, 1))[0], 1)
        for key, b in pumps:
            if now - b.get("last_pump", 0) < PUMP_INTERVAL:
                continue
            with self.world.lock:
                building = self.world.buildings.get(key)
                if building is not None:
                    building["last_pump"] = now
                    near_oil = any(abs(res["x"] - b["x"] * TILE_SIZE) < TILE_SIZE * 3 and
                                   abs(res["y"] - b["y"] * TILE_SIZE) < TILE_SIZE * 3
                                   for res in self.world.resources.values()
                                   if res["type"] == "oil_deposit")
                if near_oil:
                    self.give_to_owner(b, "oil_barrel", 1)

    def give_to_owner(self, building, item, amount):
        """Machines pay their owner (or the city warehouse owner belongs to)."""
        owner = building.get("owner")
        with self.world.lock:
            recipient = self.world.players.get(owner)
            if recipient is None:
                return
            inventory = recipient.setdefault("inventory", {})
            inventory[item] = inventory.get(item, 0) + amount
            recipient["rev"] = recipient.get("rev", 0) + 1

    def broadcast_loop(self):
        delay = 1.0 / STATE_RATE
        while self.running:
            self.broadcast_state()
            time.sleep(delay)

    # -------------------------------------------------------------------- run
    def run(self):
        def _stop(signum, _frame):
            print(f"\n[signal {signum}] saving and stopping...")
            self.save_world(quiet=True)
            self.running = False

        try:
            signal.signal(signal.SIGTERM, _stop)
        except (ValueError, AttributeError, OSError, RuntimeError):
            pass  # not the main thread (tests) - fine

        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((self.host, self.port))
        server.listen()
        server.settimeout(1.0)

        print("=" * 56)
        print(f" Civilization Survival  {BUILD}")
        print(f" Listening on {self.host}:{self.port}")
        print(f" Share this address with friends: {local_ip()}:{self.port}")
        print(f" Map: {self.world.width}x{self.world.height} tiles, "
              f"{len(self.world.resources)} resource nodes")
        if self.accounts is not None:
            print(f" Accounts: {self.accounts.account_count()} registered "
                  f"({self.accounts.path})")
        else:
            print(" Accounts: disabled (guests only, nothing is written)")
        if self.loaded_save:
            print(f" World loaded from {self.store.path} (autosave {SAVE_INTERVAL}s)")
        else:
            print(" World is kept in memory (use --save PATH to persist it)")
        print(" Chat commands: /save /wipe /regen /help")
        print("=" * 56)

        threading.Thread(target=self.game_loop, daemon=True).start()
        threading.Thread(target=self.broadcast_loop, daemon=True).start()

        try:
            while self.running:
                try:
                    conn, addr = server.accept()
                except socket.timeout:
                    continue
                player_id = str(self.player_counter)
                self.player_counter += 1
                try:
                    conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                except OSError:
                    pass
                print(f"[+] {addr[0]}:{addr[1]} connected (session {player_id})")
                threading.Thread(target=self.handle_client, args=(conn, player_id),
                                 daemon=True).start()
        except KeyboardInterrupt:
            print("\nShutting down...")
        finally:
            self.running = False
            self.save_world(quiet=True)
            if self.accounts is not None:
                self.accounts.save()
            server.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Civilization Survival server")
    parser.add_argument("--host", default=HOST, help="bind address (default: %(default)s)")
    parser.add_argument("--port", type=int, default=PORT, help="port (default: %(default)s)")
    parser.add_argument("--save", default=os.environ.get("CIV_SAVE", ""),
                        help="save the world to this file (default: memory only)")
    parser.add_argument("--accounts", default=os.environ.get("CIV_ACCOUNTS", DEFAULT_ACCOUNTS_PATH),
                        help="accounts database (default: %(default)s)")
    parser.add_argument("--no-accounts", action="store_true",
                        help="disable accounts (guests only, nothing is written)")
    parser.add_argument("--config", default="",
                        help=f"settings file (default: {CONFIG_FILE} next to the game)")
    args = parser.parse_args(argv)

    GameServer(host=args.host, port=args.port,
               save_path=args.save or None,
               accounts_path=None if args.no_accounts else args.accounts,
               config=load_config(args.config or None)).run()


if __name__ == "__main__":
    main()
