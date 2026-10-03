import pygame
import random
from shared.protocol import encode

class CivMenu:
    def __init__(self, game):
        self.game = game
        self.font = pygame.font.SysFont("Arial", 20)
        self.visible = False
        self.rect = pygame.Rect(100, 100, 600, 400)
        
        self.input_text = ""
        self.active_input = None # "city", "country", or "join_country"
        
    def toggle(self):
        self.visible = not self.visible
        self.active_input = None
        self.input_text = ""
        
    def handle_input(self, event):
        if not self.visible or not self.active_input: return
        
        if event.key == pygame.K_RETURN:
            if self.input_text:
                if self.active_input == "city":
                    self.game.net.sock.send(encode({"type": "create_city", "name": self.input_text}))
                elif self.active_input == "country":
                    self.game.net.sock.send(encode({"type": "create_country", "name": self.input_text}))
                elif self.active_input == "join_country":
                    # For now, assume input_text is the country name to join
                    # This needs to be more robust, e.g., selecting a city to join with
                    # For simplicity, let's assume the server can figure out the player's city
                    self.game.net.sock.send(encode({"type": "join_country", "country": self.input_text}))
                
                # Reset
                self.input_text = ""
                self.active_input = None
        elif event.key == pygame.K_BACKSPACE:
            self.input_text = self.input_text[:-1]
        elif event.key == pygame.K_ESCAPE:
            self.active_input = None
        else:
            self.input_text += event.unicode

    def handle_click(self, pos):
        if not self.visible: return
        
        mx, my = pos
        x = self.rect.x + 20
        y = self.rect.y + 60
        
        # Tabs Logic (Simple)
        # 1. Create City
        if pygame.Rect(x, 100, 200, 30).collidepoint(mx, my):
             self.active_input = "city_name"
        elif pygame.Rect(x, 140, 50, 30).collidepoint(mx, my):
             if self.input_text:
                 self.game.net.sock.send(encode({"type": "create_city", "name": self.input_text}))
                 self.input_text = ""
                 
        # 2. Join City List
        cy = 200
        cities = self.game.civ_state.get("cities", {})
        for name in list(cities.keys())[:5]: # Show first 5 for now
            if pygame.Rect(x, cy, 200, 30).collidepoint(mx, my):
                self.game.net.sock.send(encode({"type": "join_city", "name": name}))
            cy += 40
            
        # 3. Create Country
        cx = self.rect.x + 300
        if pygame.Rect(cx, 100, 200, 30).collidepoint(mx, my):
            self.active_input = "country_name"
        elif pygame.Rect(cx, 140, 50, 30).collidepoint(mx, my):
             if self.input_text:
                 self.game.net.sock.send(encode({"type": "create_country", "name": self.input_text}))
                 self.input_text = ""

        # 4. Join Country (As City Leader)
        cy = 200
        countries = self.game.civ_state.get("countries", {})
        # Logic: need to know MY city to join a country. 
        # For this prototype, let's assume if I click a country, I want my city (if I lead one) to join it.
        # But wait, join_country packet needs "city" and "country".
        # Let's rely on server to find my city? Or hardcode picking first city? 
        # Better: Add "Auto Join" button for currently selected country?
        # Let's keep it simple: "Research Country" button if you already own one.
        
        # Research Country - REMOVED
        # if pygame.Rect(cx, 350, 200, 40).collidepoint(mx, my):
             # self.game.net.sock.send(encode({"type": "research", "scope": "country", "country": "AUTO_FIND"})) 

        # Town Center Research (City) - REMOVED
        # if pygame.Rect(x, 350, 200, 40).collidepoint(mx, my):
             # self.game.net.sock.send(encode({"type": "research", "city": "AUTO_FIND"}))

    def draw(self, screen):
        if not self.visible: return
        
        pygame.draw.rect(screen, (40, 40, 50), self.rect)
        pygame.draw.rect(screen, (200, 200, 255), self.rect, 2)
        
        title = self.font.render("Civilization: Cities (Left) | Countries (Right)", True, (255, 255, 255))
        screen.blit(title, (self.rect.x + 20, self.rect.y + 20))
        
        x = self.rect.x + 20
        y = 100
        
        # Input Highlight
        col_c = (100, 200, 100) if self.active_input == "city_name" else (60, 60, 80)
        pygame.draw.rect(screen, col_c, (x, y, 200, 30))
        screen.blit(self.font.render(f"New City: {self.input_text if self.active_input=='city_name' else ''}", True, (255, 255, 255)), (x+5, y+5))
        pygame.draw.rect(screen, (50, 150, 50), (x, 140, 50, 30)) # OK
        screen.blit(self.font.render("OK", True, (255,255,255)), (x+10, 145))
        
        # List Cities
        y = 200
        screen.blit(self.font.render("Join City:", True, (200, 200, 200)), (x, y-25))
        cities = self.game.civ_state.get("cities", {})
        for name in list(cities.keys())[:5]:
            pygame.draw.rect(screen, (70, 70, 90), (x, y, 200, 30))
            screen.blit(self.font.render(name, True, (255, 255, 255)), (x+5, y+5))
            y += 40
            
        # Right Side (Countries)
        cx = self.rect.x + 300
        y = 100
        col_co = (100, 200, 100) if self.active_input == "country_name" else (60, 60, 80)
        pygame.draw.rect(screen, col_co, (cx, y, 200, 30))
        screen.blit(self.font.render(f"New Country: {self.input_text if self.active_input=='country_name' else ''}", True, (255, 255, 255)), (cx+5, y+5))
        pygame.draw.rect(screen, (50, 150, 50), (cx, 140, 50, 30)) # OK
        screen.blit(self.font.render("OK", True, (255,255,255)), (cx+10, 145))
        
        # Research Btns REMOVED (Moved to Buildings)
        # pygame.draw.rect(screen, (100, 50, 150), (x, 350, 200, 40))
        # screen.blit(self.font.render("Upgrade City (Tier 2)", True, (255, 255, 255)), (x+5, 360))
        
        # pygame.draw.rect(screen, (150, 50, 50), (cx, 350, 200, 40))
        # screen.blit(self.font.render("Research Table (Tech)", True, (255, 255, 255)), (cx+5, 360))
