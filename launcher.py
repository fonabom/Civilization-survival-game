"""Game launcher with a GitHub-based updater.

How updates are found (first one that works wins):
  1. GitHub Releases API -> asset "Civilization_Beta.zip" (published by
     .github/workflows/release.yml when a build tag is pushed);
  2. the repository archive from codeload (branch main) - always available,
     no release needed;
  3. explicit URLs from launcher_config.py (own hosting / local http server).

Builds are compared by their short id from build.txt (b7, b12, ...), not by
marketing versions.
"""

import argparse
import json
import logging
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from tkinter import messagebox, ttk

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from client.i18n import LANGUAGE_NAMES, available_languages, set_language, t  # noqa: E402
from shared.build import is_newer, read_build  # noqa: E402

try:
    from launcher_config import (GITHUB_BRANCH, GITHUB_REPO, UPDATE_URL_VERSION,
                                 UPDATE_URL_ZIP, DOWNLOAD_TIMEOUT)
except Exception:
    GITHUB_REPO = "fonabom/Civilization-survival-game"
    GITHUB_BRANCH = "main"
    UPDATE_URL_VERSION = ""
    UPDATE_URL_ZIP = ""
    DOWNLOAD_TIMEOUT = 30

LOG_FILE = "launcher.log"
SETTINGS_FILE = "launcher_settings.json"
GAME_SCRIPT = "run_client.py"
ASSET_NAME = "Civilization_Beta.zip"
SKIP_DIRS = {".git", "venv", ".venv", "env", "__pycache__", ".pytest_cache",
             "dist", "backup_before_update_*", "versions"}
# b12: two update channels and a rollback. "beta" follows every release
# (the bNN builds are published as pre-releases), "stable" only the versions
# you mark as a real release (1.0.0 and later).
CHANNELS = ("stable", "beta")
VERSIONS_DIR = "versions"
MAX_SNAPSHOTS = 3
USER_AGENT = "CivilizationSurvivalLauncher/1"


def setup_logging():
    logging.basicConfig(filename=str(ROOT / LOG_FILE), level=logging.INFO,
                        format="%(asctime)s %(levelname)s: %(message)s")
    return logging.getLogger("launcher")


logger = setup_logging()


# --------------------------------------------------------------------- helpers
def http_get(url: str, timeout: int = None) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                                   "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(request, timeout=timeout or DOWNLOAD_TIMEOUT) as response:
        return response.read()


def github_api(url: str):
    return json.loads(http_get(url).decode("utf-8", errors="replace"))


def build_id_from_archive(archive: Path) -> str:
    """Read build.txt from a downloaded zip (may sit in a root folder)."""
    try:
        with zipfile.ZipFile(archive) as zf:
            for name in zf.namelist():
                if name.endswith("build.txt"):
                    return zf.read(name).decode("utf-8", errors="replace").strip()
    except (zipfile.BadZipFile, OSError, KeyError):
        pass
    return ""


def strip_root_folder(extract_dir: Path) -> Path:
    """GitHub archives wrap everything in <repo>-<branch>/ - unwrap it."""
    entries = list(extract_dir.iterdir())
    if len(entries) == 1 and entries[0].is_dir():
        return entries[0]
    return extract_dir


def safe_extract(archive: Path, destination: Path):
    """Unzip, refusing entries that would escape the destination."""
    with zipfile.ZipFile(archive) as zf:
        for member in zf.infolist():
            name = member.filename
            if name.startswith(("/", "\\")) or ".." in Path(name).parts:
                raise ValueError(f"unsafe path in archive: {name}")
            zf.extract(member, destination)


class Candidate:
    """A downloadable update: where it comes from and which build it is."""

    def __init__(self, kind: str, url: str, build: str = "", size: int = 0,
                 prerelease: bool = False):
        self.kind = kind
        self.url = url
        self.build = build
        self.size = size
        self.prerelease = prerelease

    @property
    def label(self) -> str:
        name = {"release": "release", "repo": "repository",
                "direct": "own server"}.get(self.kind, self.kind)
        if self.kind == "release":
            name += " (beta)" if self.prerelease else " (stable)"
        return name


