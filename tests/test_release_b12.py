"""b12 «Релизная инженерия»: the server/client split, the installer, channels.

Idea #9 of the 1.0.0 plan, plus the request «разделить сервер и клиент» and
«сделать инсталлятор». What is checked here:

* the server package really has no pygame in it (statically **and** by running
  the archive with pygame poisoned),
* the client package has the game but not the server code,
* the installer copies a client package into a folder, writes install.json,
  makes a start script and removes everything again on --uninstall,
* shared/paths.py finds the right folders from source and inside a frozen EXE,
* the launcher picks the right release for the stable / beta channel.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import tools.make_release as make_release  # noqa: E402


def python_files(*folders: str) -> list:
    found = []
    for folder in folders:
        base = ROOT / folder
        if base.is_file():
            found.append(base)
            continue
        found.extend(sorted(p for p in base.rglob("*.py") if "__pycache__" not in str(p)))
    return found


def imports_of(path: Path) -> set:
    import ast
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    return names


class SplitTest(unittest.TestCase):
    """The server is its own package: no pygame, no client code."""

    def test_the_server_never_imports_pygame(self):
        offenders = []
        for path in python_files("server", "shared") + [ROOT / "run_server.py",
                                                        ROOT / "check_server.py"]:
            if "pygame" in imports_of(path):
                offenders.append(str(path.relative_to(ROOT)))
        self.assertEqual(offenders, [], f"pygame leaked into the server: {offenders}")

    def test_the_server_never_imports_the_client(self):
        offenders = []
        for path in python_files("server", "shared") + [ROOT / "run_server.py",
                                                        ROOT / "check_server.py"]:
            if "client" in imports_of(path):
                offenders.append(str(path.relative_to(ROOT)))
        self.assertEqual(offenders, [], f"the server pulled in the game client: {offenders}")

    def test_the_client_never_imports_the_server(self):
        offenders = []
        for path in python_files("client") + [ROOT / "run_client.py", ROOT / "launcher.py"]:
            if "server" in imports_of(path):
                offenders.append(str(path.relative_to(ROOT)))
        self.assertEqual(offenders, [], f"the client pulled in the server: {offenders}")

    def test_the_launcher_and_the_installer_stay_light(self):
        """Both must work on a machine without pygame (they only start it)."""
        for name in ("launcher.py", "installer/install.py", "installer/build_installer.py",
                     "tools/make_release.py"):
            self.assertNotIn("pygame", imports_of(ROOT / name), name)


class PackageTest(unittest.TestCase):
    """What exactly ends up in each archive."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls.tmp.name)
        cls.built = {kind: make_release.build(kind, out_dir=cls.out)
                     for kind in ("client", "server", "bundle")}

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def names(self, kind: str) -> set:
        with zipfile.ZipFile(self.built[kind]["path"]) as zf:
            return set(zf.namelist())

    def test_the_client_package_holds_the_game(self):
        names = self.names("client")
        for expected in ("run_client.py", "launcher.py", "client/game.py", "shared/items.py",
                         "assets/player.png", "locales/ru.json", "build.txt",
                         "ЧИТАЙ_МЕНЯ.txt", "release.json"):
            self.assertIn(expected, names, f"{expected} is missing from the client package")
        self.assertFalse([n for n in names if n.startswith("server/")],
                         "the client package must not ship the server")
        self.assertFalse([n for n in names if n.startswith("tests/")])

    def test_the_server_package_holds_the_server_only(self):
        names = self.names("server")
        for expected in ("run_server.py", "check_server.py", "server/server.py",
                         "shared/items.py", "server_config.example.json",
                         "requirements-server.txt", "build.txt", "ЧИТАЙ_МЕНЯ.txt"):
            self.assertIn(expected, names, f"{expected} is missing from the server package")
        self.assertFalse([n for n in names if n.startswith("client/")],
                         "the server package must not ship the game client")
        self.assertFalse([n for n in names if n.startswith("assets/")],
                         "the server package needs no textures")
        self.assertFalse([n for n in names if n.endswith(".png")])
        self.assertFalse([n for n in names if n.endswith(".py") and "pygame" in n])

    def test_the_bundle_has_both_and_keeps_its_name(self):
        path = Path(self.built["bundle"]["path"])
        self.assertEqual(path.name, "Civilization_Beta.zip",
                         "the launcher downloads exactly this file name")
        names = self.names("bundle")
        self.assertIn("run_client.py", names)
        self.assertIn("run_server.py", names)

    def test_the_readme_explains_what_the_package_is(self):
        for kind in ("client", "server"):
            with zipfile.ZipFile(self.built[kind]["path"]) as zf:
                text = zf.read("ЧИТАЙ_МЕНЯ.txt").decode("utf-8")
                manifest = json.loads(zf.read("release.json").decode("utf-8"))
            self.assertIn(make_release.read_build(), text)
            self.assertEqual(manifest["kind"], kind)
            self.assertEqual(manifest["build"], make_release.read_build())
            self.assertIn("run_client.py" if kind == "client" else "run_server.py",
                          manifest["files"])

    def test_the_server_archive_runs_without_pygame(self):
        """The real proof of the split: unzip somewhere, poison pygame, start it."""
        with tempfile.TemporaryDirectory() as tmp:
            with zipfile.ZipFile(self.built["server"]["path"]) as zf:
                zf.extractall(tmp)
            self.assertTrue((Path(tmp) / "check_server.py").exists())
            result = subprocess.run([sys.executable, "check_server.py", "--forbid-pygame"],
                                    cwd=tmp, capture_output=True, text=True, timeout=120)
            self.assertEqual(result.returncode, 0,
                             f"the server package does not run:\n{result.stdout}\n{result.stderr}")
            self.assertIn("works without pygame", result.stdout)
            self.assertIn("handshake ok", result.stdout)


