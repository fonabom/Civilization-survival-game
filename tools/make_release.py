"""Build the distributable archives of the game.

The project is one repository but **three** packages (idea #9 of the 1.0.0
plan: release engineering, and «разделить сервер и клиент»):

    python tools/make_release.py --kind bundle    -> dist/Civilization_Beta.zip
    python tools/make_release.py --kind client    -> dist/Civilization_Client_<build>.zip
    python tools/make_release.py --kind server    -> dist/Civilization_Server_<build>.zip
    python tools/make_release.py --kind all       -> all three

What goes where:

    client  - the game itself: client code, assets, locales, resource packs,
              the launcher and run_client.py. Needs pygame.
    server  - the dedicated server: server code, shared rules, run_server.py,
              the config example and check_server.py. Needs *nothing* - not
              even pygame (that is what the split buys you: a server can run
              on a cheap VPS with a bare python).
    bundle  - both of the above in one archive, kept because the launcher and
              the CI publish this file name (Civilization_Beta.zip).

Every archive carries build.txt and ЧИТАЙ_МЕНЯ.txt describing what it is.
"""

import argparse
import hashlib
import json
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

CLIENT_DIRS = ["client", "shared", "assets", "locales", "resourcepacks"]
CLIENT_FILES = ["run_client.py", "launcher.py", "launcher_config.py", "requirements.txt",
                "config.json", "build.txt", "HOW_TO_PLAY.txt", "README.md", "CHANGELOG.md"]
SERVER_DIRS = ["server", "shared"]
SERVER_FILES = ["run_server.py", "server_config.example.json", "requirements-server.txt",
                "check_server.py", "build.txt", "README.md", "CHANGELOG.md"]

EXCLUDE_SUFFIXES = {".pyc", ".pyo"}
EXCLUDE_PARTS = {"__pycache__", ".pytest_cache", "dist", "tests", "tools", "installer",
                 "server_data", "saves", ".git", "backup_before_update_*"}

CLIENT_README = """Это КЛИЕНТ игры Civilization Survival (сборка {build}).

Что внутри
----------
client/         код игры (pygame)
shared/         общие правила: предметы, постройки, технологии
assets/         картинки и звуки
locales/        тексты (en / pl / ru)
resourcepacks/  готовые паки текстур и звуков
launcher.py     лаунчер: запускает игру и обновляет её
run_client.py   запуск игры напрямую

Как играть
----------
1. Поставьте Python 3.10+ и библиотеку pygame:
       python -m pip install -r requirements.txt
2. Запустите launcher.py (он умеет проверять обновления) или run_client.py.
3. В игре нужен сервер: свой (см. сборку Civilization_Server) или адрес друга.
   Хост и порт вводятся в главном меню.

Своя папка для установки
------------------------
Если у вас Windows, проще поставить игру готовым инсталлятором
Civilization-Setup-{build}.exe со страницы релизов - Python тогда не нужен.

Сборка: {build}   Файлов: {files}
"""

SERVER_README = """Это СЕРВЕР игры Civilization Survival (сборка {build}).

Самое важное: серверу НЕ нужен pygame и вообще никаких библиотек сверх
обычного Python 3.10+ — код сервера отделён от кода игры (b12), поэтому
сервер поднимается на любом VPS.

Что внутри
----------
server/                       код сервера (авторитетный, без графики)
shared/                       общие правила игры
run_server.py                 запуск сервера
check_server.py               самопроверка: "сервер работает без pygame?"
server_config.example.json    пример настроек (скопируйте в server_config.json)
requirements-server.txt       пусто: зависимостей нет

Быстрый старт
-------------
    python run_server.py                      # порт по умолчанию
    python run_server.py --port 25565         # свой порт
    python run_server.py --config server_config.json
    python run_server.py --no-accounts        # только гости, ничего не пишем на диск
    python check_server.py                    # проверка, что всё живо (без pygame)

Проверить, что сервер действительно не тянет pygame:

    python check_server.py --forbid-pygame

Настройки (server_config.json): PvP, голод, погода, животные, налоги, победа,
скорость плавания (`swim`, `swim_speed`), стартовый набор и т.д. Полный пример —
в server_config.example.json.

Гости могут подключаться сразу; аккаунты пишутся в файл рядом (--accounts).
Мир живёт в памяти: пока сервер включён, он помнит всё; сохранение в файл
включается ключом --save world.json.

Сборка: {build}   Файлов: {files}
"""

