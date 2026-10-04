"""Entry point: menu -> game, and back to the menu when the player leaves."""

import pygame

from client.config import Config
from client.game import Game
from client.i18n import set_language
from client.menu import MainMenu
from client.settings import SCREEN_WIDTH, SCREEN_HEIGHT, FPS

DEFAULT_PORT = 5555


def parse_host(text: str):
    """Accepts 'host' and 'host:port'."""
    text = (text or "").strip() or "127.0.0.1"
    if ":" in text:
        host, _, port = text.partition(":")
        try:
            return host, int(port)
        except ValueError:
            return host, DEFAULT_PORT
    return text, DEFAULT_PORT


def _apply_fullscreen(config):
    flags = pygame.FULLSCREEN if config.get("fullscreen") else 0
    return pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT), flags)


def main():
    pygame.init()
    pygame.display.set_caption("Civilization Survival")
    config = Config()
    set_language(config.get("language"))
    screen = _apply_fullscreen(config)

    clock = pygame.time.Clock()
    while True:
        # ---- menu -----------------------------------------------------------
        menu = MainMenu(screen, config)
        while menu.active:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    pygame.quit()
                    return
                menu.handle_event(event)
            menu.draw()
            pygame.display.flip()
            clock.tick(30)

        host, port = parse_host(menu.result["server"])
        # ---- game -----------------------------------------------------------
        game = Game(screen, host, port, name=menu.result["name"],
                    mode=menu.result["mode"], password=menu.result["password"],
                    config=config)
        running = True
        while running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    pygame.quit()
                    return
                game.handle_event(event)
            game.update()
            game.draw()
            pygame.display.flip()
            clock.tick(FPS)
            if game.exit_to_menu:
                running = False

        game.net.close()
        if not config.get("fullscreen"):
            screen = pygame.display.get_surface()
        if game.exit_to_menu:
            continue
        break

    pygame.quit()


if __name__ == "__main__":
    main()
