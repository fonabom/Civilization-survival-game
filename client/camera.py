class Camera:
    """The window onto the world: follows the player, never leaves the map."""

    def __init__(self):
        self.x = 0
        self.y = 0

    def update(self, target, screen_width, screen_height,
               world_width=None, world_height=None):
        # Centre on the player ...
        self.x = target.x - screen_width // 2
        self.y = target.y - screen_height // 2
        # ... but do not show the empty space outside the map (b9: water and
        # caves make players walk along the edges much more often).
        if world_width and world_height:
            self.x = max(0, min(self.x, max(0, world_width - screen_width)))
            self.y = max(0, min(self.y, max(0, world_height - screen_height)))

    def apply(self, world_x, world_y):
        return world_x - self.x, world_y - self.y
