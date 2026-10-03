import pygame
from client.settings import *
from client.game import Game
from client.menu import MainMenu

def main():
    pygame.init()
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
    pygame.display.set_caption("Civilization Game")

    clock = pygame.time.Clock()
    
    # 1. Main Menu Loop
    menu = MainMenu(screen)
    while menu.active:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                return
            menu.handle_event(event)
        
        menu.draw()
        pygame.display.flip()
        clock.tick(30)
        
    # 2. Game Loop
    # Pass the IP from menu to Game (allow "host:port" or just "host")
    host = menu.ip_text.strip() if menu.ip_text else "127.0.0.1"
    port = 5555
    if ":" in host:
        try:
            h, p = host.split(":", 1)
            host = h
            port = int(p)
        except Exception:
            host = "127.0.0.1"
            port = 5555

    game = Game(screen, host, port)
    
    running = True
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            game.handle_event(event)

        game.update()
        game.draw()

        pygame.display.flip()
        clock.tick(FPS)

    pygame.quit()

if __name__ == "__main__":
    main()
