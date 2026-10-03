import pygame
import os
import random

# Create assets directory (absolute path to avoid CWD confusion)
# We assume this script is in d:/The civilithation game/tools/
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(BASE_DIR)
ASSETS_DIR = os.path.join(PROJECT_DIR, "assets")

if not os.path.exists(ASSETS_DIR):
    os.makedirs(ASSETS_DIR)

# Use dummy driver for headless generation
os.environ["SDL_VIDEODRIVER"] = "dummy"
pygame.init()
screen = pygame.display.set_mode((100, 100))

def save_surf(name, surf):
    path = os.path.join(ASSETS_DIR, name)
    pygame.image.save(surf, path)
    print(f"Saved {path}")

# 1. Player
surf = pygame.Surface((32, 32), pygame.SRCALPHA)
pygame.draw.circle(surf, (50, 100, 200), (16, 16), 15) # Body
pygame.draw.circle(surf, (200, 200, 200), (16, 16), 15, 2) # Outline
pygame.draw.circle(surf, (255, 255, 255), (10, 12), 4) # Eye L
pygame.draw.circle(surf, (255, 255, 255), (22, 12), 4) # Eye R
save_surf("player.png", surf)

# 2. Tree
surf = pygame.Surface((32, 32), pygame.SRCALPHA)
pygame.draw.circle(surf, (34, 139, 34), (16, 16), 14) # Leaves
pygame.draw.rect(surf, (139, 69, 19), (12, 20, 8, 12)) # Trunk
save_surf("tree.png", surf)

# 3. Rock
surf = pygame.Surface((32, 32), pygame.SRCALPHA)
pygame.draw.circle(surf, (128, 128, 128), (16, 16), 12)
pygame.draw.circle(surf, (100, 100, 100), (12, 12), 4)
save_surf("rock.png", surf)

# 4. Iron Ore
surf = pygame.Surface((32, 32), pygame.SRCALPHA)
pygame.draw.circle(surf, (100, 100, 100), (16, 16), 12) # Stone base
pygame.draw.circle(surf, (180, 80, 80), (10, 10), 4) # Ore bits
pygame.draw.circle(surf, (180, 80, 80), (20, 15), 3)
pygame.draw.circle(surf, (180, 80, 80), (14, 22), 4)
save_surf("iron_ore.png", surf)

# 5. Gold Ore
surf = pygame.Surface((32, 32), pygame.SRCALPHA)
pygame.draw.circle(surf, (100, 100, 100), (16, 16), 12) # Stone base
pygame.draw.circle(surf, (255, 215, 0), (10, 10), 4) # Gold bits
pygame.draw.circle(surf, (255, 215, 0), (20, 15), 3)
pygame.draw.circle(surf, (255, 215, 0), (14, 22), 4)
save_surf("gold_ore.png", surf)

# 6. Wall
surf = pygame.Surface((32, 32))
surf.fill((100, 100, 100))
pygame.draw.rect(surf, (80, 80, 80), (0, 0, 32, 32), 2)
pygame.draw.line(surf, (80, 80, 80), (0, 16), (32, 16), 2)
pygame.draw.line(surf, (80, 80, 80), (16, 0), (16, 16), 2)
pygame.draw.line(surf, (80, 80, 80), (16, 16), (16, 32), 2)
save_surf("wall.png", surf)

# 7. Furnace
surf = pygame.Surface((32, 32))
surf.fill((60, 60, 60))
pygame.draw.rect(surf, (30, 30, 30), (0, 0, 32, 32), 2)
pygame.draw.circle(surf, (0, 0, 0), (16, 24), 6) # Hole
pygame.draw.rect(surf, (255, 100, 0), (12, 22, 8, 4)) # Fire
save_surf("furnace.png", surf)

# 8. Wheat (Item)
surf = pygame.Surface((32, 32), pygame.SRCALPHA)
pygame.draw.ellipse(surf, (255, 215, 0), (10, 5, 12, 22))
pygame.draw.line(surf, (200, 150, 0), (16, 5), (16, 27), 2)
save_surf("wheat.png", surf)

# 9. Pickaxe
surf = pygame.Surface((32, 32), pygame.SRCALPHA)
pygame.draw.line(surf, (139, 69, 19), (16, 16), (4, 28), 3) # Handle
pygame.draw.arc(surf, (100, 100, 100), (8, 8, 16, 16), 0, 3.14, 3) # Head
save_surf("pickaxe.png", surf)

# 10. Sword
surf = pygame.Surface((32, 32), pygame.SRCALPHA)
pygame.draw.line(surf, (139, 69, 19), (16, 26), (16, 30), 3) # Hilt
pygame.draw.line(surf, (100, 100, 100), (16, 6), (16, 26), 4) # Blade
pygame.draw.line(surf, (100, 100, 100), (12, 26), (20, 26), 2) # Guard
save_surf("sword.png", surf)

# 11. Farm (Building)
surf = pygame.Surface((32, 32))
surf.fill((139, 69, 19)) # Dirt
pygame.draw.rect(surf, (100, 50, 0), (0, 0, 32, 32), 1)
pygame.draw.line(surf, (100, 200, 100), (4, 8), (28, 8), 2) # Crop rows
pygame.draw.line(surf, (100, 200, 100), (4, 16), (28, 16), 2)
pygame.draw.line(surf, (100, 200, 100), (4, 24), (28, 24), 2)
save_surf("farm.png", surf)

