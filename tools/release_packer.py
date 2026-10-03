import os
import shutil
import sys

# Configuration
SOURCE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RELEASE_DIR = os.path.join(SOURCE_DIR, "release_build")
GAME_NAME = "Civilization_Beta"

# What to include
INCLUDES = [
    "client",
    "server",
    "shared",
    "assets",
    "launcher.py",
    "run_client.py", # Fallback
    "run_server.py", # For hosting
    "version.txt",
    "README.md",
    "requirements.txt",
    "HOW_TO_PLAY.txt"
]

IGNORES = [
    "__pycache__",
    "*.pyc",
    ".git",
    ".vs",
    "venv",
    "env",
    "tests",
    "tools", # Don't pack tools
    "client3d"
]

def main():
    print(f"Packing {GAME_NAME}...")
    print(f"Source: {SOURCE_DIR}")
    print(f"Destination: {RELEASE_DIR}")
    
    # Create Release Dir
    target_path = os.path.join(RELEASE_DIR, GAME_NAME)
    if os.path.exists(target_path):
        print("Cleaning old build...")
        shutil.rmtree(target_path)
    
    os.makedirs(target_path)
    
    # Copy files
    for item in INCLUDES:
        s = os.path.join(SOURCE_DIR, item)
        d = os.path.join(target_path, item)
        
        if os.path.exists(s):
            if os.path.isdir(s):
                print(f"Copying Directory: {item}")
                shutil.copytree(s, d, ignore=shutil.ignore_patterns(*IGNORES))
            else:
                print(f"Copying File: {item}")
                shutil.copy2(s, d)
        else:
            print(f"Warning: {item} not found!")

    print("\nBuild Complete!")
    print(f"Files are located in: {target_path}")
    print("You can now zip this folder and share it.")

if __name__ == "__main__":
    main()
