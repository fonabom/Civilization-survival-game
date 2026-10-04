"""The player you see on screen: a little person, not a coloured square.

b11 replaced the cube with a human sprite (`assets/player.png`): head, body,
arms and legs, drawn in light grey tones so the per-player colour can tint it
(BLEND_RGB_MULT keeps the shading and the eyes). Everything is cached, so the
tint/flip work happens once per colour instead of once per frame.

Resource packs may override `player.png` with their own character art - the
tint and the outline still apply.
"""

import pygame

from client.settings import TILE_SIZE

# Distinct colour per player id so it is obvious who is who
PALETTE = [
    (0, 200, 0), (220, 60, 60), (80, 140, 255), (240, 200, 60),
    (200, 90, 220), (60, 210, 200), (250, 140, 60), (170, 170, 170),
]

SPRITE_HEIGHT = 30            # how tall the character is drawn in the world
TINT = (1.0, 1.0, 1.0)        # full strength: the sprite is drawn in light greys


class Player:
    def __init__(self, pid, name: str = None):
        self.id = pid
        self.name = name or f"Player {pid}"
        self.x = 0.0
        self.y = 0.0
        self.target_x = 0.0
        self.target_y = 0.0
        self.hp = 100
        self.inventory = {}
        self.selected = None          # item in hand (server authoritative)
        self.hunger = 100
        self.armor = 0
        self.armor_items = {}
        self.pets = 0
        self.durability = {}
        self.speed = 0.25
        self.facing = 1               # 1 = to the right, -1 = to the left
        self.walk_phase = 0.0         # little bob while moving
        try:
            index = int(pid)
        except (TypeError, ValueError):
            index = abs(hash(pid))
        self.color = PALETTE[index % len(PALETTE)]
        self.font = pygame.font.SysFont("Arial", 12)
        self._sprites = {}            # (facing, tinted) -> surface

    # ------------------------------------------------------------------ server
    def update_from_server(self, data):
        self.target_x = data.get("x", self.target_x)
        self.target_y = data.get("y", self.target_y)
        if data.get("name"):
            self.name = data["name"]
        if "hp" in data:
            self.hp = data["hp"]
        if "hunger" in data:
            self.hunger = data["hunger"]
        if "armor" in data:
            self.armor = data["armor"]
        if "armor_items" in data:
            self.armor_items = dict(data["armor_items"])
        if "pets" in data:
            self.pets = data["pets"]
        if "durability" in data:
            self.durability = dict(data["durability"])
        # Snap on teleport / spawn instead of gliding across the map
        if abs(self.x - self.target_x) > 200 or abs(self.y - self.target_y) > 200:
            self.x, self.y = self.target_x, self.target_y

    def update(self):
        before_x = self.x
        self.x += (self.target_x - self.x) * self.speed
        self.y += (self.target_y - self.y) * self.speed
        dx = self.x - before_x
        if abs(dx) > 0.3:
            self.facing = 1 if dx > 0 else -1
        if abs(dx) > 0.05 or abs(self.y - self.target_y) > 0.5:
            self.walk_phase += 0.55
        else:
            self.walk_phase = 0.0

    # ------------------------------------------------------------------ sprite
    def sprite(self, resources):
        """The character, tinted with this player's colour and facing the way
        he walked. Only built once per colour/direction (and per pack)."""
        key = (self.facing, getattr(resources, "pack_id", None))
        cached = self._sprites.get(key)
        if cached is not None:
            return cached
        base = resources.get("player") if resources is not None else None
        if base is None:
            self._sprites[key] = None
            return None
        scale = SPRITE_HEIGHT / base.get_height()
        sprite = pygame.transform.smoothscale(
            base, (max(1, int(base.get_width() * scale)), SPRITE_HEIGHT)).convert_alpha()
        tint = (max(60, min(255, self.color[0])), max(60, min(255, self.color[1])),
                max(60, min(255, self.color[2])), 255)
        sprite.fill(tint, special_flags=pygame.BLEND_RGB_MULT)
        if self.facing < 0:
            sprite = pygame.transform.flip(sprite, True, False)
        self._sprites[key] = sprite
        return sprite

    # -------------------------------------------------------------------- draw
    def draw(self, screen, camera, is_me: bool = False, resources=None, in_water=False):
        screen_x = int(self.x - camera.x)
        screen_y = int(self.y - camera.y)
        center_x = screen_x + TILE_SIZE // 2
        feet_y = screen_y + TILE_SIZE - 2

        if in_water:
            # ripples around the feet: it is obvious that the player is swimming
            ripple = pygame.Rect(0, 0, TILE_SIZE + 8, 14)
            ripple.center = (center_x, feet_y - 4)
            pygame.draw.ellipse(screen, (150, 205, 245), ripple, 2)
            inner = ripple.inflate(-10, -6)
            pygame.draw.ellipse(screen, (110, 170, 220), inner, 1)

        # shadow
        pygame.draw.ellipse(screen, (20, 24, 20, 90),
                            (center_x - 9, feet_y - 5, 18, 6))

        bob = 0
        if self.walk_phase:
            bob = -2 if int(self.walk_phase) % 2 else 0
        sprite = self.sprite(resources)
        if sprite is not None:
            rect = sprite.get_rect(midbottom=(center_x, feet_y + bob))
            if is_me:
                # a soft white glow marks your own character
                glow = pygame.Surface(sprite.get_size(), pygame.SRCALPHA)
                glow.blit(sprite, (0, 0))
                glow.fill((90, 90, 90, 255), special_flags=pygame.BLEND_RGB_ADD)
                screen.blit(glow, rect.move(2, -1))
            screen.blit(sprite, rect)
        else:
            # no texture (a pack that removed player.png): keep a visible body
            pygame.draw.rect(screen, (20, 24, 20), (screen_x + 2, screen_y + 3,
                                                    TILE_SIZE, TILE_SIZE))
            pygame.draw.rect(screen, self.color, (screen_x, screen_y, TILE_SIZE, TILE_SIZE))
            pygame.draw.rect(screen, (255, 255, 255),
                             (screen_x, screen_y, TILE_SIZE, TILE_SIZE),
                             2 if is_me else 1)

        # the item in hand is drawn next to the body, like a little sprite
        if self.selected and resources is not None:
            icon = resources.get(self.selected)
            if icon:
                icon = pygame.transform.smoothscale(icon, (14, 14))
                hand_x = center_x + (14 if self.facing > 0 else -28)
                screen.blit(icon, (hand_x, feet_y - 20))

        label = self.name + (" (you)" if is_me else "")
        text = self.font.render(label, True, (255, 255, 255))
        shadow = self.font.render(label, True, (0, 0, 0))
        center = (center_x, screen_y - 10)
        screen.blit(shadow, shadow.get_rect(center=(center[0] + 1, center[1] + 1)))
        screen.blit(text, text.get_rect(center=center))

        if self.hp < 100:
            bar_w = TILE_SIZE
            pygame.draw.rect(screen, (80, 0, 0), (screen_x, screen_y - 4, bar_w, 3))
            pygame.draw.rect(screen, (60, 220, 60),
                             (screen_x, screen_y - 4, int(bar_w * max(0, self.hp) / 100), 3))
