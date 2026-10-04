from shared.roles import DEFAULT_ROLE, MAX_TAX, ROLE_RIGHTS, can as role_can
from shared.techs import age_of


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
        # b10: roles of the members, the tax rate and how many times the city
        # changed hands in a war (it is a nice thing to brag about)
        self.roles = {}            # player_id (str) -> role code
        self.tax = 0               # percent of gathered resources for the fund
        self.captured = 0          # how often the city was taken by force

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
            "storage": self.storage,
            "roles": dict(self.roles),
            "tax": self.tax,
            "captured": self.captured,
        }

    # ------------------------------------------------------------- b10 roles
    def role_of(self, player_id) -> str:
        from shared.roles import role_of as _role_of
        return _role_of(self.roles, player_id, self.leader)

    def may(self, player_id, right: str) -> bool:
        return role_can(self.role_of(player_id), right)

    def city_radius(self):
        return self.get_radius()

    def to_save(self):
        data = self.to_dict()
        data["buildings"] = list(self.buildings)
        return data

    @classmethod
    def from_save(cls, data):
        city = cls(data["name"], data.get("leader"), data.get("x", 0), data.get("y", 0))
        city.members = list(data.get("members", [city.leader]))
        city.tier = int(data.get("tier", 1))
        city.storage = dict(data.get("storage", city.storage))
        city.buildings = list(data.get("buildings", []))
        city.roles = {str(pid): role for pid, role in (data.get("roles") or {}).items()
                      if role in ROLE_RIGHTS}
        city.tax = max(0, min(MAX_TAX, int(data.get("tax", 0) or 0)))
        city.captured = int(data.get("captured", 0) or 0)
        return city

