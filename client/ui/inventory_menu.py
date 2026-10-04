"""Inventory screen with a hotbar row - click an item to take it in hand."""

import pygame

from client.config import HOTBAR_SIZE
from client.i18n import t
from client.settings import SCREEN_WIDTH, SCREEN_HEIGHT
from client.ui import widgets as w
from shared.items import ITEMS, item_armor_points, item_food, item_slot

PANEL = pygame.Rect(0, 0, 880, 520)
COLS = 8
ROWS = 4
SLOT = 62
PAD = 8


class InventoryMenu:
    def __init__(self, game):
        self.game = game
        self.visible = False
        self.panel = PANEL.copy()
        self.panel.center = (SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2 - 20)
        self.slots = []
        self.hotbar_slots = []
        self.selected_index = 0
        self._layout()

    # ------------------------------------------------------------------ layout
    def _layout(self):
        start_x = self.panel.x + 30
        start_y = self.panel.y + 96
        self.slots = []
        for index in range(COLS * ROWS):
            rect = pygame.Rect(start_x + (index % COLS) * (SLOT + PAD),
                               start_y + (index // COLS) * (SLOT + PAD), SLOT, SLOT)
            self.slots.append(rect)

        # armor slots on the right side of the panel
        self.armor_slots = []
        slot_order = ("helmet", "chest", "legs", "feet")
        for index, slot in enumerate(slot_order):
            rect = pygame.Rect(self.panel.right - 210 + (index % 2) * (SLOT + PAD),
                               self.panel.y + 96 + (index // 2) * (SLOT + PAD),
                               SLOT, SLOT)
            self.armor_slots.append((slot, rect))
        self.armor_label = pygame.Rect(self.panel.right - 210, self.panel.y + 96 - 26,
                                       2 * SLOT + PAD, 20)

        bar_y = self.panel.bottom - SLOT - 60
        total = HOTBAR_SIZE * (SLOT + PAD) - PAD
        bar_x = self.panel.centerx - total // 2
        self.hotbar_slots = [pygame.Rect(bar_x + index * (SLOT + PAD), bar_y, SLOT, SLOT)
                             for index in range(HOTBAR_SIZE)]

    def toggle(self):
        self.visible = not self.visible

    # -------------------------------------------------------------------- input
    def handle_click(self, event):
        if not self.visible:
            return
        pos = event.pos
        items = self._items()

        # armor: taking a piece off
        for slot, rect in self.armor_slots:
            if rect.collidepoint(pos):
                equipped = (self.game.me.armor_items if self.game.me else {}).get(slot)
                if equipped:
                    self.game.net.send_dict({"type": "equip", "item": None, "slot": slot})
                return

        for index, rect in enumerate(self.slots):
            if rect.collidepoint(pos) and index < len(items):
                item = items[index][0]
                if event.button == 3 and item_slot(item):
                    self.game.net.send_dict({"type": "equip", "item": item})
                elif event.button == 3 and item_food(item):
                    self.game.net.send_dict({"type": "eat", "item": item})
                else:
                    self.game.set_hotbar_item(self.game.hotbar_index, item)
                    self.game.select_hotbar(self.game.hotbar_index)
                return

        for index, rect in enumerate(self.hotbar_slots):
            if rect.collidepoint(pos):
                if event.button == 3:
                    self.game.set_hotbar_item(index, None)
                else:
                    self.game.select_hotbar(index)
                return

    # --------------------------------------------------------------------- data
    def _items(self):
        """Everything in the pack, sorted - without the items that the hotbar row
        below already shows.

        b11: the same stack used to be drawn twice (once in the grid and again in
        the hotbar row) and it looked like a duplication bug. A hotbar slot is a
        shortcut, its item lives in the pack, so it is shown once, on the row.
        """
        in_bar = {item for item in (self.game.hotbar or []) if item}
        sorter = getattr(self.game, "sorted_inventory", None)
        if sorter is not None:                 # обычный путь: порядок выбрал игрок (b13)
            return [(item, count) for item, count in sorter() if item not in in_bar]
        inventory = self.game.inventory or {}  # запасной путь для заглушек в тестах
        return sorted(((item, count) for item, count in inventory.items()
                       if count > 0 and item not in in_bar),
                      key=lambda pair: (ITEMS.get(pair[0], {}).get("category", "z"),
                                        pair[0]))

    def _description(self, item):
        data = ITEMS.get(item, {})
        parts = [t(f"inv.type_{data.get('type', 'material')}")]
        if data.get("damage"):
            parts.append(f"{t('inv.stats_damage')} {data['damage']}")
        if data.get("range"):
            parts.append(f"{t('inv.stats_range')} {data['range']}")
        if data.get("efficiency"):
            parts.append(f"{t('inv.stats_efficiency')} x{data['efficiency']}")
        if data.get("durability"):
            parts.append(f"{t('inv.stats_durability')} {data['durability']}")
        if item_armor_points(item):
            parts.append(f"{t('inv.stats_armor')} {item_armor_points(item)}")
        food = item_food(item)
        if food:
            parts.append(f"{t('inv.stats_food')} +{food.get('hunger', 0)}")
        return " - ".join(parts)

    # -------------------------------------------------------------------- draw
    def draw(self, screen):
        if not self.visible:
            return
        overlay = pygame.Surface(screen.get_size(), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 110))
        screen.blit(overlay, (0, 0))

        w.panel(screen, self.panel, t("inv.title"), t("inv.hint"))
        mouse_pos = pygame.mouse.get_pos()
        items = self._items()
        hover_item = None

        for index, rect in enumerate(self.slots):
            pygame.draw.rect(screen, (42, 45, 58), rect, border_radius=5)
            pygame.draw.rect(screen, w.BORDER, rect, 1, border_radius=5)
            if index >= len(items):
                continue
            item, count = items[index]
            maximum = ITEMS.get(item, {}).get("durability")
            left = None
            if maximum and self.game.me is not None:
                left = self.game.me.durability.get(item, maximum) / maximum
            self._draw_item(screen, rect, item, count, left)
            if rect.collidepoint(mouse_pos):
                hover_item = item
                pygame.draw.rect(screen, w.ACCENT, rect, 2, border_radius=5)

        w.text(screen, t("inv.hotbar"), (self.hotbar_slots[0].x, self.hotbar_slots[0].y - 26),
               size=16, color=w.TEXT_DIM)
        keys = getattr(self.game, "keys", None)
        sort_key = keys.label("sort") if keys is not None else "O"
        sort_mode = t(f"inv.sort_{getattr(self.game, 'inventory_sort', 'category')}")
        w.text(screen, t("inv.sort_label", mode=sort_mode),
               (self.panel.x + 30, self.panel.y + 62), size=16, color=w.ACCENT)
        hint = t("inv.sort_keys", hotkey=sort_key)
        hint_x = self.panel.right - 30 - w.font(15).size(hint)[0]
        w.text(screen, hint, (hint_x, self.panel.y + 62), size=15, color=w.TEXT_DIM)
        for index, rect in enumerate(self.hotbar_slots):
            selected = index == self.game.hotbar_index
            pygame.draw.rect(screen, (55, 62, 82) if selected else (42, 45, 58), rect,
                             border_radius=5)
            pygame.draw.rect(screen, w.ACCENT if selected else w.BORDER, rect,
                             2 if selected else 1, border_radius=5)
            item = self.game.hotbar[index]
            if item:
                count = self.game.inventory.get(item, 0)
                self._draw_item(screen, rect, item, count)
                if rect.collidepoint(mouse_pos):
                    hover_item = item
                if count <= 0:
                    # the slot still points at an item that is gone: dim it
                    veil = pygame.Surface(rect.size, pygame.SRCALPHA)
                    veil.fill((0, 0, 0, 120))
                    screen.blit(veil, rect.topleft)
            w.text(screen, str(index + 1), (rect.x + 5, rect.y + 3), size=13, color=w.TEXT_DIM)

        w.text(screen, t("inv.armor", points=self.game.me.armor if self.game.me else 0),
               (self.armor_label.x, self.armor_label.y), size=16, color=w.TEXT_DIM)
        equipped = (self.game.me.armor_items if self.game.me else {}) or {}
        for slot, rect in self.armor_slots:
            item = equipped.get(slot)
            hover = rect.collidepoint(mouse_pos)
            w.slot(screen, rect, item, 0, self.game.resources, hover=hover)
            if not item:
                w.text(screen, t(f"inv.slot_{slot}"), rect.center, size=12,
                       centered_in=rect, color=w.TEXT_DIM)
            elif hover:
                hover_item = item
                pygame.draw.rect(screen, w.ACCENT, rect, 2, border_radius=6)

        held = self.game.held_item()
        w.text(screen, t("inv.in_hand", item=t(f"item.{held}") if held else "-"),
               (self.panel.x + 30, self.panel.bottom - 32), size=16)

        if hover_item:
            w.tooltip(screen, f"{t('item.' + hover_item)} - {self._description(hover_item)}",
                      mouse_pos)

    def _draw_item(self, screen, rect, item, count, durability=None):
        icon = self.game.resources.get(item)
        if icon:
            size = min(rect.width, rect.height) - 18
            screen.blit(pygame.transform.smoothscale(icon, (size, size)),
                        (rect.centerx - size // 2, rect.centery - size // 2 - 2))
        else:
            w.text(screen, item[:3].upper(), (rect.centerx, rect.centery - 4), size=18,
                   centered_in=rect)
        if count is not None:
            label = w.font(15).render(str(count), True, w.TEXT)
            screen.blit(label, (rect.right - label.get_width() - 5, rect.bottom - 20))
        if durability is not None and durability < 1:
            bar = pygame.Rect(rect.x + 5, rect.bottom - 7, rect.width - 10, 4)
            pygame.draw.rect(screen, (60, 32, 32), bar, border_radius=2)
            color = w.GOOD if durability > 0.5 else (w.WARN if durability > 0.2 else w.BAD)
            pygame.draw.rect(screen, color, (bar.x, bar.y, int(bar.width * durability), 4),
                             border_radius=2)
