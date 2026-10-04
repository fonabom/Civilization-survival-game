"""Crafting screen.

Two tabs:
  * Recipes  - grouped by category, shows what you can make and where you must
               stand. Left click crafts 1, right click crafts 5, Shift+click
               crafts as many as the resources allow.
  * Buildings - choosing one enters build mode, so you place it on the map with
               a ghost preview instead of dropping it under your feet.
"""

import pygame

from client.i18n import t
from client.settings import SCREEN_WIDTH, SCREEN_HEIGHT
from client.ui import widgets as w
from shared.items import (CATEGORY_ORDER, CRAFTING_RECIPES, craftable_amount, recipe_category,
                          recipe_cost, recipe_output, recipe_station)
from shared.structures import STRUCTURES, can_afford, get_cost, get_size, get_tech

PANEL = pygame.Rect(0, 0, 820, 560)
ROW_H = 42
ROW_GAP = 6
TAB_H = 34


class CraftingMenu:
    def __init__(self, game):
        self.game = game
        self.visible = False
        self.tab = "recipes"
        self.category = CATEGORY_ORDER[0]
        self.scroll = 0
        self.panel = PANEL.copy()
        self.panel.center = (SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2)
        self._layout()

    # ------------------------------------------------------------------ layout
    def _layout(self):
        self.tab_recipes = pygame.Rect(self.panel.x + 20, self.panel.y + 46, 150, TAB_H)
        self.tab_buildings = pygame.Rect(self.tab_recipes.right + 8, self.panel.y + 46, 150, TAB_H)
        self.category_rects = []
        y = self.panel.y + 92
        for _code in CATEGORY_ORDER:
            rect = pygame.Rect(self.panel.x + 20, y, 190, 30)
            self.category_rects.append(rect)
            y += 34
        self.list_rect = pygame.Rect(self.panel.x + 230, self.panel.y + 92,
                                     self.panel.width - 260, self.panel.height - 150)
        self.close_button = pygame.Rect(self.panel.right - 130, self.panel.bottom - 54, 110, 38)

    def toggle(self):
        self.visible = not self.visible
        self.scroll = 0

    # -------------------------------------------------------------------- input
    def handle_click(self, event):
        if not self.visible:
            return
        pos = event.pos
        if self.close_button.collidepoint(pos):
            self.visible = False
            return
        if self.tab_recipes.collidepoint(pos):
            self.tab = "recipes"
            self.scroll = 0
            return
        if self.tab_buildings.collidepoint(pos):
            self.tab = "buildings"
            self.scroll = 0
            return
        if event.button in (4, 5):
            self.scroll = max(0, self.scroll + (-40 if event.button == 4 else 40))
            return
        if self.tab == "recipes":
            for rect, code in zip(self.category_rects, CATEGORY_ORDER):
                if rect.collidepoint(pos):
                    self.category = code
                    self.scroll = 0
                    return

        for name, rect in self._rows():
            if not rect.collidepoint(pos):
                continue
            if self.tab == "recipes":
                count = 1
                if event.button == 3:
                    count = 5
                elif pygame.key.get_mods() & pygame.KMOD_SHIFT:
                    count = max(1, craftable_amount(name, self.game.inventory))
                self.game.net.send_dict({"type": "craft", "item": name, "count": count})
            else:
                self.game.enter_build_mode(name)
            return

    # --------------------------------------------------------------------- data
    def _rows_data(self):
        if self.tab == "recipes":
            return [(name, recipe_cost(name), self._can_station(name),
                     self._station(name)) for name in CRAFTING_RECIPES
                    if recipe_category(name) == self.category]
        return [(name, get_cost(name), self._can_station(None, name), get_tech(name))
                for name in STRUCTURES]

    def _station(self, recipe):
        station = recipe_station(recipe)
        return t(f"station.{station}") if station else None

    def _can_station(self, recipe=None, structure=None):
        station = recipe_station(recipe) if recipe else None
        if not station:
            return True
        player = self.game.me
        if player is None:
            return False
        for building in self.game.world.buildings.values():
            kind = building["type"]
            provides = kind == station or STRUCTURES.get(kind, {}).get("station") == station
            if not provides:
                continue
            bx = building["x"] * 32 + 16
            by = building["y"] * 32 + 16
            if ((player.x - bx) ** 2 + (player.y - by) ** 2) ** 0.5 < 80:
                return True
        return False

    def _rows(self):
        rows = []
        y = self.list_rect.y + 6 - self.scroll
        for name, _cost, _ok, _extra in self._rows_data():
            rect = pygame.Rect(self.list_rect.x, y, self.list_rect.width - 14, ROW_H)
            rows.append((name, rect))
            y += ROW_H + ROW_GAP
        return rows

    # -------------------------------------------------------------------- draw
    def draw(self, screen):
        if not self.visible:
            return
        overlay = pygame.Surface(screen.get_size(), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 120))
        screen.blit(overlay, (0, 0))

        w.panel(screen, self.panel, t("craft.title"),
                t("craft.hint_items") if self.tab == "recipes" else t("craft.hint_build"))
        mouse_pos = pygame.mouse.get_pos()

        for rect, code in zip(self.category_rects, CATEGORY_ORDER):
            if self.tab != "recipes":
                break
            active = code == self.category
            hover = rect.collidepoint(mouse_pos)
            color = (72, 86, 120) if active else ((52, 56, 74) if hover else (40, 43, 55))
            pygame.draw.rect(screen, color, rect, border_radius=5)
            if active:
                pygame.draw.rect(screen, w.ACCENT, rect, 2, border_radius=5)
            w.text(screen, t(f"craft.category_{code}"), (rect.x + 10, rect.centery - 10),
                   size=15)

        self._tab(screen, self.tab_recipes, t("craft.tab_recipes"), self.tab == "recipes")
        self._tab(screen, self.tab_buildings, t("craft.tab_build"), self.tab == "buildings")

        pygame.draw.rect(screen, (26, 28, 36), self.list_rect, border_radius=6)
        pygame.draw.rect(screen, w.BORDER, self.list_rect, 1, border_radius=6)

        rows = self._rows()
        content_height = len(rows) * (ROW_H + ROW_GAP)
        clip = screen.get_clip()
        screen.set_clip(self.list_rect)
        for name, rect in rows:
            if self.tab == "recipes":
                self._recipe_row(screen, name, rect, mouse_pos)
            else:
                self._building_row(screen, name, rect, mouse_pos)
        screen.set_clip(clip)
        w.scrollbar(screen, self.list_rect, self.scroll, content_height, self.list_rect.height)

        if self.tab == "recipes":
            w.text(screen, t("craft.have", have=f"{len(self.game.inventory)} stacks"),
                   (self.panel.x + 20, self.panel.bottom - 40), size=15, color=w.TEXT_DIM)
        w.button(screen, self.close_button, t("research.close"), mouse_pos=mouse_pos,
                 text_size=16)

    def _tab(self, screen, rect, label, active):
        hover = rect.collidepoint(pygame.mouse.get_pos())
        color = (72, 86, 120) if active else ((52, 56, 74) if hover else (40, 43, 55))
        pygame.draw.rect(screen, color, rect, border_radius=5)
        if active:
            pygame.draw.rect(screen, w.ACCENT, rect, 2, border_radius=5)
        w.text(screen, label, (0, 0), centered_in=rect, size=16)

    def _recipe_row(self, screen, name, rect, mouse_pos):
        can_make = craftable_amount(name, self.game.inventory)
        station_ok = self._can_station(name)
        affordable = can_make > 0
        row_color = (48, 62, 48) if (affordable and station_ok) else \
                    ((64, 58, 44) if not station_ok else (62, 48, 48))
        hover = rect.collidepoint(mouse_pos)
        if hover:
            row_color = tuple(min(255, channel + 22) for channel in row_color)
        pygame.draw.rect(screen, row_color, rect, border_radius=5)
        pygame.draw.rect(screen, w.BORDER, rect, 1, border_radius=5)

        icon = self.game.resources.get(name)
        if icon:
            screen.blit(pygame.transform.smoothscale(icon, (30, 30)), (rect.x + 6, rect.y + 6))
        label_x = rect.x + 44
        w.text(screen, t(f"item.{name}"), (label_x, rect.y + 4), size=16)
        w.text(screen, w.format_cost(recipe_cost(name), self.game.inventory),
               (label_x, rect.y + 23), size=13, color=w.TEXT_DIM)

        right = []
        output = recipe_output(name)
        if output > 1:
            right.append(t("craft.output", count=output))
        station = self._station(name)
        if station and not station_ok:
            right.append(t("craft.need_station", station=station))
        if affordable and station_ok:
            right.append(t("craft.crafts", count=can_make))
        label = "  ".join(right)
        if label:
            color = w.GOOD if (affordable and station_ok) else w.WARN
            rendered = w.font(13).render(label, True, color)
            screen.blit(rendered, (rect.right - rendered.get_width() - 10,
                                   rect.centery - rendered.get_height() // 2))

    def _building_row(self, screen, name, rect, mouse_pos):
        affordable = can_afford(name, self.game.inventory)
        tech = get_tech(name)
        row_color = (50, 62, 50) if affordable else (62, 48, 48)
        hover = rect.collidepoint(mouse_pos)
        if hover:
            row_color = tuple(min(255, channel + 22) for channel in row_color)
        pygame.draw.rect(screen, row_color, rect, border_radius=5)
        pygame.draw.rect(screen, w.BORDER, rect, 1, border_radius=5)

        icon = self.game.resources.get(name)
        if icon:
            screen.blit(pygame.transform.smoothscale(icon, (30, 30)), (rect.x + 6, rect.y + 6))
        w.text(screen, t(f"structure.{name}"), (rect.x + 44, rect.y + 4), size=16)
        w.text(screen, w.format_cost(get_cost(name), self.game.inventory),
               (rect.x + 44, rect.y + 23), size=13, color=w.TEXT_DIM)

        width, height = get_size(name)
        extras = [f"{width}x{height}"]
        if tech:
            extras.append(t(f"tech.{tech}"))
        rendered = w.font(13).render("  ".join(extras), True, w.TEXT_DIM)
        screen.blit(rendered, (rect.right - rendered.get_width() - 10,
                               rect.centery - rendered.get_height() // 2))
