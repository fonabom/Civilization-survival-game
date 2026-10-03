import tkinter as tk
from tkinter import ttk, messagebox
import threading
import sys
import os
import subprocess
import urllib.request
import time

# Configuration
VERSION_FILE = "version.txt"
GAME_SCRIPT = "run_client.py"

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
        if os.path.exists(VERSION_FILE):
            with open(VERSION_FILE, "r") as f:
                return f.read().strip()
        return "0.0.0"
        
    def launch_game(self):
        self.lbl_status.config(text="Launching game...")
        self.update()
        try:
            # Run the game script
            if sys.platform == "win32":
                subprocess.Popen(["python", GAME_SCRIPT], shell=True)
            else:
                subprocess.Popen(["python3", GAME_SCRIPT])
            
            # Close launcher after short delay
            self.after(2000, self.destroy)
        except Exception as e:
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
                with urllib.request.urlopen(UPDATE_URL_VERSION, timeout=5) as response:
                    remote_ver = response.read().decode('utf-8').strip()
            except Exception as e:
                self.after(0, lambda: self.finish_update("Check Failed", f"Could not connect to update server.\n(Is it running?)", error=True))
                return

            local_ver = self.get_local_version()
            
            if remote_ver != local_ver:
                self.after(0, lambda: self.lbl_status.config(text=f"Update found: {remote_ver}"))
                self.download_update()
            else:
                self.after(0, lambda: self.finish_update("Up to date", "You have the latest version."))
                
        except Exception as e:
             self.after(0, lambda: self.finish_update("Error", str(e), error=True))

    def download_update(self):
        self.after(0, lambda: self.lbl_status.config(text="Downloading update..."))
        # Placeholder for download logic
        # In a real scenario, you'd download a ZIP and extract it.
        # Here we just simulate slightly.
        for i in range(101):
            time.sleep(0.02)
            self.after(0, lambda v=i: self.progress.config(value=v))
        
        # Simulate 'Finish'
        self.after(0, lambda: self.finish_update("Update Pending", "Automatic download not fully implemented in this demo.\nPlease download manually for now.", error=True))

    def finish_update(self, status, msg, error=False):
        self.lbl_status.config(text=status)
        self.btn_update.config(state="normal")
        self.btn_play.config(state="normal")
        self.progress.config(value=0)
        
        if error:
            messagebox.showwarning("Update Status", msg)
        else:
            messagebox.showinfo("Update Status", msg)

if __name__ == "__main__":
    app = Launcher()
    app.mainloop()
