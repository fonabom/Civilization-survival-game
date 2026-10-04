"""Main menu: sign in, sign up, play as guest, settings, controls."""

import random

import pygame

from client.config import Config
from client.i18n import available_languages, language_name, set_language, t
from client.settings import SCREEN_WIDTH, SCREEN_HEIGHT
from client.ui import widgets as w
from client.ui.settings_menu import SettingsMenu

CONTROLS = [
    ("WASD", "control.move"),
    ("1-9 / wheel", "control.hotbar"),
    ("Left click", "control.gather"),
    ("Right click", "control.interact"),
    ("F", "control.interact"),
    ("C / I / V", "control.menus"),
    ("E", "control.gather"),
    ("Enter", "control.chat"),
    ("Tab (hold)", "control.players"),
    ("Esc", "control.pause"),
    ("F11", "control.fullscreen"),
]


class MainMenu:
    def __init__(self, screen, config=None):
        self.screen = screen
        self.config = config or Config()
        set_language(self.config.get("language"))

        self.font_title = w.font(52, bold=True)

        self.active = True
        self.state = "main"                 # main | help
        self.message = ""
        self.message_color = w.BAD
        self.settings_menu = SettingsMenu(config=self.config, on_change=self._settings_changed)

        self.fields = {
            "server": w.TextField((0, 0, 320, 46), t("menu.server_label"),
                                  self.config.get("last_server"),
                                  placeholder=t("menu.server_hint"), max_length=48),
            "login": w.TextField((0, 0, 320, 46), t("menu.login_label"),
                                 self.config.get("last_login"),
                                 placeholder="Player", max_length=16),
            "password": w.TextField((0, 0, 320, 46), t("menu.password_label"), "",
                                    masked=True, max_length=64, placeholder="****"),
            "guest": w.TextField((0, 0, 320, 46), t("menu.name_label"),
                                 self.config.get("guest_name"),
                                 placeholder="Player", max_length=16),
        }
        self.fields["login"].focused = True

        self.particles = [
            [random.randint(0, SCREEN_WIDTH), random.randint(0, SCREEN_HEIGHT),
             random.randint(2, 5), random.randint(2, 6)]
            for _ in range(50)
        ]

        # filled in when the player starts a session; read by main.py
        self.result = {"mode": "guest", "name": "Player", "password": "",
                       "server": self.fields["server"].value}

        self._layout()

    # ------------------------------------------------------------------ layout
    def _layout(self):
        center = SCREEN_WIDTH // 2
        self.fields["server"].rect = pygame.Rect(center - 160, 130, 320, 44)
        self.fields["login"].rect = pygame.Rect(center - 160, 206, 320, 44)
        self.fields["password"].rect = pygame.Rect(center - 160, 278, 320, 44)
        self.fields["guest"].rect = pygame.Rect(center - 160, 350, 320, 44)

        self.btn_login = pygame.Rect(center - 160, 414, 154, 44)
        self.btn_register = pygame.Rect(center + 6, 414, 154, 44)
        self.btn_guest = pygame.Rect(center - 160, 466, 320, 40)
        self.btn_settings = pygame.Rect(center - 160, 514, 154, 38)
        self.btn_help = pygame.Rect(center + 6, 514, 154, 38)
        self.btn_quit = pygame.Rect(center - 160, 558, 320, 34)
        self.btn_language = pygame.Rect(SCREEN_WIDTH - 150, 16, 134, 32)
        self.panel_rect = pygame.Rect(center - 200, 60, 400, 570)

    def _settings_changed(self, kind):
        if kind == "language":
            self._retranslate()
        if self.config.get("fullscreen"):
            pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.FULLSCREEN)
        else:
            pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))

    def _retranslate(self):
        labels = {"server": "menu.server_label", "login": "menu.login_label",
                  "password": "menu.password_label", "guest": "menu.name_label"}
        placeholders = {"server": "menu.server_hint", "guest": "Player"}
        for key, field in self.fields.items():
            field.label = t(labels[key])
            if key in placeholders:
                field.placeholder = placeholders[key]

    # ------------------------------------------------------------------ helpers
    def _validate(self, mode: str) -> bool:
        login = self.fields["login"].value.strip()
        password = self.fields["password"].value
        if mode in ("login", "register"):
            if not (3 <= len(login) <= 16) or not all(ch.isalnum() or ch == "_" for ch in login):
                self._error(t("menu.error_fill_login"))
                return False
            if len(password) < 4:
                self._error(t("menu.error_fill_password"))
                return False
        return True

    def _error(self, message):
        self.message = message
        self.message_color = w.BAD

    def _start(self, mode: str):
        if mode != "guest" and not self._validate(mode):
            return
        server = self.fields["server"].value.strip() or "127.0.0.1:5555"
        name = self.fields["login"].value.strip() if mode != "guest" else \
            (self.fields["guest"].value.strip() or "Player")
        self.result = {"mode": mode, "name": name, "password": self.fields["password"].value,
                       "server": server}
        self.config.set("last_server", server)
        if mode != "guest":
            self.config.set("last_login", name if self.config.get("remember_login") else "")
        else:
            self.config.set("guest_name", name)
        self.config.save()
        self.active = False

    # ------------------------------------------------------------------- events
    def handle_event(self, event):
        if self.settings_menu.handle_event(event):
            self.message = ""
            return

        if self.state == "help":
            if event.type in (pygame.KEYDOWN, pygame.MOUSEBUTTONDOWN):
                self.state = "main"
            return

        for field in self.fields.values():
            field.handle_event(event)

        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self.quit_game()
            elif event.key == pygame.K_RETURN:
                self._start("login" if self.fields["login"].value else "guest")
            elif event.key == pygame.K_F1:
                self.state = "help"
            elif event.key == pygame.K_F2:
                self._cycle_language()

        elif event.type == pygame.MOUSEBUTTONDOWN:
            if self.btn_language.collidepoint(event.pos):
                self._cycle_language()
            elif self.btn_login.collidepoint(event.pos):
                self._start("login")
            elif self.btn_register.collidepoint(event.pos):
                self._start("register")
            elif self.btn_guest.collidepoint(event.pos):
                self._start("guest")
            elif self.btn_settings.collidepoint(event.pos):
                self.settings_menu.open()
            elif self.btn_help.collidepoint(event.pos):
                self.state = "help"
            elif self.btn_quit.collidepoint(event.pos):
                self.quit_game()

    def _cycle_language(self):
        languages = available_languages()
        current = self.config.get("language")
        index = languages.index(current) if current in languages else -1
        language = languages[(index + 1) % len(languages)]
        self.config.set("language", language)
        self.config.save()
        set_language(language)
        self._retranslate()
        self.message = t("settings.saved")
        self.message_color = w.GOOD

    def quit_game(self):
        pygame.quit()
        raise SystemExit(0)

    # -------------------------------------------------------------------- draw
    def draw_background(self):
        self.screen.fill((10, 14, 26))
        for particle in self.particles:
            particle[1] += particle[2]
            if particle[1] > SCREEN_HEIGHT:
                particle[1] = -10
                particle[0] = random.randint(0, SCREEN_WIDTH)
            surface = pygame.Surface((particle[3], particle[3]), pygame.SRCALPHA)
            pygame.draw.circle(surface, (90, 140, 200, 140),
                               (particle[3] // 2, particle[3] // 2), particle[3] // 2)
            self.screen.blit(surface, (particle[0], particle[1]))

    def draw(self):
        self.draw_background()
        if self.state == "help":
            self._draw_help()
            return

        title = self.font_title.render(t("app.title"), True, (255, 215, 0))
        shadow = self.font_title.render(t("app.title"), True, (0, 0, 0))
        self.screen.blit(shadow, (SCREEN_WIDTH // 2 - title.get_width() // 2 + 3, 23))
        self.screen.blit(title, (SCREEN_WIDTH // 2 - title.get_width() // 2, 20))

        subtitle = w.font(18).render(t("menu.auth_hint"), True, w.TEXT_DIM)
        self.screen.blit(subtitle, (SCREEN_WIDTH // 2 - subtitle.get_width() // 2, 74))

        for field in self.fields.values():
            field.update()
            field.draw(self.screen)

        mouse = pygame.mouse.get_pos()
        w.button(self.screen, self.btn_login, t("menu.login"),
                 base_color=(50, 110, 60), hover_color=(65, 145, 78), mouse_pos=mouse)
        w.button(self.screen, self.btn_register, t("menu.register"),
                 base_color=(60, 80, 140), hover_color=(75, 100, 175), mouse_pos=mouse)
        w.button(self.screen, self.btn_guest, t("menu.guest"),
                 base_color=(70, 70, 90), hover_color=(90, 90, 115), mouse_pos=mouse,
                 text_size=17)
        w.button(self.screen, self.btn_settings, t("menu.settings"),
                 mouse_pos=mouse, text_size=16)
        w.button(self.screen, self.btn_help, t("menu.help"),
                 mouse_pos=mouse, text_size=16)
        w.button(self.screen, self.btn_quit, t("menu.quit"),
                 base_color=(105, 55, 55), hover_color=(140, 70, 70), mouse_pos=mouse,
                 text_size=16)

        language = language_name(self.config.get("language"))
        w.button(self.screen, self.btn_language, f"🌐 {language}",
                 base_color=(45, 48, 62), hover_color=(60, 64, 82), mouse_pos=mouse,
                 text_size=15)

        build = w.font(14).render(t("app.build", build=self._build()), True, w.TEXT_DIM)
        self.screen.blit(build, (14, SCREEN_HEIGHT - 24))

        if self.message:
            color = self.message_color
            label = w.font(16).render(self.message, True, color)
            self.screen.blit(label, (SCREEN_WIDTH // 2 - label.get_width() // 2, 600))
        else:
            hint = w.font(15).render(t("menu.tip_host"), True, w.TEXT_DIM)
            self.screen.blit(hint, (SCREEN_WIDTH // 2 - hint.get_width() // 2, 602))

        self.settings_menu.draw(self.screen)

    def _build(self):
        try:
            from shared.build import BUILD
            return BUILD
        except Exception:
            return "b?"

    def _draw_help(self):
        panel = pygame.Rect(SCREEN_WIDTH // 2 - 260, 70, 520, 560)
        top = w.panel(self.screen, panel, t("menu.controls_title"))
        y = top + 6
        for keys, key in CONTROLS:
            w.text(self.screen, keys, (panel.x + 24, y), size=17, color=w.ACCENT)
            w.text(self.screen, t(key), (panel.x + 200, y), size=17)
            y += 28
        y += 8
        w.text(self.screen, t("menu.tip_host"), (panel.x + 24, y), size=15, color=w.TEXT_DIM)
        w.text(self.screen, t("menu.tip_tab"), (panel.x + 24, y + 22), size=15, color=w.TEXT_DIM)
        w.text(self.screen, t("menu.controls_hint"),
               (panel.centerx, panel.bottom - 34), size=15, color=w.TEXT_DIM,
               centered_in=pygame.Rect(panel.x, panel.bottom - 44, panel.width, 20))
