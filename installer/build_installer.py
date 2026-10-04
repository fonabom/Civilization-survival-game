"""Build the player-facing installer and the standalone executables (b12).

Run it from the project root:

    python installer/build_installer.py --stage-only     # just prepare the folder
    python installer/build_installer.py --pyinstaller    # client.exe + server.exe
    python installer/build_installer.py --iscc           # Civilization-Setup-<build>.exe
    python installer/build_installer.py --all            # everything it can do

What each step needs
--------------------
* stage      - always works: builds the client and server packages into dist/ and
               unpacks the client into dist/installer/stage/
* pyinstaller - `pip install pyinstaller` (CI does it on a Windows runner)
* iscc        - Inno Setup 6 (`iscc` in PATH, CI installs it with chocolatey)

The Windows installer ships the PyInstaller builds, so a player needs no Python
at all: start menu entry, desktop shortcut and an uninstaller are included.
Users of Linux/macOS (or players with Python) use `installer/install.py`.
"""

import argparse
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INSTALLER_DIR = ROOT / "installer"
sys.path.insert(0, str(ROOT))

import tools.make_release as make_release  # noqa: E402  (path set above)


def read_build() -> str:
    return make_release.read_build(ROOT)


def stage(out_dir: Path, quiet: bool = False) -> dict:
    """Packages + an unpacked client ready for PyInstaller / Inno Setup."""
    say = (lambda *args: None) if quiet else print
    stage_dir = out_dir / "installer" / "stage"
    if stage_dir.exists():
        shutil.rmtree(stage_dir)
    stage_dir.mkdir(parents=True, exist_ok=True)

    archives = {kind: make_release.build(kind, out_dir=out_dir) for kind in ("bundle", "client", "server")}
    for kind, info in archives.items():
        say(f"package {kind}: {Path(info['path']).name} "
            f"({info['files']} files, {info['size'] / 1024:.0f} KB)")

    with zipfile.ZipFile(archives["client"]["path"]) as zf:
        zf.extractall(stage_dir)
    say(f"staged client -> {stage_dir}")

    # the python installer can be shipped next to the packages
    shutil.copy2(INSTALLER_DIR / "install.py", stage_dir / "install.py")
    return {"stage": stage_dir, "archives": archives}


def run_pyinstaller(out_dir: Path, quiet: bool = False) -> dict:
    """Build Civilization.exe (client) and CivilizationServer.exe (server)."""
    say = (lambda *args: None) if quiet else print
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        say("! PyInstaller is not installed - skipping the executables "
            "(pip install pyinstaller)")
        return {}

    specs = INSTALLER_DIR / "pyinstaller"
    work = out_dir / "pyinstaller"
    work.mkdir(parents=True, exist_ok=True)
    built = {}
    for spec, name in (("client.spec", "client"), ("server.spec", "server")):
        command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
                   "--distpath", str(work / "dist"), "--workpath", str(work / "build"),
                   "--specpath", str(work), str(specs / spec)]
        say("running:", " ".join(command))
        result = subprocess.run(command, cwd=str(ROOT), capture_output=quiet, text=True)
        if result.returncode != 0:
            say(f"! PyInstaller failed for {spec}"
                f"{(chr(10) + (result.stderr or '')[-800:]) if quiet else ''}")
            continue
        built[name] = work / "dist" / name
        say(f"built {built[name]}")
    return built


def run_iscc(out_dir: Path, built: dict, quiet: bool = False) -> int:
    """Compile the Inno Setup script into Civilization-Setup-<build>.exe."""
    say = (lambda *args: None) if quiet else print
    iscc = shutil.which("iscc") or shutil.which("ISCC.exe")
    if not iscc:
        say("! Inno Setup (iscc) not found - skipping the Windows installer. "
            "Install it from https://jrsoftware.org/isdl.php")
        return 0
    client_dir = built.get("client")
    if client_dir is None or not Path(client_dir).exists():
        say("! the client executable was not built - nothing to pack")
        return 1
    output_dir = out_dir / "installer"
    output_dir.mkdir(parents=True, exist_ok=True)
    command = [iscc,
               f"/DMyBuild={read_build()}",
               f"/DClientDir={Path(client_dir).resolve()}",
               f"/DServerExe={Path(built.get('server') or '').resolve() if built.get('server') else ''}",
               f"/DOutputDir={output_dir.resolve()}",
               str(INSTALLER_DIR / "windows" / "civilization.iss")]
    say("running:", " ".join(command))
    result = subprocess.run(command, capture_output=quiet, text=True)
    if result.returncode != 0:
        say("! iscc failed" + (f":\n{(result.stdout or '')[-1200:]}" if quiet else ""))
        return result.returncode
    say(f"installer written to {output_dir}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out-dir", default=None, help="where dist/ lives (default: ./dist)")
    parser.add_argument("--stage-only", action="store_true", help="only prepare the folder")
    parser.add_argument("--pyinstaller", action="store_true", help="build the executables")
    parser.add_argument("--iscc", action="store_true", help="build the Windows installer")
    parser.add_argument("--all", action="store_true", help="stage + pyinstaller + iscc")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    out_dir = Path(args.out_dir) if args.out_dir else ROOT / "dist"
    out_dir.mkdir(parents=True, exist_ok=True)

    everything = args.all or not (args.stage_only or args.pyinstaller or args.iscc)
    staged = stage(out_dir, quiet=args.quiet)
    built = {}
    if args.pyinstaller or args.all or everything:
        built = run_pyinstaller(out_dir, quiet=args.quiet)
    if args.iscc or args.all or everything:
        if not built:
            code = run_iscc(out_dir, {}, quiet=args.quiet)
            if not (args.iscc or args.all):
                code = 0                       # plain run must not fail without tools
            return code
        return run_iscc(out_dir, built, quiet=args.quiet)
    print(f"stage folder: {staged['stage']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