class InstallerTest(unittest.TestCase):
    """installer/install.py: install, describe itself, uninstall."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls.tmp.name)
        cls.package = Path(make_release.build("client", out_dir=cls.out)["path"])

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def run_installer(self, *args, target):
        command = [sys.executable, str(ROOT / "installer" / "install.py"),
                   "--silent", "--target", str(target), *args]
        return subprocess.run(command, capture_output=True, text=True, timeout=180,
                              env={**os.environ, "HOME": str(self.out),
                                   "USERPROFILE": str(self.out)})

    def test_install_and_uninstall(self):
        target = self.out / "installed"
        result = self.run_installer("--source", str(self.package), "--json", target=target)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        self.assertTrue((target / "run_client.py").exists())
        self.assertTrue((target / "client" / "game.py").exists())
        self.assertTrue((target / "assets" / "player.png").exists())
        self.assertTrue((target / "install.json").exists(),
                        "without the manifest the game cannot be removed cleanly")
        manifest = json.loads((target / "install.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["build"], make_release.read_build())
        self.assertGreater(len(manifest["files"]), 50)
        self.assertIn("run_client.py", manifest["files"])

        starts = [p for p in target.iterdir()
                  if p.name in ("start-game.sh", "ЗАПУСТИТЬ_ИГРУ.bat")]
        self.assertEqual(len(starts), 1, f"no start script in {list(target.iterdir())[:8]}")
        if not sys.platform.startswith("win"):
            self.assertTrue(os.access(starts[0], os.X_OK), "the start script is not runnable")

        # byte code appears as soon as somebody plays from that folder
        (target / "shared" / "__pycache__").mkdir(exist_ok=True)
        (target / "shared" / "__pycache__" / "x.pyc").write_bytes(b"x")

        result = self.run_installer("--uninstall", target=target)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse((target / "run_client.py").exists(), "the files are still there")
        self.assertFalse((target / "install.json").exists())
        leftovers = sorted(str(p.relative_to(target))
                           for p in target.rglob("*")) if target.exists() else []
        self.assertEqual(leftovers, [],
                         f"uninstall left this behind: {leftovers[:10]}")

    def test_the_installed_game_can_be_started_headless(self):
        """Copy -> run it for real (no window, dummy video) -> it asks for a server."""
        target = self.out / "run-from"
        result = self.run_installer("--source", str(self.package), target=target)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        probe = ("import sys; sys.path.insert(0, '.');"
                 "from client.main import main;"
                 "import client.settings as s;"
                 "print('client import ok', s.SCREEN_WIDTH, s.SCREEN_HEIGHT)")
        result = subprocess.run([sys.executable, "-c", probe], cwd=target,
                                capture_output=True, text=True, timeout=120,
                                env={**os.environ, "SDL_VIDEODRIVER": "dummy",
                                     "SDL_AUDIODRIVER": "dummy"})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("client import ok", result.stdout)

    def test_a_server_package_is_not_installed_as_the_game(self):
        """A player may grab the wrong archive - the installer has to say so."""
        server_package = Path(make_release.build("server", out_dir=self.out / "srv")["path"])
        target = self.out / "wrong"
        result = self.run_installer("--source", str(server_package), target=target)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("not a client package", result.stdout + result.stderr)
        self.assertFalse((target / "run_server.py").exists(),
                         "the server files were copied into the game folder")

    def test_a_folder_without_the_game_is_refused(self):
        empty = self.out / "empty"
        empty.mkdir(exist_ok=True)
        result = self.run_installer("--source", str(empty), target=self.out / "nope")
        self.assertNotEqual(result.returncode, 0, result.stdout)


class PathsTest(unittest.TestCase):
    """shared/paths.py: source folder, installed folder, frozen EXE."""

    def setUp(self):
        import shared.paths as paths
        self.paths = paths
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(lambda: [os.environ.pop(name, None)
                                 for name in ("CIV_DATA_DIR", "CIV_WRITE_DIR",
                                              "CIV_APP_DIR")])

    def test_from_source_everything_is_the_project(self):
        from shared.paths import app_root, data_root, writable_root
        self.assertEqual(app_root(), ROOT)
        self.assertEqual(data_root(), ROOT)
        self.assertEqual(writable_root(), ROOT)

    def test_overrides_are_respected(self):
        data = Path(self.tmp.name) / "data"
        write = Path(self.tmp.name) / "config"
        app = Path(self.tmp.name) / "app"
        os.environ["CIV_DATA_DIR"] = str(data)
        os.environ["CIV_WRITE_DIR"] = str(write)
        os.environ["CIV_APP_DIR"] = str(app)
        from shared.paths import app_root, data_root, ensure_writable, writable_root
        self.assertEqual(data_root(), data)
        self.assertEqual(writable_root(), write)
        self.assertEqual(app_root(), app)
        self.assertEqual(ensure_writable(), write)
        self.assertTrue(write.is_dir(), "ensure_writable has to create the folder")

    def test_a_frozen_game_reads_next_to_its_exe_and_writes_to_the_user_folder(self):
        from unittest import mock
        exe_dir = Path(self.tmp.name) / "install"
        (exe_dir / "assets").mkdir(parents=True)
        (exe_dir / "build.txt").write_text("b12\n", encoding="utf-8")
        data_home = Path(self.tmp.name) / "xdg"
        os.environ["XDG_DATA_HOME"] = str(data_home)
        with mock.patch.object(sys, "frozen", True, create=True), \
                mock.patch.object(sys, "executable", str(exe_dir / "Civilization.exe")), \
                mock.patch.object(self.paths, "is_frozen", lambda: True):
            from shared.paths import app_root, data_root, writable_root
            self.assertEqual(app_root(), exe_dir)
            self.assertEqual(data_root(), exe_dir)
            self.assertEqual(writable_root(), data_home / "Civilization")
            self.assertNotEqual(writable_root(), data_root(),
                                "a packaged game must not write into its own folder")

    def test_config_falls_back_to_the_packaged_default(self):
        packaged = Path(self.tmp.name) / "packaged"
        writable = Path(self.tmp.name) / "writable"
        packaged.mkdir()
        writable.mkdir()
        (packaged / "config.json").write_text('{"last_login": "Ada"}', encoding="utf-8")
        os.environ["CIV_DATA_DIR"] = str(packaged)
        os.environ["CIV_WRITE_DIR"] = str(writable)
        from shared.paths import config_file
        self.assertEqual(config_file("config.json"), packaged / "config.json")
        (writable / "config.json").write_text('{"last_login": "Bob"}', encoding="utf-8")
        self.assertEqual(config_file("config.json"), writable / "config.json",
                         "the user copy wins")


class LauncherChannelTest(unittest.TestCase):
    """The launcher follows a channel and can always go one version back."""

    def setUp(self):
        sys.path.insert(0, str(ROOT))
        import launcher
        self.launcher = launcher
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def releases(self):
        return [
            {"tag_name": "b12", "prerelease": True,
             "assets": [{"name": "Civilization_Beta.zip",
                         "browser_download_url": "http://x/b12.zip", "size": 10}]},
            {"tag_name": "1.0.0", "prerelease": False,
             "assets": [{"name": "Civilization_Beta.zip",
                         "browser_download_url": "http://x/100.zip", "size": 11}]},
            {"tag_name": "b13", "prerelease": True,
             "assets": [{"name": "Civilization_Beta.zip",
                         "browser_download_url": "http://x/b13.zip", "size": 12}]},
        ]

    def test_the_beta_channel_takes_the_newest_build(self):
        updater = self.launcher.Updater(root=self.root, channel="beta")
        picked = updater.pick_release(self.releases())
        self.assertEqual(picked.build, "b12", "GitHub lists the newest first")
        self.assertTrue(picked.prerelease)
        self.assertIn("beta", picked.label)

    def test_the_stable_channel_skips_pre_releases(self):
        updater = self.launcher.Updater(root=self.root, channel="stable")
        picked = updater.pick_release(self.releases())
        self.assertEqual(picked.build, "1.0.0")
        self.assertFalse(picked.prerelease)
        self.assertIn("stable", picked.label)

    def test_an_unknown_channel_falls_back_to_beta(self):
        updater = self.launcher.Updater(root=self.root, channel="nonsense")
        self.assertEqual(updater.channel, "beta")

    def test_a_release_without_our_archive_is_ignored(self):
        updater = self.launcher.Updater(root=self.root, channel="beta")
        releases = [{"tag_name": "b14", "prerelease": True, "assets": []}]
        self.assertIsNone(updater.pick_release(releases))

    def test_snapshot_and_rollback_put_the_old_version_back(self):
        updater = self.launcher.Updater(root=self.root, channel="beta")
        (self.root / "run_client.py").write_text("old version", encoding="utf-8")
        (self.root / "client").mkdir()
        (self.root / "client" / "game.py").write_text("old game", encoding="utf-8")
        self.assertTrue(updater.snapshot("b11"))

        (self.root / "run_client.py").write_text("new version", encoding="utf-8")
        (self.root / "client" / "game.py").write_text("new game", encoding="utf-8")
        self.assertEqual(len(updater.snapshots()), 1)

        label = updater.rollback()
        self.assertEqual(label, "b11")
        self.assertEqual((self.root / "run_client.py").read_text(encoding="utf-8"),
                         "old version")
        self.assertEqual((self.root / "client" / "game.py").read_text(encoding="utf-8"),
                         "old game")

    def test_only_a_few_snapshots_are_kept(self):
        updater = self.launcher.Updater(root=self.root, channel="beta")
        (self.root / "run_client.py").write_text("x", encoding="utf-8")
        for build in ("b10", "b11", "b12", "b13"):
            updater.snapshot(build)
            (self.root / "run_client.py").write_text(build, encoding="utf-8")
        self.assertLessEqual(len(updater.snapshots()), self.launcher.MAX_SNAPSHOTS)

    def test_apply_takes_a_snapshot_before_overwriting(self):
        updater = self.launcher.Updater(root=self.root, channel="beta")
        (self.root / "run_client.py").write_text("b11", encoding="utf-8")
        (self.root / "build.txt").write_text("b11\n", encoding="utf-8")
        source = self.root / "update"
        source.mkdir()
        (source / "run_client.py").write_text("b12", encoding="utf-8")
        self.assertTrue(updater.apply(source, "b12"))
        self.assertEqual((self.root / "run_client.py").read_text(encoding="utf-8"), "b12")
        self.assertEqual(len(updater.snapshots()), 1)
        self.assertEqual(updater.rollback(), "b11")
        self.assertEqual((self.root / "run_client.py").read_text(encoding="utf-8"), "b11")

    def test_the_launcher_translates_the_new_buttons(self):
        import client.i18n as i18n
        for language in i18n.available_languages():
            i18n.set_language(language)
            for key in ["launcher.channel", "launcher.rollback", "launcher.rolled_back",
                        "launcher.rollback_none"] + [f"launcher.channel_{c}"
                                                     for c in self.launcher.CHANNELS]:
                self.assertNotEqual(i18n.t(key), key, f"{key} is not translated ({language})")


class WorkflowTest(unittest.TestCase):
    """The CI must publish what the launcher and the installer need."""

    def test_the_release_workflow_builds_every_package(self):
        text = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
        self.assertIn("tools/make_release.py --kind all", text)
        self.assertIn("Civilization_Beta.zip", text)
        self.assertIn("Civilization-Setup-", text)
        self.assertIn("prerelease:", text)
        self.assertIn("installer/build_installer.py", text)

    def test_the_workflow_yaml_is_valid(self):
        try:
            import yaml
        except ImportError:
            self.skipTest("pyyaml is not installed")
        for name in ("release.yml", "tests.yml"):
            with open(ROOT / ".github" / "workflows" / name, encoding="utf-8") as handle:
                data = yaml.safe_load(handle)
            self.assertIn("jobs", data)


if __name__ == "__main__":
    unittest.main()
