# PyInstaller spec: the game client (one folder, assets inside).
#
# The folder layout is the one shared/paths.py expects: the executable sits in
# the install folder, the data (assets, locales, packs) lies in _internal next
# to it, and the settings go to the per-user folder, because Program Files is
# read-only.
#
#   pyinstaller --noconfirm installer/pyinstaller/client.spec

from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent.parent          # noqa: F821 - provided by PyInstaller
BUILD = (ROOT / "build.txt").read_text(encoding="utf-8").strip() or "b0"


def data(folder, target=None):
    path = ROOT / folder
    return (str(path), target or folder) if path.exists() else None


datas = [item for item in (
    data("assets"),
    data("locales"),
    data("resourcepacks"),
    (str(ROOT / "build.txt"), "."),
    (str(ROOT / "config.json"), "."),
    (str(ROOT / "HOW_TO_PLAY.txt"), "."),
    (str(ROOT / "README.md"), "."),
) if item]

hiddenimports = ["client.ui", "client.ui.widgets", "client.ui.inventory_menu",
                 "client.ui.crafting_menu", "client.ui.civ_menu", "client.ui.research_menu",
                 "client.ui.tasks_menu", "client.ui.trade_menu", "client.ui.chest_menu",
                 "client.ui.smelting_menu", "client.ui.settings_menu",
                 "shared.items", "shared.structures", "shared.techs", "shared.tasks",
                 "shared.roles", "shared.speed", "shared.paths"]

a = Analysis([str(ROOT / "run_client.py")],
             pathex=[str(ROOT)],
             binaries=[],
             datas=datas,
             hiddenimports=hiddenimports,
             hookspath=[],
             runtime_hooks=[],
             excludes=["server", "tests", "tools", "installer"],
             noarchive=False)
pyz = PYZ(a.pure)                                       # noqa: F821

exe = EXE(                                              # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Civilization",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,                     # a game window, not a console
    version=None,
)
coll = COLLECT(                                         # noqa: F821
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="client",
)

# the build id is written next to the executable so the launcher can read it
try:
    (Path(SPECPATH).resolve().parent / "dist" / "client" / "build.txt").write_text(  # noqa: F821
        BUILD + "\n", encoding="utf-8")
except OSError:
    pass
