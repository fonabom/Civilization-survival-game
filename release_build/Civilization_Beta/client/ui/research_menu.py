import pygame
from shared.protocol import encode

class ResearchMenu:
    def __init__(self, game):
        self.game = game
        self.font = pygame.font.SysFont("Arial", 20)
        self.visible = False
        self.active_mode = None # "city" or "country"
        self.rect = pygame.Rect(200, 150, 400, 300)
        
    def open(self, mode):
        self.visible = True
        self.active_mode = mode
        
    def close(self):
        self.visible = False
        self.active_mode = None
        
    def toggle(self):
        if self.visible: self.close()
        
    def handle_click(self, pos):
        if not self.visible: return
        
        mx, my = pos
        x = self.rect.x + 20
        y = self.rect.y + 60
        
        if self.active_mode == "city":
            # Upgrade City
            if pygame.Rect(x, y, 300, 40).collidepoint(mx, my):
                 self.game.net.sock.send(encode({"type": "research", "city": "AUTO_FIND"}))
                 
        elif self.active_mode == "country":
            # Upgrade Country - LIST
            
            # 1. Industrialization
             if pygame.Rect(x, y, 300, 40).collidepoint(mx, my):
                 self.game.net.sock.send(encode({"type": "research", "scope": "country", "country": "AUTO_FIND", "tech": "industrialization"}))
            
            # 2. Chemistry
             if pygame.Rect(x, y + 50, 300, 40).collidepoint(mx, my):
                 self.game.net.sock.send(encode({"type": "research", "scope": "country", "country": "AUTO_FIND", "tech": "chemistry"}))

            # 3. Militarization (Placeholder)
             if pygame.Rect(x, y + 100, 300, 40).collidepoint(mx, my):
                 pass

    def draw(self, screen):
        if not self.visible: return
        
        # Background
        pygame.draw.rect(screen, (30, 30, 40), self.rect)
        pygame.draw.rect(screen, (100, 100, 200), self.rect, 2)
        
        title_txt = "Research: Unknown"
        if self.active_mode == "city": title_txt = "Town Center (City Research)"
        elif self.active_mode == "country": title_txt = "Research Table (Country Tech)"
        
        title = self.font.render(title_txt, True, (255, 255, 255))
        screen.blit(title, (self.rect.x + 20, self.rect.y + 20))
        
        x = self.rect.x + 20
        y = self.rect.y + 60
        
        if self.active_mode == "city":
            pygame.draw.rect(screen, (100, 50, 150), (x, y, 300, 40))
            txt = self.font.render("Upgrade City Tier (100 Wood/Stone)", True, (255, 255, 255))
            screen.blit(txt, (x+10, y+8))
            
        elif self.active_mode == "country":
            # 1. Industrialization
            pygame.draw.rect(screen, (150, 100, 50), (x, y, 300, 40))
            txt = self.font.render("Industrialization (50 Ir/Go) -> 2x Smelt", True, (255, 255, 255))
            screen.blit(txt, (x+10, y+8))
            
            # 2. Chemistry
            pygame.draw.rect(screen, (50, 150, 100), (x, y+50, 300, 40))
            txt2 = self.font.render("Chemistry (20 Oil) -> Chem Plant", True, (255, 255, 255))
            screen.blit(txt2, (x+10, y+58))
            
            # 3. Militarization
            pygame.draw.rect(screen, (100, 50, 50), (x, y+100, 300, 40))
            txt3 = self.font.render("Militarization (Coming Soon)", True, (200, 200, 200))
            screen.blit(txt3, (x+10, y+108))
