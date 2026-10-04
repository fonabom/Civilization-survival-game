#!/usr/bin/env bash
set -e
echo "=== Update the repository to build b13 ==="
find . -name "__pycache__" -not -path "./.git/*" -prune -exec rm -rf {} + 2>/dev/null || true
rm -rf venv release_build launcher.log version.txt
git add -A
git commit -m "build b13: biomes and seasons, music, first steps, quality of life" || echo "(nothing to commit? continuing)"
git push
echo
echo "Done. Beta release:   git tag b13 && git push --tags"
echo "Stable release:       git tag 1.0.0 && git push --tags"
