"""Research screens: town centre (city tier) and research table (country techs)."""

import pygame

from client.i18n import t
from client.settings import SCREEN_WIDTH, SCREEN_HEIGHT
from client.ui import widgets as w

ROW_H = 86
ROW_GAP = 8
PANEL = pygame.Rect(0, 0, 640, 560)


class ResearchMenu:
    def __init__(self, game):
        self.game = game
        self.visible = False
        self.mode = None                  # "city" | "country"
        self.panel = PANEL.copy()
        self.panel.center = (SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2)
        self.close_button = pygame.Rect(self.panel.right - 130, self.panel.bottom - 54, 110, 38)
        self._layout()

    def _layout(self):
        self.tier_button = pygame.Rect(self.panel.x + 30, self.panel.y + 90,
                                       self.panel.width - 60, 52)
        self.list_rect = pygame.Rect(self.panel.x + 30, self.panel.y + 90,
                                     self.panel.width - 60,
                                     self.panel.bottom - self.panel.y - 160)
        self.scroll = getattr(self, "scroll", 0)

    def _tech_list(self):
        """Server order plus whatever the server said about each technology."""
        available = ((getattr(self.game, "civ_state", {}) or {})
                     .get("techs_available") or {})
        order = list(available)
        order.sort(key=lambda code: (bool(available[code].get("requires")), code))
        return [(code, available[code]) for code in order]

    def handle_wheel(self, direction):
        if not self.visible or self.mode != "country":
            return False
        rows = max(1, len(self._tech_list()))
        visible = max(1, self.list_rect.height // (ROW_H + ROW_GAP))
        self.scroll = max(0, min(max(0, rows - visible), self.scroll + direction))
        return True

    def open(self, mode):
        self.visible = True
        self.mode = mode

    def close(self):
        self.visible = False
        self.mode = None

    def toggle(self):
        if self.visible:
            self.close()

    # -------------------------------------------------------------------- input
    def handle_click(self, event):
        if not self.visible:
            return
        pos = event.pos
        if self.close_button.collidepoint(pos):
            self.close()
            return
        if self.mode == "city":
            if self.tier_button.collidepoint(pos):
                self.game.net.send_dict({"type": "research", "city": "AUTO_FIND"})
            return
        if self.mode == "country":
            for rect, (code, data) in zip(self._tech_rects(), self._tech_list()):
                if rect.collidepoint(pos) and not data.get("researched"):
                    self.game.net.send_dict({"type": "research", "scope": "country",
                                             "country": "AUTO_FIND", "tech": code})
                    return

    def _tech_rects(self):
        visible = max(1, self.list_rect.height // (ROW_H + ROW_GAP))
        return [pygame.Rect(self.list_rect.x,
                            self.list_rect.y + index * (ROW_H + ROW_GAP),
                            self.list_rect.width, ROW_H)
                for index in range(visible)]

    # --------------------------------------------------------------------- draw
    def draw(self, screen):
        if not self.visible:
            return
        overlay = pygame.Surface(screen.get_size(), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 120))
        screen.blit(overlay, (0, 0))

        title = t("research.city_title") if self.mode == "city" else t("research.country_title")
        w.panel(screen, self.panel, title)
        mouse_pos = pygame.mouse.get_pos()
        inventory = self.game.inventory

        if self.mode == "city":
            city = self._my_city()
            tier = (city or {}).get("tier", 1)
            costs = ((getattr(self.game, "civ_state", {}) or {})
                     .get("tier_costs") or {})
            cost = costs.get(str(tier + 1)) or costs.get(tier + 1)
            subtitle = t("research.tier_now", tier=tier)
            self._row(screen, self.tier_button, t("research.tier_button"), subtitle,
                      inventory, required=cost, enabled=bool(cost))
        else:
            techs = self._tech_list()
            for rect, (code, data) in zip(self._tech_rects(), techs[self.scroll:]):
                researched = list(data.get("researched_by") or [])
                done = bool(data.get("researched"))
                requires = data.get("requires")
                subtitle = t("research.done") if done else t(f"tech.{code}.desc")
                if requires and not done:
                    subtitle = f"{subtitle}  ({t('research.needs', tech=t('tech.' + requires))})"
                self._row(screen, rect, t(f"tech.{code}"), subtitle, inventory,
                          required=None if done else data.get("cost"), done=done,
                          subtitle_color=w.GOOD if done else None,
                          extra=researched)
            if not techs:
                w.text(screen, t("research.no_techs"), self.list_rect.center, size=16,
                       centered_in=self.list_rect, color=w.TEXT_DIM)

        w.button(screen, self.close_button, t("research.close"), mouse_pos=mouse_pos, text_size=16)

    def _my_city(self):
        civ_state = getattr(self.game, "civ_state", {}) or {}
        cities = civ_state.get("cities") or {}
        for city in cities.values():
            if city.get("leader") == self.game.my_id:
                return city
        return None

    def _row(self, screen, rect, title, subtitle, inventory, required=None,
             done=False, subtitle_color=None, enabled=True, extra=None):
        affordable = not required or all(inventory.get(res, 0) >= amount
                                         for res, amount in required.items())
        if done:
            color = (48, 62, 48)
        elif affordable:
            color = (54, 68, 84)
        else:
            color = (64, 52, 52)
        hover = rect.collidepoint(pygame.mouse.get_pos())
        if hover and not done:
            color = tuple(min(255, channel + 20) for channel in color)
        pygame.draw.rect(screen, color, rect, border_radius=6)
        pygame.draw.rect(screen, w.BORDER, rect, 1, border_radius=6)

        w.text(screen, title, (rect.x + 14, rect.y + 10), size=18)
        w.text(screen, subtitle, (rect.x + 14, rect.y + 36), size=14,
               color=subtitle_color or (w.TEXT if affordable or done else w.WARN))
        if required is not None:
            cost_text = w.format_cost(required, inventory)
            rendered = w.font(14).render(cost_text, True, w.TEXT_DIM)
            screen.blit(rendered, (rect.right - rendered.get_width() - 14,
                                   rect.centery - rendered.get_height() // 2))
        if extra:
            names = ", ".join(extra)
            rendered = w.font(12).render(names, True, w.GOOD)
            screen.blit(rendered, (rect.right - rendered.get_width() - 14, rect.bottom - 22))
