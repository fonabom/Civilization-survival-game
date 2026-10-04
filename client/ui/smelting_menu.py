"""Furnace menu."""

import pygame

from client.i18n import t
from client.settings import SCREEN_WIDTH, SCREEN_HEIGHT
from client.ui import widgets as w
from shared.items import SMELTING_RECIPES

PANEL = pygame.Rect(0, 0, 460, 300)


class SmeltingMenu:
    def __init__(self, game):
        self.game = game
        self.visible = False
        self.panel = PANEL.copy()
        self.panel.center = (SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2)
        self.rows = []
        self._layout()

    def _layout(self):
        y = self.panel.y + 70
        self.rows = []
        for action in SMELTING_RECIPES:
            self.rows.append((action, pygame.Rect(self.panel.x + 24, y, self.panel.width - 48, 46)))
            y += 58
        self.close_button = pygame.Rect(self.panel.right - 120, self.panel.bottom - 48, 96, 34)

    def toggle(self):
        self.visible = not self.visible

    # -------------------------------------------------------------------- input
    def handle_click(self, event):
        if not self.visible:
            return
        if self.close_button.collidepoint(event.pos):
            self.visible = False
            return
        for action, rect in self.rows:
            if rect.collidepoint(event.pos):
                self.game.net.send_dict({"type": "smelt", "action": action})
                return

    # --------------------------------------------------------------------- draw
    def draw(self, screen):
        if not self.visible:
            return
        overlay = pygame.Surface(screen.get_size(), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 120))
        screen.blit(overlay, (0, 0))
        w.panel(screen, self.panel, t("smelt.title"), t("smelt.fuel"))
        mouse_pos = pygame.mouse.get_pos()
        inventory = self.game.inventory

        for action, rect in self.rows:
            recipe = SMELTING_RECIPES[action]
            has_ore = inventory.get(recipe["input"], 0) > 0
            has_fuel = inventory.get(recipe["fuel"], 0) > 0
            ready = has_ore and has_fuel
            color = (52, 64, 52) if ready else (62, 50, 50)
            hover = rect.collidepoint(mouse_pos)
            if hover:
                color = tuple(min(255, channel + 20) for channel in color)
            pygame.draw.rect(screen, color, rect, border_radius=6)
            pygame.draw.rect(screen, w.BORDER, rect, 1, border_radius=6)

            icon = self.game.resources.get(recipe["input"])
            if icon:
                screen.blit(pygame.transform.smoothscale(icon, (32, 32)), (rect.x + 8, rect.y + 7))
            title = t("smelt.iron") if action == "smelt_iron" else t("smelt.gold")
            w.text(screen, title, (rect.x + 52, rect.y + 6), size=16)
            w.text(screen, t("smelt.fuel"), (rect.x + 52, rect.y + 26), size=13,
                   color=w.TEXT_DIM)
            if not ready:
                missing = []
                if not has_ore:
                    missing.append(t("item." + recipe["input"]))
                if not has_fuel:
                    missing.append(t("item." + recipe["fuel"]))
                rendered = w.font(13).render("+ " + ", ".join(missing), True, w.WARN)
                screen.blit(rendered, (rect.right - rendered.get_width() - 10,
                                       rect.centery - rendered.get_height() // 2))

        w.button(screen, self.close_button, t("research.close"), mouse_pos=mouse_pos, text_size=15)
