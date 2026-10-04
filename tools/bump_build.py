"""Increment the build id in build.txt (b7 -> b8).

    python tools/bump_build.py            # print the new build
    python tools/bump_build.py --commit   # also git-commit the change

Tag a release with the same id (git tag b8 && git push --tags) so the GitHub
workflow publishes Civilization_Beta.zip and launchers can update.
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD_FILE = ROOT / "build.txt"


def read_build() -> str:
    try:
        return BUILD_FILE.read_text(encoding="utf-8").strip() or "b0"
    except OSError:
        return "b0"


def next_build(current: str) -> str:
    match = re.match(r"^([A-Za-z]*)(\d+)$", current)
    if not match:
        return "b1"
    prefix, number = match.groups()
    return f"{prefix or 'b'}{int(number) + 1}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", action="store_true", help="git commit the change")
    args = parser.parse_args()

    current = read_build()
    new = next_build(current)
    BUILD_FILE.write_text(new + "\n", encoding="utf-8")
    print(f"build {current} -> {new}")
    if args.commit:
        subprocess.run(["git", "add", "build.txt"], cwd=ROOT, check=False)
        subprocess.run(["git", "commit", "-m", f"build {new}"], cwd=ROOT, check=False)
        print(f"commit created; tag it with:  git tag {new} && git push --tags")
    return 0


if __name__ == "__main__":
    sys.exit(main())
