"""Market screen (b9): post offers and take other players' offers.

Trading needs a `market` building within a few tiles - the server checks it
again, so the client only gives a friendly hint. Goods of a posted offer are
held by the market until somebody takes it back or buys it.
"""

import pygame

from client.i18n import t
from client.settings import SCREEN_HEIGHT, SCREEN_WIDTH, TILE_SIZE
from client.ui import widgets as w
from shared.items import CATEGORY_ORDER, ITEMS

PANEL = pygame.Rect(0, 0, 920, 540)
ROW_H = 44
MAX_ROWS = 5
SLOT = 46
PAD = 6
GRID_COLS = 7
GRID_ROWS = 2              # scrollable "what do you want" grid
REACH = 3                  # tiles, must match the server's market_near()


def _offer_rows(offers: list, offset: int):
    try:
        ordered = sorted(offers, key=lambda offer: int(offer.get("id", 0)))
    except (TypeError, ValueError):
        ordered = list(offers)
    return ordered[offset:offset + MAX_ROWS]


class TradeMenu:
    def __init__(self, game):
        self.game = game
        self.visible = False
        self.give_item = None
        self.want_item = None
        self.give_count = 1
        self.want_count = 1
        self.offset = 0            # first column of the "want" grid
        self.row_offset = 0        # first offer row
        self.panel = PANEL.copy()
        self.panel.center = (SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2)
        self._layout()

    # ------------------------------------------------------------------ layout
    def _layout(self):
        """Every rectangle is computed once, here - the drawing only uses them."""
        left = self.panel.x + 22
        self.offers_area = pygame.Rect(left, self.panel.y + 96, 470, MAX_ROWS * ROW_H)
        self.scroll_up = pygame.Rect(left, self.offers_area.bottom + 8, 30, 26)
        self.scroll_down = pygame.Rect(left + 36, self.offers_area.bottom + 8, 30, 26)

        self.post_area = pygame.Rect(left + 520, self.panel.y + 62, 372, 400)
        top = self.post_area.y
        self.give_row = pygame.Rect(self.post_area.x, top + 48,
                                    GRID_COLS * (SLOT + PAD) - PAD, SLOT)
        self.give_minus = pygame.Rect(self.post_area.right - 76, top + 102, 30, 26)
        self.give_plus = pygame.Rect(self.post_area.right - 40, top + 102, 30, 26)
        self.want_grid = pygame.Rect(self.post_area.x, top + 186,
                                     GRID_COLS * (SLOT + PAD) - PAD,
                                     GRID_ROWS * (SLOT + PAD) - PAD)
        self.want_minus = pygame.Rect(self.post_area.right - 76,
                                      self.want_grid.bottom + 12, 30, 26)
        self.want_plus = pygame.Rect(self.post_area.right - 40,
                                     self.want_grid.bottom + 12, 30, 26)
        self.close_button = pygame.Rect(self.panel.right - 132, self.panel.bottom - 52,
                                        110, 36)
        self.post_button = pygame.Rect(self.post_area.x, self.panel.bottom - 52, 190, 36)

    def open(self):
        self.visible = True

    def close(self):
        self.visible = False

    def toggle(self):
        self.visible = not self.visible

    # --------------------------------------------------------------- helpers
    def market_here(self) -> bool:
        """Is a market close enough? (the server asks the same question)"""
        me = self.game.me
        if me is None:
            return False
        for building in self.game.world.buildings.values():
            if building.get("type") != "market":
                continue
            bx = building["x"] * TILE_SIZE + TILE_SIZE * building.get("w", 1) / 2
            by = building["y"] * TILE_SIZE + TILE_SIZE * building.get("h", 1) / 2
            if max(abs(bx - me.x), abs(by - me.y)) / TILE_SIZE <= REACH:
                return True
        return False

    def _sellable(self) -> list:
        """What the player can put on the market: the fullest stacks first."""
        stacks = [(name, amount) for name, amount in self.game.inventory.items()
                  if amount > 0]
        stacks.sort(key=lambda entry: (-entry[1], entry[0]))
        return stacks[:GRID_COLS]

    def _all_items(self) -> list:
        """Every item the player could ask for, in a stable order."""
        def sort_key(name):
            info = ITEMS.get(name, {})
            category = info.get("category", "material")
            order = CATEGORY_ORDER.index(category) if category in CATEGORY_ORDER else 99
            return (order, name)
        return sorted(ITEMS, key=sort_key)

    def _grid_items(self) -> list:
        items = self._all_items()
        span = GRID_COLS * GRID_ROWS
        start = (self.offset * GRID_COLS) % max(len(items), 1)
        rolled = items[start:] + items[:start]
        return rolled[:span]

    def _scroll(self, step: int, offers: bool = False):
        if offers:
            count = max(1, len(self.game.trades) - MAX_ROWS + 1)
            self.row_offset = max(0, min(self.row_offset + step, count - 1))
            return
        columns = max(1, len(self._all_items()) // GRID_COLS)
        self.offset = (self.offset + step) % columns

    @staticmethod
    def _label(item):
        return t(f"item.{item}") if item else "-"

    def _send_post(self):
        if not self.give_item or not self.want_item:
            self.game.notify(t("notify.trade_need_choice"), w.WARN)
            return
        self.game.net.send_dict({
            "type": "trade_post", "give_item": self.give_item,
            "give_count": self.give_count, "want_item": self.want_item,
            "want_count": self.want_count})

    # ------------------------------------------------------------------ input
    def handle_wheel(self, event) -> bool:
        if not self.visible:
            return False
        step = -1 if event.button == 4 else 1
        over_offers = self.offers_area.collidepoint(pygame.mouse.get_pos())
        self._scroll(step, offers=over_offers)
        return True

    def handle_click(self, event):
        if not self.visible:
            return
        pos = event.pos
        if self.close_button.collidepoint(pos):
            self.close()
            return
        if self.scroll_up.collidepoint(pos):
            self._scroll(-1, offers=True)
            return
        if self.scroll_down.collidepoint(pos):
            self._scroll(1, offers=True)
            return
        if self.post_button.collidepoint(pos):
            self._send_post()
            return

        shift = pygame.key.get_pressed()[pygame.K_LSHIFT]
        for row, offer in enumerate(_offer_rows(self.game.trades, self.row_offset)):
            rect = pygame.Rect(self.offers_area.x, self.offers_area.y + row * ROW_H,
                               self.offers_area.width, ROW_H - 6)
            action = pygame.Rect(rect.right - 116, rect.y + 4, 110, ROW_H - 14)
            if not action.collidepoint(pos):
                continue
            if offer.get("owner") == self.game.my_id:
                self.game.net.send_dict({"type": "trade_cancel", "id": offer.get("id")})
            else:
                self.game.net.send_dict({"type": "trade_take", "id": offer.get("id")})
            return

        # what to give: pick from the inventory
        inventory = self._sellable()
        for rect, (name, _amount) in zip(self._row_rects(self.give_row, len(inventory)),
                                         inventory):
            if rect.collidepoint(pos):
                self.give_item = name
                self.give_count = 1
                return

        # what to want: pick from the whole catalogue
        for rect, name in zip(self._row_rects(self.want_grid, len(self._grid_items())),
                              self._grid_items()):
            if rect.collidepoint(pos):
                self.want_item = name
                self.want_count = 1
                return

        if self.give_minus.collidepoint(pos):
            self.give_count = max(1, self.give_count - (5 if shift else 1))
        elif self.give_plus.collidepoint(pos):
            ceiling = self.game.inventory.get(self.give_item, 1) if self.give_item else 1
            self.give_count = min(max(1, ceiling), self.give_count + (5 if shift else 1))
        elif self.want_minus.collidepoint(pos):
            self.want_count = max(1, self.want_count - (5 if shift else 1))
        elif self.want_plus.collidepoint(pos):
            self.want_count = min(1000, self.want_count + (5 if shift else 1))

    # --------------------------------------------------------------------- draw
    def _row_rects(self, rect, count):
        rects = []
        for index in range(max(count, GRID_COLS)):
            col, row = index % GRID_COLS, index // GRID_COLS
            rects.append(pygame.Rect(rect.x + col * (SLOT + PAD),
                                     rect.y + row * (SLOT + PAD), SLOT, SLOT))
        return rects

    def _draw_offer(self, screen, rect, offer, mouse):
        mine = offer.get("owner") == self.game.my_id
        pygame.draw.rect(screen, (44, 50, 66), rect)
        pygame.draw.rect(screen, (70, 80, 104), rect, 1)
        icon = pygame.Rect(rect.x + 6, rect.y + 4, 30, 30)
        w.slot(screen, icon, offer.get("give_item"), offer.get("give_count", 1),
               self.game.resources)
        w.text(screen, "->", (icon.right + 4, rect.y + 10), size=16, color=w.TEXT_DIM)
        want_icon = pygame.Rect(icon.right + 26, rect.y + 4, 30, 30)
        w.slot(screen, want_icon, offer.get("want_item"), offer.get("want_count", 1),
               self.game.resources)
        who = offer.get("owner_name", "?")
        where = offer.get("city") or ""
        label = f"{who}" + (f" [{where}]" if where else "")
        w.text(screen, label, (want_icon.right + 10, rect.y + 6), size=15)
        w.text(screen, t("trade.rate",
                         give=f"{offer.get('give_count', 1)}x {self._label(offer.get('give_item'))}",
                         want=f"{offer.get('want_count', 1)}x {self._label(offer.get('want_item'))}"),
               (want_icon.right + 10, rect.y + 22), size=13, color=w.TEXT_DIM)
        action = pygame.Rect(rect.right - 116, rect.y + 4, 110, ROW_H - 14)
        w.button(screen, action, t("trade.cancel" if mine else "trade.take"),
                 mouse_pos=mouse, text_size=14)

    def draw(self, screen):
        if not self.visible:
            return
        overlay = pygame.Surface(screen.get_size(), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 120))
        screen.blit(overlay, (0, 0))

        w.panel(screen, self.panel, t("trade.title"))
        mouse = pygame.mouse.get_pos()
        near = self.market_here()

        w.text(screen, t("trade.offers"), (self.offers_area.x, self.offers_area.y - 26),
               size=16, color=w.TEXT_DIM)
        rows = _offer_rows(self.game.trades, self.row_offset)
        if not rows:
            w.text(screen, t("trade.empty_offers"), self.offers_area.center, size=16,
                   centered_in=self.offers_area, color=w.TEXT_DIM)
        for index, offer in enumerate(rows):
            rect = pygame.Rect(self.offers_area.x, self.offers_area.y + index * ROW_H,
                               self.offers_area.width, ROW_H - 6)
            self._draw_offer(screen, rect, offer, mouse)
        w.button(screen, self.scroll_up, "^", mouse_pos=mouse, text_size=14)
        w.button(screen, self.scroll_down, "v", mouse_pos=mouse, text_size=14)

        # ---- posting side
        w.text(screen, t("trade.post"), (self.post_area.x, self.post_area.y + 4), size=16,
               color=w.TEXT_DIM)
        w.text(screen, t("trade.give"), (self.post_area.x, self.give_row.y - 22), size=14,
               color=w.TEXT_DIM)
        inventory = self._sellable()
        for rect, (name, amount) in zip(self._row_rects(self.give_row, len(inventory)),
                                        inventory):
            w.slot(screen, rect, name, amount, self.game.resources,
                   hover=rect.collidepoint(mouse), selected=name == self.give_item)
        for rect in self._row_rects(self.give_row, GRID_COLS)[len(inventory):]:
            w.slot(screen, rect, None, 0, self.game.resources)

        give_name = self._label(self.give_item)
        want_name = self._label(self.want_item)
        w.text(screen, f"{t('trade.give')}: {self.give_count}x {give_name}",
               (self.post_area.x, self.give_minus.y + 4), size=15)
        w.button(screen, self.give_minus, "-", mouse_pos=mouse, text_size=15)
        w.button(screen, self.give_plus, "+", mouse_pos=mouse, text_size=15)

        w.text(screen, t("trade.want"), (self.post_area.x, self.want_grid.y - 46), size=14,
               color=w.TEXT_DIM)
        for rect, name in zip(self._row_rects(self.want_grid, len(self._grid_items())),
                              self._grid_items()):
            w.slot(screen, rect, name, 0, self.game.resources,
                   hover=rect.collidepoint(mouse), selected=name == self.want_item)
        w.text(screen, f"{t('trade.want')}: {self.want_count}x {want_name}",
               (self.post_area.x, self.want_minus.y + 4), size=15)
        w.button(screen, self.want_minus, "-", mouse_pos=mouse, text_size=15)
        w.button(screen, self.want_plus, "+", mouse_pos=mouse, text_size=15)

        # the hint lives on the left: the row next to the post button is narrow
        note = t("trade.hint") if near else t("notify.no_market")
        w.text(screen, note, (self.offers_area.x, self.post_button.y - 4), size=14,
               color=w.TEXT_DIM if near else w.WARN)
        w.button(screen, self.post_button, t("trade.post_button"), mouse_pos=mouse,
                 text_size=15, base_color=(60, 96, 70) if near else (70, 60, 60))
        w.button(screen, self.close_button, t("trade.close"), mouse_pos=mouse, text_size=15)