BUNDLE_README = """Сборка {build}: клиент и сервер вместе (как раньше).
Отдельные архивы: Civilization_Client_{build}.zip и Civilization_Server_{build}.zip.
Файлов: {files}
"""


def _is_excluded(path: Path) -> bool:
    return path.suffix in EXCLUDE_SUFFIXES or bool(set(path.parts) & EXCLUDE_PARTS)


def collect(dirs, files, root: Path = None) -> list:
    """Files of one package (sorted, caches and dev folders dropped)."""
    root = Path(root or ROOT)
    found = []
    for name in dirs:
        base = root / name
        if not base.exists():
            print(f"! skipping missing directory {name}")
            continue
        found.extend(p for p in base.rglob("*") if p.is_file())
    for name in files:
        path = root / name
        if path.exists():
            found.append(path)
        else:
            print(f"! skipping missing file {name}")
    return sorted(p for p in found if not _is_excluded(p.relative_to(root)))


def client_files(root: Path = None) -> list:
    return collect(CLIENT_DIRS, CLIENT_FILES, root)


def server_files(root: Path = None) -> list:
    return collect(SERVER_DIRS, SERVER_FILES, root)


def bundle_files(root: Path = None) -> list:
    both = collect(CLIENT_DIRS, CLIENT_FILES, root) + collect(SERVER_DIRS, SERVER_FILES, root)
    return sorted(set(both))


def read_build(root: Path = None) -> str:
    path = Path(root or ROOT) / "build.txt"
    try:
        return path.read_text(encoding="utf-8").strip() or "b0"
    except OSError:
        return "b0"


def write_archive(output: Path, files: list, readme: str, build: str, kind: str,
                  root: Path = None) -> dict:
    """Write one archive plus its readme and a small release.json."""
    root = Path(root or ROOT)
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "kind": kind,
        "build": build,
        "created": time.strftime("%Y-%m-%d %H:%M:%S"),
        "files": [p.relative_to(root).as_posix() for p in files],
    }
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, path.relative_to(root).as_posix())
        archive.writestr("ЧИТАЙ_МЕНЯ.txt", readme.format(build=build, files=len(files)))
        archive.writestr("release.json", json.dumps(manifest, ensure_ascii=False, indent=1))
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    return {"path": output, "files": len(files) + 2,
            "size": output.stat().st_size, "sha256": digest, "build": build,
            "kind": kind}


def build(kind: str, output: Path = None, out_dir: Path = None, root: Path = None) -> dict:
    """Build one package and return a small report dict."""
    root = Path(root or ROOT)
    build_id = read_build(root)
    recipes = {
        "bundle": (bundle_files(root), BUNDLE_README, "Civilization_Beta.zip"),
        "client": (client_files(root), CLIENT_README, f"Civilization_Client_{build_id}.zip"),
        "server": (server_files(root), SERVER_README, f"Civilization_Server_{build_id}.zip"),
    }
    if kind not in recipes:
        raise ValueError(f"unknown package kind: {kind}")
    files, readme, default_name = recipes[kind]
    if output is None:
        output = Path(out_dir or (root / "dist")) / default_name
    return write_archive(Path(output), files, readme, build_id, kind, root)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--kind", choices=["bundle", "client", "server", "all"],
                        default="bundle", help="which package to build (default: bundle)")
    parser.add_argument("--out", default=None, help="output zip path (single package only)")
    parser.add_argument("--out-dir", default=None, help="directory for the archives")
    parser.add_argument("--manifest", default=None,
                        help="write a JSON report about the built archives here")
    args = parser.parse_args(argv)

    kinds = ["bundle", "client", "server"] if args.kind == "all" else [args.kind]
    if args.out and len(kinds) > 1:
        parser.error("--out cannot be used with --kind all")

    report = []
    for kind in kinds:
        info = build(kind, output=Path(args.out) if args.out else None,
                     out_dir=Path(args.out_dir) if args.out_dir else None)
        report.append({**info, "path": str(info["path"])})
        print(f"Built {info['path']} ({info['kind']}, build {info['build']})")
        print(f"  files : {info['files']}")
        print(f"  size  : {info['size'] / 1024:.0f} KB")
        print(f"  sha256: {info['sha256']}")

    if args.manifest:
        Path(args.manifest).write_text(json.dumps(report, ensure_ascii=False, indent=1),
                                       encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
