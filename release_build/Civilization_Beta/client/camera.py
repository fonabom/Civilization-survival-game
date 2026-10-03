class Camera:
    def __init__(self):
        self.x = 0
        self.y = 0

    def update(self, target, screen_width, screen_height):
        # Центрируем камеру на целевом объекте (игроке)
        self.x = target.x - screen_width // 2
        self.y = target.y - screen_height // 2

    def apply(self, world_x, world_y):
        # Преобразуем мировые координаты в экранные
        return world_x - self.x, world_y - self.y