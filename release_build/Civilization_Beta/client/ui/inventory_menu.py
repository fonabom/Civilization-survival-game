import pygame
from shared.protocol import encode
from client.settings import SCREEN_WIDTH, SCREEN_HEIGHT

class InventoryMenu:
    def __init__(self, game):
        self.game = game
        self.font = pygame.font.SysFont("Arial", 16)
        self.visible = False
        self.rect = pygame.Rect(SCREEN_WIDTH//2 - 200, SCREEN_HEIGHT//2 - 200, 400, 400)
        
        # Grid config
        self.cols = 5
        self.rows = 4
        self.slot_size = 50
        self.padding = 10
        
    def toggle(self):
        self.visible = not self.visible
        
    def handle_click(self, pos):
        if not self.visible: return
        
        mx, my = pos
        # Calculate grid clicks?
        # For now, simple equipping by clicking purely? 
        # Needs logic to map click to slot index.
        pass

    def draw(self, screen):
        if not self.visible: return
        
        # Background
        pygame.draw.rect(screen, (40, 40, 40), self.rect)
        pygame.draw.rect(screen, (200, 200, 200), self.rect, 2)
        
        # Title
        title = self.font.render("Inventory", True, (255, 255, 255))
        screen.blit(title, (self.rect.x + 20, self.rect.y + 10))
        
        # Get Inventory
        my_player = self.game.players.get(self.game.my_id)
        if not my_player: return
        inventory = getattr(my_player, "inventory", {})
        
        # Draw Grid
        start_x = self.rect.x + 30
        start_y = self.rect.y + 50
        
        items = list(inventory.items())
        
        for i in range(self.rows * self.cols):
            x = start_x + (i % self.cols) * (self.slot_size + self.padding)
            y = start_y + (i // self.cols) * (self.slot_size + self.padding)
            
            # Slot BG
            pygame.draw.rect(screen, (60, 60, 60), (x, y, self.slot_size, self.slot_size))
            pygame.draw.rect(screen, (100, 100, 100), (x, y, self.slot_size, self.slot_size), 1)
            
            # Item
            if i < len(items):
                try:
                    name, count = items[i]
                    # Check assets
                    
                    # Ensure world.assets exists
                    if hasattr(self.game.world, "assets"):
                        asset = self.game.world.assets.get(name)
                        if asset:
                            # Scale down
                            icon = pygame.transform.scale(asset, (32, 32))
                            screen.blit(icon, (x + 9, y + 9))
                        else:
                            # Initials
                            txt = self.font.render(name[:2].upper(), True, (200, 200, 200))
                            screen.blit(txt, (x + 10, y + 10))
                    else:
                        screen.blit(self.font.render("?", True, (255,0,0)), (x+10, y+10))

                    # Count
                    cnt = self.font.render(str(count), True, (255, 255, 255))
                    screen.blit(cnt, (x + 2, y + 32))
                except Exception as e:
                    print(f"Inventory Error Item {i}: {e}")
                    txt = self.font.render("ERR", True, (255, 0, 0))
                    screen.blit(txt, (x + 5, y + 15))
        
        # Equipment Slots (Side)
        eq_x = self.rect.right - 80
        eq_y = self.rect.y + 50
        labels = ["Hand", "Body"]
        for j, lbl in enumerate(labels):
             pygame.draw.rect(screen, (50, 50, 70), (eq_x, eq_y, self.slot_size, self.slot_size))
             pygame.draw.rect(screen, (100, 100, 150), (eq_x, eq_y, self.slot_size, self.slot_size), 1)
             
             txt = self.font.render(lbl, True, (150, 150, 150))
             screen.blit(txt, (eq_x, eq_y - 15))
             eq_y += 70


