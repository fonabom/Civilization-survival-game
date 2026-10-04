# PyInstaller spec: the dedicated server (one file, no pygame anywhere).
#
#   pyinstaller --noconfirm installer/pyinstaller/server.spec
#
# The server package is pygame-free since b12, and this build keeps it that way:
# `excludes` forbids pygame from sneaking in through an import chain, so the
# executable stays small and runs on a bare machine.

from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent.parent          # noqa: F821 - provided by PyInstaller

hiddenimports = ["shared.items", "shared.structures", "shared.techs", "shared.tasks",
                 "shared.roles", "shared.speed", "shared.paths"]

a = Analysis([str(ROOT / "run_server.py")],
             pathex=[str(ROOT)],
             binaries=[],
             datas=[(str(ROOT / "server_config.example.json"), "."),
                    (str(ROOT / "build.txt"), ".")],
             hiddenimports=hiddenimports,
             hookspath=[],
             runtime_hooks=[],
             excludes=["pygame", "client", "tests", "tools", "installer"],
             noarchive=False)
pyz = PYZ(a.pure)                                       # noqa: F821

exe = EXE(                                              # noqa: F821
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="CivilizationServer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,                      # a server is a console program
)
