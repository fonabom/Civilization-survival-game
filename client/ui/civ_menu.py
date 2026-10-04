"""Civilisation screen: cities on the left, countries on the right.

b10 «Цивилизация» adds a details strip at the bottom of the panel: the selected
city shows the health of its town centre, its fund, the tax rate and the roles
of its members. The leader sets the tax with -/+ and gives roles by clicking a
member chip (clicking cycles elder -> builder -> warrior -> citizen).

    left click a city   - join it / show its details
    right click a city  - show its details
    left click country  - join it
    right click country - pick it as the diplomacy target
"""

import pygame

from client.i18n import t
from client.settings import SCREEN_HEIGHT, SCREEN_WIDTH
from client.ui import widgets as w
from shared.roles import MAX_TAX, ROLE_ORDER

PANEL = pygame.Rect(0, 0, 900, 660)
ROWS = 6
ROW_H = 32
MEMBER_W = 150
TAX_STEP = 5

# Roles the leader cycles through by clicking a member chip
ROLE_CYCLE = ["citizen", "builder", "elder", "warrior"]
ROLE_LABELS = list(ROLE_ORDER)


def clip(screen, value, size, max_width):
    """Shorten a line so it fits into the space the layout gives it."""
    font = w.font(size)
    if font.size(value)[0] <= max_width:
        return value
    while value and font.size(value + "…")[0] > max_width:
        value = value[:-1]
    return value + "…"


