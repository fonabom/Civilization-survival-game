"""The first minutes of the game: a small chain of quests (b13).

The old tutorial was a set of one-off hints; this is a proper (but friendly)
chain: every step has a goal, a short text and a completion check that looks at
the real game state. Progress is kept in `config.json` under `onboarding`, so a
returning player continues where he stopped, and it can be switched off in the
settings (`tutorial`).

Nothing here talks to the server: the steps only read what the client already
knows (inventory, buildings nearby, hunger, day, season, city).
"""

ONBOARDING_KEY = "onboarding"
FINISHED = "done"

# code -> (locale key of the title, locale key of the hint)
STEPS = (
    ("look", ("quest.look.title", "quest.look.hint")),
    ("wood", ("quest.wood.title", "quest.wood.hint")),
    ("craft", ("quest.craft.title", "quest.craft.hint")),
    ("stone", ("quest.stone.title", "quest.stone.hint")),
    ("table", ("quest.table.title", "quest.table.hint")),
    ("fire", ("quest.fire.title", "quest.fire.hint")),
    ("eat", ("quest.eat.title", "quest.eat.hint")),
    ("torch", ("quest.torch.title", "quest.torch.hint")),
    ("city", ("quest.city.title", "quest.city.hint")),
    ("winter", ("quest.winter.title", "quest.winter.hint")),
)

STEP_INDEX = {code: index for index, (code, _text) in enumerate(STEPS)}
TITLES = {code: text[0] for code, text in STEPS}
HINTS = {code: text[1] for code, text in STEPS}


class Onboarding:
    """Keeps track of what the player has already done in his first session."""

    def __init__(self, game):
        self.game = game
        self.done = set()
        self.started_tile = None
        self.travelled = 0.0
        self.panel_open = False
        self.finished_notified = False
        self.load()

    # ------------------------------------------------------------------ storage
    def load(self):
        data = {}
        if self.game is not None and self.game.config is not None:
            data = self.game.config.get(ONBOARDING_KEY, {}) or {}
        steps = data.get("steps") if isinstance(data, dict) else None
        self.done = set(steps or [])
        self.finished_notified = bool(data.get("notified")) if isinstance(data, dict) else False

    def save(self):
        if self.game is None or self.game.config is None:
            return
        if FINISHED in self.done:
            self.done.discard(FINISHED)
        self.game.config.set(ONBOARDING_KEY, {
            "steps": sorted(self.done, key=lambda code: STEP_INDEX.get(code, 99)),
            "notified": self.finished_notified,
        })
        self.game.config.save()

    def reset(self):
        self.done = set()
        self.travelled = 0.0
        self.started_tile = None
        self.finished_notified = False
        self.save()

    # -------------------------------------------------------------------- state
    @property
    def enabled(self) -> bool:
        return bool(self.game is not None and
                    self.game.config.get("tutorial", True)) and not self.is_finished()

    def is_finished(self) -> bool:
        return all(code in self.done for code, _text in STEPS)

    def completed(self, code) -> bool:
        return code in self.done

    def current(self):
        """The first step that is not done yet (or None when everything is done)."""
        for code, _text in STEPS:
            if code not in self.done:
                return code
        return None

    def progress(self):
        """(done, total) - for the panel and for the settings screen."""
        return (sum(1 for code, _text in STEPS if code in self.done), len(STEPS))

    def order(self):
        """The steps in play order with their state, for the panel and F1 help."""
        rows = []
        for code, text in STEPS:
            if code in self.done:
                state = "done"
            elif code == self.current():
                state = "current"
            else:
                state = "later"
            rows.append((code, text[0], text[1], state))
        return rows

    def mark(self, code, silent=False):
        if code in self.done:
            return
        self.done.add(code)
        self.save()
        if not silent and self.game is not None:
            from client.i18n import t
            from client.ui import widgets as w
            self.game.notify(t(TITLES.get(code, code)), w.GOOD)

    # ------------------------------------------------------------- ticking
    def tick(self):
        """Every frame: look at the world and finish steps that are really done."""
        if not self.game.config.get("tutorial", True):
            return
        inventory = self.game.inventory or {}
        me = self.game.me
        if me is None:
            return

        # 1. оглядеться: walk a little
        if self.started_tile is None:
            self.started_tile = (me.x, me.y)
        else:
            self.travelled += (((me.x - self.started_tile[0]) ** 2 +
                                (me.y - self.started_tile[1]) ** 2) ** 0.5)
            self.started_tile = (me.x, me.y)
            if self.travelled > 5 * 32:
                self.mark("look")

        # 2. дерево
        if inventory.get("wood", 0) >= 10 or inventory.get("stick", 0) >= 5:
            self.mark("wood")
        # 3. первый инструмент
        if any(inventory.get(item, 0) > 0 for item in ("axe", "pickaxe")):
            self.mark("craft")
        # 4. камень
        if inventory.get("stone", 0) >= 10:
            self.mark("stone")
        # 5. верстак
        if any(b.get("type") == "crafting_table"
               for b in self.game.world.buildings.values()):
            self.mark("table")
        # 6. костёр
        if any(b.get("type") == "campfire"
               for b in self.game.world.buildings.values()):
            self.mark("fire")
        # 7. поесть
        if me.hunger is not None and me.hunger >= 95 and inventory:
            self.mark("eat")
        # 8. свет: факел или костёр рядом (это постройки, а не предметы)
        if inventory.get("torch", 0) > 0 or \
                any(b.get("type") in ("torch", "lamp")
                    for b in self.game.world.buildings.values()):
            self.mark("torch")
        # 9. своя деревня
        cities = (self.game.civ_state or {}).get("cities") or {}
        if any(data.get("leader") == self.game.my_id for data in cities.values()):
            self.mark("city")
        # 10. пережить зиму
        if self.game.season == "winter" or self.game.day > 3:
            self.mark("winter")

        if self.is_finished() and not self.finished_notified:
            self.finished_notified = True
            self.save()
            from client.i18n import t
            from client.ui import widgets as w
            self.game.notify(t("quest.all_done"), w.GOOD)

    # ------------------------------------------------------------------- panel
    def toggle_panel(self):
        self.panel_open = not self.panel_open
