import random
from server.civilization import CivManager

class WorldState:
    def __init__(self):
        self.players = {}  # id -> {x, y, inventory}
        self.resources = {} # (x, y) -> type: "tree"|"rock"
        self.buildings = {} # (x, y) -> type: "wall"|...
        self.civs = CivManager()
        self._generate_resources()

    def _generate_resources(self):
        # World is 100x100 tiles * 32 = 3200x3200
        W, H = 3200, 3200
        
        def add(count, rtype):
            for _ in range(count):
                rx, ry = random.randint(0, W-1), random.randint(0, H-1)
                self.resources[f"{rx},{ry}"] = {"x": rx, "y": ry, "type": rtype}
        
        # Much higher density for a "full" feel
        add(400, "tree")
        add(200, "rock")
        add(100, "iron_ore")
        add(50, "gold_ore")
        add(100, "coal_ore")
        
        # Generate Oil (Rare)
        add(20, "oil_deposit")

    def regenerate_resources(self):
        # Keep populations stable
        types = {
            "tree": 400,
            "rock": 200,
            "iron_ore": 100,
            "gold_ore": 50,
            "coal_ore": 100
        }
        
        current_counts = {}
        for r in self.resources.values():
            t = r["type"]
            current_counts[t] = current_counts.get(t, 0) + 1
            
        W, H = 3200, 3200
        changes = False
        
        for rtype, target in types.items():
            count = current_counts.get(rtype, 0)
            if count < target:
                diff = target - count
                # Regenerate a batch (e.g. 5 at a time) to avoid spikes
                to_add = min(diff, 5)
                for _ in range(to_add):
                    x = random.randint(0, W)
                    y = random.randint(0, H)
                    # Simple check to avoid exact overlap (not perfect but fast)
                    if f"{x},{y}" not in self.resources:
                        self.resources[f"{x},{y}"] = {"x": x, "y": y, "type": rtype}
                        changes = True
        return changes

    def add_player(self, player_id):
        self.players[player_id] = {
            "x": 500, 
            "y": 500,
            "inventory": {"wood": 0, "stone": 0}
        }

    def remove_player(self, player_id):
        self.players.pop(player_id, None)
