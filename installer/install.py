"""Installer of the game client (b12, idea #9 of the 1.0.0 plan).

Two ways to use it:

    python installer/install.py                 # a small window: choose folder, press Install
    python installer/install.py --silent --target ~/Civilization --source Civilization_Client_b12.zip

What it does
------------
1. takes the client package (a `Civilization_Client_*.zip` next to the script,
   or `--source` = a zip **or** a folder with the game),
2. copies it into the target folder,
3. writes `install.json` (build, files, date) so it can be uninstalled cleanly,
4. makes a start script (`ЗАПУСТИТЬ_ИГРУ.bat` on Windows, `start-game.sh`
   elsewhere), a desktop shortcut and a menu entry,
5. optionally installs the python dependencies (`--install-deps`).

Remove everything again:

    python installer/install.py --uninstall --target ~/Civilization

The Windows installer (Civilization-Setup-<build>.exe) does the same job for
players who have no Python at all - it is built from this folder by
`installer/build_installer.py` (PyInstaller + Inno Setup).
"""

import argparse
import json
import os
import shutil
import stat
import sys
import time
import zipfile
from pathlib import Path

APP_NAME = "Civilization Survival"
FOLDER_NAME = "Civilization"
GAME_SCRIPT = "run_client.py"
MANIFEST = "install.json"
BUILD_FILE = "build.txt"

# what a client package consists of when installing from a plain folder
# (a zip source is copied as it is; the zip is built by tools/make_release.py)
CLIENT_DIRS = ["client", "shared", "assets", "locales", "resourcepacks"]
CLIENT_FILES = ["run_client.py", "launcher.py", "launcher_config.py", "requirements.txt",
                "config.json", "build.txt", "HOW_TO_PLAY.txt", "README.md", "CHANGELOG.md"]
SKIP_DIRS = {"__pycache__", ".pytest_cache", ".git", "dist", "tests", "tools", "installer",
             "server", "venv", ".venv"}

WINDOWS = sys.platform.startswith("win")
MACOS = sys.platform == "darwin"


# --------------------------------------------------------------------- helpers
def default_target() -> Path:
    """A folder a normal user may write to."""
    if WINDOWS:
        base = os.environ.get("LOCALAPPDATA") or str(Path.home())
        return Path(base) / "Programs" / FOLDER_NAME
    if MACOS:
        return Path.home() / "Applications" / FOLDER_NAME
    return Path.home() / FOLDER_NAME


def find_source(explicit: str = "") -> Path:
    """`--source`, then a client zip next to the script, then the project itself."""
    if explicit:
        return Path(explicit).expanduser()
    here = Path(__file__).resolve().parent
    for folder in (here, here.parent, Path.cwd()):
        for archive in sorted(folder.glob("Civilization_Client_*.zip")):
            return archive
    project = here.parent
    if (project / GAME_SCRIPT).exists():
        return project
    for archive in sorted(Path.cwd().glob("Civilization_Client_*.zip")):
        return archive
    raise FileNotFoundError(
        "no client package found: put Civilization_Client_*.zip next to the installer "
        "or pass --source PATH")