class Updater:
    """Finds, downloads and installs updates. No GUI in here, so it is testable."""

    def __init__(self, root: Path = None, repo: str = None, branch: str = None,
                 direct_version_url: str = None, direct_zip_url: str = None,
                 timeout: int = None, channel: str = "beta"):
        self.channel = channel if channel in CHANNELS else "beta"
        self.root = Path(root or ROOT)
        self.repo = GITHUB_REPO if repo is None else repo
        self.branch = GITHUB_BRANCH if branch is None else branch
        self.direct_version_url = UPDATE_URL_VERSION if direct_version_url is None \
            else direct_version_url
        self.direct_zip_url = UPDATE_URL_ZIP if direct_zip_url is None else direct_zip_url
        self.timeout = timeout or DOWNLOAD_TIMEOUT

    # ---------------------------------------------------------------- discovery
    def releases(self) -> list:
        """All published releases, newest first (empty list when offline)."""
        try:
            data = github_api(f"https://api.github.com/repos/{self.repo}/releases?per_page=30")
        except (urllib.error.URLError, ValueError, OSError) as exc:
            logger.info("release list failed: %s", exc)
            return []
        return data if isinstance(data, list) else []

    def pick_release(self, releases, channel: str = None):
        """Newest release that carries our archive; the channel decides which.

        `beta` takes everything (bNN builds are published as pre-releases),
        `stable` only releases that are not marked as a pre-release.
        """
        channel = channel or self.channel
        for data in releases or []:
            if channel == "stable" and data.get("prerelease"):
                continue
            for asset in data.get("assets", []):
                if asset.get("name", "").lower() == ASSET_NAME.lower():
                    return Candidate("release", asset["browser_download_url"],
                                     build=data.get("tag_name", ""),
                                     size=asset.get("size", 0),
                                     prerelease=bool(data.get("prerelease")))
        return None

    def find_release(self):
        found = self.pick_release(self.releases())
        if found is not None:
            return found
        # fallback for a repository that only has /releases/latest working
        try:
            data = github_api(f"https://api.github.com/repos/{self.repo}/releases/latest")
        except (urllib.error.URLError, ValueError, OSError) as exc:
            logger.info("release lookup failed: %s", exc)
            return None
        return self.pick_release([data], channel="beta")

    def repo_candidate(self):
        return Candidate("repo",
                         f"https://codeload.github.com/{self.repo}/zip/refs/heads/{self.branch}")

    def direct_candidate(self):
        if not self.direct_zip_url:
            return None
        build = ""
        if self.direct_version_url:
            try:
                build = http_get(self.direct_version_url, self.timeout).decode(
                    "utf-8", errors="replace").strip()
            except (urllib.error.URLError, OSError):
                build = ""
        return Candidate("direct", self.direct_zip_url, build=build)

    def best_candidate(self):
        """The first source that works: release -> repository -> own server."""
        candidate = None
        if self.repo:
            candidate = self.find_release()
            if candidate is None:
                candidate = self.repo_candidate()
        direct = self.direct_candidate()
        if candidate is None:
            candidate = direct
        elif not candidate.build and direct is not None:
            candidate.build = direct.build
        return candidate

    # --------------------------------------------------------------- downloading
    def download(self, candidate, progress=None) -> Path:
        """Fetch the archive into a temp dir; `progress` gets 0..100."""
        tmp_dir = Path(tempfile.mkdtemp(prefix="civ_update_"))
        target = tmp_dir / "update.zip"
        request = urllib.request.Request(candidate.url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=self.timeout) as response, \
                open(target, "wb") as out:
            header = response.getheader("Content-Length")
            total = int(header) if header and header.isdigit() else candidate.size
            done = 0
            while True:
                chunk = response.read(16384)
                if not chunk:
                    break
                out.write(chunk)
                done += len(chunk)
                if total and progress:
                    progress(int(done / total * 100))
        return target

    def check(self, progress=None) -> tuple:
        """Returns (candidate_or_None, build_id). Downloads nothing but the listing."""
        candidate = self.best_candidate()
        if candidate is None:
            return None, ""
        if candidate.kind == "repo" and not candidate.build:
            try:
                archive = self.download(candidate, progress)
            except (urllib.error.URLError, OSError) as exc:
                logger.info("could not read the repository archive: %s", exc)
                return candidate, ""
            candidate.build = build_id_from_archive(archive)
        return candidate, candidate.build

    def install(self, archive: Path, progress=None) -> tuple:
        """Unpack a downloaded archive and copy it over the game files."""
        with tempfile.TemporaryDirectory(prefix="civ_extract_") as tmp:
            extract_dir = Path(tmp)
            safe_extract(archive, extract_dir)
            content = strip_root_folder(extract_dir)
            if not (content / GAME_SCRIPT).exists() and not list(content.rglob(GAME_SCRIPT)):
                raise ValueError("the archive does not contain " + GAME_SCRIPT)
            build = build_id_from_archive(archive)
            if not self.apply(content, build):
                raise OSError("could not copy the update into place")
            return content, build

    # ------------------------------------------------ b12: snapshots & rollback
    @property
    def versions_dir(self) -> Path:
        return self.root / VERSIONS_DIR

    def local_build(self) -> str:
        """The build that is installed *here* (not the one of the project).

        A portable copy of the game has its own build.txt; taking the label from
        the running sources would name snapshots after the wrong version.
        """
        try:
            text = (self.root / "build.txt").read_text(encoding="utf-8").strip()
            if text:
                return text
        except OSError:
            pass
        return read_build()

    def snapshots(self) -> list:
        """Saved versions, newest first: [{"label", "file", "build", "created"}]."""
        index_file = self.versions_dir / "index.json"
        try:
            data = json.loads(index_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        entries = [entry for entry in data if (self.versions_dir / entry.get("file", ""))
                   .is_file()]
        entries.sort(key=lambda entry: entry.get("created", ""), reverse=True)
        return entries

    def snapshot(self, label: str = "") -> str:
        """Save the current game files as a zip so the update can be undone."""
        label = (label or self.local_build()).strip() or "b0"
        self.versions_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        name = f"{label}_{stamp}.zip"
        target = self.versions_dir / name
        try:
            with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
                for path in sorted(self.root.rglob("*")):
                    if not path.is_file():
                        continue
                    relative = path.relative_to(self.root)
                    if any(part in SKIP_DIRS or part.startswith("backup_before_update_")
                           or part.startswith(VERSIONS_DIR) for part in relative.parts):
                        continue
                    archive.write(path, relative.as_posix())
        except OSError:
            logger.exception("could not take a snapshot")
            return ""
        entries = [entry for entry in self.snapshots() if entry.get("file") != name]
        entries.insert(0, {"label": label, "file": name, "build": self.local_build(),
                           "created": stamp})
        entries = entries[:MAX_SNAPSHOTS]
        for extra in self.snapshots():
            if extra.get("file") not in [entry["file"] for entry in entries]:
                try:
                    (self.versions_dir / extra["file"]).unlink()
                except OSError:
                    pass
        try:
            (self.versions_dir / "index.json").write_text(
                json.dumps(entries, ensure_ascii=False, indent=1), encoding="utf-8")
        except OSError:
            logger.warning("could not write the snapshot index")
        logger.info("snapshot %s saved", name)
        return name

    def rollback(self, to: str = "") -> str:
        """Return to a saved version: newest one, or the one whose name matches."""
        entries = self.snapshots()
        if not entries:
            return ""
        chosen = None
        if to:
            for entry in entries:
                if to in entry.get("label", "") or to in entry.get("file", ""):
                    chosen = entry
                    break
        chosen = chosen or entries[0]
        archive = self.versions_dir / chosen["file"]
        try:
            with tempfile.TemporaryDirectory(prefix="civ_rollback_") as tmp:
                safe_extract(archive, Path(tmp))
                if not self.apply(Path(tmp), chosen.get("build", ""), snapshot_old=False):
                    return ""
        except (OSError, ValueError, zipfile.BadZipFile):
            logger.exception("rollback failed")
            return ""
        logger.info("rolled back to %s", chosen["label"])
        return chosen["label"]

    def apply(self, source_dir: Path, build: str, snapshot_old: bool = True) -> bool:
        """Copy `source_dir` over the game folder, keeping a backup."""
        if snapshot_old:
            # b12: the previous version is always recoverable - the launcher
            # stops offering an update if there is no way back.
            self.snapshot(self.local_build())
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        backup = self.root / f"backup_before_update_{timestamp}"
        try:
            shutil.copytree(self.root, backup,
                            ignore=shutil.ignore_patterns(*SKIP_DIRS), dirs_exist_ok=True)
            for item in source_dir.rglob("*"):
                relative = item.relative_to(source_dir)
                if any(part in SKIP_DIRS or part.startswith("backup_before_update_")
                       for part in relative.parts):
                    continue
                target = self.root / relative
                if item.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(item, target)
            if build:
                (self.root / "build.txt").write_text(str(build).strip() + "\n",
                                                     encoding="utf-8")
            logger.info("applied build %s", build)
            return True
        except OSError:
            logger.exception("apply failed, rolling back from %s", backup)
            try:
                for item in backup.rglob("*"):
                    relative = item.relative_to(backup)
                    target = self.root / relative
                    if item.is_dir():
                        target.mkdir(parents=True, exist_ok=True)
                    elif not target.exists() or target.stat().st_mtime < item.stat().st_mtime:
                        shutil.copy2(item, target)
            except OSError:
                logger.exception("rollback failed")
            return False


# ------------------------------------------------------------------- the app
class Launcher(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Civilization Survival")
        self.geometry("500x430")
        self.resizable(False, False)

        self.settings = self._load_settings()
        channel = self.settings.get("channel", "beta")
        self.updater = Updater(root=ROOT, channel=channel)
        set_language(self.settings.get("language", "en"))

        style = ttk.Style()
        style.configure("TButton", padding=6, font=("Arial", 11))
        style.configure("TLabel", font=("Arial", 10))
        style.configure("TCombobox", padding=4)

        self.header = tk.Label(self, font=("Arial", 20, "bold"), bg="#333", fg="white")
        self.header.pack(fill=tk.X, ipady=10)

        self.status_frame = tk.Frame(self)
        self.status_frame.pack(pady=14)
        self.lbl_status = tk.Label(self.status_frame, font=("Arial", 12))
        self.lbl_status.pack()
        self.lbl_build = tk.Label(self.status_frame, fg="gray")
        self.lbl_build.pack()
        self.lbl_source = tk.Label(self.status_frame, fg="gray", font=("Arial", 9))
        self.lbl_source.pack()

        self.progress = ttk.Progressbar(self, orient=tk.HORIZONTAL, length=340, mode="determinate")
        self.progress.pack(pady=8)

        language_frame = tk.Frame(self)
        language_frame.pack(pady=2)
        self.lbl_language = tk.Label(language_frame)
        self.lbl_language.pack(side=tk.LEFT, padx=6)
        self.language_box = ttk.Combobox(language_frame, state="readonly", width=12,
                                         values=[LANGUAGE_NAMES.get(code, code)
                                                 for code in available_languages()])
        self.language_box.pack(side=tk.LEFT)
        self.language_box.bind("<<ComboboxSelected>>", self.on_language_change)

        # b12: which channel to follow (stable releases or every beta build)
        self.channel_frame = tk.Frame(self)
        self.channel_frame.pack(pady=2)
        self.lbl_channel = tk.Label(self.channel_frame)
        self.lbl_channel.pack(side=tk.LEFT, padx=6)
        self.channel_box = ttk.Combobox(self.channel_frame, state="readonly", width=12,
                                        values=[self._channel_name(code) for code in CHANNELS])
        self.channel_box.pack(side=tk.LEFT)
        self.channel_box.bind("<<ComboboxSelected>>", self.on_channel_change)

        buttons = tk.Frame(self)
        buttons.pack(side=tk.BOTTOM, pady=16)
        self.btn_play = ttk.Button(buttons, command=self.launch_game)
        self.btn_play.pack(side=tk.LEFT, padx=6)
        self.btn_update = ttk.Button(buttons, command=self.check_update)
        self.btn_update.pack(side=tk.LEFT, padx=6)
        self.btn_rollback = ttk.Button(buttons, command=self.do_rollback)
        self.btn_rollback.pack(side=tk.LEFT, padx=6)
        self.btn_site = ttk.Button(buttons, command=self.open_website)
        self.btn_site.pack(side=tk.LEFT, padx=6)

        self.retranslate()
        self.after(300, self.auto_check)

    # ------------------------------------------------------------------ settings
    @property
    def settings_path(self) -> Path:
        return ROOT / SETTINGS_FILE

    def _load_settings(self) -> dict:
        try:
            return json.loads(self.settings_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save_settings(self):
        try:
            self.settings_path.write_text(json.dumps(self.settings, indent=1), encoding="utf-8")
        except OSError:
            logger.warning("could not write %s", self.settings_path)

    def _channel_name(self, code: str) -> str:
        return t(f"launcher.channel_{code}")

    def on_channel_change(self, _event=None):
        index = self.channel_box.current()
        if 0 <= index < len(CHANNELS):
            self.settings["channel"] = CHANNELS[index]
            self.updater.channel = CHANNELS[index]
            self._save_settings()
            self.finish(t("launcher.ready"))

    def do_rollback(self, auto: bool = False):
        """Put the previous version back (kept by Updater.snapshot)."""
        versions = self.updater.snapshots()
        if not versions:
            self.finish(t("launcher.rollback_none"), error=not auto)
            return False
        label = self.updater.rollback()
        if not label:
            self.finish(t("launcher.rollback_none"), error=not auto)
            return False
        self.finish(t("launcher.rolled_back", build=label))
        return True

    def on_language_change(self, _event=None):
        index = self.language_box.current()
        codes = available_languages()
        if 0 <= index < len(codes):
            self.settings["language"] = codes[index]
            set_language(codes[index])
            self._save_settings()
            self.retranslate()

    def retranslate(self):
        language = self.settings.get("language", "en")
        codes = available_languages()
        self.header.config(text=t("app.title"))
        self.language_box.set(LANGUAGE_NAMES.get(language, language))
        self.lbl_language.config(text=t("launcher.language"))
        self.lbl_channel.config(text=t("launcher.channel"))
        self.channel_box.set(self._channel_name(self.settings.get("channel", "beta")))
        self.lbl_status.config(text=t("launcher.ready"))
        self.lbl_build.config(text=t("launcher.current", build=read_build()))
        self.btn_play.config(text=t("launcher.play"))
        self.btn_update.config(text=t("launcher.check"))
        self.btn_rollback.config(text=t("launcher.rollback"))
        self.btn_site.config(text=t("launcher.website"))
        if language not in codes:
            self.settings["language"] = codes[0]
            set_language(codes[0])

    # ------------------------------------------------------------------- actions
    def open_website(self):
        import webbrowser
        webbrowser.open("https://retik132142121.itch.io/the-survival-civ-game")

    def launch_game(self):
        self.lbl_status.config(text=t("launcher.playing"))
        self.update_idletasks()
        script = ROOT / GAME_SCRIPT
        if not script.exists():
            messagebox.showerror("Error", f"{GAME_SCRIPT} not found")
            return
        try:
            subprocess.Popen([sys.executable, str(script)], cwd=str(ROOT))
            logger.info("launched %s", script)
            self.after(1200, self.destroy)
        except Exception as exc:                        # noqa: BLE001 - report to user
            logger.exception("launch failed")
            messagebox.showerror("Error", str(exc))

    def auto_check(self):
        if not GITHUB_REPO and not UPDATE_URL_ZIP:
            return
        self.check_update(auto=True)

    def check_update(self, auto: bool = False):
        self.btn_update.config(state="disabled")
        self.btn_play.config(state="disabled")
        self.lbl_status.config(text=t("launcher.checking"))
        threading.Thread(target=self._check_thread, args=(auto,), daemon=True).start()

    # --------------------------------------------------------------- update flow
    def _check_thread(self, auto: bool):
        local_build = read_build()
        try:
            candidate, remote_build = self.updater.check(
                progress=lambda p: self.after(0, lambda: self.progress.config(value=p)))
        except (urllib.error.URLError, ValueError, OSError) as exc:
            logger.exception("update check failed")
            self.after(0, lambda error=str(exc): self.finish(
                t("launcher.failed", error=error), error=True))
            return

        if candidate is None:
            self.after(0, lambda: self.finish(t("launcher.no_urls"), error=True))
            return

        if remote_build and not is_newer(remote_build, local_build):
            self.after(0, lambda: self.finish(t("launcher.up_to_date", build=local_build)))
            return
        if auto and not remote_build:
            self.after(0, lambda: self.finish(t("launcher.ready")))
            return

        self.after(0, lambda: self.lbl_status.config(
            text=t("launcher.update_found", build=remote_build or "?")))
        self._download_and_apply(candidate, remote_build)

    def _download_and_apply(self, candidate: Candidate, remote_build: str = ""):
        try:
            self.after(0, lambda: self.lbl_status.config(text=t("launcher.downloading")))
            archive = self.updater.download(candidate, progress=self._set_progress)

            self.after(0, lambda: self.lbl_status.config(text=t("launcher.installing")))
            _, build = self.updater.install(archive)
            build = build or remote_build or "b?"
            self.after(0, lambda: self.finish(t("launcher.updated", build=build)))
        except (urllib.error.URLError, OSError, ValueError) as exc:
            logger.exception("update failed")
            self.after(0, lambda error=str(exc): self.finish(
                t("launcher.failed", error=error), error=True))

    def _set_progress(self, percent):
        self.after(0, lambda: self.progress.config(value=percent))

    def apply_update(self, source_dir: Path, build: str) -> bool:
        """Kept for compatibility with older scripts."""
        return self.updater.apply(source_dir, build)

    def finish(self, message, error=False):
        self.lbl_status.config(text=message)
        self.lbl_build.config(text=t("launcher.current", build=read_build()))
        self.btn_update.config(state="normal")
        self.btn_play.config(state="normal")
        self.progress.config(value=0)
        if error:
            messagebox.showwarning(t("app.title"), message)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Civilization Survival launcher")
    parser.add_argument("--check", action="store_true", help="check for updates and exit")
    parser.add_argument("--channel", choices=list(CHANNELS), default=None,
                        help="update channel used for this run")
    parser.add_argument("--rollback", action="store_true",
                        help="restore the previous version and exit")
    args = parser.parse_args(argv)

    if args.rollback:
        app = Launcher()
        app.withdraw()
        if args.channel:
            app.updater.channel = args.channel
        ok = app.do_rollback(auto=True)
        app.destroy()
        return 0 if ok else 1

    if args.check:
        app = Launcher()
        app.withdraw()
        if args.channel:
            app.updater.channel = args.channel
        app.check_update()
        app.after(60000, app.destroy)
        app.mainloop()
        return 0

    Launcher().mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
