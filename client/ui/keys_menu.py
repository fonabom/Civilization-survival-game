"""Rebinding keys (b13).

Opened from the settings screen («Управление»). Click a row, press the key you
want - done. A key that is already taken is not stolen silently: the message
says which action uses it, and the row offers to swap the two actions instead.
"""

import pygame

from client.i18n import t
from client.settings import SCREEN_HEIGHT, SCREEN_WIDTH
from client.ui import widgets as w

PANEL = pygame.Rect(0, 0, 760, 560)
ROW_HEIGHT = 34


class KeysMenu:
    def __init__(self, game=None, config=None, on_change=None):
        self.game = game
        self.config = config
        self.on_change = on_change
        self.visible = False
        self.panel = PANEL.copy()
        self.scroll = 0
        self.waiting_for = ""            # action that waits for a key press
        self.message = ""
        self.message_timer = 0
        self.swap_offer = ("", "")       # (action, other action)
        self._layout()

    # ------------------------------------------------------------------ layout
    def _layout(self):
        self.panel.center = (SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2)
        self.area = pygame.Rect(self.panel.x + 24, self.panel.y + 84,
                                self.panel.width - 64, self.panel.height - 190)
        self.back_button = pygame.Rect(self.panel.right - 160, self.panel.bottom - 58,
                                       130, 40)
        self.reset_button = pygame.Rect(self.panel.x + 24, self.panel.bottom - 58, 220, 40)
        self.swap_button = pygame.Rect(self.panel.centerx - 90, self.panel.bottom - 58,
                                       180, 40)
        self.rows = []
        y = self.area.y - self.scroll
        for action, label_key, key_label in self._rows():
            self.rows.append((action, label_key, key_label,
                              pygame.Rect(self.area.x, y, self.area.width, ROW_HEIGHT)))
            y += ROW_HEIGHT + 4

    def _rows(self):
        keys = getattr(self.game, "keys", None)
        if keys is None:
            from client.keys import KeyMap
            keys = KeyMap(self.config)
        return keys.rows()

    def screen_size(self):
        return (SCREEN_WIDTH, SCREEN_HEIGHT)

    # ------------------------------------------------------------------- input
    def open(self):
        self.visible = True
        self.waiting_for = ""
        self.scroll = 0
        self._layout()

    def close(self):
        self.visible = False
        self.waiting_for = ""

    def _keys(self):
        keys = getattr(self.game, "keys", None)
        if keys is not None:
            return keys
        from client.keys import KeyMap
        return KeyMap(self.config)

    def handle_event(self, event) -> bool:
        if not self.visible:
            return False
        keys = self._keys()
        if self.waiting_for and event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self.waiting_for = ""
                self._say(t("keys.cancelled"))
                return True
            reason = keys.bind_keycode(self.waiting_for, event.key)
            if reason == "":
                self._say(t("keys.saved"))
                self._changed()
            elif reason in ("unknown", "forbidden"):
                self._say(t("keys.cannot_bind"))
            else:
                other = keys.rows()
                label = next((t(label_key) for action, label_key, _k in other
                              if action == reason), reason)
                self.swap_offer = (self.waiting_for, reason)
                self._say(t("keys.taken", action=label))
            self.waiting_for = ""
            self._layout()
            return True

        if event.type == pygame.MOUSEBUTTONDOWN:
            if self.back_button.collidepoint(event.pos):
                self.close()
                return True
            if self.reset_button.collidepoint(event.pos):
                keys.reset()
                self.swap_offer = ("", "")
                self._say(t("keys.reset_done"))
                self._changed()
                self._layout()
                return True
            if self.swap_button.collidepoint(event.pos) and self.swap_offer[0]:
                keys.swap(*self.swap_offer)
                self.swap_offer = ("", "")
                self._say(t("keys.swapped"))
                self._changed()
                self._layout()
                return True
            for action, _label_key, _key_label, rect in self.rows:
                if rect.collidepoint(event.pos):
                    self.waiting_for = action
                    return True
            return True
        if event.type == pygame.MOUSEWHEEL:
            self.scroll = max(0, self.scroll - event.y * ROW_HEIGHT)
            self._layout()
            return True
        return True

    # ------------------------------------------------------------------ helpers
    def _say(self, message: str):
        self.message = message
        self.message_timer = 200

    def _changed(self):
        if self.on_change:
            self.on_change("keys")

    def update(self):
        if self.message_timer > 0:
            self.message_timer -= 1

    # -------------------------------------------------------------------- draw
    def draw(self, screen):
        if not self.visible:
            return
        overlay = pygame.Surface(screen.get_size(), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 140))
        screen.blit(overlay, (0, 0))
        w.panel(screen, self.panel, t("keys.title"),
                t("keys.waiting") if self.waiting_for else t("keys.subtitle"))
        mouse = pygame.mouse.get_pos()
        keys = self._keys()

        previous_clip = screen.get_clip()
        screen.set_clip(self.area)
        for action, label_key, _key_label, rect in self.rows:
            hover = rect.collidepoint(mouse)
            waiting = action == self.waiting_for
            base = (70, 110, 175) if waiting else ((56, 62, 84) if hover else (44, 48, 62))
            pygame.draw.rect(screen, base, rect, border_radius=6)
            pygame.draw.rect(screen, w.BORDER, rect, 1, border_radius=6)
            w.text(screen, t(label_key), (rect.x + 14, rect.y + 7), size=18)
            value = "..." if waiting else keys.label(action)
            w.text(screen, value, (rect.right - 130, rect.y + 7), size=18,
                   color=w.ACCENT if not waiting else w.WARN)
        screen.set_clip(previous_clip)

        if len(self.rows) * (ROW_HEIGHT + 4) > self.area.height:
            w.scrollbar(screen, pygame.Rect(self.area.right + 6, self.area.y, 8,
                                            self.area.height),
                        self.scroll, len(self.rows) * (ROW_HEIGHT + 4), self.area.height)

        w.button(screen, self.reset_button, t("keys.reset"), mouse_pos=mouse, text_size=17)
        if self.swap_offer[0]:
            w.button(screen, self.swap_button, t("keys.swap"), mouse_pos=mouse,
                     base_color=(150, 110, 40), hover_color=(180, 135, 55), text_size=17)
        w.button(screen, self.back_button, t("ui.close"), mouse_pos=mouse)
        if self.message_timer > 0 and self.message:
            w.text(screen, self.message, (self.panel.x + 260, self.panel.bottom - 48),
                   size=17, color=w.WARN)
