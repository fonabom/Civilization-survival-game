import socket
import threading
from server.world_state import WorldState
from shared.protocol import encode
from shared.structures import STRUCTURES
from shared.items import CRAFTING_RECIPES

HOST = "127.0.0.1"
PORT = 5555

def main():
    world = WorldState()

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1) # Fix "Address currently in use"
    server.bind((HOST, PORT))
    server.listen()

    print("Server started")

    player_counter = 0
    clients = {} # {player_id: conn}
    clients_lock = threading.Lock()

    def broadcast(data, exclude_id=None):
        encoded = encode(data)
        with clients_lock:
            for pid, conn in clients.items():
                if pid == exclude_id:
                    continue
                try:
                    conn.send(encoded)
                except:
                    pass # Connection issues handled in their own threads

    def handle_client(conn, player_id):
        with clients_lock:
            clients[player_id] = conn
        
        world.add_player(player_id)
        from shared.protocol import Protocol, encode
        proto = Protocol()
        
        # Send welcome with ID
        conn.send(encode({
            "type": "welcome",
            "id": player_id
        }))

        # Send initial full state immediately
        conn.send(encode({
            "type": "state",
            "players": world.players,
            "resources": world.resources,
            "buildings": world.buildings,
            "civs": world.civs.get_state()
        }))
        
        try:
            while True:
                data = conn.recv(1024)
                if not data:
                    break

                messages = proto.receive(data)
                for msg in messages:
                    if msg["type"] == "move":
                        dx = msg["dx"]
                        dy = msg["dy"]
                        
                        # Current pos
                        cx = world.players[player_id]["x"]
                        cy = world.players[player_id]["y"]
                        
                        nx = cx + dx
                        ny = cy + dy
                        
                        # Collision with Buildings (Walls, Towers, Furnaces)
                        # Simple grid collision: Check if center of player is inside a building tile
                        # Building coords are in Grid (x, y) but stored as world coords * TILE_SIZE? 
                        # Wait, world.buildings stores {x, y} which are GRID coordinates.
                        # Player stores {x, y} which are PIXEL coordinates.
                        # TILE_SIZE is 32.
                        
                        TILE_SIZE = 32
                        grid_x = int(nx // TILE_SIZE)
                        grid_y = int(ny // TILE_SIZE)
                        
                        collision = False
                        if f"{grid_x},{grid_y}" in world.buildings:
                            # Strict blocking? Only if not a farm
                            b_type = world.buildings[f"{grid_x},{grid_y}"].get("type", "wall")
                            if b_type != "farm":
                                collision = True
                        
                        if not collision:
                            world.players[player_id]["x"] = nx
                            world.players[player_id]["y"] = ny
                    
                    elif msg["type"] == "chat":
                        text = msg["text"]
                        if text == "/wipe":
                            # Reset World
                            world.resources = {}
                            world.buildings = {}
                            from server.world_state import WorldState
                            # Re-init world state logic if needed or just clear
                            # Actually better to just call generate
                            world._generate_resources() # Use internal method
                            broadcast({"type": "notification", "msg": "WORLD WIPED!"})
                            
                            # Broadcast new state
                            broadcast({
                                "type": "state", 
                                "players": world.players,
                                "resources": world.resources,
                                "buildings": world.buildings,
                                "civs": world.civs.get_state()
                            })
                        elif text == "/regen":
                            world.regenerate_resources()
                            broadcast({"type": "notification", "msg": "Resources Regenerated!"})
                            broadcast({
                                "type": "state", 
                                "players": world.players,
                                "resources": world.resources,
                                "buildings": world.buildings,
                                "civs": world.civs.get_state()
                            })
                        else:
                            # Broadcast chat to all
                            broadcast({
                                "type": "chat",
                                "id": player_id,
                                "msg": text
                            })

                    elif msg["type"] == "research":
                        # Upgrade City Tier
                        city_name = msg.get("city")
                        target_city = None
                        
                        if city_name == "AUTO_FIND":
                            # Find city led by player
                            for c in world.civs.cities.values():
                                if c.leader == player_id:
                                    target_city = c
                                    break
                        elif city_name in world.civs.cities:
                            target_city = world.civs.cities[city_name]
                            
                        if target_city:
                            city = target_city
                            if city.leader == player_id:
                                # City Research
                                if city.tier == 1:
                                    inv = world.players[player_id]["inventory"]
                                    if inv.get("wood", 0) >= 100 and inv.get("stone", 0) >= 100:
                                        inv["wood"] -= 100
                                        inv["stone"] -= 100
                                        city.tier = 2
                                        conn.send(encode({"type": "notification", "msg": "City Tier 2! Radius -> 500"}))
                                        broadcast({"type": "notification", "msg": f"City {city.name} reached Tier 2!"})
                                    else:
                                        conn.send(encode({"type": "notification", "msg": "Need 100 Wood, 100 Stone!"}))
                                else:
                                    conn.send(encode({"type": "notification", "msg": "Max Tier reached!"}))
                            else:
                                conn.send(encode({"type": "notification", "msg": "Only leader can upgrade!"}))
                        elif msg.get("scope") == "country":
                            # Country Research
                            country_name = msg.get("country")
                            target_country = None
                            
                            if country_name == "AUTO_FIND":
                                for c in world.civs.countries.values():
                                    if c.leader == player_id:
                                        target_country = c
                                        break
                            elif country_name in world.civs.countries:
                                target_country = world.civs.countries[country_name]
                                
                            if target_country:
                                country = target_country
                                if country.leader == player_id:
                                    tech_name = msg.get("tech", "industrialization") # Default or specific
                                    
                                    if tech_name in country.techs:
                                        conn.send(encode({"type": "notification", "msg": "Already researched!"}))
                                    
                                    elif tech_name == "chemistry":
                                        # Cost: 20 Oil Barrels
                                        cost_oil = 20
                                        inv = world.players[player_id]["inventory"]
                                        if inv.get("oil_barrel", 0) >= cost_oil:
                                            inv["oil_barrel"] -= cost_oil
                                            country.techs.append(tech_name)
                                            conn.send(encode({"type": "notification", "msg": f"Researched {tech_name}!"}))
                                            broadcast({"type": "notification", "msg": f"Country {country.name} unlocked {tech_name}!"})
                                        else:
                                            conn.send(encode({"type": "notification", "msg": f"Need {cost_oil} Oil Barrels!"}))

                                    elif tech_name == "industrialization": # Existing
                                        # Costs
                                        cost_iron = 50
                                        cost_gold = 50
                                        
                                        inv = world.players[player_id]["inventory"]
                                        if inv.get("iron_ingot", 0) >= cost_iron and inv.get("gold_ingot", 0) >= cost_gold:
                                            inv["gold_ingot"] -= cost_gold
                                            
                                            country.techs.append(tech_name)
                                            conn.send(encode({"type": "notification", "msg": f"Researched {tech_name}!"}))
                                            broadcast({"type": "notification", "msg": f"Country {country.name} unlocked {tech_name}!"})
                                        else:
                                            conn.send(encode({"type": "notification", "msg": f"Need {cost_iron} Iron, {cost_gold} Gold!"}))
                                else:
                                    conn.send(encode({"type": "notification", "msg": "Only Country Leader!"}))
                            else:
                                 conn.send(encode({"type": "notification", "msg": "Country not found!"}))
                        else:
                             conn.send(encode({"type": "notification", "msg": "City not found!"}))

                    elif msg["type"] == "gather":
                        # Check distance to closest resource
                        px = world.players[player_id]["x"]
                        py = world.players[player_id]["y"]
                        inv = world.players[player_id].setdefault("inventory", {})
                        
                        to_remove = None
                        for key, res in world.resources.items():
                            dist = ((px - res["x"])**2 + (py - res["y"])**2)**0.5
                            if dist < 50: # Interaction range
                                to_remove = key
                                rtype = res["type"]
                                
                                # TOOL LOGIC
                                amount = 1
                                # Check best tool in inventory
                                has_axe = inv.get("iron_axe", 0) > 0 or inv.get("axe", 0) > 0
                                has_pick = inv.get("iron_pickaxe", 0) > 0 or inv.get("pickaxe", 0) > 0
                                
                                if rtype == "tree":
                                    if inv.get("iron_axe", 0) > 0: amount = 3
                                    elif inv.get("axe", 0) > 0: amount = 2
                                    inv["wood"] = inv.get("wood", 0) + amount
                                    
                                elif rtype in ["rock", "stone"]: 
                                    if inv.get("iron_pickaxe", 0) > 0: amount = 3
                                    elif inv.get("pickaxe", 0) > 0: amount = 2
                                    inv["stone"] = inv.get("stone", 0) + amount
                                
                                elif rtype in ["iron_ore", "gold_ore", "coal_ore", "oil_deposit"]:
                                    if inv.get("iron_pickaxe", 0) > 0: amount = 2
                                    elif inv.get("pickaxe", 0) > 0: amount = 1 # Basic pickaxe ok
                                    else: amount = 0 # Need pickaxe for ores? Let's say yes for realism, or 0 if strict. 
                                    # For gameplay, let's allow hand mining at 1, but tools give 2.
                                    if amount == 0: amount = 1 
                                    
                                    key_name = rtype
                                    if rtype == "coal_ore": key_name = "coal"
                                    elif rtype == "oil_deposit": key_name = "oil_barrel"
                                    
                                    inv[key_name] = inv.get(key_name, 0) + amount
                                
                                conn.send(encode({"type": "notification", "msg": f"+{amount} {rtype}"}))
                                break
                        
                        if to_remove:
                            del world.resources[to_remove]
                        else:
                            # 2. Interact with Buildings (Farm)
                            px = world.players[player_id]["x"]
                            py = world.players[player_id]["y"]
                            # print(f"[Debug] Player {player_id} trying to gather at {px},{py}")
                            
                            found_farm = False
                            for b_pos, b_data in world.buildings.items():
                                bx, by = b_data["x"]*32 + 16, b_data["y"]*32 + 16 # Center of tile
                                dist = ((px - bx)**2 + (py - by)**2)**0.5
                                
                                # print(f"Checking building {b_data['type']} at {bx},{by} (Dist: {dist})")
                                
                                if dist < 64: # Increased radius (2 blocks)
                                    if b_data["type"] == "farm":
                                        found_farm = True
                                        import time
                                        now = time.time()
                                        last = b_data.get("last_harvest", 0)
                                        # 10 seconds cooldown
                                        if now - last > 10: 
                                            b_data["last_harvest"] = now
                                            inv = world.players[player_id].setdefault("inventory", {})
                                            inv["wheat"] = inv.get("wheat", 0) + 1
                                            conn.send(encode({"type": "notification", "msg": "+1 Wheat"}))
                                            # print(f"Harvested Farm at {b_pos}")
                                        else:
                                            wait = int(10 - (now - last))
                                            conn.send(encode({"type": "notification", "msg": f"Growing... {wait}s"}))
                                    break
                            
                            # if not found_farm:
                            #    print("No farm found nearby.")

                    elif msg["type"] == "build":
                        # msg = {"type": "build", "structure": "wall", "x": x, "y": y}
                        # Build at player's current position
                        from shared.structures import STRUCTURES
                        
                        structure_type = msg["structure"]
                        if structure_type in STRUCTURES:
                            cost = STRUCTURES[structure_type]
                            inv = world.players[player_id].setdefault("inventory", {})
                            
                            # Check cost
                            if all(inv.get(res, 0) >= amount for res, amount in cost.items()):
                                # Tech Check
                                if structure_type in ["drill", "advanced_workbench", "pump", "chemical_plant"]:
                                    # Find country
                                    has_tech = False
                                    required_tech = "industrialization"
                                    if structure_type in ["chemical_plant"]: required_tech = "chemistry" # Chemistry tier
                                    
                                    user_country = None
                                    for country in world.civs.countries.values():
                                         owns_city = False
                                         for c in country.cities:
                                             if c.leader == player_id:
                                                 owns_city = True
                                                 break
                                         if owns_city or country.leader == player_id:
                                             user_country = country
                                             break
                                    
                                    if user_country and required_tech in user_country.techs:
                                        has_tech = True
                                    
                                    if not has_tech:
                                        conn.send(encode({"type": "notification", "msg": f"Need '{required_tech}' (Country Tech)!"}))
                                        can_build = False # Fail immediately
                                        # Skip rest
                                        continue
                                
                                bx = world.players[player_id]["x"]
                                by = world.players[player_id]["y"]
                                
                                # Convert to Grid
                                gx = int(bx // 32)
                                gy = int(by // 32)
                                
                                # Dimensions
                                w = cost.get("w", 1)
                                h = cost.get("h", 1)
                                
                                can_build = True
                                
                                # Check overlapping tiles
                                for dx in range(w):
                                    for dy in range(h):
                                        key = f"{gx+dx},{gy+dy}"
                                        if key in world.occupied or key in world.buildings:
                                            can_build = False
                                            break
                                    if not can_build: break
                                    
                                if not can_build:
                                     conn.send(encode({"type": "notification", "msg": "Space occupied!"}))
                                
                                # Check Player Collision (Don't build on top of self or others)
                                if can_build:
                                    # Center of the whole structure
                                    struct_cx = (gx * 32) + (w * 32 / 2)
                                    struct_cy = (gy * 32) + (h * 32 / 2)
                                    # Radius approx
                                    struct_r = max(w, h) * 16 
                                    
                                    for p in world.players.values():
                                        dist = ((p["x"] - struct_cx)**2 + (p["y"] - struct_cy)**2)**0.5
                                        if dist < (struct_r + 10): # Simple radius check
                                            can_build = False
                                            conn.send(encode({"type": "notification", "msg": "Blocked by player!"}))
                                            break
                                
                                if can_build:
                                    # Territory Check (Center point ok?)
                                    for city in world.civs.cities.values():
                                        dist = ((bx - city.x)**2 + (by - city.y)**2)**0.5
                                        if dist < city.get_radius(): # Territory
                                            if player_id not in city.members:
                                                can_build = False
                                                conn.send(encode({"type": "notification", "msg": "Enemy territory!"}))
                                                break
                                
                                if can_build:
                                    # Special checks for Town Center
                                    if structure_type == "town_center":
                                        # Must be leader of a city
                                        user_city = None
                                        for city in world.civs.cities.values():
                                            if city.leader == player_id:
                                                user_city = city
                                                break
                                        
                                        if not user_city:
                                            can_build = False
                                            conn.send(encode({"type": "notification", "msg": "Must lead a city!"}))
                                        else:
                                            # Check if already has one? (Simple checks for now: just allow multiple or assume good faith)
                                            # Ideally scan buildings for type town_center tied to this city... 
                                            # But buildings don't store city ID efficiently yet.
                                            pass

                                if can_build:
                                    # Deduct
                                    for res, amount in cost.items():
                                        inv[res] -= amount
                                    
                                    # Place building (Grid Coords)
                                    # Store dimensions for client rendering
                                    world.buildings[f"{gx},{gy}"] = {
                                        "x": gx, "y": gy, 
                                        "type": structure_type, 
                                        "owner": player_id,
                                        "w": w, "h": h
                                    }
                                    
                                    # Mark Occupied
                                    for dx in range(w):
                                        for dy in range(h):
                                            world.occupied.add(f"{gx+dx},{gy+dy}")
                                            
                                    conn.send(encode({"type": "notification", "msg": f"Built {structure_type}!"}))
                            else:
                                 conn.send(encode({"type": "notification", "msg": "Not enough resources!"}))

                    elif msg["type"] == "create_city":
                        # Check limit
                        already_owns = any(c.leader == player_id for c in world.civs.cities.values())
                        if already_owns:
                            conn.send(encode({"type": "notification", "msg": "You already own a city!"}))
                        else:
                            success = world.civs.create_city(msg["name"], player_id, world.players[player_id]["x"], world.players[player_id]["y"])
                            if not success:
                                conn.send(encode({"type": "notification", "msg": "Name already taken!"}))
                    
                    elif msg["type"] == "create_country":
                        already_owns = any(c.leader == player_id for c in world.civs.countries.values())
                        if already_owns:
                            conn.send(encode({"type": "notification", "msg": "You already own a country!"}))
                        else:
                             success = world.civs.create_country(msg["name"], player_id)
                             if not success:
                                conn.send(encode({"type": "notification", "msg": "Name already taken!"}))

                    elif msg["type"] == "join_country":
                        # msg = {"type": "join_country", "city": "Name", "country": "Name"}
                        if world.civs.join_country(msg["city"], msg["country"], player_id):
                            conn.send(encode({"type": "notification", "msg": f"Joined {msg['country']}!"}))
                        else:
                            conn.send(encode({"type": "notification", "msg": "Failed to join country!"}))

                    elif msg["type"] == "attack":
                        target_id = msg.get("target_id")
                        if target_id and target_id in world.players:
                             attacker = world.players[player_id]
                             target = world.players[target_id]
                             
                             # Range Check
                             dx = target["x"] - attacker["x"]
                             dy = target["y"] - attacker["y"]
                             dist = (dx**2 + dy**2)**0.5
                             
                             inv = attacker.setdefault("inventory", {})
                             
                             # Weapon Check
                             damage = 5 # Fists
                             max_range = 40
                             
                             if inv.get("pistol", 0) > 0:
                                 # Firearm Logic
                                 if inv.get("ammo", 0) > 0:
                                     damage = 40
                                     max_range = 300
                                     inv["ammo"] -= 1 # Consume ammo
                                     conn.send(encode({"type": "notification", "msg": "Bang! -1 Ammo"}))
                                 else:
                                     conn.send(encode({"type": "notification", "msg": "Click... No Ammo!"}))
                                     max_range = 10 # Pistol whip?
                             elif inv.get("iron_sword", 0) > 0: 
                                 damage = 20
                                 max_range = 50
                             elif inv.get("sword", 0) > 0: 
                                 damage = 10
                                 max_range = 50
                             
                             if dist < max_range:
                                 # Hit!
                                 conn.send(encode({"type": "notification", "msg": f"Hit for {damage} dmg!"}))
                                 # Apply damage (Not implemented in player struct yet, just notify)
                                 # TODO: self.world.damage_player(target_id, damage)
                             else:
                                 conn.send(encode({"type": "notification", "msg": "Out of range!"}))

                    elif msg["type"] == "join_city":
                        # msg = {"type": "join_city", "name": "Name"}
                        if world.civs.join_city(msg["name"], player_id):
                             conn.send(encode({"type": "notification", "msg": f"Joined {msg['name']}!"}))
                        else:
                             conn.send(encode({"type": "notification", "msg": "Failed to join city!"}))
                        
                    elif msg["type"] == "smelt":
                        inv = world.players[player_id].setdefault("inventory", {})
                        action = msg["action"]
                        
                        # Check for Furnace proximity
                        px, py = world.players[player_id]["x"], world.players[player_id]["y"]
                        near_furnace = False
                        for b_pos, b_data in world.buildings.items():
                            if b_data["type"] == "furnace":
                                dist = ((px - b_data["x"]*32)**2 + (py - b_data["y"]*32)**2)**0.5
                                if dist < 64: # Range
                                    near_furnace = True
                                    break
                        
                        if not near_furnace:
                            conn.send(encode({"type": "notification", "msg": "You must be near a Furnace!"}))
                        else:
                            mult = 1  # Check bonuses (Country Tech)
                            # Find player's country
                            for country in world.civs.countries.values():
                                # If leader of country OR member of a city in that country
                                # For now, check if leader of a city in that country
                                owns_city = False
                                for c in country.cities:
                                    if c.leader == player_id:  # Simplified check: is city leader
                                        owns_city = True
                                        break
                                if owns_city or country.leader == player_id:
                                    if "industrialization" in country.techs:
                                        mult = 2
                                    break

                            if inv.get("coal", 0) < 1:
                                conn.send(encode({"type": "notification", "msg": "Need 1 Coal for fuel!"}))
                            else:
                                if action == "smelt_iron":
                                    if inv.get("iron_ore", 0) >= 1:
                                        inv["coal"] -= 1
                                        inv["iron_ore"] -= 1
                                        inv["iron_ingot"] = inv.get("iron_ingot", 0) + (1 * mult)
                                        conn.send(encode({"type": "notification", "msg": f"Smelted {1*mult} Iron Ingot!"}))
                                    else:
                                        conn.send(encode({"type": "notification", "msg": "Need 1 Iron Ore!"}))
                                        
                                elif action == "smelt_gold":
                                    if inv.get("gold_ore", 0) >= 1:
                                        inv["coal"] -= 1
                                        inv["gold_ore"] -= 1
                                        inv["gold_ingot"] = inv.get("gold_ingot", 0) + (1 * mult)
                                        conn.send(encode({"type": "notification", "msg": f"Smelted {1*mult} Gold Ingot!"}))
                                    else:
                                        conn.send(encode({"type": "notification", "msg": "Need 1 Gold Ore!"}))
                                         
                    elif msg["type"] == "craft":
                        item = msg["item"]
                        if item in CRAFTING_RECIPES:
                            cost = CRAFTING_RECIPES[item]
                            inv = world.players[player_id].setdefault("inventory", {})
                            
                            can_craft = True
                            for res, amt in cost.items():
                                if inv.get(res, 0) < amt:
                                    can_craft = False
                                    break
                            
                            if can_craft:
                                for res, amt in cost.items():
                                    inv[res] -= amt
                                inv[item] = inv.get(item, 0) + 1
                                conn.send(encode({"type": "notification", "msg": f"Crafted {item}!"}))
                            else:
                                conn.send(encode({"type": "notification", "msg": "Missing resources!"}))

                # Send state update
                conn.send(encode({
                    "type": "state",
                    "players": world.players,
                    "resources": world.resources,
                    "buildings": world.buildings,
                    "civs": world.civs.get_state()
                }))
        finally:
            with clients_lock:
                if player_id in clients:
                    del clients[player_id]
            world.remove_player(player_id)
            conn.close()
    
    def game_loop():
        import time
        import pygame # Assuming pygame is available for Rect and collidepoint
        last_regen = time.time() # Initialize last_regen
        while True:
            # Resource Regen Loop
            if time.time() - last_regen > 60:
                last_regen = time.time()
                if len(world.resources) < 3000:
                    print("Regenerating resources...")
                    world.regenerate_resources()
                    broadcast({"type": "notification", "msg": "Nature grows..."})
                    broadcast({
                        "type": "state", 
                        "players": world.players,
                        "resources": world.resources,
                        "buildings": world.buildings,
                        "civs": world.civs.get_state()
                    })
            
            # Drill Loop (Every 1 second check, but act every 5s)
            now = time.time()
            for b_key, b_data in world.buildings.items():
                if b_data["type"] == "drill":
                    last_drill = b_data.get("last_drill", 0)
                    if now - last_drill > 5:
                        b_data["last_drill"] = now
                        # Find resource under drill
                        dx = b_data["x"] * 32
                        dy = b_data["y"] * 32
                        drill_rect = pygame.Rect(dx, dy, 32, 32)
                        
                        # Check resources collision
                        mined_type = None
                        for r_key, r_data in world.resources.items():
                            rx, ry = r_data["x"], r_data["y"]
                            # Resource is point or small circle. Let's assume point.
                            # Check strictly inside
                            if drill_rect.collidepoint(rx, ry):
                                mined_type = r_data["type"]
                                break
                        
                        if mined_type:
                            owner = b_data.get("owner")
                            if owner and owner in world.players:
                                inv = world.players[owner].setdefault("inventory", {})
                                
                                item = "stone" # Default
                                if mined_type == "tree": item = "wood"
                                elif mined_type == "rock": item = "stone"
                                elif mined_type == "iron_ore": item = "iron_ore"
                                elif mined_type == "gold_ore": item = "gold_ore"
                                elif mined_type == "coal_ore": item = "coal"
                                elif mined_type == "oil_deposit": item = "oil_barrel"
                                
                                inv[item] = inv.get(item, 0) + 1
                                # Notify owner periodically? Maybe too spammy.
                                # Send only if connected? 
                                # Let's not spam notifications per drill tick.
                                
                                # Optional: Send sound/particle effect packet?
                                pass

            time.sleep(1/60)

    threading.Thread(target=game_loop, daemon=True).start()

    while True:
        conn, addr = server.accept()
        pid = str(player_counter)
        player_counter += 1

        threading.Thread(
            target=handle_client,
            args=(conn, pid),
            daemon=True
        ).start()

