"""F1 help: what the keys are and what to do in the first minutes (b13).

Four pages, switched with the buttons at the top (or with the arrow keys and
the mouse wheel):

* «Первые шаги» - the onboarding chain with the player's own progress;
* «Управление» - every key binding as it is set right now (rebinding is in the
  settings screen, but here it is visible without opening a menu);
* «Мир» - biomes, seasons, hunger, weather;
* «Город» - cities, roles, taxes, the market and the war.

The text comes from the locale files, so translated pages stay in sync.
"""

import pygame

from client.i18n import t
from client.settings import SCREEN_HEIGHT, SCREEN_WIDTH
from client.ui import widgets as w

PANEL = pygame.Rect(0, 0, 900, 560)

PAGES = (
    ("quests", "help.tab_quests"),
    ("keys", "help.tab_keys"),
    ("world", "help.tab_world"),
    ("civ", "help.tab_civ"),
)

WORLD_TEXT = (
    "help.world_biomes.title",
    "help.world_biomes.text",
    "help.world_seasons.title",
    "help.world_seasons.text",
    "help.world_survival.title",
    "help.world_survival.text",
    "help.world_water.title",
    "help.world_water.text",
)

CIV_TEXT = (
    "help.civ_city.title",
    "help.civ_city.text",
    "help.civ_roles.title",
    "help.civ_roles.text",
    "help.civ_taxes.title",
    "help.civ_taxes.text",
    "help.civ_war.title",
    "help.civ_war.text",
)


