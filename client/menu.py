import pygame
import random
from client.settings import SCREEN_WIDTH, SCREEN_HEIGHT

class MainMenu:
    def __init__(self, screen):
        self.screen = screen
        self.font_title = pygame.font.SysFont("Verdana", 60, bold=True)
        self.font_btn = pygame.font.SysFont("Arial", 30)
        self.font_sm = pygame.font.SysFont("Arial", 18)
        
        self.active = True
        self.state = "main" # main, settings
        
        # Inputs
        self.ip_text = "127.0.0.1"
        self.name_text = "Player"
        
        # Animations
        self.particles = []
        for _ in range(50):
            self.particles.append([
                random.randint(0, SCREEN_WIDTH), 
                random.randint(0, SCREEN_HEIGHT),
                random.randint(2, 5), # Speed
                random.randint(2, 6) # Size
            ])
        
    def draw_background(self):
        # Gradientish Dark Blue
        self.screen.fill((10, 15, 30))
        
        # Animated Particles (Stars/Dust)
        for p in self.particles:
            p[1] += p[2] # Fall down
            if p[1] > SCREEN_HEIGHT:
                p[1] = -10
                p[0] = random.randint(0, SCREEN_WIDTH)
            
            # Draw
            color = (100, 150, 200, 150)
            s = pygame.Surface((p[3], p[3]), pygame.SRCALPHA)
            pygame.draw.circle(s, color, (p[3]//2, p[3]//2), p[3]//2)
            self.screen.blit(s, (p[0], p[1]))

    def handle_event(self, event):
        if self.state == "main":
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_RETURN:
                    self.active = False
                elif event.key == pygame.K_BACKSPACE:
                    self.ip_text = self.ip_text[:-1]
                else:
                    self.ip_text += event.unicode
            elif event.type == pygame.MOUSEBUTTONDOWN:
                mx, my = event.pos
                if hasattr(self, 'btn_play') and self.btn_play.collidepoint(mx, my):
                     self.active = False
                if hasattr(self, 'btn_settings') and self.btn_settings.collidepoint(mx, my):
                     print("Settings - To Be Implemented") # TODO
                if hasattr(self, 'btn_exit') and self.btn_exit.collidepoint(mx, my):
                     pygame.quit()
                     exit()
                     
    def draw(self):
        self.draw_background()
        
        if self.state == "main":
            # Title Shadow
            shadow = self.font_title.render("Civilization Game", True, (0, 0, 0))
            self.screen.blit(shadow, (SCREEN_WIDTH//2 - shadow.get_width()//2 + 5, 85))
            
            # Title Main
            title = self.font_title.render("Civilization Game", True, (255, 215, 0))
            self.screen.blit(title, (SCREEN_WIDTH//2 - title.get_width()//2, 80))
            
            # IP Input Box
            rect_ip = pygame.Rect(SCREEN_WIDTH//2 - 150, 200, 300, 50)
            pygame.draw.rect(self.screen, (20, 20, 40), rect_ip)
            pygame.draw.rect(self.screen, (100, 200, 255), rect_ip, 2)
            
            ip_lbl = self.font_sm.render("Server IP:", True, (150, 200, 255))
            self.screen.blit(ip_lbl, (rect_ip.x, rect_ip.y - 25))
            
            txt = self.font_btn.render(self.ip_text, True, (255, 255, 255))
            self.screen.blit(txt, (rect_ip.x + 10, rect_ip.y + 10))
            
            # Buttons Helper
            mx, my = pygame.mouse.get_pos()
            
            def draw_btn(text, y, func_check=None):
                rect = pygame.Rect(SCREEN_WIDTH//2 - 100, y, 200, 60)
                hover = rect.collidepoint(mx, my)
                col = (60, 180, 60) if hover else (40, 120, 40)
                if text == "EXIT": col = (180, 60, 60) if hover else (120, 40, 40)
                if text == "SETTINGS": col = (60, 60, 180) if hover else (40, 40, 120)

                pygame.draw.rect(self.screen, col, rect, border_radius=10)
                pygame.draw.rect(self.screen, (255, 255, 255), rect, 2, border_radius=10)
                lbl = self.font_btn.render(text, True, (255, 255, 255))
                self.screen.blit(lbl, (rect.centerx - lbl.get_width()//2, rect.centery - lbl.get_height()//2))
                return rect

            self.btn_play = draw_btn("PLAY", 280)
            self.btn_settings = draw_btn("SETTINGS", 360) 
            self.btn_exit = draw_btn("EXIT", 440)
