"""Key bindings that the player may change (b13).

Every action has a name, a default key and a locale key for the settings
screen. `KeyMap` is the only place that knows how a name such as `"w"` or
`"f1"` becomes a pygame key constant, so the rest of the client just asks
`keys.matches(event, "inventory")` or `keys.pressed("up")`.

Bindings live in `config.json` as `{"keys": {"up": "w", ...}}`. An unknown or
clashing key never breaks the game: `KeyMap.key()` falls back to the default.
"""

from collections import OrderedDict

import pygame

# action -> (default key name, locale key for its label)
ACTIONS = OrderedDict((
    ("up", ("w", "keys.up")),
    ("down", ("s", "keys.down")),
    ("left", ("a", "keys.left")),
    ("right", ("d", "keys.right")),
    ("inventory", ("i", "keys.inventory")),
    ("craft", ("c", "keys.craft")),
    ("build", ("b", "keys.build")),
    ("civ", ("v", "keys.civ")),
    ("tasks", ("k", "keys.tasks")),
    ("trade", ("y", "keys.trade")),
    ("minimap", ("m", "keys.minimap")),
    ("interact", ("f", "keys.interact")),
    ("use", ("e", "keys.use")),
    ("eat", ("q", "keys.eat")),
    ("medkit", ("h", "keys.medkit")),
    ("tame", ("t", "keys.tame")),
    ("repair", ("r", "keys.repair")),
    ("armor", ("g", "keys.armor")),
    ("waypoint", ("p", "keys.waypoint")),
    ("sort", ("o", "keys.sort")),
    ("help", ("f1", "keys.help")),
    ("chat", ("return", "keys.chat")),
    ("pause", ("escape", "keys.pause")),
))

DEFAULT_KEYS = {action: default for action, (default, _label) in ACTIONS.items()}

# Human-readable names for the settings screen and for the key names a player
# may type in the config file.
_NAMES = {
    "escape": pygame.K_ESCAPE, "return": pygame.K_RETURN, "space": pygame.K_SPACE,
    "tab": pygame.K_TAB, "backspace": pygame.K_BACKSPACE, "shift": pygame.K_LSHIFT,
    "f1": pygame.K_F1, "f2": pygame.K_F2, "f3": pygame.K_F3, "f4": pygame.K_F4,
    "f5": pygame.K_F5, "f6": pygame.K_F6, "f7": pygame.K_F7, "f8": pygame.K_F8,
    "f9": pygame.K_F9, "f10": pygame.K_F10, "f11": pygame.K_F11, "f12": pygame.K_F12,
}
for _letter in "abcdefghijklmnopqrstuvwxyz":
    _NAMES[_letter] = getattr(pygame, f"K_{_letter}")
for _digit in "0123456789":
    _NAMES[_digit] = getattr(pygame, f"K_{_digit}")
_NAMES["minus"] = pygame.K_MINUS
_NAMES["equals"] = pygame.K_EQUALS
_NAMES["comma"] = pygame.K_COMMA
_NAMES["period"] = pygame.K_PERIOD
_NAMES["slash"] = pygame.K_SLASH
_NAMES["semicolon"] = pygame.K_SEMICOLON
_NAMES["quote"] = pygame.K_QUOTE
_NAMES["left"] = pygame.K_LEFT
_NAMES["right"] = pygame.K_RIGHT
_NAMES["up"] = pygame.K_UP
_NAMES["down"] = pygame.K_DOWN

# A readable label for every key name (what a player sees in the settings).
PRETTY = {name: name.upper() if len(name) == 1 else name.capitalize()
          for name in _NAMES}
PRETTY.update({"escape": "Esc", "return": "Enter", "space": "Space", "tab": "Tab"})
for _index in range(1, 13):
    PRETTY[f"f{_index}"] = f"F{_index}"

# Everything a player is allowed to bind. Letter and digit keys first - most
# comfortable to press.
BINDABLE = [name for name in _NAMES if name not in ("shift", "backspace")]


def name_of(key_code: int) -> str:
    """Pygame key constant -> the short name used in the config."""
    for name, code in _NAMES.items():
        if code == key_code:
            return name
    return ""


class KeyMap:
    """Player key bindings on top of the defaults."""

    def __init__(self, config=None):
        self.config = config
        self.bindings = dict(DEFAULT_KEYS)
        self.load()

    def load(self):
        stored = {}
        if self.config is not None:
            stored = self.config.get("keys", {}) or {}
        self.bindings = dict(DEFAULT_KEYS)
        for action, name in stored.items():
            if action in DEFAULT_KEYS and name in _NAMES:
                self.bindings[action] = name

    def save(self):
        if self.config is not None:
            self.config.set("keys", dict(self.bindings))
            self.config.save()

    # ------------------------------------------------------------------ lookup
    def name(self, action: str) -> str:
        return self.bindings.get(action, DEFAULT_KEYS.get(action, ""))

    def label(self, action: str) -> str:
        """How the key is written on screen."""
        return PRETTY.get(self.name(action), self.name(action).upper())

    def key(self, action: str) -> int:
        """The pygame constant of an action (0 when nothing is bound)."""
        return _NAMES.get(self.name(action), 0)

    def matches(self, event, action: str) -> bool:
        code = self.key(action)
        return bool(code) and getattr(event, "key", None) == code

    def pressed(self, action: str) -> bool:
        code = self.key(action)
        if not code:
            return False
        try:
            return bool(pygame.key.get_pressed()[code])
        except (IndexError, TypeError):
            return False

    # ----------------------------------------------------------------- editing
    def conflict(self, action: str, key_name: str) -> str:
        """Which other action already uses this key ("" when free)."""
        for other, name in self.bindings.items():
            if other != action and name == key_name:
                return other
        return ""

    def bind(self, action: str, key_name: str) -> bool:
        """Rebind one action. False when the key is unknown or already taken."""
        if action not in DEFAULT_KEYS or key_name not in _NAMES:
            return False
        if self.conflict(action, key_name):
            return False
        self.bindings[action] = key_name
        self.save()
        return True

    def bind_keycode(self, action: str, key_code: int) -> str:
        """Rebind from a pressed key. Returns "" on success, else the reason."""
        key_name = name_of(key_code)
        if not key_name:
            return "unknown"
        if key_name not in BINDABLE:
            return "forbidden"
        taken = self.conflict(action, key_name)
        if taken:
            return taken
        self.bindings[action] = key_name
        self.save()
        return ""

    def reset(self):
        self.bindings = dict(DEFAULT_KEYS)
        self.save()

    def swap(self, first: str, second: str):
        """Swap two actions - handy when the wanted key is already taken."""
        if first in self.bindings and second in self.bindings:
            self.bindings[first], self.bindings[second] = (self.bindings[second],
                                                           self.bindings[first])
            self.save()

    def rows(self):
        """(action, label_key, key_label) for the settings screens."""
        return [(action, label_key, self.label(action))
                for action, (_default, label_key) in ACTIONS.items()]
