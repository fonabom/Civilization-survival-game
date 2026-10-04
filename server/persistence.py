"""World persistence: save/load the whole game state to a single JSON file.

What is saved:
  * terrain (seed + the authoritative tile string),
  * every resource node and building,
  * cities, countries and researched technologies,
  * per-player progress (inventory, hp, position) keyed by player name, so
    somebody who rejoins with the same name gets their stuff back.

The server autosaves every `SAVE_INTERVAL` seconds, on shutdown, and on the
`/save` chat command.
"""

import json
import os
import tempfile
import time
from pathlib import Path

SAVE_VERSION = 2
DEFAULT_SAVE_PATH = "saves/world.json"


def _atomic_write(path: Path, text: str):
    """Write via a temp file + replace so a crash cannot corrupt the save."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as tmp:
            tmp.write(text)
        os.replace(tmp_name, path)
    except OSError:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


class WorldStore:
    def __init__(self, path):
        self.path = Path(path) if path else None

    # ------------------------------------------------------------------- save
    def save(self, world) -> bool:
        if self.path is None:
            return False
        with world.lock:
            payload = {
                "save_version": SAVE_VERSION,
                "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "seed": world.seed,
                "world_size": [world.width, world.height],
                "terrain": world.terrain_string(),
                "resources": {key: dict(value) for key, value in world.resources.items()},
                "buildings": {key: dict(value) for key, value in world.buildings.items()},
                "animals": {aid: dict(value) for aid, value in world.animals.items()},
                "civs": world.civs.to_save(),
                "players": {
                    player.get("name", f"Player {pid}"): {
                        "x": player["x"], "y": player["y"],
                        "hp": player.get("hp", 100),
                        "inventory": dict(player.get("inventory", {})),
                    }
                    for pid, player in world.players.items()
                },
            }
        try:
            _atomic_write(self.path, json.dumps(payload, indent=1))
            return True
        except (OSError, TypeError, ValueError) as exc:
            print(f"[save] could not write {self.path}: {exc}")
            return False

    # ------------------------------------------------------------------- load
    def load(self, world) -> bool:
        """Apply a save file to `world`. Returns False when there is nothing to load."""
        if self.path is None or not self.path.exists():
            return False
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            print(f"[save] {self.path} is unreadable ({exc}); starting a fresh world")
            return False

        if payload.get("save_version", 0) > SAVE_VERSION:
            print("[save] the file was written by a newer version; ignoring it")
            return False

        with world.lock:
            world.load_terrain(payload.get("terrain"), payload.get("world_size"))
            world.resources = {key: dict(value)
                               for key, value in payload.get("resources", {}).items()}
            world.buildings = {key: dict(value)
                               for key, value in payload.get("buildings", {}).items()}
            world.rebuild_occupancy()
            world.civs.load_save(payload.get("civs", {}))
            world.animals = {aid: dict(value)
                             for aid, value in payload.get("animals", {}).items()}
            if world.animals:
                world.next_animal = max((int(aid) for aid in world.animals
                                         if str(aid).isdigit()), default=-1) + 1
            else:
                world.spawn_animals(initial=True)
            world.saved_players = payload.get("players", {})
            world.touch("resources", "buildings", "civs", "animals")
            player_count = len(world.players)
            print(f"[save] loaded {self.path.name}: "
                  f"{len(world.resources)} resources, {len(world.buildings)} buildings, "
                  f"{len(world.civs.cities)} cities, {len(world.animals)} animals, "
                  f"{len(world.saved_players)} known players"
                  + (f" ({player_count} online)" if player_count else ""))
        return True

    def delete(self):
        if self.path is not None and self.path.exists():
            try:
                self.path.unlink()
            except OSError:
                pass
