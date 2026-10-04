#!/usr/bin/env bash
# Civilization Survival — установка на Linux/macOS (b12).
#
#   bash installer/linux/install.sh                  # в ~/Civilization
#   bash installer/linux/install.sh ~/games/civ      # своя папка
#   bash installer/linux/install.sh --uninstall ~/Civilization
#
# Ставит клиент из архива Civilization_Client_*.zip рядом со скриптом (или из
# папки репозитория) и делает ярлык в меню приложений.

set -euo pipefail

SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TARGET="${1:-$HOME/Civilization}"
MODE="install"

if [ "${1:-}" = "--uninstall" ]; then
    MODE="uninstall"
    TARGET="${2:-$HOME/Civilization}"
fi

echo "=== Civilization Survival installer (${MODE}) ==="
echo "источник: ${SOURCE_DIR}"
echo "папка   : ${TARGET}"

if [ "$MODE" = "uninstall" ]; then
    if [ -f "${TARGET}/install.json" ]; then
        python3 "${SOURCE_DIR}/installer/install.py" --uninstall --target "${TARGET}" --silent
    else
        echo "нечего удалять: ${TARGET}/install.json не найден"
    fi
    rm -f "$HOME/.local/share/applications/civilization.desktop"
    echo "готово"
    exit 0
fi

ZIP="$(ls "${SOURCE_DIR}"/Civilization_Client_*.zip 2>/dev/null | head -1 || true)"
if [ -n "${ZIP}" ]; then
    python3 "${SOURCE_DIR}/installer/install.py" --silent --source "${ZIP}" --target "${TARGET}"
else
    python3 "${SOURCE_DIR}/installer/install.py" --silent --source "${SOURCE_DIR}" --target "${TARGET}"
fi

cat <<EOF

Готово. Запуск:
  ${TARGET}/start-game.sh
  или ярлык "Civilization Survival" в меню приложений.

Если pygame ещё не установлен:
  python3 -m pip install -r "${TARGET}/requirements.txt"

Сервер для друзей: архив Civilization_Server_*.zip — там есть README и
check_server.py (проверка, что сервер работает даже без pygame).
EOF