def read_build(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip() or "b0"
    except OSError:
        return "b0"


def looks_like_client(folder: Path) -> bool:
    return (folder / GAME_SCRIPT).exists() and (folder / "client").is_dir()


def folder_content(folder: Path) -> list:
    """Relative paths of a client folder (used when installing from source)."""
    found = []
    for name in CLIENT_DIRS:
        base = folder / name
        if not base.is_dir():
            print(f"! missing folder {name} - skipping")
            continue
        for path in base.rglob("*"):
            relative = path.relative_to(folder)
            if path.is_file() and not set(relative.parts) & SKIP_DIRS:
                found.append(relative)
    for name in CLIENT_FILES:
        if (folder / name).is_file():
            found.append(Path(name))
    return sorted(set(found))


def zip_content(archive: Path) -> list:
    with zipfile.ZipFile(archive) as zf:
        return [Path(member.filename) for member in zf.infolist() if not member.is_dir()]


def zip_root_prefix(names) -> str:
    """A GitHub archive wraps everything in one folder - find and strip it."""
    parts = {Path(name).parts[0] for name in names if Path(name).parts}
    if len(parts) == 1:
        prefix = parts.pop() + "/"
        if any(str(name) == prefix + GAME_SCRIPT for name in names):
            return prefix
    return ""


def looks_like_client_names(names) -> bool:
    text = {str(name) for name in names}
    return GAME_SCRIPT in text and any(name.startswith("client/") for name in text)


def safe_members(names) -> list:
    safe = []
    for name in names:
        parts = Path(name).parts
        if name.is_absolute() or ".." in parts or parts[:1] == ("/",):
            continue
        safe.append(Path(name))
    return safe


# ------------------------------------------------------------------- installing
def install(source: Path, target: Path, shortcuts: bool = True, quiet: bool = False) -> dict:
    """Copy the client package into `target`; returns the install manifest."""
    say = (lambda *args: None) if quiet else print

    prefix = ""
    if source.is_dir():
        if not looks_like_client(source):
            raise ValueError(f"{source} does not look like the game client "
                             f"(no {GAME_SCRIPT})")
        names = folder_content(source)
        say(f"installing from the folder {source} ({len(names)} files)")
    elif source.is_file() and source.suffix.lower() == ".zip":
        raw = safe_members(zip_content(source))
        prefix = zip_root_prefix(raw)
        names = [Path(str(name)[len(prefix):]) for name in raw]
        # a server package or a random zip must not end up installed as the game
        if not looks_like_client_names(names):
            raise ValueError(
                f"{source} is not a client package (no {GAME_SCRIPT} and no client/ "
                f"inside). Install the file Civilization_Client_*.zip - the server "
                f"package is Civilization_Server_*.zip.")
        say(f"installing from the archive {source} ({len(names)} files)")
    else:
        raise ValueError(f"the source must be a client zip or folder: {source}")

    if not names:
        raise ValueError("the package is empty")

    target.mkdir(parents=True, exist_ok=True)
    written = []
    if source.is_dir():
        for relative in names:
            destination = target / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source / relative, destination)
            written.append(relative.as_posix())
    else:
        with zipfile.ZipFile(source) as zf:
            for member in zf.infolist():
                if member.is_dir():
                    continue
                relative = Path(member.filename)
                if relative.is_absolute() or ".." in relative.parts:
                    continue
                if prefix:
                    text = str(relative).replace("\\", "/")
                    if not text.startswith(prefix):
                        continue
                    relative = Path(text[len(prefix):])
                    if not str(relative):
                        continue
                destination = target / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(member) as src, open(destination, "wb") as out:
                    shutil.copyfileobj(src, out)
                written.append(relative.as_posix())

    build = read_build(target / BUILD_FILE)
    manifest = {
        "app": APP_NAME,
        "build": build,
        "installed": time.strftime("%Y-%m-%d %H:%M:%S"),
        "source": str(source),
        "target": str(target),
        "files": sorted(written),
        "python": sys.version.split()[0],
    }
    (target / MANIFEST).write_text(json.dumps(manifest, ensure_ascii=False, indent=1),
                                   encoding="utf-8")
    made = []
    if shortcuts:
        made = make_shortcuts(target)
        manifest["shortcuts"] = made
        (target / MANIFEST).write_text(json.dumps(manifest, ensure_ascii=False, indent=1),
                                       encoding="utf-8")
    say(f"installed build {build} into {target}")
    for item in made:
        say(f"  shortcut: {item}")
    return manifest


def start_script(target: Path) -> Path:
    """A double-clickable "start the game" file for this platform."""
    if WINDOWS:
        path = target / "ЗАПУСТИТЬ_ИГРУ.bat"
        path.write_text(
            "@echo off\r\n"
            "chcp 65001 >nul\r\n"
            "cd /d \"%~dp0\"\r\n"
            "echo Starting Civilization Survival...\r\n"
            "where python >nul 2>nul && (python run_client.py & goto :end)\r\n"
            "where py >nul 2>nul && (py run_client.py & goto :end)\r\n"
            "echo Python was not found. Install it from https://python.org\r\n"
            "pause\r\n"
            ":end\r\n", encoding="utf-8")
        return path
    path = target / "start-game.sh"
    path.write_text("#!/usr/bin/env bash\n"
                    "cd \"$(dirname \"$0\")\"\n"
                    "exec python3 run_client.py \"$@\"\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


def desktop_file(target: Path) -> Path:
    path = target / "civilization.desktop"
    path.write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={APP_NAME}\n"
        "Comment=Survival and civilisation, together with friends\n"
        "Exec=python3 run_client.py\n"
        f"Path={target}\n"
        "Terminal=false\n"
        "Categories=Game;\n"
        "Icon=applications-games\n", encoding="utf-8")
    return path