class HelpMenu:
    def __init__(self, game):
        self.game = game
        self.visible = False
        self.panel = PANEL.copy()
        self.panel.center = (SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2)
        self.tab = "quests"
        self.scroll = 0
        self._layout()

    # ------------------------------------------------------------------ layout
    def _layout(self):
        self.panel.center = (SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2)
        self.tabs = {}
        width = (self.panel.width - 40) // len(PAGES)
        for index, (name, _label) in enumerate(PAGES):
            rect = pygame.Rect(self.panel.x + 20 + index * width, self.panel.y + 58,
                               width - 8, 38)
            self.tabs[name] = rect
        self.close_button = pygame.Rect(self.panel.right - 130, self.panel.bottom - 54,
                                        110, 38)
        self.up_button = pygame.Rect(self.panel.right - 44, self.panel.y + 110, 26, 30)
        self.down_button = pygame.Rect(self.panel.right - 44, self.panel.bottom - 100,
                                       26, 30)

    def toggle(self):
        self.visible = not self.visible
        if self.visible:
            self.scroll = 0

    def open(self, tab=""):
        self.visible = True
        if tab:
            self.tab = tab
        self.scroll = 0

    def close(self):
        self.visible = False

    # ------------------------------------------------------------------- input
    def handle_event(self, event) -> bool:
        if not self.visible:
            return False
        if event.type == pygame.MOUSEBUTTONDOWN:
            if self.close_button.collidepoint(event.pos):
                self.close()
                return True
            if self.up_button.collidepoint(event.pos):
                self.scroll = max(0, self.scroll - 40)
                return True
            if self.down_button.collidepoint(event.pos):
                self.scroll += 40
                return True
            for name, rect in self.tabs.items():
                if rect.collidepoint(event.pos):
                    self.tab = name
                    self.scroll = 0
                    return True
            return self.panel.collidepoint(event.pos)
        if event.type == pygame.MOUSEWHEEL:
            self.scroll = max(0, self.scroll - event.y * 40)
            return True
        if event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_ESCAPE, pygame.K_F1):
                self.close()
                return True
            order = [name for name, _label in PAGES]
            if event.key in (pygame.K_RIGHT, pygame.K_TAB):
                self.tab = order[(order.index(self.tab) + 1) % len(order)]
                self.scroll = 0
                return True
            if event.key == pygame.K_LEFT:
                self.tab = order[(order.index(self.tab) - 1) % len(order)]
                self.scroll = 0
                return True
            if event.key == pygame.K_DOWN:
                self.scroll += 30
                return True
            if event.key == pygame.K_UP:
                self.scroll = max(0, self.scroll - 30)
                return True
        return False

    # -------------------------------------------------------------------- draw
    def _lines(self):
        """[(text, size, colour)] of the current page."""
        lines = []
        if self.tab == "keys":
            keys = getattr(self.game, "keys", None)
            pairs = []
            if keys is not None:
                for action, label_key, key_label in keys.rows():
                    pairs.append((t(label_key), key_label))
            half = (len(pairs) + 1) // 2
            for index in range(half):
                left = f"{pairs[index][0]}: {pairs[index][1]}"
                right = ""
                if index + half < len(pairs):
                    right = f"{pairs[index + half][0]}: {pairs[index + half][1]}"
                lines.append((f"{left:<28}{right}", 18, w.TEXT))
            lines.append(("", 8, w.TEXT))
            lines.append((t("help.hotbar_keys"), 18, w.TEXT_DIM))
            lines.append((t("help.rebind_hint"), 16, w.TEXT_DIM))
        elif self.tab == "quests":
            onboarding = getattr(self.game, "onboarding", None)
            rows = onboarding.order() if onboarding is not None else []
            done, total = onboarding.progress() if onboarding is not None else (0, 0)
            lines.append((t("help.quests_progress", done=done, total=total), 20, w.ACCENT))
            lines.append(("", 8, w.TEXT))
            for index, (code, title_key, hint_key, state) in enumerate(rows, start=1):
                mark = "[x]" if state == "done" else ("[>]" if state == "current" else "[ ]")
                colour = (w.GOOD if state == "done" else
                          (w.ACCENT if state == "current" else w.TEXT_DIM))
                lines.append((f"{mark} {index}. {t(title_key)}", 19, colour))
                if state != "later":
                    lines.append((f"      {t(hint_key)}", 16, w.TEXT_DIM))
            lines.append(("", 8, w.TEXT))
            lines.append((t("help.quests_hint"), 16, w.TEXT_DIM))
        else:
            source = WORLD_TEXT if self.tab == "world" else CIV_TEXT
            for index, key in enumerate(source):
                if key.endswith(".title"):
                    lines.append((t(key), 20, w.ACCENT))
                else:
                    for paragraph in t(key).split("\\n"):
                        lines.append((paragraph, 17, w.TEXT))
                lines.append(("", 6, w.TEXT))
        return lines

    def draw(self, screen):
        if not self.visible:
            return
        overlay = pygame.Surface(screen.get_size(), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 130))
        screen.blit(overlay, (0, 0))

        w.panel(screen, self.panel, t("help.title"), t("help.subtitle"))
        mouse = pygame.mouse.get_pos()
        for name, label_key in PAGES:
            rect = self.tabs[name]
            active = name == self.tab
            w.button(screen, rect, t(label_key),
                     base_color=(70, 110, 175) if active else (50, 56, 74),
                     hover_color=(90, 140, 210) if active else (66, 74, 98),
                     mouse_pos=mouse, text_size=17)

        area = pygame.Rect(self.panel.x + 28, self.panel.y + 110,
                           self.panel.width - 84, self.panel.height - 180)
        previous_clip = screen.get_clip()
        screen.set_clip(area)
        y = area.y - self.scroll
        content_height = 0
        for value, size, colour in self._lines():
            content_height += size + 12
            if value and y + size > area.y - 40 and y < area.bottom:
                w.text(screen, value, (area.x, y), size=size, color=colour)
            y += size + 12
        screen.set_clip(previous_clip)
        if content_height > area.height:
            w.scrollbar(screen, pygame.Rect(area.right + 8, area.y, 8, area.height),
                        self.scroll, content_height, area.height)
            w.button(screen, self.up_button, "^", mouse_pos=mouse, text_size=16)
            w.button(screen, self.down_button, "v", mouse_pos=mouse, text_size=16)
        w.button(screen, self.close_button, t("ui.close"), mouse_pos=mouse)
