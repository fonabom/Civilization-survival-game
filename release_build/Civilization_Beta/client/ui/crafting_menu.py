import pygame
from shared.protocol import encode
from shared.structures import STRUCTURES
from shared.items import CRAFTING_RECIPES

class CraftingMenu:
    def __init__(self, game):
        self.game = game
        self.font = pygame.font.SysFont("Arial", 18)
        self.visible = False
        self.rect = pygame.Rect(100, 100, 600, 500)
        
    def toggle(self):
        self.visible = not self.visible
        
    def handle_click(self, pos):
        if not self.visible: return
        
        mx, my = pos
        x = self.rect.x + 20
        y = self.rect.y + 60
        
        # 1. Tools (Item Crafting)
        for name, cost in CRAFTING_RECIPES.items():
            btn_rect = pygame.Rect(x, y, 250, 40)
            if btn_rect.collidepoint(mx, my):
                self.game.net.sock.send(encode({"type": "craft", "item": name}))
            y += 50
        
        # 2. Structures (Building) - Maybe separate column?
        y = self.rect.y + 60
        x += 300
        for name, cost in STRUCTURES.items():
            btn_rect = pygame.Rect(x, y, 250, 40)
            if btn_rect.collidepoint(mx, my):
                self.game.net.sock.send(encode({"type": "build", "structure": name}))
            y += 50

    def draw(self, screen):
        if not self.visible: return
        
        # Background
        pygame.draw.rect(screen, (40, 40, 40), self.rect)
        pygame.draw.rect(screen, (200, 200, 200), self.rect, 2)
        
        # Titles
        title = self.font.render("Crafting (Items)            Building (Structures)", True, (255, 255, 255))
        screen.blit(title, (self.rect.x + 20, self.rect.y + 20))
        
        # Tools
        x = self.rect.x + 20
        y = self.rect.y + 60
        for name, cost in CRAFTING_RECIPES.items():
            pygame.draw.rect(screen, (60, 60, 80), (x, y, 250, 40))
            cost_str = ", ".join([f"{k}:{v}" for k,v in cost.items()])
            text = self.font.render(f"{name.capitalize()} ({cost_str})", True, (255, 255, 255))
            screen.blit(text, (x + 5, y + 8))
            y += 50
            
        # Structures
        y = self.rect.y + 60
        x += 300
        for name, cost in STRUCTURES.items():
            pygame.draw.rect(screen, (80, 60, 60), (x, y, 250, 40))
            cost_str = ", ".join([f"{k}:{v}" for k,v in cost.items()])
            text = self.font.render(f"{name.capitalize()} ({cost_str})", True, (255, 255, 255))
            screen.blit(text, (x + 5, y + 8))
            y += 50
