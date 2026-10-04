# Configuration for the launcher updater.
#
# The launcher looks for updates in this order:
#   1. GitHub Releases API of GITHUB_REPO -> asset "Civilization_Beta.zip"
#      (produced by .github/workflows/release.yml when you push a build tag)
#   2. the repository archive (branch GITHUB_BRANCH) - works without any release
#   3. UPDATE_URL_VERSION / UPDATE_URL_ZIP below (own hosting or a local server)
#
# A "build" is the short id from build.txt, e.g. b7. The launcher compares the
# numbers: b12 is newer than b9.

GITHUB_REPO = "fonabom/Civilization-survival-game"
GITHUB_BRANCH = "main"

# Optional: your own hosting. Leave empty to use GitHub only.
# Example for a local test server:  python -m http.server 8000
UPDATE_URL_VERSION = ""     # e.g. "http://localhost:8000/build.txt"
UPDATE_URL_ZIP = ""         # e.g. "http://localhost:8000/game.zip"

DOWNLOAD_TIMEOUT = 30
