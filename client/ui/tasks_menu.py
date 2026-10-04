"""Tasks and achievements screen (key K)."""

import pygame

from client.i18n import t
from client.settings import SCREEN_HEIGHT, SCREEN_WIDTH
from client.ui import widgets as w
from shared.tasks import TASK_ORDER, TASKS, progress

PANEL = pygame.Rect(0, 0, 720, 520)
ROW_H = 42


class TasksMenu:
    def __init__(self, game):
        self.game = game
        self.visible = False
        self.tab = "task"                   # task | achievement | stats
        self.scroll = 0
        self.panel = PANEL.copy()
        self.panel.center = (SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2)
        self._layout()

    def _layout(self):
        self.tab_tasks = pygame.Rect(self.panel.x + 20, self.panel.y + 52, 150, 32)
        self.tab_achievements = pygame.Rect(self.tab_tasks.right + 8, self.panel.y + 52,
                                           190, 32)
        self.tab_stats = pygame.Rect(self.tab_achievements.right + 8, self.panel.y + 52,
                                     130, 32)
        self.list_rect = pygame.Rect(self.panel.x + 20, self.panel.y + 96,
                                     self.panel.width - 40, self.panel.height - 160)
        self.close_button = pygame.Rect(self.panel.right - 130, self.panel.bottom - 54,
                                        110, 38)

    def toggle(self):
        self.visible = not self.visible
        self.scroll = 0

    def handle_click(self, event):
        if not self.visible:
            return
        pos = event.pos
        if self.close_button.collidepoint(pos):
            self.visible = False
            return
        if self.tab_tasks.collidepoint(pos):
            self.tab, self.scroll = "task", 0
        elif self.tab_achievements.collidepoint(pos):
            self.tab, self.scroll = "achievement", 0
        elif self.tab_stats.collidepoint(pos):
            self.tab, self.scroll = "stats", 0
        elif event.button == 4:
            self.scroll = max(0, self.scroll - 1)
        elif event.button == 5:
            self.scroll = min(self._rows_count() - 1, self.scroll + 1)

    def handle_wheel(self, direction):
        if not self.visible:
            return False
        self.scroll = max(0, min(max(0, self._rows_count() - 1), self.scroll + direction))
        return True

    def _code_list(self):
        return [code for code in TASK_ORDER if TASKS[code]["kind"] == self.tab]

    def _rows_count(self):
        return len(self._code_list()) if self.tab != "stats" else len(self.game.stats)

    # --------------------------------------------------------------------- draw
    def draw(self, screen):
        if not self.visible:
            return
        overlay = pygame.Surface(screen.get_size(), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 120))
        screen.blit(overlay, (0, 0))

        w.panel(screen, self.panel, t("tasks.title"))
        mouse = pygame.mouse.get_pos()

        for rect, key, label in ((self.tab_tasks, "task", t("tasks.tab_tasks")),
                                 (self.tab_achievements, "achievement",
                                  t("tasks.tab_achievements")),
                                 (self.tab_stats, "stats", t("tasks.tab_stats"))):
            active = self.tab == key
            color = (72, 88, 120) if active else (50, 54, 66)
            pygame.draw.rect(screen, color, rect, border_radius=6)
            pygame.draw.rect(screen, w.ACCENT if active else w.BORDER, rect, 1,
                             border_radius=6)
            w.text(screen, label, rect.center, size=15, centered_in=rect,
                   color=w.TEXT if active else w.TEXT_DIM)

        if self.tab == "stats":
            self._draw_stats(screen)
        else:
            self._draw_tasks(screen, mouse)

        w.button(screen, self.close_button, t("tasks.close"), mouse_pos=mouse, text_size=16)

    def _draw_tasks(self, screen, mouse):
        codes = self._code_list()
        visible_rows = self.list_rect.height // ROW_H
        self.scroll = max(0, min(self.scroll, max(0, len(codes) - visible_rows)))
        for index, code in enumerate(codes[self.scroll:self.scroll + visible_rows]):
            rect = pygame.Rect(self.list_rect.x, self.list_rect.y + index * ROW_H,
                               self.list_rect.width, ROW_H - 4)
            data = TASKS[code]
            current, target = progress(self.game.stats, code)
            done = code in (self.game.tasks or {})
            color = (48, 62, 48) if done else (52, 56, 68)
            if rect.collidepoint(mouse):
                color = tuple(min(255, channel + 16) for channel in color)
            pygame.draw.rect(screen, color, rect, border_radius=5)
            pygame.draw.rect(screen, w.BORDER, rect, 1, border_radius=5)

            title = t(f"task.{code}")
            w.text(screen, title, (rect.x + 12, rect.y + 4), size=16,
                   color=w.GOOD if done else w.TEXT)
            w.text(screen, t(f"task.{code}.desc"), (rect.x + 12, rect.y + 22), size=13,
                   color=w.TEXT_DIM)

            bar = pygame.Rect(rect.right - 340, rect.centery - 7, 150, 14)
            pygame.draw.rect(screen, (40, 44, 54), bar, border_radius=5)
            filled = int(bar.width * (current / max(1, target)))
            pygame.draw.rect(screen, w.GOOD if done else w.ACCENT,
                             (bar.x, bar.y, filled, bar.height), border_radius=5)
            w.text(screen, f"{int(current)}/{target}", bar.center, size=12,
                   centered_in=bar, color=w.TEXT)

            reward = ", ".join(f"{amount}x {t('item.' + item)}"
                               for item, amount in data.get("reward", {}).items())
            w.text(screen, reward, (rect.right - 12 - w.font(13).size(reward)[0],
                                    rect.centery - 8), size=13, color=w.WARN)

    def _draw_stats(self, screen):
        from shared.tasks import STAT_LABELS
        stats = self.game.stats or {}
        y = self.list_rect.y
        shown = sorted(((key, value) for key, value in stats.items() if value),
                       key=lambda entry: -entry[1])
        if not shown:
            w.text(screen, t("tasks.no_stats"), (self.list_rect.x + 12, y), size=15,
                   color=w.TEXT_DIM)
            return
        for key, value in shown:
            label = t(STAT_LABELS.get(key, key))
            w.text(screen, label, (self.list_rect.x + 12, y), size=15)
            text = f"{int(value)}"
            w.text(screen, text, (self.list_rect.right - 12 - w.font(15).size(text)[0], y),
                   size=15, color=w.ACCENT)
            y += 26
