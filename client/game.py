import pygame
import random
from client.network import Network
from client.player import Player
from client.world import World
from client.camera import Camera
from client.settings import SCREEN_WIDTH, SCREEN_HEIGHT
from shared.protocol import encode
from client.ui.crafting_menu import CraftingMenu
from client.ui.civ_menu import CivMenu
from client.ui.smelting_menu import SmeltingMenu
from client.ui.inventory_menu import InventoryMenu
from client.ui.research_menu import ResearchMenu

class Game:
    def __init__(self, screen, host: str = "127.0.0.1", port: int = 5555):
        self.screen = screen
        self.world = World()
        self.camera = Camera()
        self.net = Network(host, port)
        self.players = {}
        self.my_id = None 
        
        # UI Components
        self.crafting_menu = CraftingMenu(self) 
        self.civ_menu = CivMenu(self) 
        self.smelting_menu = SmeltingMenu(self) 
        self.inventory_menu = InventoryMenu(self)
        self.research_menu = ResearchMenu(self) 

        # Chat and Notifications
        self.chat_messages = []
        self.chat_input = ""
        self.chat_active = False
        self.notifications = [] 

        # Main Loop Clock
        self.clock = pygame.time.Clock()

    def update(self):
        self.clock.tick(60)
        
        # Update Notifications
        self.notifications = [(txt, t-1) for txt, t in self.notifications if t > 0]

        # Network
        messages = self.net.receive()
        for msg in messages:
            if msg.get("type") == "welcome":
                self.my_id = msg["id"]
                print(f"Connected as Player {self.my_id}")
            
            elif msg.get("type") == "notification":
                self.notifications.append((msg["msg"], 120)) 
                
            elif msg.get("type") == "chat":
                self.chat_messages.append(f"Player {msg['id']}: {msg['msg']}")

            elif msg.get("type") == "state":
                # Update players
                for pid, pdata in msg["players"].items():
                    if pid not in self.players:
                        self.players[pid] = Player(pid)
                    self.players[pid].update_from_server(pdata)
                    if pid == self.my_id and "inventory" in pdata:
                        self.players[pid].inventory = pdata["inventory"]
                
                # Update Resources
                if "resources" in msg:
                    self.world.resources = msg["resources"]
                
                # Update Buildings
                if "buildings" in msg:
                    self.world.buildings = msg["buildings"]
                
                # Update Civs
                if "civs" in msg:
                    self.civ_state = msg["civs"]

        # Input
        keys = pygame.key.get_pressed()
        
        if not self.chat_active:
            dx = dy = 0
            speed = 4
            if keys[pygame.K_w]: dy = -speed
            if keys[pygame.K_s]: dy = speed
            if keys[pygame.K_a]: dx = -speed
            if keys[pygame.K_d]: dx = speed

            if dx != 0 or dy != 0:
                self.net.send_move(dx, dy)
                # Client-side prediction: immediately move our local player for smooth control
                if self.my_id and self.my_id in self.players:
                    p = self.players[self.my_id]
                    p.x += dx
                    p.y += dy
                    # Also nudge target so interpolation doesn't fight prediction
                    p.target_x = p.x
                    p.target_y = p.y

        # Update Local State
        for player in self.players.values():
            player.update()

        # Camera
        if self.my_id and self.my_id in self.players:
             self.camera.update(self.players[self.my_id], SCREEN_WIDTH, SCREEN_HEIGHT)
        elif self.players:
             self.camera.update(next(iter(self.players.values())), SCREEN_WIDTH, SCREEN_HEIGHT)

    def draw(self):
        self.screen.fill((0, 0, 0))
        self.world.draw(self.screen, self.camera)
        for player in self.players.values():
            player.draw(self.screen, self.camera)
        
        self.draw_ui()
        self.draw_chat()
        self.draw_inventory()
        self.crafting_menu.draw(self.screen)
        self.civ_menu.draw(self.screen) 
        self.smelting_menu.draw(self.screen)
        self.inventory_menu.draw(self.screen)
        self.research_menu.draw(self.screen)
        
        if pygame.key.get_pressed()[pygame.K_TAB]:
            self.draw_player_list()
            
        self.draw_notifications()
        # Connection status overlay
        try:
            self.draw_connection_status()
        except Exception:
            pass

    def handle_event(self, event):
        # Pass clicks to menus
        if event.type == pygame.MOUSEBUTTONDOWN:
            consumed = False
            if self.crafting_menu.visible:
                self.crafting_menu.handle_click(event.pos)
                consumed = True
            if self.civ_menu.visible:
                self.civ_menu.handle_click(event.pos)
                consumed = True
            if self.smelting_menu.visible:
                self.smelting_menu.handle_click(event.pos)
                consumed = True
            if self.inventory_menu.visible:
                self.inventory_menu.handle_click(event.pos)
                consumed = True
            if self.research_menu.visible:
                self.research_menu.handle_click(event.pos)
                consumed = True
            if consumed: return
            
            # Interaction (Right Click - Button 3)
            if event.button == 3:
                # Convert Screen -> World
                mx, my = event.pos
                wx = mx + self.camera.x
                wy = my + self.camera.y
                
                # Check Buildings
                for b_key, b_data in self.world.buildings.items():
                    bx = b_data["x"] * 32
                    by = b_data["y"] * 32
                    rect = pygame.Rect(bx, by, 32, 32)
                    if rect.collidepoint(wx, wy):
                        if b_data["type"] == "town_center":
                            self.research_menu.open("city")
                        elif b_data["type"] == "research_table":
                            self.research_menu.open("country")
                        break
            
        if event.type == pygame.KEYDOWN:
            # Priority: Civ Menu Input
            if self.civ_menu.visible and self.civ_menu.active_input:
                self.civ_menu.handle_input(event)
                return

            if self.chat_active:
                if event.key == pygame.K_RETURN:
                    if self.chat_input:
                        self.net.sock.send(encode({"type": "chat", "text": self.chat_input}))
                        self.chat_messages.append(f"Me: {self.chat_input}")
                        self.chat_input = ""
                    self.chat_active = False
                elif event.key == pygame.K_BACKSPACE:
                    self.chat_input = self.chat_input[:-1]
                else:
                    self.chat_input += event.unicode
            else:
                # Gameplay Inputs
                if event.key == pygame.K_RETURN:
                    self.chat_active = True
                
                # Menus
                elif event.key == pygame.K_c:
                    self.crafting_menu.toggle()
                elif event.key == pygame.K_v:
                    self.civ_menu.toggle()
                elif event.key == pygame.K_f:
                    self.interact_at_cursor()
                elif event.key == pygame.K_i:
                    self.inventory_menu.toggle()

                # Actions
                elif event.key == pygame.K_e:
                    self.net.sock.send(encode({"type": "gather"}))

    def interact_at_cursor(self):
        # Convert Screen -> World
        mx, my = pygame.mouse.get_pos()
        wx = mx + self.camera.x
        wy = my + self.camera.y
        
        # Check Buildings
        found = False
        for b_key, b_data in self.world.buildings.items():
            bx = b_data["x"] * 32
            by = b_data["y"] * 32
            rect = pygame.Rect(bx, by, 32, 32)
            
            if rect.collidepoint(wx, wy):
                found = True
                if b_data["type"] == "furnace":
                    self.smelting_menu.toggle()
                elif b_data["type"] == "town_center":
                    self.research_menu.open("city")
                elif b_data["type"] == "research_table":
                    self.research_menu.open("country")
                elif b_data["type"] == "crafting_table":
                    self.crafting_menu.toggle()
                else:
                    found = False # Not an interactive UI block
                
                if found: break # Interact with top/first found
        
        if not found:
             # Maybe notification?
             pass

    def draw_notifications(self):
        if not self.notifications: return
        font = pygame.font.SysFont("Arial", 24)
        y = 100
        for txt, t in self.notifications:
            surf = font.render(txt, True, (255, 50, 50))
            self.screen.blit(surf, (SCREEN_WIDTH//2 - surf.get_width()//2, y))
            y += 30

    def draw_inventory(self):
        if not self.my_id or self.my_id not in self.players: return
        inv = getattr(self.players[self.my_id], "inventory", {})
        font = pygame.font.SysFont("Arial", 20)
        items = list(inv.items())
        h = max(50, len(items) * 20 + 10)
        y = SCREEN_HEIGHT - h - 10
        pygame.draw.rect(self.screen, (50, 50, 50), (10, y, 150, h))
        pygame.draw.rect(self.screen, (200, 200, 200), (10, y, 150, h), 2)
        text_y = y + 5
        for item, count in items:
            col = (255, 255, 255)
            if "wood" in item: col = (200, 150, 50)
            elif "stone" in item: col = (150, 150, 150)
            elif "gold" in item: col = (255, 215, 0)
            elif "iron" in item: col = (180, 150, 150)
            text = font.render(f"{item.capitalize()}: {count}", True, col)
            self.screen.blit(text, (20, text_y))
            text_y += 20

    def draw_chat(self):
        font = pygame.font.SysFont("Arial", 18)
        y = SCREEN_HEIGHT - 150
        for msg in self.chat_messages[-5:]:
            text = font.render(msg, True, (255, 255, 255))
            self.screen.blit(text, (10, y))
            y += 20
        if self.chat_active:
            pygame.draw.rect(self.screen, (0, 0, 0), (10, SCREEN_HEIGHT - 30, 400, 25))
            pygame.draw.rect(self.screen, (255, 255, 255), (10, SCREEN_HEIGHT - 30, 400, 25), 2)
            text = font.render(self.chat_input, True, (255, 255, 255))
            self.screen.blit(text, (15, SCREEN_HEIGHT - 28))
            
    def draw_player_list(self):
        overlay = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 150))
        self.screen.blit(overlay, (0, 0))
        
        rect = pygame.Rect(100, 100, SCREEN_WIDTH - 200, SCREEN_HEIGHT - 200)
        pygame.draw.rect(self.screen, (30, 30, 40), rect)
        pygame.draw.rect(self.screen, (100, 100, 120), rect, 2)
        
        font = pygame.font.SysFont("Arial", 28)
        title = font.render(f"Players: {len(self.players)}", True, (255, 255, 255))
        self.screen.blit(title, (rect.x + 20, rect.y + 20))
        
        y = rect.y + 70
        font_sm = pygame.font.SysFont("Arial", 22)
        
        self.screen.blit(font_sm.render("ID", True, (200, 200, 200)), (rect.x + 20, y))
        self.screen.blit(font_sm.render("Name", True, (200, 200, 200)), (rect.x + 100, y))
        self.screen.blit(font_sm.render("Ping", True, (200, 200, 200)), (rect.x + 300, y))
        y += 40
        pygame.draw.line(self.screen, (100, 100, 100), (rect.x + 10, y), (rect.right - 10, y))
        y += 10
        
        for pid, p in self.players.items():
            is_me = "(You)" if pid == self.my_id else ""
            self.screen.blit(font_sm.render(str(pid), True, (255, 255, 255)), (rect.x + 20, y))
            self.screen.blit(font_sm.render(f"Player {pid} {is_me}", True, (255, 255, 255)), (rect.x + 100, y))
            self.screen.blit(font_sm.render("0 ms", True, (150, 255, 150)), (rect.x + 300, y))
            y += 30

    def draw_ui(self):
        if not hasattr(self, "civ_state") or not self.civ_state: return
        font = pygame.font.SysFont("Arial", 14)
        x = SCREEN_WIDTH - 200
        y = 10
        
        title = font.render(f"Cities:", True, (255, 215, 0))
        self.screen.blit(title, (x, y))
        y += 20
        cities = self.civ_state.get("cities", {})
        if cities:
            for name, data in cities.items():
                text = font.render(f"- {name} ({len(data['members'])})", True, (255, 255, 255))
                self.screen.blit(text, (x, y))
                y += 20
        else:
            text = font.render("(None)", True, (150, 150, 150))
            self.screen.blit(text, (x, y))
            y += 20
            
        y += 10
        title = font.render(f"Countries:", True, (255, 215, 0))
        self.screen.blit(title, (x, y))
        y += 20
        countries = self.civ_state.get("countries", {})
        if countries:
            for name, data in countries.items():
                text = font.render(f"- {name}", True, (255, 255, 255))
                self.screen.blit(text, (x, y))
                y += 20
        else:
             text = font.render("(None)", True, (150, 150, 150))
             self.screen.blit(text, (x, y))

    def draw_connection_status(self):
        # Small indicator top-left
        font = pygame.font.SysFont("Arial", 16)
        status = "Connected" if getattr(self.net, 'connected', False) else "Connecting..."
        color = (50, 200, 50) if getattr(self.net, 'connected', False) else (200, 180, 50)
        text = font.render(status, True, (255, 255, 255))
        bg = pygame.Surface((text.get_width()+10, text.get_height()+6))
        bg.fill((30, 30, 30))
        pygame.draw.rect(bg, color, (0, 0, bg.get_width(), bg.get_height()), 2)
        self.screen.blit(bg, (10, 10))
        self.screen.blit(text, (15, 13))
