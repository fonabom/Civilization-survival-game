"""City roles and what they are allowed to do (b10 «Цивилизация»).

A city has one leader (the founder) and the rest of the members get a role.
Roles decide who may build inside the city, use the common storage, research
and hand out roles. Everything is data so the server, the menus and the tests
read the same rules.

    role_of(roles, player_id) -> "leader" | "elder" | "builder" | "warrior"
                                 | "citizen"
    can(role, "build")        -> True / False
"""

# Order for the menus (the leader first)
ROLE_ORDER = ["leader", "elder", "builder", "warrior", "citizen"]

# What each role may do. "leader" is on top, "citizen" is what a plain member
# has: no special rights inside the city, but nothing is taken away either.
ROLE_RIGHTS = {
    "leader": {"build", "storage", "research", "manage", "role"},
    "elder": {"build", "storage", "research"},
    "builder": {"build", "storage"},
    "warrior": set(),
    "citizen": set(),
}

# Every right the game knows about
RIGHTS = ("build", "storage", "research", "manage", "role")

# Warrior bonus: +10 % melee damage (the only role with a combat perk)
WARRIOR_DAMAGE_BONUS = 1.10

DEFAULT_ROLE = "citizen"

# Tax: the leader may send this share of every gathered resource to the fund
MAX_TAX = 40


def role_of(roles: dict, player_id, leader_id=None) -> str:
    """The role of a player in a city (the leader is the leader)."""
    if player_id is not None and player_id == leader_id:
        return "leader"
    role = (roles or {}).get(str(player_id))
    return role if role in ROLE_RIGHTS else DEFAULT_ROLE


def can(role: str, right: str) -> bool:
    return right in ROLE_RIGHTS.get(role, set())


def rights_for(role: str) -> list:
    return sorted(ROLE_RIGHTS.get(role, set()))
