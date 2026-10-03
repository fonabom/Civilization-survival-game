import pygame
from shared.protocol import encode

class SmeltingMenu:
    def __init__(self, game):
        self.game = game
        self.font = pygame.font.SysFont("Arial", 20)
        self.visible = False
        self.rect = pygame.Rect(150, 150, 400, 300)
        
    def toggle(self):
        self.visible = not self.visible
        
    def handle_click(self, pos):
        if not self.visible: return
        
        mx, my = pos
        x = self.rect.x + 20
        y = self.rect.y + 60
        
        # Recipes
        recipes = [
            ("Smelt Iron (1 Ore -> 1 Ingot)", "smelt_iron"),
            ("Smelt Gold (1 Ore -> 1 Ingot)", "smelt_gold")
        ]
        
        for label, action in recipes:
            if pygame.Rect(x, y, 300, 40).collidepoint(mx, my):
                self.game.net.sock.send(encode({"type": "smelt", "action": action}))
            y += 50

    def draw(self, screen):
        if not self.visible: return
        
        # Background
        pygame.draw.rect(screen, (60, 40, 40), self.rect)
        pygame.draw.rect(screen, (255, 100, 100), self.rect, 2)
        
        # Title
        title = self.font.render("Furnace", True, (255, 200, 200))
        screen.blit(title, (self.rect.x + 20, self.rect.y + 20))
        
        x = self.rect.x + 20
        y = self.rect.y + 60
        
        recipes = [
            "Smelt Iron (1 Ore + 1 Coal)",
            "Smelt Gold (1 Ore + 1 Coal)"
        ]
        
        for label in recipes:
            pygame.draw.rect(screen, (80, 50, 50), (x, y, 300, 40))
            text = self.font.render(label, True, (255, 255, 255))
            screen.blit(text, (x+10, y+8))
            y += 50
