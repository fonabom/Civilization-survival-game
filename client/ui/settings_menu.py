"""Settings screen: language, resource pack, fullscreen, debug, hotbar.

Usable both from the main menu and from the in-game pause menu; every change is
written to config.json immediately.
"""

import pygame

from client.config import HOTBAR_SIZE
from client.i18n import available_languages, language_name, set_language, t
from client.resources import discover_packs
from client.ui import widgets as w

PANEL = pygame.Rect(0, 0, 720, 520)


class SettingsMenu:
    def __init__(self, game=None, config=None, on_change=None):
        self.game = game
        self.config = config
        self.on_change = on_change
        self.visible = False
        self.panel = PANEL.copy()
        self.scroll = 0
        self.message = ""
        self.message_timer = 0
        self._layout()

    # ------------------------------------------------------------------ layout
    def _layout(self):
        self.panel.center = (self.screen_size()[0] // 2, self.screen_size()[1] // 2)
        self.panel.height = min(560, self.screen_size()[1] - 80)
        self.panel.width = min(720, self.screen_size()[0] - 60)
        self.langs = available_languages()
        self.packs = list(discover_packs().keys())
        self.rows = []
        row_h = 44
        # two columns: the screen does not get taller than the window (b13)
        left_x = self.panel.x + 24
        column_w = (self.panel.width - 60) // 2
        right_x = self.panel.x + self.panel.width - 24 - column_w
        order = ("language", "pack", "fullscreen", "debug", "remember",
                 "sound", "volume", "music", "music_volume", "tutorial", "quiet")
        for index, kind in enumerate(order):
            column = 0 if index < 5 else 1
            row = index % 5
            x = left_x if column == 0 else right_x
            y = self.panel.y + 90 + row * (row_h + 8)
            self.rows.append((kind, pygame.Rect(x, y, column_w, row_h)))
        y = self.panel.y + 90 + 5 * (row_h + 8) + 14
        # b13: rebinding and the onboarding reset
        self.keys_button = pygame.Rect(left_x, y, column_w, 40)
        self.quests_button = pygame.Rect(right_x, y, column_w, 40)
        y += 52
        self.hotbar_reset = pygame.Rect(left_x, y, column_w, 40)
        self.reset_button = pygame.Rect(right_x, y, column_w, 40)
        self.back_button = pygame.Rect(self.panel.right - 180, self.panel.bottom - 60, 150, 44)

    def screen_size(self):
        if self.game is not None:
            return self.game.screen.get_size()
        return (1280, 720)

    # ------------------------------------------------------------------- input
    def open(self):
        self.visible = True
        self._layout()

    def close(self):
        self.visible = False
        if self.config:
            self.config.save()

    def handle_event(self, event) -> bool:
        """Returns True when the event was consumed."""
        if not self.visible:
            return False
        if event.type == pygame.MOUSEBUTTONDOWN:
            if self.back_button.collidepoint(event.pos):
                self.close()
                return True
            if self.reset_button.collidepoint(event.pos):
                self.config.data.update({"language": "en", "resource_pack": "default",
                                         "fullscreen": False, "show_debug": True,
                                         "remember_login": True, "sound": True,
                                         "sound_volume": 0.7, "music": True,
                                         "music_volume": 0.45, "tutorial": True,
                                         "inventory_sort": "category", "chat_channel": "global"})
                if self.game is not None:
                    self.game.keys.reset()
                    self.game.inventory_sort = "category"
                    self.game.chat_channel = "global"
                set_language("en")
                self._changed("reset")
                return True
            if getattr(self, "keys_button", None) is not None and \
                    self.keys_button.collidepoint(event.pos):
                if self.game is not None:
                    self.game.keys_menu.open()
                return True
            if getattr(self, "quests_button", None) is not None and \
                    self.quests_button.collidepoint(event.pos):
                if self.game is not None:
                    self.game.onboarding.reset()
                    self.game.notify(t("quest.reset_done"), w.WARN)
                    self._changed("onboarding")
                return True
            if self.hotbar_reset.collidepoint(event.pos):
                self.config.set("hotbar", [None] * HOTBAR_SIZE)
                self._changed("hotbar")
                return True
            for kind, rect in self.rows:
                if rect.collidepoint(event.pos):
                    self._cycle(kind)
                    return True
        elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self.close()
            return True
        return False

    def _cycle(self, kind):
        if kind == "language":
            current = self.config.get("language")
            index = self.langs.index(current) if current in self.langs else -1
            language = self.langs[(index + 1) % len(self.langs)]
            self.config.set("language", language)
            set_language(language)
            self._changed("language")
        elif kind == "pack":
            packs = self.packs or ["default"]
            current = self.config.get("resource_pack")
            index = packs.index(current) if current in packs else -1
            pack = packs[(index + 1) % len(packs)]
            self.config.set("resource_pack", pack)
            if self.game is not None and getattr(self.game, "resources", None):
                self.game.resources.reload(pack)
                self.game.world.set_textures(self.game.resources)
            self._changed("pack")
        elif kind == "fullscreen":
            value = not self.config.get("fullscreen")
            self.config.set("fullscreen", value)
            if self.game is not None:
                self.game.apply_display_settings()
            self._changed("fullscreen")
        elif kind == "debug":
            self.config.set("show_debug", not self.config.get("show_debug"))
            self._changed("debug")
        elif kind == "remember":
            self.config.set("remember_login", not self.config.get("remember_login"))
            self._changed("remember")
        elif kind == "sound":
            value = not self.config.get("sound", True)
            self.config.set("sound", value)
            if self.game is not None and getattr(self.game, "audio", None):
                self.game.audio.enabled = value
                if value:
                    self.game.audio.play("pickup")
            self._changed("sound")
        elif kind == "volume":
            steps = [0.0, 0.25, 0.5, 0.7, 0.85, 1.0]
            current = float(self.config.get("sound_volume", 0.7))
            index = min(range(len(steps)), key=lambda i: abs(steps[i] - current))
            volume = steps[(index + 1) % len(steps)]
            self.config.set("sound_volume", volume)
            if self.game is not None and getattr(self.game, "audio", None):
                self.game.audio.set_volume(volume)
                self.game.audio.play("craft")
            self._changed("volume")
        elif kind == "music":
            value = not self.config.get("music", True)
            self.config.set("music", value)
            audio = getattr(self.game, "audio", None) if self.game is not None else None
            if audio is not None:
                audio.set_music_enabled(value)
                if value:
                    audio.play_music(audio.music_mood or "day")
            self._changed("music")
        elif kind == "music_volume":
            steps = [0.0, 0.15, 0.3, 0.45, 0.6, 0.8]
            current = float(self.config.get("music_volume", 0.45))
            index = min(range(len(steps)), key=lambda i: abs(steps[i] - current))
            volume = steps[(index + 1) % len(steps)]
            self.config.set("music_volume", volume)
            audio = getattr(self.game, "audio", None) if self.game is not None else None
            if audio is not None:
                audio.set_music_volume(volume)
            self._changed("music_volume")
        elif kind == "tutorial":
            self.config.set("tutorial", not self.config.get("tutorial", True))
            self._changed("tutorial")
        elif kind == "quiet":
            self.config.set("quiet_notifications",
                            not self.config.get("quiet_notifications", False))
            self._changed("quiet")

    def _changed(self, kind):
        self.config.save()
        self.message = t("settings.saved")
        self.message_timer = 120
        if self.on_change:
            self.on_change(kind)

    def update(self):
        if self.message_timer > 0:
            self.message_timer -= 1

    # -------------------------------------------------------------------- draw
    def draw(self, screen):
        if not self.visible:
            return
        overlay = pygame.Surface(screen.get_size(), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 120))
        screen.blit(overlay, (0, 0))

        w.panel(screen, self.panel, t("settings.title"))
        mouse = pygame.mouse.get_pos()
        for kind, rect in self.rows:
            if kind == "language":
                self._row(screen, rect, t("settings.language"),
                          language_name(self.config.get("language")))
            elif kind == "pack":
                pack_id = self.config.get("resource_pack")
                packs = discover_packs()
                info = packs.get(pack_id)
                label = f"{pack_id}" + (f" - {info.description}" if info and info.description else "")
                self._row(screen, rect, t("settings.resource_pack"), label)
            elif kind == "fullscreen":
                w.toggle(screen, rect, t("settings.fullscreen"),
                         bool(self.config.get("fullscreen")), mouse)
            elif kind == "debug":
                w.toggle(screen, rect, t("settings.debug"),
                         bool(self.config.get("show_debug")), mouse)
            elif kind == "remember":
                w.toggle(screen, rect, t("settings.autologin"),
                         bool(self.config.get("remember_login")), mouse)
            elif kind == "sound":
                w.toggle(screen, rect, t("settings.sound"),
                         bool(self.config.get("sound", True)), mouse)
            elif kind == "volume":
                self._row(screen, rect, t("settings.volume"),
                          f"{int(float(self.config.get('sound_volume', 0.7)) * 100)}%")
            elif kind == "music":
                w.toggle(screen, rect, t("settings.music"),
                         bool(self.config.get("music", True)), mouse)
            elif kind == "music_volume":
                self._row(screen, rect, t("settings.music_volume"),
                          f"{int(float(self.config.get('music_volume', 0.45)) * 100)}%")
            elif kind == "tutorial":
                w.toggle(screen, rect, t("settings.tutorial"),
                         bool(self.config.get("tutorial", True)), mouse)
            elif kind == "quiet":
                w.toggle(screen, rect, t("settings.quiet"),
                         bool(self.config.get("quiet_notifications", False)), mouse)

        if getattr(self, "keys_button", None) is not None:
            w.button(screen, self.keys_button, t("settings.keys"), mouse_pos=mouse,
                     text_size=16)
            w.button(screen, self.quests_button, t("settings.quest_reset"), mouse_pos=mouse,
                     text_size=16)
        w.button(screen, self.hotbar_reset, t("settings.hotbar_reset"),
                 mouse_pos=mouse, text_size=16)
        w.button(screen, self.reset_button, t("settings.reset"),
                 base_color=(110, 70, 70), hover_color=(140, 85, 85),
                 mouse_pos=mouse, text_size=16)
        w.button(screen, self.back_button, t("settings.back"),
                 base_color=(60, 90, 140), hover_color=(75, 115, 175), mouse_pos=mouse)

        hint = w.font(14).render(t("settings.pack_hint"), True, w.TEXT_DIM)
        screen.blit(hint, (self.panel.x + 24, self.back_button.y))

        if self.message_timer > 0:
            w.text(screen, self.message, (self.panel.right - 220, self.panel.y + 24),
                   size=16, color=w.GOOD)

    def _row(self, screen, rect, label, value):
        hover = rect.collidepoint(pygame.mouse.get_pos())
        pygame.draw.rect(screen, (44, 48, 62) if hover else (36, 39, 50), rect, border_radius=5)
        pygame.draw.rect(screen, w.BORDER, rect, 1, border_radius=5)
        w.text(screen, label, (rect.x + 12, rect.centery - 10), size=17)
        w.text(screen, f"< {value} >", (rect.right - 16 - w.font(17).size(f"< {value} >")[0],
                                        rect.centery - 10), size=17, color=w.ACCENT)