# 12. Crafting Table (Building)
surf = pygame.Surface((32, 32))
surf.fill((160, 82, 45)) # Sienna
pygame.draw.rect(surf, (139, 69, 19), (0, 0, 32, 32), 2)
pygame.draw.line(surf, (100, 50, 0), (0, 16), (32, 16), 2) # Plank lines
pygame.draw.rect(surf, (200, 200, 200), (8, 8, 16, 16)) # Tools on top?
save_surf("crafting_table.png", surf)

# --- 3D Block Textures ---
# Grass Block
surf = pygame.Surface((32, 32))
surf.fill((50, 200, 50))
# Add noise
for _ in range(20):
    pygame.draw.rect(surf, (30, 150, 30), (random.randint(0,28), random.randint(0,28), 4, 4))
save_surf("grass.png", surf)

# Stone Block
surf = pygame.Surface((32, 32))
surf.fill((150, 150, 150))
for _ in range(10):
    pygame.draw.rect(surf, (100, 100, 100), (random.randint(0,28), random.randint(0,28), 6, 6))
save_surf("stone.png", surf)

# Wood Block
surf = pygame.Surface((32, 32))
surf.fill((139, 69, 19))
for i in range(0, 32, 8):
    pygame.draw.line(surf, (100, 50, 0), (0, i), (32, i), 2)
save_surf("wood.png", surf)

# 13. Coal Ore
surf = pygame.Surface((32, 32), pygame.SRCALPHA)
pygame.draw.circle(surf, (100, 100, 100), (16, 16), 12)  # Stone base
pygame.draw.circle(surf, (30, 30, 30), (10, 10), 4)  # Coal bits
pygame.draw.circle(surf, (20, 20, 20), (20, 15), 3)
pygame.draw.circle(surf, (25, 25, 25), (14, 22), 4)
save_surf("coal_ore.png", surf)

# 14. Oil Deposit
surf = pygame.Surface((32, 32), pygame.SRCALPHA)
pygame.draw.ellipse(surf, (10, 10, 10), (4, 8, 24, 16))  # Black puddle
pygame.draw.ellipse(surf, (0, 0, 0), (8, 10, 16, 12))  # Darker center
pygame.draw.circle(surf, (40, 40, 40), (12, 14), 2)  # Bubbles
pygame.draw.circle(surf, (40, 40, 40), (20, 16), 2)
save_surf("oil_deposit.png", surf)

# 15. Drill (Building)
surf = pygame.Surface((32, 32))
surf.fill((80, 80, 80))  # Metal grey
pygame.draw.rect(surf, (60, 60, 60), (0, 0, 32, 32), 2)
pygame.draw.rect(surf, (100, 100, 100), (12, 8, 8, 16))  # Drill bit
pygame.draw.circle(surf, (200, 200, 0), (16, 6), 3)  # Yellow light
save_surf("drill.png", surf)

# 16. Pump (Building)
surf = pygame.Surface((32, 32))
surf.fill((70, 70, 70))  # Dark metal
pygame.draw.rect(surf, (50, 50, 50), (0, 0, 32, 32), 2)
pygame.draw.circle(surf, (100, 100, 100), (16, 16), 8)  # Pump wheel
pygame.draw.line(surf, (0, 0, 0), (16, 8), (16, 28), 2)  # Pipe
save_surf("pump.png", surf)

# 17. Chemical Plant (Building)
surf = pygame.Surface((32, 32))
surf.fill((120, 120, 150))  # Blueish grey
pygame.draw.rect(surf, (80, 80, 100), (0, 0, 32, 32), 2)
pygame.draw.rect(surf, (200, 200, 0), (8, 8, 6, 10))  # Yellow tank
pygame.draw.rect(surf, (0, 200, 0), (18, 8, 6, 10))  # Green tank
pygame.draw.circle(surf, (255, 0, 0), (16, 24), 4)  # Red warning light
save_surf("chemical_plant.png", surf)

# 18. Tower (Building)
surf = pygame.Surface((32, 32))
surf.fill((90, 90, 90))  # Stone grey
pygame.draw.rect(surf, (70, 70, 70), (0, 0, 32, 32), 2)
pygame.draw.rect(surf, (110, 110, 110), (8, 4, 4, 4))  # Crenellations
pygame.draw.rect(surf, (110, 110, 110), (20, 4, 4, 4))
pygame.draw.rect(surf, (60, 60, 60), (12, 20, 8, 8))  # Window
save_surf("tower.png", surf)

# 19. Town Center (Building)
surf = pygame.Surface((32, 32))
surf.fill((150, 100, 80))  # Brown/brick
pygame.draw.rect(surf, (120, 80, 60), (0, 0, 32, 32), 2)
pygame.draw.rect(surf, (200, 180, 0), (4, 4, 24, 6))  # Gold roof
pygame.draw.rect(surf, (80, 50, 30), (12, 16, 8, 12))  # Door
save_surf("town_center.png", surf)

# 20. Advanced Workbench (Building)
surf = pygame.Surface((32, 32))
surf.fill((140, 90, 60))  # Wood
pygame.draw.rect(surf, (110, 70, 40), (0, 0, 32, 32), 2)
pygame.draw.rect(surf, (100, 100, 100), (4, 4, 8, 8))  # Metal anvil
pygame.draw.line(surf, (200, 200, 200), (16, 8), (22, 14), 2)  # Tool
pygame.draw.rect(surf, (255, 100, 0), (20, 20, 8, 8))  # Fire/forge
save_surf("advanced_workbench.png", surf)

print("Done generating assets.")
pygame.quit()
