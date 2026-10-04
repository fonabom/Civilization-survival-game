@echo off
chcp 65001 >nul
echo === Update the repository to build b13 ===
for /d /r %%d in (__pycache__) do @if exist "%%d" rmdir /s /q "%%d"
if exist venv rmdir /s /q venv
if exist release_build rmdir /s /q release_build
if exist launcher.log del /q launcher.log
if exist version.txt del /q version.txt
git add -A
git commit -m "build b13: biomes and seasons, music, first steps, quality of life"
if errorlevel 1 echo (nothing to commit? continuing)
git push
echo.
echo Done. Beta release:   git tag b13 ^&^& git push --tags
echo Stable release:       git tag 1.0.0 ^&^& git push --tags
pause
