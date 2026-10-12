#!/usr/bin/env bash
# ==============================================================================
# Logitech Battery Monitor Uninstaller
# Stops the application and removes installed binaries, launchers, and icons.
# ==============================================================================

set -euo pipefail

INSTALL_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/logitech-battery-tray"
BIN_DIR="${HOME}/.local/bin"
DESKTOP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ICON_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/scalable/apps"
AUTOSTART_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/autostart"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/logitech-battery-tray"

PURGE_CONFIG=false

show_help() {
    cat <<HELP
Logitech Battery Monitor Uninstaller

Usage:
  ./uninstall.sh [OPTIONS]

Options:
  --purge        Also delete user configuration (~/.config/logitech-battery-tray)
  -h, --help     Show this help message
HELP
}

for arg in "$@"; do
    case "$arg" in
        --purge)
            PURGE_CONFIG=true
            ;;
        -h|--help)
            show_help
            exit 0
            ;;
        *)
            echo "Unknown option: $arg"
            show_help
            exit 1
            ;;
    esac
done

echo "Uninstalling Logitech Battery Monitor..."

# 1. Stop any running instances
echo "Stopping any running instances..."
pkill -f "logitech_battery.py" 2>/dev/null || true
pkill -f "logitech-battery-tray" 2>/dev/null || true

# 2. Remove installed binaries and launchers
echo "Removing CLI launcher and desktop files..."
rm -f "${BIN_DIR}/logitech-battery-tray"
rm -f "${DESKTOP_DIR}/logitech-battery-tray.desktop"
rm -f "${AUTOSTART_DIR}/logitech-battery-tray.desktop"
rm -f "${ICON_DIR}/logitech-battery-tray.svg"

# 3. Remove application installation directory
if [ -d "${INSTALL_DIR}" ]; then
    echo "Removing application directory ${INSTALL_DIR}..."
    rm -rf "${INSTALL_DIR}"
fi

# 4. Handle configuration directory
if [ "$PURGE_CONFIG" = true ]; then
    if [ -d "${CONFIG_DIR}" ]; then
        echo "Purging configuration directory ${CONFIG_DIR}..."
        rm -rf "${CONFIG_DIR}"
    fi
else
    if [ -d "${CONFIG_DIR}" ]; then
        echo "Configuration preserved at ${CONFIG_DIR} (use './uninstall.sh --purge' to delete)."
    fi
fi

# 5. Refresh desktop and icon databases
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "${DESKTOP_DIR}" >/dev/null 2>&1 || true
fi

if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -f -q -t "${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor" >/dev/null 2>&1 || true
fi

if command -v kbuildsycoca6 >/dev/null 2>&1; then
    kbuildsycoca6 --noincremental >/dev/null 2>&1 || true
elif command -v kbuildsycoca5 >/dev/null 2>&1; then
    kbuildsycoca5 --noincremental >/dev/null 2>&1 || true
fi

echo ""
echo "Logitech Battery Monitor has been uninstalled successfully."
