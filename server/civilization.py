class City:
    def __init__(self, name, leader_id, x, y):
        self.name = name
        self.leader = leader_id
        self.members = [leader_id]
        self.buildings = []
        self.x = x
        self.y = y
        # Research & Economy
        self.tier = 1
        self.storage = {"wood": 0, "stone": 0, "iron_ingot": 0, "gold_ingot": 0}

    def get_radius(self):
        # Tier 1: 300
        # Tier 2: 500 (+200)
        return 300 + (self.tier - 1) * 200

    def to_dict(self):
        return {
            "name": self.name,
            "leader": self.leader,
            "members": self.members,
            "x": self.x,
            "y": self.y,
            "tier": self.tier,
            "storage": self.storage
        }

class Country:
    def __init__(self, name, leader_id):
        self.name = name
        self.leader = leader_id
        self.leader = leader_id
        self.cities = []
        self.techs = [] # List of researched technologies

    def to_dict(self):
        return {
            "name": self.name,
            "leader": self.leader,
            "cities": [c.name for c in self.cities],
            "techs": self.techs
        }

class CivManager:
    def __init__(self):
        self.cities = {} # name -> City
        self.countries = {} # name -> Country

    def create_city(self, name, leader_id, x, y):
        if name in self.cities:
            return False
        self.cities[name] = City(name, leader_id, x, y)
        return True

    def join_city(self, name, player_id):
        if name not in self.cities:
            return False
        city = self.cities[name]
        if player_id not in city.members:
            city.members.append(player_id)
            return True
        return False

    def create_country(self, name, leader_id):
        if name in self.countries:
            return False
        self.countries[name] = Country(name, leader_id)
        return True
    
    def join_country(self, city_name, country_name, player_id):
        # Validation
        if city_name not in self.cities or country_name not in self.countries:
            return False
        
        city = self.cities[city_name]
        country = self.countries[country_name]
        
        # Only city leader can join a country (for now)
        if city.leader != player_id:
            return False
            
        # Already in a country? (Not tracked explicitly yet, but let's assume one)
        # Add to country list
        if city_name not in [c.name for c in country.cities]:
            country.cities.append(city)
            return True
        return False
    
    def get_state(self):
        return {
            "cities": {n: c.to_dict() for n, c in self.cities.items()},
            "countries": {n: c.to_dict() for n, c in self.countries.items()}
        }