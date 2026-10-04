"""Small reusable UI widgets.

Everything is drawn with plain pygame primitives so the game keeps working
without fonts or images from the internet, and every label goes through i18n.
"""

import pygame

from client.i18n import t

# Shared palette
BG = (30, 32, 42)
BG_DARK = (20, 22, 30)
BORDER = (120, 130, 160)
BORDER_LIGHT = (200, 210, 235)
TEXT = (238, 240, 248)
TEXT_DIM = (150, 158, 178)
ACCENT = (90, 170, 255)
GOOD = (76, 175, 96)
BAD = (200, 80, 80)
WARN = (230, 180, 70)
PANEL_ALPHA = 236


def font(size: int, bold: bool = False):
    return pygame.font.SysFont("Arial", size, bold=bold)


def panel(screen, rect, title=None, subtitle=None, alpha=PANEL_ALPHA):
    surface = pygame.Surface(rect.size, pygame.SRCALPHA)
    surface.fill((*BG, alpha))
    screen.blit(surface, rect.topleft)
    pygame.draw.rect(screen, BORDER, rect, 2, border_radius=8)
    top = rect.y + 12
    if title:
        label = font(22, bold=True).render(title, True, TEXT)
        screen.blit(label, (rect.x + 16, top))
        top += 30
    if subtitle:
        label = font(15).render(subtitle, True, TEXT_DIM)
        screen.blit(label, (rect.x + 16, top))
        top += 22
    return top + (6 if title or subtitle else 0)