def make_shortcuts(target: Path) -> list:
    """Desktop / menu shortcuts. Returns the paths that were created."""
    made = []
    script = start_script(target)
    made.append(str(script))
    if WINDOWS:
        try:
            import subprocess
            desktop = Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Desktop"
            desktop.mkdir(parents=True, exist_ok=True)
            link = desktop / f"{APP_NAME}.lnk"
            subprocess.run([
                "powershell", "-NoProfile", "-Command",
                "$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%s');"
                "$s.TargetPath='%s';$s.WorkingDirectory='%s';$s.Save()"
                % (link, target / GAME_SCRIPT, target)], check=False, capture_output=True)
            made.append(str(link))
        except OSError:
            pass
        return made

    entry = desktop_file(target)
    made.append(str(entry))
    applications = Path.home() / ".local" / "share" / "applications"
    try:
        applications.mkdir(parents=True, exist_ok=True)
        menu_entry = applications / "civilization.desktop"
        shutil.copy2(entry, menu_entry)
        made.append(str(menu_entry))
    except OSError:
        pass
    desktop = Path.home() / "Desktop"
    if desktop.is_dir():
        try:
            link = desktop / "civilization.desktop"
            shutil.copy2(entry, link)
            link.chmod(link.stat().st_mode | stat.S_IXUSR)
            made.append(str(link))
        except OSError:
            pass
    return made


def uninstall(target: Path, quiet: bool = False) -> int:
    """Remove exactly what `install.json` lists, then the folder if it is empty."""
    say = (lambda *args: None) if quiet else print
    manifest_path = target / MANIFEST
    if not manifest_path.exists():
        say(f"nothing to remove: {manifest_path} was not found")
        return 1
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    removed = 0
    for name in manifest.get("files", []):
        path = target / name
        try:
            if path.is_file():
                path.unlink()
                removed += 1
        except OSError as exc:
            say(f"  could not remove {path}: {exc}")
    for shortcut in manifest.get("shortcuts", []):
        try:
            # both the start script inside the folder and the link on the
            # desktop / in the menu were made by us, so both go away
            path = Path(shortcut)
            if path.is_file() or path.is_symlink():
                path.unlink()
        except OSError:
            pass
    # files the game creates while playing (byte code cache, screenshots)
    for pattern in ("**/__pycache__", "**/*.pyc", "**/*.pyo"):
        for path in sorted(target.glob(pattern), reverse=True):
            try:
                if path.is_dir():
                    shutil.rmtree(path)
                elif path.is_file():
                    path.unlink()
            except OSError:
                pass
    try:
        manifest_path.unlink()
    except OSError:
        pass

    def prune(folder: Path):
        for child in sorted(folder.rglob("*"), reverse=True):
            if child.is_dir() and not any(child.iterdir()):
                child.rmdir()
        if folder.is_dir() and not any(folder.iterdir()):
            folder.rmdir()

    try:
        prune(target)
    except OSError:
        pass
    say(f"removed {removed} files from {target}")
    return 0


def install_dependencies(target: Path, quiet: bool = False) -> bool:
    """`pip install -r requirements.txt` inside the installed folder."""
    import subprocess
    requirements = target / "requirements.txt"
    if not requirements.exists():
        return False
    command = [sys.executable, "-m", "pip", "install", "-r", str(requirements)]
    if not quiet:
        print("running:", " ".join(command))
    result = subprocess.run(command, capture_output=quiet, text=True)
    return result.returncode == 0