class CivMenu:
    def __init__(self, game):
        self.game = game
        self.visible = False
        self.panel = PANEL.copy()
        self.panel.center = (SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2)
        self.input_text = ""
        self.active_input = None          # None | "city" | "country"
        self.target = ""                  # diplomacy target (country)
        self.city_target = ""             # city shown in the details strip
        self.member_rects = []            # (rect, player_id) of the visible chips
        self._layout()

    def _layout(self):
        top = self.panel.y
        self.city_input = pygame.Rect(self.panel.x + 24, top + 64, 250, 34)
        self.city_ok = pygame.Rect(self.city_input.right + 8, top + 64, 60, 34)
        self.country_input = pygame.Rect(self.panel.x + 480, top + 64, 250, 34)
        self.country_ok = pygame.Rect(self.country_input.right + 8, top + 64, 60, 34)
        self.list_top = top + 150
        self.city_rows = [pygame.Rect(self.panel.x + 24, self.list_top + index * ROW_H,
                                      376, ROW_H - 4) for index in range(ROWS)]
        self.country_rows = [pygame.Rect(self.panel.x + 480, self.list_top + index * ROW_H,
                                         366, ROW_H - 4) for index in range(ROWS)]
        # b10: details of the selected city (fund, tax, roles)
        strip_h = 136
        self.strip = pygame.Rect(self.panel.x + 24, self.list_top + ROWS * ROW_H + 14,
                                 self.panel.width - 48, strip_h)
        self.tax_minus = pygame.Rect(self.strip.right - 96, self.strip.y + 30, 30, 26)
        self.tax_plus = pygame.Rect(self.strip.right - 58, self.strip.y + 30, 30, 26)
        # diplomacy (b9): pick a country with the right mouse button, then act
        self.diplomacy = {
            "war": pygame.Rect(self.panel.x + 480, self.strip.bottom + 34, 96, 32),
            "peace": pygame.Rect(self.panel.x + 584, self.strip.bottom + 34, 96, 32),
            "ally": pygame.Rect(self.panel.x + 688, self.strip.bottom + 34, 96, 32),
        }
        self.close_button = pygame.Rect(self.panel.right - 134, self.panel.bottom - 50,
                                        110, 34)

    # -------------------------------------------------------------------- state
    def _civ_state(self):
        return getattr(self.game, "civ_state", {}) or {}

    def _cities(self):
        return list((self._civ_state().get("cities") or {}).items())[:ROWS]

    def _countries(self):
        return list((self._civ_state().get("countries") or {}).items())[:ROWS]

    def _my_country(self):
        player_id = self.game.my_id
        for name, data in (self._civ_state().get("countries") or {}).items():
            if data.get("leader") == player_id or \
                    player_id in [str(member) for member in data.get("members", [])]:
                return name, data
        return None, None

    def _city_data(self):
        civ_state = self._civ_state()
        name = self.city_target
        if not name or name not in (civ_state.get("cities") or {}):
            cities = civ_state.get("cities") or {}
            my_id = self.game.my_id
            name = next((key for key, data in cities.items()
                         if data.get("leader") == my_id or
                         str(my_id) in [str(m) for m in data.get("members", [])]), "")
            self.city_target = name
        return (civ_state.get("cities") or {}).get(name)

    def _member_name(self, pid):
        player = self.game.players.get(pid)
        if player is not None and getattr(player, "name", ""):
            return player.name
        return str(pid)

    # -------------------------------------------------------------------- input
    def toggle(self):
        self.visible = not self.visible
        self.active_input = None
        self.input_text = ""
        if not self.visible:
            self.target = ""
            self.city_target = ""

    def handle_input(self, event):
        if not self.visible or not self.active_input:
            return
        if event.key == pygame.K_RETURN:
            self._submit()
        elif event.key == pygame.K_ESCAPE:
            self.active_input = None
            self.input_text = ""
        elif event.key == pygame.K_BACKSPACE:
            self.input_text = self.input_text[:-1]
        elif getattr(event, "unicode", "") and event.unicode.isprintable() \
                and len(self.input_text) < 24:
            self.input_text += event.unicode

    def _submit(self):
        value = self.input_text.strip()
        if value and self.active_input == "city":
            self.game.net.send_dict({"type": "create_city", "name": value})
        elif value and self.active_input == "country":
            self.game.net.send_dict({"type": "create_country", "name": value})
        self.input_text = ""
        self.active_input = None

    def handle_click(self, event):
        if not self.visible:
            return
        pos = event.pos
        if self.close_button.collidepoint(pos):
            self.visible = False
            return
        if self.city_input.collidepoint(pos):
            self.active_input = "city"
            self.input_text = ""
            return
        if self.country_input.collidepoint(pos):
            self.active_input = "country"
            self.input_text = ""
            return
        if self.city_ok.collidepoint(pos):
            self.active_input = self.active_input or "city"
            self._submit()
            return
        if self.country_ok.collidepoint(pos):
            self.active_input = self.active_input or "country"
            self._submit()
            return

        for rect, (name, _data) in zip(self.city_rows, self._cities()):
            if rect.collidepoint(pos):
                self.city_target = name
                if event.button != 3:                    # left click: try to join
                    self.game.net.send_dict({"type": "join_city", "name": name})
                return
        for rect, (name, _data) in zip(self.country_rows, self._countries()):
            if rect.collidepoint(pos):
                if event.button == 3:                    # right click picks a target
                    self.target = name
                else:
                    self.game.net.send_dict({"type": "join_country", "country": name})
                return

        for action, rect in self.diplomacy.items():
            if rect.collidepoint(pos):
                if not self.target:
                    self.game.notify(t("civ.pick_target"), w.WARN)
                    return
                self.game.net.send_dict({"type": "diplomacy", "action": action,
                                         "target": self.target})
                return

        city = self._city_data()
        if city is None:
            return
        if self.tax_minus.collidepoint(pos) or self.tax_plus.collidepoint(pos):
            if city.get("leader") != self.game.my_id:
                self.game.notify(t("civ.only_leader_tax"), w.WARN)
                return
            step = TAX_STEP if self.tax_plus.collidepoint(pos) else -TAX_STEP
            value = max(0, min(MAX_TAX, int(city.get("tax", 0)) + step))
            self.game.net.send_dict({"type": "set_tax", "value": value})
            return

        # member chips: the leader cycles the role of the clicked member
        for rect, pid in self.member_rects:
            if rect.collidepoint(pos):
                if city.get("leader") != self.game.my_id:
                    self.game.notify(t("civ.only_leader_roles"), w.WARN)
                    return
                current = self._role_of(city, pid)
                if current not in ROLE_CYCLE:
                    return
                role = ROLE_CYCLE[(ROLE_CYCLE.index(current) + 1) % len(ROLE_CYCLE)]
                self.game.net.send_dict({"type": "set_role",
                                         "target": self._member_name(pid),
                                         "role": role})
                return

    def _role_of(self, city, pid):
        if pid == city.get("leader"):
            return "leader"
        return (city.get("roles") or {}).get(str(pid), "citizen")

    # --------------------------------------------------------------------- draw
    def draw(self, screen):
        if not self.visible:
            return
        overlay = pygame.Surface(screen.get_size(), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 110))
        screen.blit(overlay, (0, 0))
        w.panel(screen, self.panel, t("civ.title"))
        mouse_pos = pygame.mouse.get_pos()
        player_id = self.game.my_id

        self._draw_field(screen, self.city_input, self.city_ok, "city",
                         t("civ.city_placeholder"), t("civ.found_city"))
        self._draw_field(screen, self.country_input, self.country_ok, "country",
                         t("civ.country_placeholder"), t("civ.found_country"))

        w.text(screen, t("civ.cities"), (self.city_rows[0].x, self.city_rows[0].y - 26),
               size=17, color=(255, 215, 0), bold=True)
        cities = self._cities()
        if not cities:
            w.text(screen, t("civ.empty_cities"), (self.city_rows[0].x, self.city_rows[0].y),
                   size=15, color=w.TEXT_DIM)
        for rect, (name, data) in zip(self.city_rows, cities):
            members = data.get("members", [])
            mine = player_id in [str(member) for member in members] or \
                data.get("leader") == player_id
            info = t("civ.members", n=len(members))
            if mine:
                info += "  ·  " + t("civ.yours")
            self._row(screen, rect, name, info, mouse_pos,
                      highlight=data.get("leader") == player_id,
                      selected=name == self.city_target)

        w.text(screen, t("civ.countries"), (self.country_rows[0].x,
                                            self.country_rows[0].y - 26),
               size=17, color=(255, 215, 0), bold=True)
        countries = self._countries()
        if not countries:
            w.text(screen, t("civ.empty_countries"), (self.country_rows[0].x,
                                                      self.country_rows[0].y),
                   size=15, color=w.TEXT_DIM)
        _my_name, my_country = self._my_country()
        for rect, (name, data) in zip(self.country_rows, countries):
            info = t("age." + data.get("age", "stone"))
            if my_country is not None and data is not my_country:
                if name in (my_country.get("wars") or []):
                    info = t("civ.at_war") + "  " + info
                elif name in (my_country.get("allies") or []):
                    info = t("civ.ally") + "  " + info
            self._row(screen, rect, name, info, mouse_pos,
                      highlight=data.get("leader") == player_id,
                      selected=name == self.target)

        self._draw_city_strip(screen, mouse_pos)

        w.text(screen, t("civ.diplomacy_target", country=self.target or "-"),
               (self.panel.x + 480, self.strip.bottom + 12), size=14, color=w.TEXT_DIM)
        for action, rect in self.diplomacy.items():
            w.button(screen, rect, t(f"civ.{action}"), mouse_pos=mouse_pos, text_size=15)
        w.text(screen, t("civ.hint_pick"), (self.panel.x + 480, self.strip.bottom + 72),
               size=13, color=w.TEXT_DIM)

        w.text(screen, t("civ.hint_city"), (self.panel.x + 24, self.strip.bottom + 42),
               size=14, color=w.TEXT_DIM)
        w.text(screen, t("civ.hint_country"), (self.panel.x + 24, self.strip.bottom + 60),
               size=14, color=w.TEXT_DIM)
        w.button(screen, self.close_button, t("research.close"), mouse_pos=mouse_pos,
                 text_size=16)

    def _draw_city_strip(self, screen, mouse_pos):
        """Details of the selected city: HP, fund, tax and the member roles."""
        pygame.draw.rect(screen, (36, 39, 48), self.strip, border_radius=6)
        pygame.draw.rect(screen, w.BORDER, self.strip, 1, border_radius=6)
        self.member_rects = []
        data = self._city_data()
        if data is None:
            w.text(screen, t("civ.select_city"), self.strip.center, size=15,
                   centered_in=self.strip, color=w.TEXT_DIM)
            self.member_rects = []
            return

        inner = self.strip.width - 24
        name = self.city_target
        head = f"{name}  ·  {t('civ.tier')} {data.get('tier', 1)}"
        hp_text = self._city_hp_text(name)
        if hp_text:
            head += f"  ·  {hp_text}"
        if data.get("captured"):
            head += f"  ·  {t('civ.captured', n=data.get('captured'))}"
        w.text(screen, clip(screen, head, 16, inner), (self.strip.x + 12, self.strip.y + 10),
               size=16, bold=True)

        tax_x = self.strip.x + 520
        storage = data.get("storage") or {}
        fund = ", ".join(f"{item} {amount}" for item, amount in sorted(storage.items())
                         if amount) or t("civ.fund_empty")
        w.text(screen, clip(screen, f"{t('civ.fund')}: {fund}", 15, tax_x - self.strip.x - 24),
               (self.strip.x + 12, self.strip.y + 34), size=15, color=w.TEXT_DIM)

        leader = data.get("leader") == self.game.my_id
        tax = int(data.get("tax", 0))
        label = t("civ.tax", n=tax) if tax else t("civ.tax_off")
        w.text(screen, label, (tax_x, self.strip.y + 35), size=15,
               color=w.GOOD if tax else w.TEXT_DIM)
        if leader:
            w.button(screen, self.tax_minus, "-", mouse_pos=mouse_pos, text_size=15)
            w.button(screen, self.tax_plus, "+", mouse_pos=mouse_pos, text_size=15)

        members = list(data.get("members", []))[:6]
        for index, pid in enumerate(members):
            rect = pygame.Rect(self.strip.x + 12 + (index % 3) * (MEMBER_W + 8),
                               self.strip.y + 62 + (index // 3) * 24, MEMBER_W, 20)
            self.member_rects.append((rect, pid))
            role = self._role_of(data, pid)
            mine = pid == self.game.my_id
            color = w.ACCENT if mine else w.TEXT
            pygame.draw.rect(screen, (52, 62, 82) if mine else (48, 52, 64), rect,
                             border_radius=4)
            w.text(screen, clip(screen, f"{self._member_name(pid)}: {t('role.' + role)}",
                                14, rect.width - 16),
                   (rect.x + 8, rect.y + 3), size=14, color=color)
        if members:
            hint = t("civ.role_hint") if leader else t("civ.only_leader_roles")
            w.text(screen, hint, (self.strip.x + 12, self.strip.bottom - 18), size=13,
                   color=w.TEXT_DIM)

    def _city_hp_text(self, name):
        """Health of the city's town centre, read from the buildings we know."""
        data = (self._civ_state().get("cities") or {}).get(name)
        if data is None:
            return ""
        for building in (getattr(self.game.world, "buildings", {}) or {}).values():
            if building.get("type") != "town_center":
                continue
            if building.get("owner") == data.get("leader"):
                return f"{int(building.get('hp', 0))}/{int(building.get('max_hp', 0))} HP"
        return ""

    def _draw_field(self, screen, rect, ok_rect, mode, placeholder, action_label):
        active = self.active_input == mode
        pygame.draw.rect(screen, (26, 28, 36), rect, border_radius=5)
        pygame.draw.rect(screen, w.GOOD if active else w.BORDER, rect, 2 if active else 1,
                         border_radius=5)
        value = self.input_text if active else ""
        w.text(screen, clip(screen, value or placeholder, 16, rect.width - 20),
               (rect.x + 10, rect.centery - 9), size=16,
               color=w.TEXT if value else w.TEXT_DIM)
        mouse_pos = pygame.mouse.get_pos()
        hover = ok_rect.collidepoint(mouse_pos)
        w.button(screen, ok_rect, "OK",
                 base_color=(65, 150, 75) if hover else (50, 120, 60),
                 mouse_pos=mouse_pos, text_size=16)
        w.text(screen, action_label, (rect.x, rect.y - 22), size=14, color=w.TEXT_DIM)

    def _row(self, screen, rect, name, info, mouse_pos, highlight=False, selected=False):
        """One list row: name on the left, details right-aligned before the hint."""
        hover = rect.collidepoint(mouse_pos)
        color = (70, 78, 104) if highlight else ((54, 58, 74) if hover else (44, 47, 58))
        if selected:
            color = (96, 84, 56)
        pygame.draw.rect(screen, color, rect, border_radius=4)
        pygame.draw.rect(screen, w.BORDER, rect, 1, border_radius=4)
        hint = w.font(14).render(t("civ.join"), True, w.ACCENT)
        screen.blit(hint, (rect.right - 10 - hint.get_width(),
                           rect.centery - hint.get_height() // 2))
        name_x = rect.x + 10
        name_width = w.font(16).size(name)[0]
        w.text(screen, clip(screen, name, 16, rect.width - 150), (name_x, rect.centery - 9),
               size=16)
        info_width = rect.right - 18 - hint.get_width() - (name_x + name_width)
        if info_width > 40:
            w.text(screen, clip(screen, info, 13, info_width),
                   (name_x + name_width + 14, rect.centery - 8), size=13, color=w.TEXT_DIM)
