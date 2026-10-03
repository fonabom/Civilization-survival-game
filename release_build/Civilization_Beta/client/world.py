import pygame
import random
from client.settings import TILE_SIZE, WORLD_WIDTH, WORLD_HEIGHT

GRASS = 0
STONE = 1

class World:
    def __init__(self):
        self.tiles = [
            [random.choices([GRASS, STONE], weights=[80, 20])[0]
             for _ in range(WORLD_WIDTH)]
            for _ in range(WORLD_HEIGHT)
        ]
        self.resources = {} # Synchronized from server
        self.buildings = {}
        
        # Load Assets
        self.assets = {}
        try:
            import os
            asset_dir = "assets"
            if os.path.exists(asset_dir):
                for f in os.listdir(asset_dir):
                    if f.endswith(".png"):
                        name = f
                        path = os.path.join(asset_dir, f)
                        try:
                            img = pygame.image.load(path).convert_alpha()
                            # Scale to TILE_SIZE? Maybe not, rely on asset being correct size.
                            # But let's scale just in case for uniformity if needed, or keep original.
                            # For now, keep original, assuming gen_assets made them 32x32.
                            self.assets[name] = img
                            # Also store without extension for easier lookup
                            self.assets[name.split('.')[0]] = img
                        except Exception as e:
                            print(f"Failed to load asset {f}: {e}")
            else:
                print("Warning: 'assets' directory not found.")
        except Exception as e:
            print(f"Asset loading error: {e}")

    def is_blocked(self, x, y):
        tile_x = int(x // TILE_SIZE)
        tile_y = int(y // TILE_SIZE)

        if tile_x < 0 or tile_y < 0:
            return True
        if tile_x >= WORLD_WIDTH or tile_y >= WORLD_HEIGHT:
            return True

        return self.tiles[tile_y][tile_x] == STONE

    def draw(self, screen, camera):
        for y in range(WORLD_HEIGHT):
            for x in range(WORLD_WIDTH):
                tile = self.tiles[y][x]

                world_x = x * TILE_SIZE
                world_y = y * TILE_SIZE
                screen_x, screen_y = camera.apply(world_x, world_y)

                color = (50, 160, 50) if tile == GRASS else (100, 100, 100)

                pygame.draw.rect(
                    screen,
                    color,
                    (screen_x, screen_y, TILE_SIZE, TILE_SIZE)
                )
                
                # Draw grid border
                pygame.draw.rect(
                    screen,
                    (30, 100, 30) if tile == GRASS else (80, 80, 80),
                    (screen_x, screen_y, TILE_SIZE, TILE_SIZE),
                    1
                )
        
        # Draw Resources
        for res in self.resources.values():
            rx = int(res["x"] - camera.x)
            ry = int(res["y"] - camera.y)
            rtype = res["type"]
            
            # 1. Try Asset
            asset = self.assets.get(rtype + ".png")
            if not asset: asset = self.assets.get(rtype)
            
            if asset:
                 screen.blit(asset, (rx, ry))
            else:
                 # 2. Fallback Shapes
                 if rtype == "tree":
                     color = (34, 139, 34)
                     pygame.draw.circle(screen, color, (rx, ry), 10)
                 elif rtype == "rock":
                     color = (128, 128, 128)
                     pygame.draw.circle(screen, color, (rx, ry), 8)
                 elif "ore" in rtype:
                     color = (139, 0, 0) # Fallback
                     if "iron" in rtype: color = (100, 100, 100) # Wait, iron is usually greyish? Rock is grey. Iron Ore is rusty.
                     elif "gold" in rtype: color = (255, 215, 0)
                     elif "coal" in rtype: color = (20, 20, 20)
                     
                     pygame.draw.circle(screen, color, (rx, ry), 6)
                 
                 elif rtype == "oil_deposit":
                     color = (10, 10, 10) # Black
                     pygame.draw.ellipse(screen, color, (rx-12, ry-8, 24, 16))
                 else: # Default fallback if no specific type matches
                     color = (150, 150, 150) # default rock
                     pygame.draw.circle(screen, color, (rx, ry), 15)

        # Draw Buildings
        for b in self.buildings.values():
            bx = int(b["x"] * TILE_SIZE - camera.x)
            by = int(b["y"] * TILE_SIZE - camera.y)
            color = (100, 100, 100) # Wall color
            if b["type"] == "crafting_table":
                color = (150, 100, 50)
            
            # Draw Texture if available
            asset = self.assets.get(b["type"] + ".png")
            # Or try without png extension if dict keys differ
            if not asset: asset = self.assets.get(b["type"])
            
            if asset:
                 screen.blit(asset, (bx, by))
            else:
                 pygame.draw.rect(screen, color, (bx, by, TILE_SIZE, TILE_SIZE))