# ------------------------------------------------------------------------ GUI
def run_gui(source: Path, target: Path, shortcuts: bool = True) -> int:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    root = tk.Tk()
    root.title(f"{APP_NAME} — установка")
    root.geometry("520x260")
    root.resizable(False, False)

    tk.Label(root, text=f"Установка {APP_NAME}", font=("Arial", 16, "bold")).pack(pady=10)
    tk.Label(root, text=f"Источник: {source}", fg="gray", wraplength=490,
             justify="left").pack()

    frame = tk.Frame(root)
    frame.pack(pady=10, fill=tk.X, padx=16)
    tk.Label(frame, text="Папка установки:").pack(anchor="w")
    entry = tk.Entry(frame)
    entry.insert(0, str(target))
    entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
    tk.Button(frame, text="…", width=3,
              command=lambda: entry.delete(0, tk.END) or
              entry.insert(0, filedialog.askdirectory() or str(target))).pack(side=tk.LEFT)

    desktop_var = tk.IntVar(value=1 if shortcuts else 0)
    tk.Checkbutton(root, text="Ярлык на рабочем столе и в меню",
                   variable=desktop_var).pack(anchor="w", padx=16)
    deps_var = tk.IntVar(value=0)
    tk.Checkbutton(root, text="Установить зависимости (pygame) через pip",
                   variable=deps_var).pack(anchor="w", padx=16)

    progress = ttk.Progressbar(root, orient=tk.HORIZONTAL, length=470, mode="determinate")
    progress.pack(pady=10)
    status = tk.Label(root, text="Готово к установке", fg="gray")
    status.pack()

    def do_install():
        button.config(state="disabled")
        chosen = Path(entry.get()).expanduser()
        try:
            status.config(text="Копирую файлы…")
            root.update_idletasks()
            progress.config(value=40)
            manifest = install(source, chosen, shortcuts=bool(desktop_var.get()), quiet=True)
            if deps_var.get():
                status.config(text="Устанавливаю зависимости (это может занять минуту)…")
                root.update_idletasks()
                progress.config(value=70)
                install_dependencies(chosen, quiet=True)
            progress.config(value=100)
            messagebox.showinfo(APP_NAME, f"Готово! Сборка {manifest['build']}.\n\n"
                                          f"Папка: {chosen}\n"
                                          f"Запуск: {chosen / 'ЗАПУСТИТЬ_ИГРУ.bat' if WINDOWS else chosen / 'start-game.sh'}")
            root.destroy()
        except (OSError, ValueError, zipfile.BadZipFile) as exc:
            messagebox.showerror(APP_NAME, f"Не получилось: {exc}")
            status.config(text="Ошибка установки")
            button.config(state="normal")

    button = ttk.Button(root, text="Установить", command=do_install)
    button.pack(pady=6)
    root.mainloop()
    return 0


# ----------------------------------------------------------------------- main
def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", default="",
                        help="client zip or a folder with the game (default: automatic)")
    parser.add_argument("--target", default="", help=f"install folder (default: {default_target()})")
    parser.add_argument("--silent", action="store_true", help="no window, no questions")
    parser.add_argument("--no-shortcuts", action="store_true",
                        help="do not create desktop / menu shortcuts")
    parser.add_argument("--install-deps", action="store_true",
                        help="run pip install -r requirements.txt after copying")
    parser.add_argument("--uninstall", action="store_true", help="remove an installation")
    parser.add_argument("--json", action="store_true", help="print the install manifest")
    args = parser.parse_args(argv)

    target = Path(args.target).expanduser() if args.target else default_target()

    if args.uninstall:
        return uninstall(target, quiet=args.silent)

    try:
        source = find_source(args.source)
    except FileNotFoundError as exc:
        print(f"error: {exc}")
        return 2
    print(f"source : {source}")
    print(f"target : {target}")

    if not args.silent:
        try:
            return run_gui(source, target, shortcuts=not args.no_shortcuts)
        except ImportError:
            print("(no tkinter available - falling back to silent install)")

    try:
        manifest = install(source, target, shortcuts=not args.no_shortcuts,
                           quiet=args.silent)
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        print(f"error: {exc}")
        return 1
    if args.install_deps:
        install_dependencies(target, quiet=args.silent)
    if args.json:
        print(json.dumps(manifest, ensure_ascii=False, indent=1))
    print("ready. start the game with: python run_client.py  (or the start script)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
