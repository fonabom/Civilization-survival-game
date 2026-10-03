import tkinter as tk
from tkinter import ttk, messagebox
import threading
import sys
import os
import subprocess
import urllib.request
import time
import logging
from pathlib import Path
import shutil
import tempfile
import zipfile
from urllib.error import URLError, HTTPError

# Configuration
VERSION_FILE = "version.txt"
GAME_SCRIPT = "run_client.py"
LOG_FILE = "launcher.log"

# Try to import external config (hosted URLs). Falls back to defaults above if missing.
try:
    from launcher_config import UPDATE_URL_VERSION, UPDATE_URL_ZIP, DOWNLOAD_TIMEOUT
except Exception:
    UPDATE_URL_VERSION = "http://localhost:8000/version.txt"
    UPDATE_URL_ZIP = "http://localhost:8000/game.zip"
    DOWNLOAD_TIMEOUT = 10

# Setup basic logging to a file next to this script
_log_path = Path(__file__).with_name(LOG_FILE)
logging.basicConfig(filename=str(_log_path), level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# Placeholder URLs - Replace these with your actual hosting URLs!
# Example: "https://raw.githubusercontent.com/yourname/yourrepo/main/version.txt"
UPDATE_URL_VERSION = "http://localhost:8000/version.txt" 
UPDATE_URL_ZIP = "http://localhost:8000/game.zip"

class Launcher(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Civilization Game Launcher")
        self.geometry("400x300")
        self.resizable(False, False)
        
        # Style
        style = ttk.Style()
        style.configure("TButton", padding=6, font=("Arial", 12))
        style.configure("TLabel", font=("Arial", 10))
        
        # Header
        header = tk.Label(self, text="Civilization Beta", font=("Arial", 20, "bold"), bg="#333", fg="white")
        header.pack(fill=tk.X, pady=0, ipady=10)
        
        # Status Frame
        self.status_frame = tk.Frame(self)
        self.status_frame.pack(pady=20)
        
        self.lbl_status = tk.Label(self.status_frame, text="Ready", font=("Arial", 12))
        self.lbl_status.pack()
        
        self.lbl_version = tk.Label(self.status_frame, text=f"Installed Version: {self.get_local_version()}", fg="gray")
        self.lbl_version.pack()
        
        # Progress Bar
        self.progress = ttk.Progressbar(self, orient=tk.HORIZONTAL, length=300, mode='determinate')
        self.progress.pack(pady=10)
        
        # Buttons
        btn_frame = tk.Frame(self)
        btn_frame.pack(side=tk.BOTTOM, pady=20)
        
        self.btn_play = ttk.Button(btn_frame, text="PLAY", command=self.launch_game)
        self.btn_play.pack(side=tk.LEFT, padx=10)
        
        self.btn_update = ttk.Button(btn_frame, text="Check Updates", command=self.check_update)
        self.btn_update.pack(side=tk.LEFT, padx=10)
        
        self.btn_site = ttk.Button(btn_frame, text="Visit Website", command=self.open_website)
        self.btn_site.pack(side=tk.LEFT, padx=10)
        
    def open_website(self):
        import webbrowser
        webbrowser.open("https://retik132142141.itch.io/the-survival-civ-game")

    def get_local_version(self):
        try:
            path = Path(__file__).parent / VERSION_FILE
            if path.exists():
                return path.read_text(encoding="utf-8").strip()
        except Exception as e:
            logger.exception("Error reading local version file")
        return "0.0.0"
        
    def launch_game(self):
        self.lbl_status.config(text="Launching game...")
        self.update()
        try:
            # Run the game script using the same Python executable (respects venv)
            script_path = Path(__file__).parent / GAME_SCRIPT
            subprocess.Popen([sys.executable, str(script_path)], cwd=str(Path(__file__).parent))
            logger.info("Launched game: %s %s", sys.executable, script_path)

            # Close launcher after short delay
            self.after(2000, self.destroy)
        except Exception as e:
            logger.exception("Failed to launch game")
            messagebox.showerror("Error", f"Failed to launch game:\n{e}")
            self.lbl_status.config(text="Launch Failed")

    def check_update(self):
        self.btn_update.config(state="disabled")
        self.btn_play.config(state="disabled")
        self.lbl_status.config(text="Checking for updates...")
        
        thread = threading.Thread(target=self._check_update_thread)
        thread.start()
        
    def _check_update_thread(self):
        try:
            # 1. Fetch Remote Version
            # For beta test without server, this will fail unless user runs a local server
            # We add a friendly fail message.
            try:
                with urllib.request.urlopen(UPDATE_URL_VERSION, timeout=DOWNLOAD_TIMEOUT) as response:
                    remote_ver = response.read().decode('utf-8').strip()
            except (URLError, HTTPError, TimeoutError) as e:
                logger.exception("Failed to fetch remote version")
                self.after(0, lambda: self.finish_update("Check Failed", f"Could not connect to update server.\n(Is it running?)", error=True))
                return

            local_ver = self.get_local_version()
            
            if remote_ver != local_ver:
                self.after(0, lambda: self.lbl_status.config(text=f"Update found: {remote_ver}"))
                self.download_update(remote_ver)
            else:
                self.after(0, lambda: self.finish_update("Up to date", "You have the latest version."))
                
        except Exception as e:
             self.after(0, lambda: self.finish_update("Error", str(e), error=True))

    def download_update(self, remote_ver: str):
        """Download update ZIP, extract to temp, and apply safely."""
        self.after(0, lambda: self.lbl_status.config(text="Downloading update..."))
        tmp_dir = None
        tmp_zip = None
        try:
            tmp_dir = tempfile.mkdtemp(prefix="civ_update_")
            tmp_zip = Path(tmp_dir) / "update.zip"

            # Stream download and update progress by bytes
            with urllib.request.urlopen(UPDATE_URL_ZIP, timeout=DOWNLOAD_TIMEOUT) as resp:
                total = resp.getheader('Content-Length')
                if total is not None:
                    total = int(total)
                downloaded = 0
                chunk_size = 8192
                with open(tmp_zip, 'wb') as out:
                    while True:
                        chunk = resp.read(chunk_size)
                        if not chunk:
                            break
                        out.write(chunk)
                        downloaded += len(chunk)
                        if total:
                            percent = int(downloaded / total * 100)
                        else:
                            percent = 0
                        self.after(0, lambda v=percent: self.progress.config(value=v))

            self.after(0, lambda: self.lbl_status.config(text="Extracting update..."))
            extract_dir = Path(tmp_dir) / "extracted"
            extract_dir.mkdir(exist_ok=True)
            with zipfile.ZipFile(str(tmp_zip), 'r') as z:
                z.extractall(path=str(extract_dir))

            # Apply update (make backup first)
            applied = self.apply_update(extract_dir, remote_ver)
            if applied:
                self.after(0, lambda: self.finish_update("Update Applied", f"Updated to version {remote_ver}.") )
            else:
                self.after(0, lambda: self.finish_update("Update Failed", "Failed to apply update.", error=True))

        except Exception as e:
            logger.exception("Error during update download/apply")
            self.after(0, lambda: self.finish_update("Update Error", str(e), error=True))
        finally:
            try:
                if tmp_zip and tmp_zip.exists():
                    tmp_zip.unlink()
                # keep extracted folder for debugging if needed; it's in tmp_dir
            except Exception:
                pass

    def finish_update(self, status, msg, error=False):
        self.lbl_status.config(text=status)
        self.btn_update.config(state="normal")
        self.btn_play.config(state="normal")
        self.progress.config(value=0)
        
        if error:
            messagebox.showwarning("Update Status", msg)
        else:
            messagebox.showinfo("Update Status", msg)

    def apply_update(self, extract_dir: Path, remote_ver: str) -> bool:
        """Copy extracted files into project directory with backup.

        Returns True on success.
        """
        try:
            project_dir = Path(__file__).parent
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            backup_dir = project_dir / f"backup_before_update_{timestamp}"
            logger.info("Creating backup of project to %s", backup_dir)
            shutil.copytree(project_dir, backup_dir, dirs_exist_ok=True)

            # Copy files from extract_dir into project_dir
            for src in extract_dir.rglob('*'):
                rel = src.relative_to(extract_dir)
                dest = project_dir / rel
                if src.is_dir():
                    dest.mkdir(parents=True, exist_ok=True)
                else:
                    # Ensure parent exists
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dest)

            # Update version file
            try:
                (project_dir / VERSION_FILE).write_text(str(remote_ver), encoding='utf-8')
            except Exception:
                logger.exception("Failed to write version file")

            logger.info("Update applied successfully to %s", project_dir)
            return True
        except Exception as e:
            logger.exception("Failed to apply update")
            return False

if __name__ == "__main__":
    app = Launcher()
    app.mainloop()
