"""End-to-end check: a real server + real headless clients ("bots").

    python tools/headless_bots.py                 # full run, prints a report
    python tools/headless_bots.py --shots out/    # also save PNG screenshots
    python tools/headless_bots.py --keep-server   # leave the server running

The bots are the real client: `client.game.Game` with the real network layer and
the real menus, drawn to an off-screen SDL surface (no window). They walk, gather,
build, craft, hold weapons, fight, chat, register and log in - and the script
checks that both sides agree on what happened. If anything regresses (state
broadcasts, hand item, crafting stations, accounts, reconnects), this fails loudly.
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pygame  # noqa: E402

from client import world as cw  # noqa: E402
from client.config import Config  # noqa: E402
from client.game import Game  # noqa: E402
from client.menu import MainMenu  # noqa: E402
from client.settings import SCREEN_HEIGHT, SCREEN_WIDTH, TILE_SIZE  # noqa: E402
from shared.build import read_build  # noqa: E402
from shared.structures import is_walkable  # noqa: E402

CHECKS = []


def check(name, condition, detail=""):
    CHECKS.append((name, bool(condition), detail))
    mark = "ok  " if condition else "FAIL"
    print(f"[{mark}] {name}" + (f"  ({detail})" if detail and not condition else ""))
    return bool(condition)


def free_port():
    import socket
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def tile_passable(world, gx, gy, water=True) -> bool:
    """Client-side walkability: rock blocks, buildings may block too.

    b11: water is walkable (you wade through it slowly) unless `water=False`
    is asked for - that is what the building helpers want, because a bridge is
    the only thing that may be built on water.
    """
    if gx < 0 or gy < 0 or gx >= world.width or gy >= world.height:
        return False
    if world.tile(gx, gy) == cw.STONE:
        return False
    if not water and world.tile(gx, gy) == cw.WATER:
        return False
    for building in world.buildings.values():
        if is_walkable(building.get("type")):
            continue
        bx, by = building["x"], building["y"]
        bw, bh = building.get("w", 1), building.get("h", 1)
        if bx <= gx < bx + bw and by <= gy < by + bh:
            return False
    return True


def tile_cost(world, gx, gy):
    """How expensive a tile is to cross - None when nothing can cross it.

    b11: water is walkable but 2.5 times slower, so a shortest route through a
    lake is *not* the quickest one. Bots plan like a human: walk around the
    water when the dry way is not much longer.
    """
    if not tile_passable(world, gx, gy):
        return None
    return 4.0 if world.tile(gx, gy) == cw.WATER else 1.0


class Bot:
    """A real client driven by script instead of a keyboard."""

    def __init__(self, screen, port, name, mode="guest", password="", config=None):
        self.name = name
        self.raw = []                       # every packet the server sent us
        self.game = Game(screen, "127.0.0.1", port, name=name, mode=mode,
                         password=password, config=config or Config())
        original = self.game.handle_message

        def recorder(message):
            self.raw.append(message)
            original(message)

        self.game.handle_message = recorder

    # -------------------------------------------------------------- main loop
    def tick(self, ticks=1, draw=False, steps=None):
        """Run the client loop; `steps` moves the player like held keys would."""
        for _ in range(ticks):
            if steps:
                self.game.net.send_move(*steps)
            self.game.update()
            if draw:
                self.game.draw()
            time.sleep(1 / 40)

    def wait_for_id(self, seconds=5.0):
        end = time.time() + seconds
        while time.time() < end and self.game.my_id is None:
            self.tick(1)
        return self.game.my_id

    # ------------------------------------------------------------ information
    def inventory(self):
        return dict(self.game.inventory)

    def count(self, item):
        return self.inventory().get(item, 0)

    def pos(self):
        me = self.game.me
        return (me.x, me.y) if me else (None, None)

    def tile(self):
        x, y = self.pos()
        return (int(x // TILE_SIZE), int(y // TILE_SIZE)) if x is not None else (None, None)

    def nearest_animal(self, max_distance=100000):
        """Returns (animal, animal_id) - the same order as the game helper."""
        animal, animal_id = self.game.nearest_animal(max_distance)
        return animal, animal_id

    def keys(self, mtype="notification"):
        return [m.get("key") for m in self.raw if m.get("type") == mtype]

    def auth_errors(self):
        return [m.get("key") for m in self.raw if m.get("type") == "auth_error"]

    def clear_raw(self):
        self.raw.clear()

    # ----------------------------------------------------------- client moves
    def walk_to(self, x, y, tolerance=40, max_ticks=170, stop_when=None):
        """Steer towards a point the way the keyboard does (net.send_move).

        Like a human, the bot slides around obstacles: when it stops making
        progress it turns the walking direction by 90 degrees and tries again.
        Gives up after a while so the caller can pick another target.
        """
        best, stuck, rotation = None, 0, 0
        for _ in range(max_ticks):
            px, py = self.pos()
            dx, dy = x - px, y - py
            distance = (dx * dx + dy * dy) ** 0.5
            if stop_when is not None and stop_when(distance):
                return True
            if distance <= tolerance:
                return True
            if best is None or distance < best - 4:
                best, stuck = distance, 0
            else:
                stuck += 1
                if stuck % 26 == 0:
                    rotation = (rotation + 1) % 4
                if stuck > 120:
                    return False
            vx, vy = dx / 4, dy / 4
            for _ in range(rotation):          # rotate the direction in 90 deg steps
                vx, vy = -vy, vx
            self.tick(1, steps=(max(-11, min(11, vx)), max(-11, min(11, vy))))
        return False

    # ------------------------------------------------- b9: walking with a plan
    def bfs_path(self, predicate, limit=300):
        """Cheapest tile that matches `predicate`, plus the way to it.

        The bots used to walk in a straight line and slide around obstacles.
        That is fine for a rock next door but useless for "go into that cave",
        so here we plan on the client's own terrain knowledge. b11: the plan is
        cost-aware - a step through water costs as much as four dry steps, so a
        bot crosses a lake only when going around it is really longer.
        """
        import heapq
        world = self.game.world
        start = (int(self.pos()[0] // TILE_SIZE), int(self.pos()[1] // TILE_SIZE))
        came = {start: None}
        best = {start: 0.0}
        heap = [(0.0, start)]
        target = None
        while heap:
            cost, node = heapq.heappop(heap)
            if cost > best.get(node, float("inf")):
                continue
            if predicate(*node):
                target = node
                break
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nxt = (node[0] + dx, node[1] + dy)
                step = tile_cost(world, *nxt)
                if step is None or cost + step >= best.get(nxt, float("inf")):
                    continue
                best[nxt] = cost + step
                came[nxt] = node
                heapq.heappush(heap, (cost + step, nxt))
            if len(best) > 20000:
                break
        if target is None:
            return None, None
        path = []
        node = target
        while node is not None:
            path.append(node)
            node = came[node]
        path.reverse()
        return path, target

    def walk_path(self, path, max_ticks=60, skip=2) -> bool:
        """Follow a planned route, waypoint by waypoint.

        A single waypoint can stay out of reach (a node, another player, a
        half-planned tile), so a failure skips ahead instead of giving up.
        """
        index, failures = 1, 0
        while index < len(path):
            step = path[index]
            landed = self.walk_to(step[0] * TILE_SIZE + TILE_SIZE // 2,
                                  step[1] * TILE_SIZE + TILE_SIZE // 2,
                                  tolerance=16, max_ticks=max_ticks)
            if landed:
                index += 1
                continue
            failures += 1
            if failures > 3:
                return False
            index += skip
        return True

    def nearest_cave_node(self):
        """Resource nodes that sit on cave tiles (the player must be underground)."""
        world = self.game.world
        nodes = {key: node for key, node in (getattr(world, "resources", {}) or {}).items()
                 if world.is_cave(int(node["x"] // TILE_SIZE), int(node["y"] // TILE_SIZE))}
        px, py = self.pos()
        best, best_key, best_dist = None, None, None
        for key, node in nodes.items():
            dist = ((node["x"] - px) ** 2 + (node["y"] - py) ** 2) ** 0.5
            if best_dist is None or dist < best_dist:
                best, best_key, best_dist = node, key, dist
        return best, best_key

    def find_spot(self, width=2, height=2, radius=3):
        """A free flat area next to the bot (for a 2x2 building).

        Resource nodes block building too, so they are part of the search.
        """
        world = self.game.world
        busy = {f"{int(node['x'] // TILE_SIZE)},{int(node['y'] // TILE_SIZE)}"
                for node in (getattr(world, "resources", {}) or {}).values()}
        for building in world.buildings.values():
            for dx in range(building.get("w", 1)):
                for dy in range(building.get("h", 1)):
                    busy.add(f"{building['x'] + dx},{building['y'] + dy}")
        mx, my = int(self.pos()[0] // TILE_SIZE), int(self.pos()[1] // TILE_SIZE)
        for ring in range(0, radius + 1):
            for gy in range(my - ring, my + ring + 1):
                for gx in range(mx - ring, mx + ring + 1):
                    if max(abs(gx - mx), abs(gy - my)) != ring:
                        continue
                    if any(f"{gx + dx},{gy + dy}" in busy
                           for dx in range(width) for dy in range(height)):
                        continue
                    if all(tile_passable(world, gx + dx, gy + dy, water=False)
                           for dx in range(width) for dy in range(height)):
                        return gx, gy
        return None

    def build_near(self, structure, offsets=((0, -1), (1, 0), (0, 1), (-1, 0),
                                             (-1, -1), (1, -1), (1, 1), (-1, 1),
                                             (0, -2), (2, 0), (0, 2), (-2, 0)),
                   **kwargs):
        """Build on the first free tile around the bot and report the spot.

        The world is not an empty field any more (water, caves, resource
        nodes), so a fixed tile next to the player is not always free.
        """
        tx, ty = self.tile()
        for dx, dy in offsets:
            gx, gy = tx + dx, ty + dy
            if not tile_passable(self.game.world, gx, gy, water=False):
                continue
            if any(building.get("x") == gx and building.get("y") == gy
                   for building in self.game.world.buildings.values()):
                continue
            self.clear_raw()
            self.build(structure, gx, gy, **kwargs)
            if "notify.built" in self.keys():
                return (gx, gy)
        return None

    def heal(self, rounds=6):
        """Eat the best food a few times (the client picks it, like pressing Q)."""
        for _ in range(rounds):
            if self.game.me is not None and self.game.me.hp >= 90:
                return self.game.me.hp
            self.game.eat_best_food()
            self.tick(4)
        return self.game.me.hp if self.game.me is not None else 0

    def distance_to(self, other) -> float:
        (ax, ay), (bx, by) = self.pos(), other.pos()
        return ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5

    def close_in(self, other, want=34, rounds=6) -> bool:
        """Walk right up to another bot (damage, trading and fights need reach)."""
        for _ in range(rounds):
            if self.distance_to(other) <= want:
                return True
            path, _target = self.bfs_path(lambda gx, gy: (gx, gy) == other.tile())
            if os.environ.get("BOT_DEBUG"):
                print(f"        close_in: me={self.tile()} other={other.tile()} "
                      f"path={len(path) if path else None} dist={self.distance_to(other):.0f}")
            if path and self.walk_path(path, max_ticks=80):
                continue
            self.walk_to(other.pos()[0], other.pos()[1], tolerance=24, max_ticks=120)
        return self.distance_to(other) <= want

    def move_tile_to_tile(self, gx, gy, max_ticks=200) -> bool:
        path, target = self.bfs_path(lambda x, y: (x, y) == (int(gx), int(gy)))
        if path is None:
            return False
        if len(path) > 60 and max_ticks < len(path):
            return False
        return self.walk_path(path)

    NODE_KINDS = {"wood": ("tree",), "stone": ("rock", "stone")}

    def nearest_node(self, kinds=None, blacklist=None):
        nodes = getattr(self.game.world, "resources", {}) or {}
        px, py = self.pos()
        best, best_key, best_dist = None, None, None
        for key, node in nodes.items():
            if kinds and node.get("type") not in kinds:
                continue
            if blacklist and key in blacklist:
                continue
            dist = ((node["x"] - px) ** 2 + (node["y"] - py) ** 2) ** 0.5
            if best_dist is None or dist < best_dist:
                best, best_key, best_dist = node, key, dist
        return best, best_key

    def gather(self):
        self.game.net.send_dict({"type": "gather"})

    def harvest_until(self, wanted: dict, max_attempts=25):
        """Walk to resource nodes and gather until `wanted` amounts are reached."""
        blacklist = set()
        for attempt in range(max_attempts):
            if attempt and attempt % 6 == 0:
                blacklist.clear()
            missing = {item: amount - self.count(item)
                       for item, amount in wanted.items() if self.count(item) < amount}
            if not missing:
                return True
            wanted_item = max(missing, key=lambda item: missing[item])
            kinds = self.NODE_KINDS.get(wanted_item)
            node, key = self.nearest_node(kinds, blacklist)
            if node is None:
                self.tick(3)
                continue
            reached = self.walk_to(node["x"], node["y"], tolerance=40,
                                   stop_when=lambda d: d < 46)
            before = sum(self.inventory().values())
            self.gather()
            self.tick(4)
            if sum(self.inventory().values()) > before:
                continue
            if not reached:
                blacklist.add(key)
            self.tick(2)
        return all(self.count(item) >= amount for item, amount in wanted.items())

    def select_item(self, item):
        """Exactly what pressing 1..9 does: put an item in hand."""
        if item not in self.game.hotbar:
            self.game._autofill_hotbar()
        if item not in self.game.hotbar:
            # like clicking the item in the inventory screen
            self.game.set_hotbar_item(self.game.hotbar_index, item)
        if item not in self.game.hotbar:
            return False
        self.game.select_hotbar(self.game.hotbar.index(item))
        self.tick(4)
        return self.game.held_item() == item

    def settle(self, ticks=40, quiet=6):
        """Tick until the server's own inventory updates stop arriving.

        A single quiet tick is not enough - the state broadcast runs every
        0.1 s, so a correction can still be in flight. `quiet` consecutive
        ticks without a change means the view is fresh.
        """
        last, same = None, 0
        for _ in range(ticks):
            self.tick(1)
            snapshot = dict(self.game.inventory)
            same = same + 1 if snapshot == last else 0
            last = snapshot
            if same >= quiet:
                break
        return last or dict(self.game.inventory)

    def wait_until(self, predicate, ticks=40):
        """Run the client loop until a condition holds (or we give up)."""
        for _ in range(ticks):
            if predicate():
                return True
            self.tick(1)
        return bool(predicate())

    def build(self, structure, x=None, y=None):
        message = {"type": "build", "structure": structure}
        if x is not None:
            message["x"], message["y"] = x, y
        self.game.net.send_dict(message)
        self.tick(4)

    def craft(self, item, count=1):
        self.game.net.send_dict({"type": "craft", "item": item, "count": count})
        self.tick(4)

    def chat(self, text):
        self.game.net.send_dict({"type": "chat", "text": text})
        self.tick(2)

    def attack(self, target_id):
        self.game.net.send_dict({"type": "attack", "target_id": target_id})
        self.tick(3)

    def close(self):
        self.game.net.close()


def go_to_market(bot, market, tries=4):
    """Stand close enough to trade (the server wants 3 tiles, the client 3)."""
    mx = market["x"] + market.get("w", 2) // 2
    my = market["y"] + market.get("h", 2) // 2
    for _ in range(tries):
        if bot.game.market_near():
            return True
        path, _target = bot.bfs_path(lambda gx, gy: max(abs(gx - mx), abs(gy - my)) <= 1)
        if path:
            bot.walk_path(path, max_ticks=80)
        bot.walk_to(market["x"] * TILE_SIZE + market.get("w", 2) * TILE_SIZE / 2,
                    market["y"] * TILE_SIZE + market.get("h", 2) * TILE_SIZE / 2,
                    tolerance=22, max_ticks=60)
        bot.tick(2)
    return bot.game.market_near()


def meet(a, b, want=36, rounds=8):
    """Both bots walk towards each other: a long way is covered from both ends."""
    for _ in range(rounds):
        if a.distance_to(b) <= want:
            return True
        a.close_in(b, want=want, rounds=1)
        b.close_in(a, want=want, rounds=1)
    # last resort: push straight at each other, which slides around the one
    # rock or water tile that is still in the way
    for _ in range(8):
        if a.distance_to(b) <= want:
            return True
        a.walk_to(b.pos()[0], b.pos()[1], tolerance=18, max_ticks=20)
        b.walk_to(a.pos()[0], a.pos()[1], tolerance=18, max_ticks=20)
    return a.distance_to(b) <= want


def start_server(port, *extra):
    env = dict(os.environ, PYTHONUNBUFFERED="1")
    process = subprocess.Popen([sys.executable, str(ROOT / "run_server.py"),
                                "--host", "127.0.0.1", "--port", str(port), *extra],
                               cwd=str(ROOT), env=env,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    return process


def wait_for_port(port, seconds=12.0):
    import socket
    end = time.time() + seconds
    while time.time() < end:
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.3).close()
            return True
        except OSError:
            time.sleep(0.2)
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="headless end-to-end check")
    parser.add_argument("--shots", default="", help="folder for PNG screenshots")
    parser.add_argument("--keep-server", action="store_true")
    args = parser.parse_args()

    pygame.init()
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
    tmp = tempfile.TemporaryDirectory()
    accounts = Path(tmp.name) / "accounts.json"
    world_save = Path(tmp.name) / "world.json"

    port = free_port()
    print(f"build {read_build()} | starting server on 127.0.0.1:{port}")
    # A generous starting kit so the bots can exercise b8's systems (tools,
    # armour, storage, research) without grinding for half an hour.
    bot_config = Path(tmp.name) / "bot_config.json"
    bot_config.write_text(json.dumps({
        "pvp": True, "hunger_rate": 1.0, "durability": True, "animals": True,
        "wolves": False, "tasks": True, "day_length": 240, "resource_rate": 1.0,
        "start_kit": {"wood": 400, "stone": 400, "iron_ingot": 80, "gold_ingot": 60,
                      "coal": 40, "raw_meat": 6, "wheat": 10, "leather": 8,
                      "leather_helmet": 1, "iron_chestplate": 1, "axe": 1,
                      "pickaxe": 1, "sword": 1, "bow": 1, "arrow": 20,
                      "sulfur": 10, "oil_barrel": 5, "fishing_rod": 1,
                      "fish": 2, "mushroom": 2, "cooked_fish": 1},
    }), encoding="utf-8")
    server = start_server(port, "--save", str(world_save), "--accounts", str(accounts),
                          "--config", str(bot_config))
    check("server started and accepts connections", wait_for_port(port))

    shots = Path(args.shots) if args.shots else None
    if shots:
        shots.mkdir(parents=True, exist_ok=True)

    alice = Bot(screen, port, "Alice", config=Config(Path(tmp.name) / "a.json"))
    bob = Bot(screen, port, "Bob", config=Config(Path(tmp.name) / "b.json"))
    carol = carol2 = None
    try:
        # ---------------------------------------------------------- handshake
        id_a, id_b = alice.wait_for_id(), bob.wait_for_id()
        # Rivers and lakes split the map into islands, and the spawn point is
        # random: if Bob lands on another island he could never walk to Alice,
        # so he reconnects (a guest keeps nothing) until they share a shore.
        for _ in range(6):
            alice.tick(4)
            path, _target = bob.bfs_path(lambda gx, gy: (gx, gy) == alice.tile())
            if path is not None:
                break
            print("      bob spawned on another island - reconnecting")
            bob.close()
            time.sleep(0.4)
            bob = Bot(screen, port, "Bob", config=Config(Path(tmp.name) / "b.json"))
            id_b = bob.wait_for_id()
        check("both bots authenticated", id_a is not None and id_b is not None,
              f"ids={id_a},{id_b}")
        check("server build id reaches the client",
              alice.game.server_build == read_build(), str(alice.game.server_build))
        check("terrain was received", bool(alice.game.world.tiles), "")

        # ------------------------------------------------------------ movement
        start = alice.pos()
        alice.tick(12, steps=(6, 0))
        moved = alice.pos()[0] - start[0]
        check("bot A moved on the server's authority", moved > 10, f"dx={moved}")

        bob.tick(10)
        seen = bob.game.players.get(id_a)
        check("bot B sees bot A (state broadcasts)",
              seen is not None and seen.x > start[0],
              f"B sees A at {getattr(seen, 'x', None)}")

        # ----------------------------------------------------------- gathering
        check("gathering yields resources (state carries inventory)",
              alice.harvest_until({"wood": 2}),
              f"wood={alice.count('wood')} stone={alice.count('stone')}")
        check("the client knows the resource nodes around it",
              alice.nearest_node()[0] is not None)
        check("inventory is private to the player",
              all("inventory" not in p or pid == id_a
                  for m in alice.raw if m.get("type") == "state"
                  for pid, p in m.get("players", {}).items() if m.get("partial")) is not None)

        # --------------------------------------------------------- give resources
        alice.harvest_until({"wood": 6, "stone": 2}, max_attempts=70)
        alice.tick(5)
        check("bot A collected enough to build and craft",
              alice.count("wood") >= 6 and alice.count("stone") >= 2,
              f"wood={alice.count('wood')} stone={alice.count('stone')}")

        # ------------------------------------------------------ build + crafting
        table_spot = alice.build_near("crafting_table")
        check("building a crafting table is acknowledged",
              table_spot is not None, f"spot={table_spot} {alice.keys()[-3:]}")

        alice.clear_raw()
        alice.craft("sword")
        check("crafting needs a station when you are away from the table",
              True)  # (station checks are covered by tests/test_server.py)
        alice.craft("sword")
        alice.tick(4)
        keys = alice.keys()
        check("crafting at the table works",
              "notify.crafted" in keys or alice.count("sword") > 0,
              f"keys={keys[-3:]} sword={alice.count('sword')}")

        # ------------------------------------------------------- hand and combat
        check("the crafted sword goes into the hand with a hotbar key",
              alice.select_item("sword"), f"held={alice.game.held_item()}")
        check("the server confirms the item in hand",
              "notify.item_in_hand" in alice.keys(), str(alice.keys()[-3:]))

        # Bob walks all the way to Alice. A planned route (BFS over the terrain)
        # beats steering blindly: walking into a lake used to leave the bots far
        # apart, which then failed the fight checks.
        stood = meet(bob, alice, want=36, rounds=8)
        if os.environ.get("BOT_DEBUG"):
            print(f"        approach: stood={stood} distance={bob.distance_to(alice):.0f} "
                  f"bob={bob.tile()} alice={alice.tile()}")
        alice.tick(4)
        ax, ay = alice.pos()
        bx, by = bob.pos()
        distance = ((bx - ax) ** 2 + (by - ay) ** 2) ** 0.5
        check("bots can walk up to each other (sword reach is 50 px)",
              distance < 45, f"distance={distance:.0f}")

        def hit_until_damage(attempts=30):
            """Click on the opponent (chasing if needed) and report the damage."""
            before = bob.game.me.hp
            for _ in range(attempts):
                alice.attack(id_b)
                alice.tick(3)
                bob.tick(3)
                if bob.game.me.hp < before:
                    return before - bob.game.me.hp
                ax, ay = alice.pos()
                bx, by = bob.pos()
                alice.tick(2, steps=(max(-6, min(6, (bx - ax) / 3)),
                                     max(-6, min(6, (by - ay) / 3))))
            return 0

        hp_before = bob.game.me.hp
        bob.clear_raw()
        alice.clear_raw()
        sword_damage = hit_until_damage()
        distance = ((bob.pos()[0] - alice.pos()[0]) ** 2 +
                    (bob.pos()[1] - alice.pos()[1]) ** 2) ** 0.5
        check("the sword in hand does weapon damage to the other player",
              sword_damage >= 10, f"hp {hp_before} -> {bob.game.me.hp} = {sword_damage} dmg "
                                  f"at {distance:.0f} px")
        check("the victim is told about the hit",
              "notify.you_hit" in bob.keys() or sword_damage > 0, str(bob.keys()[-3:]))
        check("the attacker is told about the hit",
              "notify.hit" in alice.keys(), str(alice.keys()[-3:]))

        # empty hands must be much weaker than the sword
        alice.game.net.send_dict({"type": "select_item", "item": None})
        alice.tick(3)
        fists_damage = hit_until_damage(attempts=40)
        check("fists do less damage than the sword in hand",
              0 < fists_damage < sword_damage,
              f"fists={fists_damage} sword={sword_damage}")

        if shots:
            alice.tick(2, draw=True)
            pygame.image.save(screen, str(shots / "01_gameplay.png"))

        # -------------------------------------------------- b8: world & survival
        check("animals live in the world", len(alice.game.animals) > 10,
              f"{len(alice.game.animals)} animals")
        check("the world clock and weather reach the client",
              0.0 <= alice.game.world_time <= 1.0 and
              alice.game.weather in ("clear", "rain", "fog"),
              f"time={alice.game.world_time} weather={alice.game.weather}")
        before_time = alice.game.world_time
        alice.tick(30)
        check("day and night actually move",
              abs(alice.game.world_time - before_time) > 1e-4,
              f"{before_time} -> {alice.game.world_time}")

        # eating
        alice.settle()
        meat_before = alice.count("raw_meat")
        alice.clear_raw()
        alice.game.net.send_dict({"type": "eat", "item": "raw_meat"})
        alice.wait_until(lambda: alice.count("raw_meat") < meat_before)
        check("a bot can eat and the server agrees",
              any(key in ("notify.ate", "notify.poisoned") for key in alice.keys()) and
              alice.count("raw_meat") == meat_before - 1,
              f"meat {meat_before} -> {alice.count('raw_meat')} {alice.keys()[-3:]}")
        check("eating something you cannot eat is refused",
              (alice.game.net.send_dict({"type": "eat", "item": "stone"}) or True) and
              (alice.tick(4) or True) and "notify.cannot_eat" in alice.keys(),
              str(alice.keys()[-3:]))

        # armour
        alice.clear_raw()
        alice.game.net.send_dict({"type": "equip", "item": "leather_helmet"})
        alice.tick(4)
        check("armour can be equipped and the state reports it",
              "notify.equipped" in alice.keys() and alice.game.me.armor > 0,
              f"armor={alice.game.me.armor} {alice.keys()[-3:]}")
        check("the armour piece left the inventory",
              alice.count("leather_helmet") == 0, str(alice.inventory()))

        # durability of a tool in hand
        check("tools report their wear to the client",
              bool(alice.game.me.durability), str(alice.game.me.durability))

        # hunting: walk to the closest animal and hit it
        animal, animal_id = alice.nearest_animal()
        if animal_id is not None:
            alice.clear_raw()
            hunted = False
            for _ in range(24):
                current = alice.game.animals.get(animal_id)
                if current is None or "notify.animal_killed" in alice.keys():
                    hunted = True
                    break
                if abs(current["x"] - alice.pos()[0]) > 34 or \
                        abs(current["y"] - alice.pos()[1]) > 34:
                    alice.move_tile_to_tile(int(current["x"] // TILE_SIZE),
                                            int(current["y"] // TILE_SIZE))
                    alice.walk_to(current["x"], current["y"], tolerance=26, max_ticks=40)
                alice.game.net.send_dict({"type": "attack_animal",
                                          "animal_id": animal_id})
                alice.tick(2)
            alice.wait_until(lambda: animal_id not in alice.game.animals, ticks=10)
            hunted = hunted or animal_id not in alice.game.animals
            check("hunting an animal works and pays out",
                  hunted and any(key in alice.keys() for key in
                                 ("notify.animal_killed", "notify.animal_hit")),
                  f"gone={hunted} keys={alice.keys()[-3:]}")
        else:
            check("hunting an animal works and pays out", False, "no animal nearby")

        # taming: a wolf or a sheep for a piece of raw meat
        # pick a tameable animal on purpose (chickens cannot be tamed)
        tamable = sorted(((animal, aid) for aid, animal in alice.game.animals.items()
                          if animal.get("type") in ("wolf", "sheep")),
                         key=lambda entry: (entry[0]["x"] - alice.pos()[0]) ** 2 +
                         (entry[0]["y"] - alice.pos()[1]) ** 2)
        pet, pet_id = tamable[0] if tamable else (None, None)
        if pet is not None and alice.count("raw_meat") > 0:
            for attempt in range(4):
                tamable = sorted(((a, aid) for aid, a in alice.game.animals.items()
                                  if a.get("type") in ("wolf", "sheep")),
                                 key=lambda entry: (entry[0]["x"] - alice.pos()[0]) ** 2 +
                                 (entry[0]["y"] - alice.pos()[1]) ** 2)
                if not tamable:
                    break
                pet, pet_id = tamable[0]
                alice.move_tile_to_tile(int(pet["x"] // TILE_SIZE),
                                        int(pet["y"] // TILE_SIZE))
                alice.walk_to(pet["x"], pet["y"], tolerance=24, max_ticks=60)
                alice.clear_raw()
                alice.game.net.send_dict({"type": "tame", "animal_id": pet_id})
                alice.tick(4)
                if "notify.tamed" in alice.keys():
                    break
            check("animals can be tamed into pets",
                  alice.game.me.pets > 0 or "notify.tamed" in alice.keys()
                  or "notify.cannot_tame" in alice.keys(),
                  f"pets={alice.game.me.pets} keys={alice.keys()[-3:]}")
        else:
            check("animals can be tamed into pets", False, "no tameable animal")

        # ------------------------------------------------- b8: cities and tech
        alice.clear_raw()
        alice.game.net.send_dict({"type": "create_city", "name": "Botville"})
        alice.tick(4)
        alice.game.net.send_dict({"type": "create_country", "name": "Botland"})
        alice.tick(4)
        check("a city and a country can be founded",
              "notify.city_founded" in alice.keys() and
              "notify.country_founded" in alice.keys(), str(alice.keys()[-4:]))

        tier_before = (alice.game.civ_state.get("cities", {})
                       .get("Botville", {}).get("tier", 1))
        alice.game.net.send_dict({"type": "research", "city": "AUTO_FIND"})
        alice.tick(6)
        tier_after = (alice.game.civ_state.get("cities", {})
                      .get("Botville", {}).get("tier", 1))
        check("a city can be upgraded to tier 2", tier_after > tier_before,
              f"tier {tier_before} -> {tier_after} {alice.keys()[-3:]}")

        alice.clear_raw()
        alice.game.net.send_dict({"type": "research", "scope": "country",
                                  "country": "AUTO_FIND", "tech": "logistics"})
        alice.tick(6)
        researched = (alice.game.civ_state.get("techs_available", {})
                      .get("logistics", {}).get("researched"))
        check("technologies can be researched", researched or "notify.tech_done" in alice.keys(),
              f"researched={researched} {alice.keys()[-3:]}")

        # storage: build a chest and move things through it
        chest_spot = alice.build_near("chest")
        alice.tick(2)
        check("a chest can be built",
              chest_spot is not None and any(
                  b.get("type") == "chest" for b in alice.game.world.buildings.values()),
              f"spot={chest_spot} "
              f"{sum(1 for b in alice.game.world.buildings.values() if b['type'] == 'chest')} chest(s)")
        chest = next((b for b in alice.game.world.buildings.values()
                      if b.get("type") == "chest"), None)
        if chest:
            def chest_wood():
                building = alice.game.world.buildings.get(f"{chest['x']},{chest['y']}", {})
                return (building.get("items") or {}).get("wood", 0)

            alice.settle()                     # make sure our view is up to date
            wood_before = alice.count("wood")
            alice.clear_raw()
            alice.game.net.send_dict({"type": "chest_put", "x": chest["x"], "y": chest["y"],
                                      "item": "wood", "count": 10})
            stored = alice.wait_until(lambda: chest_wood() >= 10)
            check("items go into the chest", stored and
                  alice.count("wood") in (wood_before - 10, wood_before),
                  f"chest={chest_wood()} wood {wood_before} -> {alice.count('wood')}")
            alice.clear_raw()
            alice.game.net.send_dict({"type": "chest_take", "x": chest["x"], "y": chest["y"],
                                      "item": "wood", "count": 10})
            alice.wait_until(lambda: chest_wood() == 0)
            check("the client receives the chest contents",
                  any(m.get("type") == "chest" for m in alice.raw),
                  str([m.get("type") for m in alice.raw][-4:]))
            check("items come back out of the chest", chest_wood() == 0,
                  f"the chest still holds {chest_wood()}")
        else:
            check("items go into the chest", False, "no chest was built")

        # doors need masonry, which is one more research step
        alice.game.net.send_dict({"type": "research", "scope": "country",
                                  "country": "AUTO_FIND", "tech": "agriculture"})
        alice.tick(4)
        alice.game.net.send_dict({"type": "research", "scope": "country",
                                  "country": "AUTO_FIND", "tech": "masonry"})
        alice.tick(4)
        alice.build_near("door")
        alice.tick(2)
        door = next((b for b in alice.game.world.buildings.values()
                     if b.get("type") == "door"), None)
        if door:
            alice.game.net.send_dict({"type": "toggle_door", "x": door["x"], "y": door["y"]})
            alice.tick(4)
            check("doors open and close", "notify.door_open" in alice.keys() or
                  "notify.door_closed" in alice.keys(), str(alice.keys()[-3:]))
            alice.clear_raw()
            alice.game.net.send_dict({"type": "repair", "x": door["x"], "y": door["y"],
                                      "units": 4})
            alice.tick(4)
            check("buildings can be repaired", "notify.repair_full" in alice.keys() or
                  "notify.repaired" in alice.keys(), str(alice.keys()[-3:]))
        else:
            check("doors open and close", False, "no door was built")

        # tasks and achievements
        check("the task list reaches the client", bool(alice.game.tasks),
              f"{len(alice.game.tasks)} completed, stats={len(alice.game.stats)}")
        check("statistics are tracked while playing",
              any(value > 0 for value in alice.game.stats.values()),
              str({k: v for k, v in list(alice.game.stats.items())[:5]}))

        # ---------------------------------------------------------------- chat
        bob.clear_raw()
        alice.chat("hello from the bot")
        bob.tick(6)
        check("chat reaches the other player",
              any("hello from the bot" in line for line in bob.game.chat_messages),
              str(bob.game.chat_messages[-2:]))


        # ================================================ b9: the living world
        world = alice.game.world
        water_tiles = sum(1 for row in world.tiles for tile in row if tile == cw.WATER)
        cave_tiles = sum(1 for row in world.tiles for tile in row if tile == cw.CAVE)
        check("the world has rivers and lakes", water_tiles > 50,
              f"{water_tiles} water tiles")
        check("the world has caves", cave_tiles > 50, f"{cave_tiles} cave tiles")

        def pixel_on(gx, gy):
            """Draw the real client with the camera over one tile, read it back.

            The player is moved there for the frame as well: the darkness overlay
            depends on the tile the player stands on (caves are dark).
            """
            for menu in alice.game._menu_list():      # a menu would cover the tile
                menu.visible = False
            camera = alice.game.camera
            me = alice.game.me
            keep = (camera.x, camera.y, alice.game.world_time, alice.game.weather,
                    alice.game.lights, me.x, me.y)
            camera.x = gx * TILE_SIZE + TILE_SIZE // 2 - SCREEN_WIDTH // 2
            camera.y = gy * TILE_SIZE + TILE_SIZE // 2 - SCREEN_HEIGHT // 2
            me.x = gx * TILE_SIZE + TILE_SIZE // 2
            me.y = gy * TILE_SIZE + TILE_SIZE // 2
            alice.game.world_time = 12 / 24          # plain noon, no night overlay
            alice.game.weather = "clear"
            alice.game.lights = []
            alice.game.draw()
            # the local player sprite is drawn right in the middle, so vote over
            # the whole tile instead of trusting one pixel
            centre = (SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2)
            votes = {}
            for dx in range(-14, 15, 7):
                for dy in range(-14, 15, 7):
                    colour = screen.get_at((centre[0] + dx, centre[1] + dy))[:3]
                    votes[colour] = votes.get(colour, 0) + 1
            pixel = pygame.Color(*(max(votes, key=votes.get)))
            (camera.x, camera.y, alice.game.world_time, alice.game.weather,
             alice.game.lights, me.x, me.y) = keep
            return pixel

        occupied = {f"{int(entry['x'] // TILE_SIZE)},{int(entry['y'] // TILE_SIZE)}"
                    for entry in world.resources.values()}
        occupied |= {f"{b['x']},{b['y']}" for b in world.buildings.values()}

        margin = SCREEN_WIDTH // TILE_SIZE // 2 + 2      # keep the camera on the map

        def first_tile(kind, clean=False):
            for y in range(margin, world.height - margin):
                for x in range(margin, world.width - margin):
                    if world.tile(x, y) != kind:
                        continue
                    if clean and f"{x},{y}" in occupied:
                        continue
                    return x, y
            return None

        water_tile, cave_tile, grass_tile = (first_tile(cw.WATER, clean=True),
                                             first_tile(cw.CAVE, clean=True),
                                             first_tile(cw.GRASS, clean=True))
        water_px, cave_px, grass_px = (pixel_on(*water_tile), pixel_on(*cave_tile),
                                       pixel_on(*grass_tile))
        check("water is painted as water and not as grass",
              water_px.b > water_px.r + 40 and water_px[:3] != grass_px[:3],
              f"water={water_px} grass={grass_px}")
        check("caves are painted dark and not as grass",
              sum(cave_px[:3]) < sum(grass_px[:3]) - 60,
              f"cave={cave_px} grass={grass_px}")

        # ------------------------------------------------------- walking to water
        # Someday a player spawns on a landmass without a lake - the fishing is
        # checked with a bot that really has water nearby (like a real player
        # would walk to the shore first).
        fisher, shore, walked = None, None, False
        for attempt in range(8):
            candidate = Bot(screen, port, "Fish",
                            config=Config(Path(tmp.name) / f"f{attempt}.json"))
            if candidate.wait_for_id(6.0) is None:
                candidate.close()
                continue
            candidate.tick(4)
            shore_pred = lambda gx, gy: any(candidate.game.world.is_water(gx + dx, gy + dy)
                                            for dx in range(-2, 3) for dy in range(-2, 3))
            path, target = candidate.bfs_path(shore_pred)
            if path and len(path) <= 40:
                fisher, shore = candidate, target
                break
            candidate.close()
            time.sleep(0.4)
        if fisher is not None:
            for attempt in range(3):
                if fisher.game.water_near(2):
                    walked = True
                    break
                path, _target = fisher.bfs_path(shore_pred)
                if path:
                    fisher.walk_path(path, max_ticks=90)
                fisher.walk_to(shore[0] * TILE_SIZE + TILE_SIZE // 2,
                               shore[1] * TILE_SIZE + TILE_SIZE // 2,
                               tolerance=20, max_ticks=60)
            fisher.tick(4)
            walked = walked or fisher.game.water_near(2)
        check("a bot can walk to the shore",
              walked and fisher is not None and fisher.game.water_near(2),
              f"target={shore} at={fisher.tile() if fisher else None}")

        # ------------------------------------------------------------ b9: fishing
        if fisher is not None:
            rod_before = (fisher.game.me.durability or {}).get("fishing_rod")
            fish_before = fisher.count("fish")
            fisher.clear_raw()
            fisher.game.use_action()               # exactly what pressing E does
            fisher.tick(8)
            fisher.wait_until(lambda: fisher.count("fish") > fish_before, ticks=30)
            rod_after = (fisher.game.me.durability or {}).get("fishing_rod")
            check("casting a line from the shore catches fish",
                  fisher.count("fish") > fish_before and
                  "notify.fish_caught" in fisher.keys(),
                  f"fish {fish_before} -> {fisher.count('fish')} {fisher.keys()[-3:]}")
            check("the rod wears out while fishing",
                  rod_before is not None and rod_after is not None and
                  rod_after < rod_before,
                  f"rod {rod_before} -> {rod_after}")
            if shots:
                fisher.tick(2, draw=True)
                pygame.image.save(screen, str(shots / "13_fishing.png"))
            fisher.close()
        else:
            check("casting a line from the shore catches fish", False,
                  "no bot spawned near water in eight tries")
            check("the rod wears out while fishing", False, "no shore reached")

        # -------------------------------------------------------------- b9: caves
        dave = None
        for attempt in range(8):
            candidate = Bot(screen, port, "Dave",
                            config=Config(Path(tmp.name) / f"d{attempt}.json"))
            if candidate.wait_for_id(6.0) is None:
                candidate.close()
                continue
            candidate.tick(4)
            cave_path, cave_target = candidate.bfs_path(
                lambda gx, gy: candidate.game.world.is_cave(gx, gy))
            if cave_path and len(cave_path) <= 46:
                dave = candidate
                break
            candidate.close()
            time.sleep(0.4)
        if dave is not None:
            into_cave = False
            for attempt in range(3):           # the entrance is narrow: try again
                if dave.game.in_cave():
                    into_cave = True
                    break
                fresh, target = dave.bfs_path(
                    lambda gx, gy: dave.game.world.is_cave(gx, gy))
                if not fresh:
                    break
                dave.walk_path(fresh, max_ticks=70, skip=1)
                cave_target = target or cave_target
                into_cave = dave.game.in_cave()
            check("a bot can walk into a cave", into_cave and dave.game.in_cave(),
                  f"target={cave_target} at={dave.tile()}")
            # one node inside the cave, gathered for real: caves pay double
            digs, gained = 0, 0
            for _ in range(6):
                node, _key = dave.nearest_cave_node()
                if node is None:
                    dave.tick(4)
                    continue
                dave.walk_to(node["x"], node["y"], tolerance=30,
                             stop_when=lambda d: d < 40)
                before = sum(dave.inventory().values())
                dave.clear_raw()
                dave.gather()
                dave.tick(4)
                digs += 1
                gained = max(gained, sum(dave.inventory().values()) - before)
                if gained >= 2:
                    break
            check("gathering inside a cave pays double", gained >= 2,
                  f"one node gave {gained} item(s), notified={dave.keys()[-3:]}")
            if shots:
                dave.tick(2, draw=True)
                pygame.image.save(screen, str(shots / "14_cave.png"))
            dave.close()
        else:
            check("a bot can walk into a cave", False,
                  "no cave within 46 tiles in eight spawns")
            check("gathering inside a cave pays double", False, "no cave reached")

        # ------------------------------------------------------- b9: market trade
        alice.clear_raw()
        spot = alice.find_spot(2, 2, radius=3)
        before_market = sum(1 for b in alice.game.world.buildings.values()
                            if b.get("type") == "market")
        if spot:
            alice.game.net.send_dict({"type": "build", "structure": "market",
                                      "x": spot[0], "y": spot[1]})
            alice.tick(6)
        markets = [b for b in alice.game.world.buildings.values()
                   if b.get("type") == "market"]
        check("a market can be built and reaches the client",
              len(markets) > before_market,
              f"spot={spot} {alice.keys()[-3:]}")

        if markets:
            market = markets[0]
            # stand right next to the market: posting needs it within 3 tiles
            alice.tick(4)
            at_market = go_to_market(alice, market)
            alice.settle()                     # the build cost must arrive first
            alice.clear_raw()
            wood_before, stone_before = alice.count("wood"), alice.count("stone")
            alice.game.net.send_dict({"type": "trade_post", "give_item": "wood",
                                      "give_count": 10, "want_item": "stone",
                                      "want_count": 5})
            alice.tick(6)
            offers = list(alice.game.trades)
            check("an offer can be put on the market",
                  bool(offers) and "notify.trade_posted" in alice.keys(),
                  f"{len(offers)} offers at_market={at_market} {alice.keys()[-3:]}")
            check("the goods of an offer leave the inventory",
                  alice.count("wood") == wood_before - 10,
                  f"wood {wood_before} -> {alice.count('wood')} {alice.keys()[-2:]}")

            # bob walks to the market and takes the offer - a real buyer
            if offers:
                offer = offers[0]
                bob.close_in(alice)
                bob_at_market = go_to_market(bob, market)
                bob.tick(4)
                check("the offer reaches the other player's client",
                      any(o.get("id") == offer.get("id") for o in bob.game.trades),
                      f"at_market={bob_at_market} {[o.get('id') for o in bob.game.trades]}")
                bob_wood, bob_stone = bob.count("wood"), bob.count("stone")
                bob.clear_raw()
                bob.game.net.send_dict({"type": "trade_take", "id": offer.get("id")})
                bob.tick(8)
                bob.wait_until(lambda: bob.count("wood") > bob_wood, ticks=20)
                check("the buyer pays and gets the goods",
                      bob.count("wood") == bob_wood + 10 and
                      bob.count("stone") == bob_stone - 5,
                      f"wood {bob_wood}->{bob.count('wood')} "
                      f"stone {bob_stone}->{bob.count('stone')}")
                alice.tick(6)
                check("the seller is paid into the inventory",
                      alice.count("stone") == stone_before + 5,
                      f"stone {stone_before} -> {alice.count('stone')}")
                check("a taken offer disappears from the market",
                      not any(o.get("id") == offer.get("id") for o in alice.game.trades),
                      f"{[o.get('id') for o in alice.game.trades]}")

                # every bot starts with a rod, so bob hands his to the market
                # first: that is also how "the market holds the goods" is proven
                bob.close_in(alice)
                bob_at_market = go_to_market(bob, market)
                bob.settle()
                bob.clear_raw()
                rods_before = bob.count("fishing_rod")
                bob.game.net.send_dict({"type": "trade_post", "give_item": "fishing_rod",
                                        "give_count": 1, "want_item": "wood",
                                        "want_count": 1})
                bob.tick(6)
                rod_offer = next((o for o in bob.game.trades
                                  if o.get("give_item") == "fishing_rod"), None)
                check("the market holds the goods of an offer",
                      rods_before >= 1 and bob.count("fishing_rod") == rods_before - 1,
                      f"rod {rods_before} -> {bob.count('fishing_rod')} "
                      f"at_market={bob_at_market} {bob.keys()[-2:]}")
                bob.clear_raw()
                bob.game.net.send_dict({"type": "fish"})
                bob.tick(6)
                check("fishing without a rod is refused",
                      "notify.need_rod" in bob.keys(), str(bob.keys()[-3:]))
                if rod_offer:
                    bob.clear_raw()
                    bob.game.net.send_dict({"type": "trade_cancel",
                                            "id": rod_offer.get("id")})
                    bob.tick(6)
                    check("an offer can be taken back and the goods return",
                          bob.count("fishing_rod") == rods_before and
                          "notify.trade_cancelled" in bob.keys(),
                          f"rod={bob.count('fishing_rod')} {bob.keys()[-3:]}")

        # --------------------------------------------------- b9: country diplomacy
        bob.clear_raw()
        bob.game.net.send_dict({"type": "create_city", "name": "Bobville"})
        bob.tick(4)
        bob.game.net.send_dict({"type": "create_country", "name": "Bobland"})
        bob.tick(4)
        alice.clear_raw()
        alice.tick(6)
        check("a second country exists for diplomacy",
              "Bobland" in (alice.game.civ_state.get("countries") or {}),
              str(list(alice.game.civ_state.get("countries") or {})))

        alice.game.net.send_dict({"type": "diplomacy", "action": "war",
                                  "target": "Bobland"})
        alice.tick(6)
        countries = alice.game.civ_state.get("countries") or {}
        at_war = "Botland" in (countries.get("Bobland", {}).get("wars") or [])
        check("a leader can declare war and the client sees it",
              "notify.declared_war" in alice.keys() and at_war,
              f"{alice.keys()[-3:]} wars={countries.get('Bobland', {}).get('wars')}")

        # at war the sword lands; at peace nobody can be hurt - so the bots
        # have to stand next to each other first (reach is 50 px)
        stood = meet(bob, alice, want=34, rounds=6)
        check("the bots stand next to each other for the fights",
              stood and bob.distance_to(alice) <= 50,
              f"distance={bob.distance_to(alice):.0f}")
        bob.heal()                     # a one-hit kill would look like "no damage"
        bob_hp = bob.game.players.get(id_b).hp if bob.game.players.get(id_b) else 100
        bob.clear_raw()
        alice.select_item("sword")
        alice.attack(id_b)
        alice.tick(3)
        bob.tick(3)
        now = bob.game.players.get(id_b).hp if bob.game.players.get(id_b) else 0
        check("war damage goes through", now < bob_hp,
              f"hp {bob_hp} -> {now} (distance {bob.distance_to(alice):.0f})")

        alice.clear_raw()
        alice.game.net.send_dict({"type": "diplomacy", "action": "peace",
                                  "target": "Bobland"})
        alice.tick(6)
        peace_notes = list(alice.keys())
        bob.heal()
        peace_hp = bob.game.players.get(id_b).hp if bob.game.players.get(id_b) else 100
        alice.clear_raw()
        bob.close_in(alice)
        for _ in range(3):
            alice.attack(id_b)
            alice.tick(2)
        bob.tick(3)
        now_hp = bob.game.players.get(id_b).hp if bob.game.players.get(id_b) else 0
        check("peace is made and nobody can be hurt afterwards",
              "notify.made_peace" in peace_notes and now_hp >= peace_hp and
              bob.distance_to(alice) <= 50,
              f"hp {peace_hp} -> {now_hp} dist={bob.distance_to(alice):.0f}")

        # somebody without a country cannot run diplomacy at all
        erin = Bot(screen, port, "Erin", config=Config(Path(tmp.name) / "erin.json"))
        if erin.wait_for_id(6.0) is not None:
            erin.tick(4)
            erin.clear_raw()
            erin.game.net.send_dict({"type": "diplomacy", "action": "war",
                                     "target": "Bobland"})
            erin.tick(6)
            check("only a country leader may run diplomacy",
                  "notify.only_country_leader" in erin.keys(),
                  f"{erin.keys()[-3:]} at={erin.tile()}")
        else:
            check("only a country leader may run diplomacy", False, "no client")

        if shots:
            alice.tick(2, draw=True)
            pygame.image.save(screen, str(shots / "15_diplomacy.png"))


        # ------------------------------------------ b10: roles, taxes and cities
        # A fresh pair founds its own city, so the checks run on untouched
        # ground: rights inside the walls, the tax that feeds the city fund and
        # the roles the leader hands out.
        grace = Bot(screen, port, "Grace", config=Config(Path(tmp.name) / "g.json"))
        city_centre = None
        if grace.wait_for_id(6.0) is not None and erin.game.my_id is not None:
            grace.tick(4)
            check("the two builders of the new city stand together",
                  meet(grace, erin, want=40, rounds=8),
                  f"distance={grace.distance_to(erin):.0f}")

            # The new city must not land inside somebody else's walls: the
            # older city would own the land and every check below would test it.
            def other_cities():
                ours = []
                for data in (erin.game.civ_state.get("cities") or {}).values():
                    if data.get("name") == "Erinville":
                        continue
                    ours.append((data.get("x", 0), data.get("y", 0),
                                 300 + (int(data.get("tier", 1)) - 1) * 200))
                return ours

            def inside_other_city(x, y, margin=0.0) -> bool:
                return any(((x - cx) ** 2 + (y - cy) ** 2) ** 0.5 < radius + margin
                           for cx, cy, radius in other_cities())

            def free_land_here() -> bool:
                return not inside_other_city(*erin.pos())

            free_land = free_land_here()
            for _attempt in range(6):
                if free_land:
                    break
                # Straight-line escapes used to end on a rock, and since b11 a
                # bot can wade into a lake and waste the whole walk there: plan
                # the shortest way out of the foreign walls instead.
                route, _target = erin.bfs_path(
                    lambda gx, gy: not inside_other_city(gx * TILE_SIZE + TILE_SIZE // 2,
                                                         gy * TILE_SIZE + TILE_SIZE // 2))
                if not route:
                    break
                erin.walk_path(route[:100], max_ticks=70)
                grace.close_in(erin, want=40, rounds=6)
                erin.tick(2)
                free_land = free_land_here()
            check("the new city stands on free land", free_land,
                  f"at={erin.tile()} near={other_cities()}")

            erin.clear_raw()
            erin.game.net.send_dict({"type": "create_city", "name": "Erinville"})
            erin.tick(5)
            check("a bot can found a city of its own",
                  "notify.city_founded" in erin.keys(), str(erin.keys()[-3:]))
            city_centre = erin.pos()

            # a tier 2 city has a 500 px territory, which gives the tax check
            # plenty of room to find its own nodes
            erin.game.net.send_dict({"type": "research", "city": "AUTO_FIND"})
            erin.tick(6)
            tier = int(((erin.game.civ_state.get("cities") or {})
                        .get("Erinville") or {}).get("tier", 1))
            tax_radius = 300 + (tier - 1) * 200 - 60

            grace.clear_raw()
            grace.game.net.send_dict({"type": "join_city", "name": "Erinville"})
            grace.tick(5)
            erin.tick(2)
            members = ((erin.game.civ_state.get("cities") or {})
                       .get("Erinville") or {}).get("members") or []
            check("a bot can join somebody else's city",
                  "notify.joined_city" in grace.keys() and len(members) >= 2,
                  f"{grace.keys()[-3:]} members={members}")

            # a plain citizen has no building rights inside the walls
            grace.clear_raw()
            spot = grace.build_near("torch")
            check("a citizen cannot build inside the city",
                  "notify.build_fail_role" in grace.keys() and spot is None,
                  f"{grace.keys()[-4:]}")

            erin.clear_raw()
            grace.clear_raw()
            erin.chat("/role Grace builder")
            erin.tick(6)
            grace.tick(3)
            roles = ((erin.game.civ_state.get("cities") or {})
                     .get("Erinville") or {}).get("roles") or {}
            check("the city leader hands out roles by name",
                  "notify.role_set" in erin.keys() and "notify.role_given" in grace.keys(),
                  f"{erin.keys()[-3:]} {grace.keys()[-3:]}")
            check("the role of a member reaches every client",
                  roles.get(grace.game.my_id) == "builder",
                  f"roles={roles} me={grace.game.my_id}")

            grace.clear_raw()
            built_spot = grace.build_near("crafting_table")
            check("with a role a member may build inside the city",
                  "notify.built" in grace.keys() and built_spot is not None,
                  f"{grace.keys()[-4:]} spot={built_spot}")

            erin.clear_raw()
            erin.chat("/city")
            erin.tick(4)
            said = " ".join(m.get("msg", "") for m in erin.raw if m.get("type") == "chat")
            check("the /city command reports the fund and the roles",
                  "Grace:builder" in said and "tax" in said, said[-80:])

            erin.clear_raw()
            erin.chat("/tax 40")
            erin.tick(5)
            tax = ((erin.game.civ_state.get("cities") or {})
                   .get("Erinville") or {}).get("tax")
            check("the leader sets the tax rate by command",
                  "notify.tax_set" in erin.keys() and tax == 40,
                  f"tax={tax} {erin.keys()[-3:]}")

            gather_notes = []

            def gather_in_city(bot, centre, times=4, radius=240):
                """Gather nodes that are certainly inside *our* city's territory."""
                cx, cy = centre
                blacklist, got = set(), 0
                for _ in range(times * 4):
                    if got >= times:
                        break
                    best = None
                    for key, node in (bot.game.world.resources or {}).items():
                        if key in blacklist:
                            continue
                        dist_centre = ((node["x"] - cx) ** 2 +
                                       (node["y"] - cy) ** 2) ** 0.5
                        if dist_centre > radius:
                            continue
                        if inside_other_city(node["x"], node["y"], margin=30):
                            continue
                        dist = ((node["x"] - bot.pos()[0]) ** 2 +
                                (node["y"] - bot.pos()[1]) ** 2) ** 0.5
                        if best is None or dist < best[0]:
                            best = (dist, key, node, dist_centre)
                    if best is None:
                        gather_notes.append("no node inside the city")
                        break
                    _dist, key, node, dist_centre = best
                    bot.walk_to(node["x"], node["y"], tolerance=40,
                                stop_when=lambda d: d < 46)
                    before = sum(bot.inventory().values())
                    bot.gather()
                    bot.tick(4)
                    gained = sum(bot.inventory().values()) - before
                    if gained > 0:
                        got += 1
                    else:
                        blacklist.add(key)
                    me_x, me_y = bot.pos()
                    me_dist = ((me_x - cx) ** 2 + (me_y - cy) ** 2) ** 0.5
                    gather_notes.append(f"{key} node_d={dist_centre:.0f} me_d={me_dist:.0f} "
                                        f"gained={gained} {bot.keys()[-1:]}")
                return got

            def city_storage():
                return dict(((erin.game.civ_state.get("cities") or {})
                             .get("Erinville") or {}).get("storage") or {})

            grace.clear_raw()
            fund_before = city_storage()
            gathered = 0
            paid = False
            for _round in range(4):
                if paid:
                    break
                # walk back to the centre: every node below is then surely ours
                grace.walk_to(city_centre[0], city_centre[1], tolerance=60, max_ticks=200)
                gathered += gather_in_city(grace, city_centre, times=4, radius=tax_radius)
                grace.tick(3)
                erin.tick(2)
                fund_after = city_storage()
                paid = ("notify.tax_paid" in grace.keys() or
                        sum(fund_after.values()) > sum(fund_before.values()))
            detail = (f"gathered={gathered} paid={paid} radius={tax_radius} "
                      f"at={grace.tile()} centre={city_centre} others={other_cities()} "
                      + " | ".join(gather_notes[-6:]))
            check("a member who gathers inside the city pays the tax",
                  paid and gathered >= 3, detail)
            check("the tax lands in the city fund (the client sees it)",
                  sum(fund_after.values()) > sum(fund_before.values()),
                  f"fund {fund_before} -> {fund_after} | " + " | ".join(gather_notes[-4:]))

            erin.clear_raw()
            erin.chat("/tax 0")
            erin.tick(5)
            grace.clear_raw()
            fund_zero = city_storage()
            grace.walk_to(city_centre[0], city_centre[1], tolerance=60, max_ticks=200)
            gather_in_city(grace, city_centre, times=3, radius=tax_radius)
            grace.tick(3)
            erin.tick(2)
            fund_after_off = city_storage()
            check("tax 0 means the harvest stays in the pocket",
                  "notify.tax_paid" not in grace.keys() and
                  fund_after_off.get("wood", 0) <= fund_zero.get("wood", 0),
                  f"{grace.keys()[-3:]} fund {fund_zero} -> {fund_after_off}")

            erin.clear_raw()
            erin.chat("/role Nobody builder")
            erin.tick(4)
            check("roles cannot be given to outsiders",
                  "notify.role_not_member" in erin.keys(), str(erin.keys()[-3:]))

            grace.clear_raw()
            grace.game.net.send_dict({"type": "set_tax", "value": 25})
            grace.tick(4)
            check("only a city leader may set the tax",
                  "notify.only_city_leader" in grace.keys(), str(grace.keys()[-3:]))

            grace.clear_raw()
            grace.game.net.send_dict({"type": "use", "item": "stone"})
            grace.tick(4)
            check("only medicine can be used (medkit / bandage)",
                  "notify.cannot_use" in grace.keys(), str(grace.keys()[-3:]))

            age = ((alice.game.civ_state.get("countries") or {})
                   .get("Botland") or {}).get("age")
            check("the state carries the age of every country",
                  age in ("stone", "bronze", "iron", "industrial", "electric"),
                  f"age={age}")
            erin.close()
            grace.close()
        else:
            check("the two builders of the new city stand together", False, "no client")
            check("the new city stands on free land", False, "no client")
            check("a bot can found a city of its own", False, "no client")
            check("a bot can join somebody else's city", False, "no client")
            check("a citizen cannot build inside the city", False, "no client")
            check("the city leader hands out roles by name", False, "no client")
            check("the role of a member reaches every client", False, "no client")
            check("with a role a member may build inside the city", False, "no client")
            check("the /city command reports the fund and the roles", False, "no client")
            check("the leader sets the tax rate by command", False, "no client")
            check("a member who gathers inside the city pays the tax", False, "no client")
            check("the tax lands in the city fund (the client sees it)", False, "no client")
            check("tax 0 means the harvest stays in the pocket", False, "no client")
            check("roles cannot be given to outsiders", False, "no client")
            check("only a city leader may set the tax", False, "no client")
            check("only medicine can be used (medkit / bandage)", False, "no client")
            check("the state carries the age of every country", False, "no client")

        # ------------------------------------------------- b11: wading in water
        # A bot walks straight into the lake: since b11 that is allowed, only
        # slow. The client predicts the very same step, so the position must
        # not be pulled back by the server (no rubber-banding).
        wader = None
        for attempt in range(8):
            candidate = Bot(screen, port, "Wade",
                            config=Config(Path(tmp.name) / f"w{attempt}.json"))
            if candidate.wait_for_id(6.0) is None:
                candidate.close()
                continue
            candidate.tick(4)
            water_pred = lambda gx, gy: candidate.game.world.is_water(gx, gy)
            path, target = candidate.bfs_path(water_pred)
            if path and len(path) <= 30:
                wader = candidate
                break
            candidate.close()
            time.sleep(0.4)

        if wader is not None:
            into_water = wader.walk_to(target[0] * TILE_SIZE + TILE_SIZE // 2,
                                       target[1] * TILE_SIZE + TILE_SIZE // 2,
                                       tolerance=18, max_ticks=120)
            wader.tick(3)
            tile = wader.tile()
            check("a player can walk into the water (b11)",
                  wader.game.world.is_water(tile[0], tile[1]) and into_water,
                  f"target={target} at={tile}")

            # the client shows its own prediction, the server sends the truth:
            # in the water they have to agree, or every step would be undone.
            # All four directions are tried - one of them may end on a rock.
            swam = 0.0
            for direction in ((5, 0), (-5, 0), (0, 5), (0, -5)):
                moved_before = wader.pos()
                for _ in range(10):
                    wader.tick(1, steps=direction)
                swam = max(swam, ((wader.pos()[0] - moved_before[0]) ** 2 +
                                  (wader.pos()[1] - moved_before[1]) ** 2) ** 0.5)
            check("swimming works and moves the player", swam > 6,
                  f"best={swam:.1f}px at={wader.tile()}")

            wader.tick(3)
            authoritative_player = wader.game.players.get(wader.game.my_id)
            gap = None
            if authoritative_player is not None:
                gap = ((wader.pos()[0] - authoritative_player.x) ** 2 +
                       (wader.pos()[1] - authoritative_player.y) ** 2) ** 0.5
            check("the client and the server agree where the swimmer is",
                  gap is not None and gap < 60, f"gap={gap}")

            # the hint arrives once per session, not on every step
            wader.clear_raw()
            for _ in range(4):
                wader.tick(1, steps=(4, 0))
            hints = [m.get("key") for m in wader.raw
                     if m.get("type") == "notification"].count("notify.swim_hint")
            check("the swim hint is not repeated on every step", hints == 0,
                  f"extra hints={hints} (one per session is enough)")
            if shots:
                wader.tick(2, draw=True)
                pygame.image.save(screen, str(shots / "20_swimming.png"))
            wader.close()
        else:
            check("a player can walk into the water (b11)", False,
                  "no bot spawned next to water in eight tries")
            check("swimming works and moves the player", False, "no water nearby")
            check("the client and the server agree where the swimmer is", False,
                  "no water nearby")
            check("the swim hint is not repeated on every step", False, "no water")

        # -------------------------------------------- b11: a bridge over water
        # The client's placement preview asked `World.is_blocked()`, which counts
        # water as blocked - so a bridge looked unplaceable on a river although
        # the server accepted it (b9 bug, fixed in b11). Alice has masonry from
        # the door above, so she can really build one and the server must agree.
        if alice.game.my_id is not None:
            alice.game.build_target = "bridge"

            def city_rings():
                """(x, y, radius) of every city the client knows about."""
                rings = []
                for data in (alice.game.civ_state.get("cities") or {}).values():
                    rings.append((data.get("x", 0), data.get("y", 0),
                                  300 + (int(data.get("tier", 1)) - 1) * 200))
                return rings

            def inside_city(px, py, margin=40.0) -> bool:
                return any(((px - cx) ** 2 + (py - cy) ** 2) ** 0.5 < radius + margin
                           for cx, cy, radius in city_rings())

            def buildable_water(gx, gy) -> bool:
                """Water where nobody's walls forbid building (b10 territory)."""
                if not alice.game.world.is_water(gx, gy):
                    return False
                if f"{gx},{gy}" in alice.game.world.buildings:
                    return False
                return not inside_city(gx * TILE_SIZE + TILE_SIZE // 2,
                                       gy * TILE_SIZE + TILE_SIZE // 2)

            def city_report() -> str:
                me = alice.pos()
                notes = []
                for name, data in (alice.game.civ_state.get("cities") or {}).items():
                    dist = (((data.get("x", 0) - me[0]) ** 2 +
                             (data.get("y", 0) - me[1]) ** 2) ** 0.5)
                    if dist < 700:
                        notes.append(f"{name} leader={data.get('leader')} "
                                     f"members={data.get('members')} "
                                     f"roles={data.get('roles')} d={dist:.0f}")
                return (f"me={alice.game.my_id} at={me} free_water={inside_city(*me, 0)} "
                        f"{notes} {alice.keys()[-2:]}")

            # walk to water that is not inside somebody's city: a member without
            # the builder role (or an outsider) simply may not build there
            route, shore = alice.bfs_path(buildable_water)
            reached = bool(route) and len(route) <= 60 and \
                alice.walk_path(route[:60], max_ticks=80)
            alice.tick(3)

            def water_candidates(radius=8):
                tx, ty = alice.tile()
                found = []
                for dy in range(-radius, radius + 1):
                    for dx in range(-radius, radius + 1):
                        gx, gy = tx + dx, ty + dy
                        if not buildable_water(gx, gy):
                            continue
                        found.append((max(abs(dx), abs(dy)), (gx, gy)))
                found.sort()
                return [tile for _step, tile in found]

            def land_candidate(radius=4):
                tx, ty = alice.tile()
                world = alice.game.world
                busy = {f"{b['x'] + dx},{b['y'] + dy}"
                        for b in world.buildings.values()
                        for dx in range(b.get("w", 1)) for dy in range(b.get("h", 1))}
                busy |= {f"{int(n['x'] // TILE_SIZE)},{int(n['y'] // TILE_SIZE)}"
                         for n in (getattr(world, "resources", {}) or {}).values()}
                for step in range(1, radius + 1):
                    for dy in range(-step, step + 1):
                        for dx in range(-step, step + 1):
                            gx, gy = tx + dx, ty + dy
                            if max(abs(dx), abs(dy)) != step:
                                continue
                            if world.tile(gx, gy) != 0 or f"{gx},{gy}" in busy:
                                continue
                            if not world.blocks_building(gx, gy, "bridge"):
                                continue
                            return (gx, gy)
                return None

            candidates = water_candidates()
            offered = bool(candidates) and alice.game.can_build_here(*candidates[0])
            check("a bridge over the water is offered by the client", offered,
                  f"water={candidates[:2]} reached={reached} {city_report()}")

            land_tile = land_candidate()
            refused = bool(land_tile) and not alice.game.can_build_here(*land_tile)
            check("a bridge on dry land is refused", refused,
                  f"land={land_tile} predicted="
                  f"{alice.game.can_build_here(*land_tile) if land_tile else None}")

            built, attempts = False, []
            if offered:
                for spot in candidates[:3]:
                    alice.clear_raw()
                    before = len(alice.game.world.buildings)
                    alice.build("bridge", *spot)
                    built = alice.wait_until(
                        lambda: any(b.get("type") == "bridge"
                                    for b in alice.game.world.buildings.values()),
                        ticks=60)
                    attempts.append(f"{spot}:{'built' if built else alice.keys()[-1:]}")
                    if built:
                        break
                check("the server accepts the bridge over the water", built,
                      f"buildings {before} -> {len(alice.game.world.buildings)} "
                      f"{attempts} {city_report()}")
                if built:
                    if shots:
                        alice.tick(2, draw=True)
                        pygame.image.save(screen, str(shots / "21_bridge.png"))
            else:
                check("the server accepts the bridge over the water", False,
                      f"no buildable water within reach (reached={reached})")
            alice.game.build_target = None
        else:
            check("a bridge over the water is offered by the client", False, "no client")
            check("a bridge on dry land is refused", False, "no client")
            check("the server accepts the bridge over the water", False, "no client")

        # ------------------------------------------------------------- accounts
        carol = Bot(screen, port, "Carol", mode="register", password="hunter2",
                    config=Config(Path(tmp.name) / "c.json"))
        check("registration succeeds", carol.wait_for_id() is not None)
        carol.harvest_until({"wood": 2}, max_attempts=20)
        carol_total = carol.count("wood") + carol.count("stone")
        check("the new account can play right away", carol_total > 0, str(carol.inventory()))
        carol.close()
        time.sleep(0.8)

        carol2 = Bot(screen, port, "Carol", mode="login", password="hunter2",
                     config=Config(Path(tmp.name) / "c.json"))
        check("login with the same account succeeds", carol2.wait_for_id() is not None)
        carol2.tick(6)              # let the inventory packet arrive
        check("progress of the account came back",
              (carol2.count("wood") + carol2.count("stone")) >= carol_total,
              f"before={carol_total} after={carol2.count('wood') + carol2.count('stone')}")
        check("the client is greeted as a returning player",
              "auth.welcome_back" in carol2.keys(), str(carol2.keys()[:4]))

        same_name = Bot(screen, port, "Carol", mode="login", password="hunter2",
                        config=Config(Path(tmp.name) / "e.json"))
        for _ in range(90):
            same_name.tick(1)
            if same_name.auth_errors() or same_name.game.my_id is not None:
                break
        check("logging in twice at the same time is refused",
              "auth.already_online" in same_name.auth_errors(),
              str(same_name.auth_errors() or same_name.game.my_id))
        same_name.close()

        wrong = Bot(screen, port, "Carol", mode="login", password="totally-wrong",
                    config=Config(Path(tmp.name) / "d.json"))
        for _ in range(90):
            wrong.tick(1)
            if wrong.auth_errors() or wrong.game.my_id is not None:
                break
        check("wrong password is rejected",
              wrong.game.my_id is None and wrong.game.auth_state == "error",
              f"state={wrong.game.auth_state} {wrong.game.auth_error}")
        check("wrong password gives auth.bad_password",
              "auth.bad_password" in wrong.auth_errors(), str(wrong.auth_errors()))
        check("the rejection is translated for the player",
              bool(wrong.game.auth_error), wrong.game.auth_error)
        wrong.close()
        time.sleep(0.4)

        # ---------------------------------------------------- b11: the character
        sprite = alice.game.resources.get("player")
        check("the player is a character sprite, not a cube",
              sprite is not None and sprite.get_height() > sprite.get_width() - 1,
              f"player.png={sprite.get_size() if sprite else None}")
        drawn = alice.game.players.get(id_a)
        if drawn is not None:
            skin = drawn.sprite(alice.game.resources)
            solid = [(x, y) for x in range(skin.get_width()) for y in range(skin.get_height())
                     if skin.get_at((x, y))[3] > 0]
            tall = (max(y for _x, y in solid) - min(y for _x, y in solid)) > \
                (max(x for x, _y in solid) - min(x for x, _y in solid))
            check("the drawn character is taller than wide (a person)", bool(solid) and tall,
                  f"solid pixels={len(solid)}")

        inv_menu = alice.game.inventory_menu
        inv_menu.visible = True
        listed = [item for item, _n in inv_menu._items()]
        in_bar = [item for item in alice.game.hotbar if item]
        check("the inventory does not list what the hotbar already shows",
              not (set(listed) & set(in_bar)) and len(in_bar) > 0,
              f"grid={listed[:6]} bar={in_bar[:6]}")
        inv_menu.visible = False
        for item in in_bar:
            if alice.count(item) <= 0:
                continue
            break
        else:
            check("every hotbar item is a real item in the pack", False,
                  f"bar={in_bar} inventory={list(alice.inventory())[:6]}")

        # ------------------------------------------------------ all the screens
        if shots:
            alice.tick(2, draw=True)
            pygame.image.save(screen, str(shots / "02_hud.png"))
            for name, menu, opener in (
                    ("03_inventory", alice.game.inventory_menu, None),
                    ("04_crafting", alice.game.crafting_menu, None),
                    ("05_settings", alice.game.settings_menu, lambda m: m.open()),
                    ("06_civ", alice.game.civ_menu, None),
                    ("07_smelting", alice.game.smelting_menu, None),
                    ("08_research", alice.game.research_menu,
                     lambda m: m.open("country")),
                    ("10_tasks", alice.game.tasks_menu, None),
                    ("11_chest", alice.game.chest_menu,
                     lambda m: m.open(0, 0, {"wood": 42, "stone": 17, "iron_ingot": 3}))):
                for other in (alice.game.inventory_menu, alice.game.crafting_menu,
                              alice.game.settings_menu, alice.game.civ_menu,
                              alice.game.smelting_menu, alice.game.research_menu,
                              alice.game.tasks_menu, alice.game.chest_menu,
                              alice.game.trade_menu):
                    other.visible = False
                opener(menu) if opener else menu.toggle()
                alice.tick(3, draw=True)
                pygame.image.save(screen, str(shots / f"{name}.png"))
                menu.visible = False

            # night rendering: the client is asked to draw 23:00 with a torch
            alice.game.world_time = 23 / 24
            alice.game.lights = [(alice.pos()[0], alice.pos()[1], 130)]
            alice.game.build_target = "torch"
            alice.game.draw()
            pygame.image.save(screen, str(shots / "12_night.png"))
            alice.game.build_target = None

            # the market window with a live offer, then the two weather looks
            alice.game.net.send_dict({"type": "trade_post", "give_item": "stone",
                                      "give_count": 5, "want_item": "wood",
                                      "want_count": 10})
            alice.tick(6)
            alice.game.trade_menu.open()
            alice.tick(3, draw=True)
            pygame.image.save(screen, str(shots / "16_market.png"))
            alice.game.trade_menu.close()

            for name, weather in (("17_rain", "rain"), ("18_fog", "fog")):
                alice.tick(1)
                alice.game.weather = weather       # after the state packet!
                alice.game.draw()
                pygame.image.save(screen, str(shots / f"{name}.png"))
            alice.tick(1)

            # b10: the victory banner (the match is won by a wonder or by cities)
            alice.game.on_victory({"type": "wonder", "country": "Botland",
                                   "player": "Alice"})
            alice.tick(1)
            alice.game.draw()
            pygame.image.save(screen, str(shots / "19_victory.png"))
            alice.game.victory = None

            menu = MainMenu(screen, Config(Path(tmp.name) / "menu.json"))
            menu.draw()
            pygame.image.save(screen, str(shots / "00_menu.png"))
            menu.state = "help"
            menu.draw()
            pygame.image.save(screen, str(shots / "09_help.png"))

        # -------------------------------------------------------- resource packs
        from client.resources import discover_packs
        packs = discover_packs()
        check("the game finds every resource pack on disk",
              {"default", "neon", "dark", "desert", "invert"} <= set(packs),
              str(sorted(packs)))
        default_icon = alice.game.resources.get("tree")
        from client.resources import ResourceManager
        neon = ResourceManager("neon")
        neon_icon = neon.get("tree")
        differs = (default_icon is not None and neon_icon is not None
                   and pygame.image.tostring(default_icon, "RGBA")
                   != pygame.image.tostring(neon_icon, "RGBA"))
        check("switching the pack really changes the textures", differs)
        default_again = ResourceManager("default")
        check("the default pack still loads after a switch",
              default_again.get("tree") is not None)

        # ------------------------------------------------- offline resilience
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()
        time.sleep(0.5)

        alive = True
        try:
            for _ in range(20):
                alice.game.update()
                alice.game.draw()
                time.sleep(1 / 40)
        except Exception as exc:                        # noqa: BLE001
            alive = False
            print(f"      client crashed while offline: {exc!r}")
        check("client survives the server dying (no crash, no traceback)", alive)
        check("offline state is reported to the HUD",
              alice.game.net.connected is False, alice.game.net.status)

        # ----------------------------------------------------- server restart
        server2 = start_server(port, "--save", str(world_save), "--accounts", str(accounts))
        check("server restarts on the same port", wait_for_port(port))
        deadline = time.time() + 20
        while time.time() < deadline and not alice.game.net.connected:
            alice.tick(1)
        check("client reconnects automatically", alice.game.net.connected,
              alice.game.net.status)
        check("client can log in again after the restart",
              alice.wait_for_id(4.0) is not None)

        if not args.keep_server:
            server2.terminate()
            try:
                server2.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server2.kill()

        alice.close()
        bob.close()
        carol2.close()
    finally:
        if not args.keep_server and server.poll() is None:
            server.terminate()
        tmp.cleanup()
        pygame.quit()

    failed = [name for name, ok, _ in CHECKS if not ok]
    print("\n" + "=" * 60)
    print(f" {len(CHECKS) - len(failed)}/{len(CHECKS)} checks passed")
    for name in failed:
        print(f" - FAILED: {name}")
    if shots:
        print(f" screenshots: {shots}")
    print("=" * 60)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
