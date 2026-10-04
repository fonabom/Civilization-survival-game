"""Waypoints: your own marks on the map (b13).

A waypoint is a named point that only you see: it shows up on the minimap and
as a small arrow with the distance in the corner of the screen, so finding your
camp again is a matter of one key press.

They are kept per server (host:port) in `waypoints.json` inside the writable
data folder, so two different servers do not share marks.
"""

import json
from pathlib import Path

from shared.paths import data_root

MAX_WAYPOINTS = 20
FILE_NAME = "waypoints.json"


def store_path() -> Path:
    return Path(data_root()) / FILE_NAME


def _key_for(host: str, port) -> str:
    return f"{host}:{port}"


class Waypoints:
    def __init__(self, host: str = "127.0.0.1", port=5555, game=None):
        self.game = game
        self.key = _key_for(host, port)
        self.items = []          # [{"name": str, "x": float, "y": float, "color": [r, g, b]}]
        self.load()

    # ------------------------------------------------------------------ storage
    def _read_file(self) -> dict:
        path = store_path()
        if not path.is_file():
            return {}
        try:
            with path.open(encoding="utf-8") as handle:
                data = json.load(handle)
        except (ValueError, OSError):
            return {}
        return data if isinstance(data, dict) else {}

    def _write_file(self, data: dict):
        path = store_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=1)
        except OSError:
            pass

    def load(self):
        data = self._read_file()
        stored = data.get(self.key) or []
        self.items = [item for item in stored
                      if isinstance(item, dict) and "x" in item and "y" in item]

    def save(self):
        data = self._read_file()
        data[self.key] = self.items[:MAX_WAYPOINTS]
        self._write_file(data)

    # ----------------------------------------------------------------- actions
    def add(self, x: float, y: float, name: str = "", colour=(255, 210, 90)) -> dict:
        if len(self.items) >= MAX_WAYPOINTS:
            self.items.pop(0)
        waypoint = {"name": name or "", "x": round(float(x), 1), "y": round(float(y), 1),
                    "color": list(colour)}
        self.items.append(waypoint)
        self.save()
        return waypoint

    def remove_nearest(self, x: float, y: float, radius: float = 400.0) -> dict:
        """Delete the closest waypoint, but only if it is really close."""
        near = [(self._distance(item, x, y), index, item)
                for index, item in enumerate(self.items)]
        if not near:
            return {}
        near.sort(key=lambda entry: entry[0])
        distance, index, item = near[0]
        if distance > radius:
            return {}
        self.items.pop(index)
        self.save()
        return item

    def clear(self):
        self.items = []
        self.save()

    def rename(self, index: int, name: str) -> bool:
        if 0 <= index < len(self.items):
            self.items[index]["name"] = name.strip()
            self.save()
            return True
        return False

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _distance(item, x, y) -> float:
        return ((item["x"] - x) ** 2 + (item["y"] - y) ** 2) ** 0.5

    def nearest(self, x: float, y: float):
        """(waypoint, distance) of the closest mark, or (None, 0)."""
        if not self.items:
            return None, 0.0
        item = min(self.items, key=lambda entry: self._distance(entry, x, y))
        return item, self._distance(item, x, y)

    def sorted_by_distance(self, x: float, y: float):
        return [(item, self._distance(item, x, y))
                for item in sorted(self.items, key=lambda entry: self._distance(entry, x, y))]