def button(screen, rect, label, base_color=(60, 70, 100), hover_color=(80, 95, 140),
           enabled=True, text_color=TEXT, text_size=18, radius=6, mouse_pos=None):
    mouse_pos = mouse_pos or pygame.mouse.get_pos()
    hover = enabled and rect.collidepoint(mouse_pos)
    color = hover_color if hover else base_color
    if not enabled:
        color = (55, 58, 66)
        text_color = (120, 124, 132)
    pygame.draw.rect(screen, color, rect, border_radius=radius)
    pygame.draw.rect(screen, BORDER if enabled else (80, 82, 90), rect, 1, border_radius=radius)
    text = font(text_size).render(label, True, text_color)
    screen.blit(text, (rect.centerx - text.get_width() // 2,
                       rect.centery - text.get_height() // 2))
    return rect


def toggle(screen, rect, label, value, mouse_pos=None):
    """Draw a checkbox-style row. Returns the rect."""
    mouse_pos = mouse_pos or pygame.mouse.get_pos()
    hover = rect.collidepoint(mouse_pos)
    box = pygame.Rect(rect.x, rect.centery - 10, 20, 20)
    pygame.draw.rect(screen, (45, 48, 60) if not hover else (58, 62, 78), box, border_radius=4)
    pygame.draw.rect(screen, BORDER, box, 1, border_radius=4)
    if value:
        pygame.draw.rect(screen, GOOD, box.inflate(-8, -8), border_radius=2)
    screen.blit(font(17).render(label, True, TEXT), (rect.x + 32, rect.centery - 10))
    return rect


class TextField:
    """Single line input with optional masking (passwords) and max length."""

    def __init__(self, rect, label="", value="", masked=False, max_length=64,
                 placeholder=""):
        self.rect = pygame.Rect(rect)
        self.label = label
        self.value = value
        self.masked = masked
        self.max_length = max_length
        self.placeholder = placeholder
        self.focused = False
        self.cursor_blink = 0

    # ------------------------------------------------------------------ events
    def handle_event(self, event) -> bool:
        """Returns True when the value changed."""
        if event.type == pygame.MOUSEBUTTONDOWN:
            if self.rect.collidepoint(event.pos):
                self.focused = True
            elif self.focused:
                self.focused = False
            return False
        if event.type != pygame.KEYDOWN or not self.focused:
            return False
        if event.key == pygame.K_BACKSPACE:
            self.value = self.value[:-1]
            return True
        if event.key in (pygame.K_RETURN, pygame.K_TAB, pygame.K_ESCAPE):
            return False
        char = getattr(event, "unicode", "")
        if char and char.isprintable() and len(self.value) < self.max_length:
            self.value += char
            return True
        return False

    def update(self, dt_ms=16):
        self.cursor_blink = (self.cursor_blink + dt_ms) % 1000

    @property
    def display(self) -> str:
        if self.masked:
            return "*" * len(self.value)
        return self.value

    # -------------------------------------------------------------------- draw
    def draw(self, screen):
        if self.label:
            screen.blit(font(15).render(self.label, True, TEXT_DIM),
                        (self.rect.x, self.rect.y - 20))
        pygame.draw.rect(screen, BG_DARK, self.rect, border_radius=5)
        border = ACCENT if self.focused else BORDER
        pygame.draw.rect(screen, border, self.rect, 2 if self.focused else 1, border_radius=5)
        text = self.display
        color = TEXT if text else (110, 116, 136)
        shown = text if text else self.placeholder
        screen.blit(font(19).render(shown, True, color),
                    (self.rect.x + 10, self.rect.centery - 11))
        if self.focused and self.cursor_blink < 500:
            caret = self.rect.x + 12 + font(19).size(text)[0]
            pygame.draw.line(screen, TEXT, (caret, self.rect.y + 7),
                             (caret, self.rect.bottom - 7), 2)


def tooltip(screen, text, pos):
    label = font(15).render(text, True, TEXT)
    rect = pygame.Rect(0, 0, label.get_width() + 16, label.get_height() + 10)
    rect.topleft = (pos[0] + 14, pos[1] + 14)
    screen.blit(pygame.Surface(rect.size, pygame.SRCALPHA).convert_alpha(), rect.topleft)
    surface = pygame.Surface(rect.size, pygame.SRCALPHA)
    surface.fill((*BG_DARK, 240))
    screen.blit(surface, rect.topleft)
    pygame.draw.rect(screen, BORDER, rect, 1, border_radius=5)
    screen.blit(label, (rect.x + 8, rect.y + 5))


def scrollbar(screen, rect, offset, content_height, view_height):
    """Simple vertical scrollbar; returns nothing, drawn only when needed."""
    if content_height <= view_height:
        return
    track = pygame.Rect(rect.right - 8, rect.y, 6, rect.height)
    pygame.draw.rect(screen, (45, 48, 60), track, border_radius=3)
    ratio = max(0.1, view_height / content_height)
    height = int(track.height * ratio)
    top = track.y + int((track.height - height) * (offset / max(1, content_height - view_height)))
    pygame.draw.rect(screen, BORDER, (track.x, top, 6, height), border_radius=3)


def text(screen, value, pos, size=16, color=TEXT, bold=False, centered_in=None):
    label = font(size, bold).render(value, True, color)
    if centered_in is not None:
        screen.blit(label, (centered_in.centerx - label.get_width() // 2,
                            centered_in.centery - label.get_height() // 2))
    else:
        screen.blit(label, pos)
    return label


def slot(screen, rect, item=None, count=0, resources=None, hover=False, selected=False,
         durability=None):
    """One inventory/chest slot with the item icon, amount and wear bar."""
    base = (58, 63, 78) if hover else (46, 50, 62)
    if selected:
        base = (72, 88, 120)
    pygame.draw.rect(screen, base, rect, border_radius=6)
    pygame.draw.rect(screen, ACCENT if selected else BORDER, rect, 2 if selected else 1,
                     border_radius=6)
    if not item:
        return
    icon = resources.get(item) if resources is not None else None
    if icon is not None:
        size = min(rect.width, rect.height) - 14
        screen.blit(pygame.transform.smoothscale(icon, (size, size)),
                    (rect.centerx - size // 2, rect.centery - size // 2 - 2))
    else:
        text(screen, str(item)[:2].upper(), rect.center, size=16, centered_in=rect)
    if count:
        label = font(13).render(f"{count}", True, TEXT)
        screen.blit(label, (rect.right - label.get_width() - 5,
                            rect.bottom - label.get_height() - 3))
    if durability is not None and 0 <= durability < 1:
        bar = pygame.Rect(rect.x + 5, rect.bottom - 7, rect.width - 10, 4)
        pygame.draw.rect(screen, (60, 30, 30), bar, border_radius=2)
        color = GOOD if durability > 0.5 else (WARN if durability > 0.2 else BAD)
        pygame.draw.rect(screen, color, (bar.x, bar.y, int(bar.width * durability),
                                         bar.height), border_radius=2)


def format_cost(cost: dict, inventory: dict = None) -> str:
    """'wood 2, stone 3' with the missing parts marked by '!'."""
    parts = []
    for resource, amount in cost.items():
        label = t("item." + resource) if t("item." + resource) != "item." + resource else resource
        if inventory is not None and inventory.get(resource, 0) < amount:
            parts.append(f"!{label} {amount}")
        else:
            parts.append(f"{label} {amount}")
    return ", ".join(parts) if parts else t("craft.free")