class Country:
    def __init__(self, name, leader_id):
        self.name = name
        self.leader = leader_id
        self.cities = []
        self.techs = [] # List of researched technologies
        # b9 diplomacy: countries start at peace with each other
        self.wars = set()      # country names we are at war with
        self.allies = set()    # country names we are allied with

    def members(self):
        """Everybody who lives in the country (b13): its cities' people.

        The class used to have no `members` at all, which country chat ran into.
        The leader always counts, even when his city is not listed yet.
        """
        people = [self.leader] if self.leader else []
        for city in self.cities:
            if city.leader and city.leader not in people:
                people.append(city.leader)
            for pid in city.members:
                if pid not in people:
                    people.append(pid)
        return people

    def to_dict(self):
        return {
            "name": self.name,
            "leader": self.leader,
            "cities": [c.name for c in self.cities],
            "techs": self.techs,
            "wars": sorted(self.wars),
            "allies": sorted(self.allies),
        }

    def to_save(self):
        data = self.to_dict()
        data["cities"] = [c.name for c in self.cities]
        return data

    @classmethod
    def from_save(cls, data, city_lookup):
        country = cls(data["name"], data.get("leader"))
        country.techs = list(data.get("techs", []))
        country.cities = [city_lookup[name] for name in data.get("cities", [])
                          if name in city_lookup]
        country.wars = set(data.get("wars", []))
        country.allies = set(data.get("allies", []))
        return country

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

    def to_save(self):
        return {
            "cities": {n: c.to_save() for n, c in self.cities.items()},
            "countries": {n: c.to_save() for n, c in self.countries.items()},
        }

    def load_save(self, data: dict) -> bool:
        """Rebuild cities/countries from a save file."""
        if not isinstance(data, dict):
            return False
        cities = {}
        for name, city_data in (data.get("cities") or {}).items():
            try:
                cities[name] = City.from_save(city_data)
            except (KeyError, TypeError, ValueError):
                continue
        countries = {}
        for name, country_data in (data.get("countries") or {}).items():
            try:
                countries[name] = Country.from_save(country_data, cities)
            except (KeyError, TypeError, ValueError):
                continue
        self.cities = cities
        self.countries = countries
        return True

    # ------------------------------------------------------- b10: roles & tax
    def set_role(self, city, player_id, role) -> bool:
        """Leader action: give a member a role (or make him a plain citizen)."""
        if city is None or player_id is None or role not in ROLE_RIGHTS:
            return False
        if role == "leader" or player_id == city.leader:
            return False
        if player_id not in city.members:
            return False
        if role == DEFAULT_ROLE:
            city.roles.pop(str(player_id), None)
        else:
            city.roles[str(player_id)] = role
        return True

    def set_tax(self, city, value) -> int:
        city.tax = max(0, min(MAX_TAX, int(value)))
        return city.tax

    def city_at(self, x, y):
        """The city whose territory covers a point (or None)."""
        for city in self.cities.values():
            if ((x - city.x) ** 2 + (y - city.y) ** 2) ** 0.5 < city.get_radius():
                return city
        return None

    def country_age(self, country) -> str:
        return age_of(getattr(country, "techs", [])) if country else "stone"

    # ------------------------------------------------------- b10: conquest
    def capture_city(self, city, new_leader_id, country) -> dict:
        """A town centre fell: the city changes hands.

        Returns what happened so the server can tell everybody about it.
        """
        info = {"city": city.name, "old_leader": city.leader, "old_country": ""}
        for name, other in list(self.countries.items()):
            if city in other.cities:
                info["old_country"] = name
                other.cities.remove(city)
        city.captured += 1
        if city.leader is not None and city.leader in city.members:
            # the ruler who lost the town centre is thrown out of the city
            city.members.remove(city.leader)
        city.leader = new_leader_id
        # the new ruler brings his own staff: every post is vacant again
        city.roles.clear()
        if new_leader_id is not None and new_leader_id not in city.members:
            city.members.insert(0, new_leader_id)
        if country is not None and city not in country.cities:
            country.cities.append(city)
        return info

    def dissolve_country(self, name) -> bool:
        """Remove a country (its last city was lost) and clean up diplomacy."""
        country = self.countries.pop(name, None)
        if country is None:
            return False
        for other in self.countries.values():
            other.wars.discard(name)
            other.allies.discard(name)
        return True

    def countries_owning_everything(self) -> list:
        """Countries that hold every city on the map (victory condition)."""
        if len(self.cities) < 2:
            return []
        return [country for country in self.countries.values()
                if len(country.cities) == len(self.cities)]

    # ------------------------------------------------------------- lookups
    def find_city_of(self, player_id):
        for city in self.cities.values():
            if city.leader == player_id or player_id in city.members:
                return city
        return None

    def find_city_led_by(self, player_id):
        for city in self.cities.values():
            if city.leader == player_id:
                return city
        return None

    def find_country_led_by(self, player_id):
        for country in self.countries.values():
            if country.leader == player_id:
                return country
        return None

    def find_country_of(self, player_id):
        """The country a player belongs to (as leader or through a city)."""
        if player_id is None:
            return None
        for country in self.countries.values():
            if country.leader == player_id:
                return country
            for city in country.cities:
                if city.leader == player_id or player_id in city.members:
                    return country
        return None

    # ---------------------------------------------------------- diplomacy
    def relation(self, a: "Country", b: "Country") -> str:
        """"same", "war", "ally" or "peace" (the default)."""
        if a is None or b is None:
            return "none"
        if a is b or a.name == b.name:
            return "same"
        if b.name in a.wars or a.name in b.wars:
            return "war"
        if b.name in a.allies and a.name in b.allies:
            return "ally"
        return "peace"

    def relation_between(self, player_a, player_b) -> str:
        return self.relation(self.find_country_of(player_a), self.find_country_of(player_b))

    def set_relation(self, actor: "Country", target: "Country", action: str) -> bool:
        """Leader action: declare war / make peace / offer or accept an alliance."""
        if actor is None or target is None or actor.name == target.name:
            return False
        if action == "war":
            # a war is between two countries: both sides see it in their menus
            actor.wars.add(target.name)
            target.wars.add(actor.name)
            actor.allies.discard(target.name)
            target.allies.discard(actor.name)
            return True
        if action == "peace":
            actor.wars.discard(target.name)
            target.wars.discard(actor.name)
            return True
        if action == "ally":
            actor.allies.add(target.name)
            actor.wars.discard(target.name)
            target.wars.discard(actor.name)
            if target.leader == actor.leader and actor.name in target.allies:
                return True
            return True
        return False