# Установщик и релизные сборки (b12)

Здесь лежит всё, что превращает репозиторий в то, что человек может скачать и
запустить: разделение на клиент и сервер, установщик для Windows, скрипт
установки для Linux/macOS и сборка исполняемых файлов.

## Что из чего собирается

```
tools/make_release.py --kind client   ->  Civilization_Client_b12.zip   (игра, нужен pygame)
tools/make_release.py --kind server   ->  Civilization_Server_b12.zip   (сервер, pygame НЕ нужен)
tools/make_release.py --kind bundle   ->  Civilization_Beta.zip         (оба вместе; его качает лаунчер)
tools/make_release.py --kind all      ->  все три сразу
installer/build_installer.py --all    ->  exe-файлы + Civilization-Setup-b12.exe
```

Разделение настоящее, а не на словах: `check_server.py` из серверного архива
специально запрещает импорт pygame и проверяет, что сервер всё равно работает:

```
python check_server.py --forbid-pygame
```

## Для игрока без Python (Windows)

`Civilization-Setup-<build>.exe` — обычный установщик: выбор папки, ярлык на
рабочем столе и в меню «Пуск», удаление через «Установка и удаление программ».
Внутри — два исполняемых файла:

* `Civilization.exe` — игра (Python и pygame внутри, ничего ставить не надо);
* `CivilizationServer.exe` — необязательный компонент «Сервер для друзей»,
  чтобы поднять мир для компании на этой же машине.

Настройки игра пишет в `%APPDATA%\Civilization`, а не в папку установки:
папка установки может быть только для чтения (это делает `shared/paths.py`).

## Для игрока с Python (Linux/macOS/Windows)

```
python installer/install.py                 # окно: выбрать папку и нажать «Установить»
python installer/install.py --silent --target ~/Civilization --install-deps
python installer/install.py --uninstall --target ~/Civilization
bash installer/linux/install.sh             # то же самое одной командой
```

Установщик берёт `Civilization_Client_*.zip` рядом с собой (или папку
репозитория), копирует файлы, пишет `install.json` (по нему потом удаляет всё),
создаёт `start-game.sh`/`ЗАПУСТИТЬ_ИГРУ.bat` и ярлык в меню.

## Как сделать релиз (кратко)

```
python tools/bump_build.py --commit        # b12 -> b13
git push                                   # тесты прогонятся сами
git tag b13 && git push --tags             # CI соберёт архивы, exe и установщик
```

Тег `bN` публикуется как **предрелиз** — он попадает в бету-канал лаунчера.
Тег вида `1.0.0` станет обычным релизом и попадёт в стабильный канал
(переключатель «Стабильная / Бета» в лаунчере и кнопка «Откатить» уже в игре).

Проверки перед тегом: `python -m pytest tests -q` и
`python tools/headless_bots.py` (настоящий сервер + клиенты-боты).
