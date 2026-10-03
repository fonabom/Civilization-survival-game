import pygame
from client.settings import TILE_SIZE

class Player:
    def __init__(self, pid):
        self.id = pid
        self.x = 0
        self.y = 0
        self.target_x = 0
        self.target_y = 0
        self.color = (0, 200, 0)
        self.font = pygame.font.SysFont("Arial", 12)
        self.speed = 0.25 # Interpolation factor (0.0 to 1.0)

    def update_from_server(self, data):
        self.target_x = data["x"]
        self.target_y = data["y"]
        
        # Initial snap if far away (teleport/spawn)
        if abs(self.x - self.target_x) > 100 or abs(self.y - self.target_y) > 100:
            self.x = self.target_x
            self.y = self.target_y

    def update(self):
        # Linear interpolation
        self.x += (self.target_x - self.x) * self.speed
        self.y += (self.target_y - self.y) * self.speed

    def draw(self, screen, camera):
        screen_x = int(self.x - camera.x)
        screen_y = int(self.y - camera.y)

        # Draw player body
        pygame.draw.rect(
            screen,
            self.color,
            (screen_x, screen_y, TILE_SIZE, TILE_SIZE)
        )
        
        # Draw Border
        pygame.draw.rect(
            screen,
            (255, 255, 255),
            (screen_x, screen_y, TILE_SIZE, TILE_SIZE),
            1
        )

        # Draw name/ID
        text = self.font.render(f"P{self.id}", True, (255, 255, 255))
        text_rect = text.get_rect(center=(screen_x + TILE_SIZE // 2, screen_y - 10))
        screen.blit(text, text_rect)
