"""Chest / warehouse screen: move items between your inventory and the storage."""

import pygame

from client.i18n import t
from client.settings import SCREEN_HEIGHT, SCREEN_WIDTH
from client.ui import widgets as w

PANEL = pygame.Rect(0, 0, 860, 470)
COLUMNS = 6
ROWS = 4
SLOT = 56
PAD = 8


class ChestMenu:
    def __init__(self, game):
        self.game = game
        self.visible = False
        self.position = (0, 0)             # tile coordinates of the chest
        self.items = {}
        self.panel = PANEL.copy()
        self.panel.center = (SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2)
        self._layout()

    # ------------------------------------------------------------------ layout
    def _layout(self):
        self.left = pygame.Rect(self.panel.x + 24, self.panel.y + 92,
                                COLUMNS * (SLOT + PAD) - PAD, ROWS * (SLOT + PAD) - PAD)
        self.right = pygame.Rect(self.panel.centerx + 14, self.panel.y + 92,
                                 COLUMNS * (SLOT + PAD) - PAD, ROWS * (SLOT + PAD) - PAD)
        self.close_button = pygame.Rect(self.panel.right - 130, self.panel.bottom - 54,
                                        110, 38)
        self.take_all = pygame.Rect(self.panel.x + 24, self.panel.bottom - 54, 170, 38)

    def open(self, tile_x, tile_y, items: dict):
        self.visible = True
        self.position = (int(tile_x), int(tile_y))
        self.items = dict(items or {})
        self._layout()

    def close(self):
        self.visible = False

    def toggle(self):
        if self.visible:
            self.close()

    def update_items(self, items: dict):
        self.items = dict(items or {})

    # -------------------------------------------------------------------- slots
    def _slots(self, mapping: dict) -> list:
        return [entry for entry in sorted(mapping.items()) if entry[1] > 0]

    def _slot_rects(self, rect, count):
        rects = []
        for index in range(max(count, COLUMNS)):
            col, row = index % COLUMNS, index // COLUMNS
            rects.append(pygame.Rect(rect.x + col * (SLOT + PAD),
                                     rect.y + row * (SLOT + PAD), SLOT, SLOT))
        return rects

    # -------------------------------------------------------------------- input
    def handle_click(self, event):
        if not self.visible:
            return
        pos = event.pos
        if self.close_button.collidepoint(pos):
            self.close()
            return
        if self.take_all.collidepoint(pos):
            for item in list(self.items)[:12]:
                self.game.net.send_dict({"type": "chest_take", "x": self.position[0],
                                         "y": self.position[1], "item": item,
                                         "count": self.items.get(item, 1)})
            return

        storage = self._slots(self.items)
        for rect, (item, amount) in zip(self._slot_rects(self.left, len(storage)), storage):
            if not rect.collidepoint(pos):
                continue
            take = amount if event.button == 3 else 1
            if pygame.key.get_pressed()[pygame.K_LSHIFT]:
                take = amount
            self.game.net.send_dict({"type": "chest_take", "x": self.position[0],
                                     "y": self.position[1], "item": item, "count": take})
            return

        inventory = self._slots(self.game.inventory)
        for rect, (item, amount) in zip(self._slot_rects(self.right, len(inventory)),
                                        inventory):
            if not rect.collidepoint(pos):
                continue
            give = amount if event.button == 3 else 1
            if pygame.key.get_pressed()[pygame.K_LSHIFT]:
                give = amount
            self.game.net.send_dict({"type": "chest_put", "x": self.position[0],
                                     "y": self.position[1], "item": item, "count": give})
            return

    # --------------------------------------------------------------------- draw
    def draw(self, screen):
        if not self.visible:
            return
        overlay = pygame.Surface(screen.get_size(), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 120))
        screen.blit(overlay, (0, 0))

        w.panel(screen, self.panel, t("chest.title"))
        mouse = pygame.mouse.get_pos()

        w.text(screen, t("chest.storage"), (self.left.x, self.left.y - 26), size=16,
               color=w.TEXT_DIM)
        w.text(screen, t("chest.yours"), (self.right.x, self.right.y - 26), size=16,
               color=w.TEXT_DIM)

        storage = self._slots(self.items)
        for rect, (item, amount) in zip(self._slot_rects(self.left, len(storage)), storage):
            hover = rect.collidepoint(mouse)
            w.slot(screen, rect, item, amount, self.game.resources, hover=hover)
        for rect in self._slot_rects(self.left, COLUMNS * ROWS)[len(storage):]:
            w.slot(screen, rect, None, 0, self.game.resources)

        inventory = self._slots(self.game.inventory)
        for rect, (item, amount) in zip(self._slot_rects(self.right, len(inventory)),
                                        inventory):
            hover = rect.collidepoint(mouse)
            w.slot(screen, rect, item, amount, self.game.resources, hover=hover)
        for rect in self._slot_rects(self.right, COLUMNS * ROWS)[len(inventory):]:
            w.slot(screen, rect, None, 0, self.game.resources)

        w.text(screen, t("chest.hint"), (self.panel.x + 24, self.panel.bottom - 92),
               size=14, color=w.TEXT_DIM)
        w.button(screen, self.take_all, t("chest.take_all"), mouse_pos=mouse, text_size=15)
        w.button(screen, self.close_button, t("chest.close"), mouse_pos=mouse, text_size=15)

        if w.ACCENT and not storage:
            w.text(screen, t("chest.empty"), self.left.center, size=16,
                   centered_in=self.left, color=w.TEXT_DIM)
