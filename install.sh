#!/usr/bin/env bash
# ==============================================================================
# Logitech Battery Monitor Installer
# Installs application files, CLI launcher, icon, desktop entry, and permissions.
# ==============================================================================

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/logitech-battery-tray"
BIN_DIR="${HOME}/.local/bin"
DESKTOP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ICON_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/scalable/apps"
AUTOSTART_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/autostart"

ENABLE_AUTOSTART=false
SETUP_UDEV=false

show_help() {
    cat <<HELP
Logitech Battery Monitor Installer

Usage:
  ./install.sh [OPTIONS]

Options:
  --autostart    Enable autostart on system boot/login
  --udev         Automatically install /etc/udev/rules.d udev rule via sudo
  -h, --help     Show this help message
HELP
}

for arg in "$@"; do
    case "$arg" in
        --autostart)
            ENABLE_AUTOSTART=true
            ;;
        --udev)
            SETUP_UDEV=true
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

echo "Installing Logitech Battery Monitor..."

# 1. Check Python 3 (>= 3.8)
if ! command -v python3 >/dev/null 2>&1; then
    echo "Error: python3 is not installed. Please install Python 3 (>= 3.8) first." >&2
    exit 1
fi

PY_MAJOR="$(python3 -c 'import sys; print(sys.version_info.major)')"
PY_MINOR="$(python3 -c 'import sys; print(sys.version_info.minor)')"

if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 8 ]; }; then
    echo "Error: Python 3.8 or newer is required. Found Python ${PY_MAJOR}.${PY_MINOR}." >&2
    exit 1
fi

# 2. Check and install Python dependencies
check_and_install_dependencies() {
    local missing_qt=true
    if python3 -c "import PySide6" >/dev/null 2>&1 || \
       python3 -c "import PyQt6" >/dev/null 2>&1 || \
       python3 -c "import PyQt5" >/dev/null 2>&1; then
        missing_qt=false
    fi

    local missing_setproctitle=false
    if ! python3 -c "import setproctitle" >/dev/null 2>&1; then
        missing_setproctitle=true
    fi

    if [ "$missing_qt" = true ] || [ "$missing_setproctitle" = true ]; then
        echo "Missing optional or required Python packages detected."
        if [ -f "${REPO_DIR}/requirements.txt" ] && command -v pip3 >/dev/null 2>&1 || command -v pip >/dev/null 2>&1; then
            echo "Attempting to install Python dependencies via pip..."
            local pip_args=()
            if python3 -m pip install --help 2>&1 | grep -q -- '--break-system-packages'; then
                pip_args+=(--break-system-packages)
            fi
            python3 -m pip install --user "${pip_args[@]}" -r "${REPO_DIR}/requirements.txt" || true
        fi

        if ! python3 -c "import PySide6" >/dev/null 2>&1 && \
           ! python3 -c "import PyQt6" >/dev/null 2>&1 && \
           ! python3 -c "import PyQt5" >/dev/null 2>&1; then
            echo ""
            echo "Notice: A Qt binding (PySide6, PyQt6, or PyQt5) is required to run the tray application."
            echo "You can install dependencies via your distribution package manager or pip:"
            echo "  Fedora / Nobara: sudo dnf install python3-pyside6 python3-setproctitle"
            echo "  Ubuntu / Debian: sudo apt install python3-pyside6 python3-setproctitle"
            echo "  Arch Linux:      sudo pacman -S python-pyside6 python-setproctitle"
            echo "  Pip:             pip install -r requirements.txt"
            echo ""
        fi
    fi
}

check_and_install_dependencies

# 3. Create target directories
mkdir -p "${INSTALL_DIR}" "${INSTALL_DIR}/icons" "${BIN_DIR}" "${DESKTOP_DIR}" "${ICON_DIR}" "${AUTOSTART_DIR}"

# 4. Copy application files to ~/.local/share/logitech-battery-tray
echo "Copying application files to ${INSTALL_DIR}..."
cp -f "${REPO_DIR}/logitech_battery.py" "${INSTALL_DIR}/logitech_battery.py"
cp -f "${REPO_DIR}/get_battery.py" "${INSTALL_DIR}/get_battery.py"
cp -f "${REPO_DIR}/requirements.txt" "${INSTALL_DIR}/requirements.txt"
cp -rf "${REPO_DIR}/icons/"* "${INSTALL_DIR}/icons/"

chmod +x "${INSTALL_DIR}/logitech_battery.py"
chmod +x "${INSTALL_DIR}/get_battery.py"

# 5. Create CLI launcher wrapper in ~/.local/bin
echo "Creating CLI launcher: ${BIN_DIR}/logitech-battery-tray..."
cat > "${BIN_DIR}/logitech-battery-tray" <<'LAUNCHER_EOF'
#!/usr/bin/env bash
APP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/logitech-battery-tray"
exec python3 "${APP_DIR}/logitech_battery.py" "$@"
LAUNCHER_EOF
chmod +x "${BIN_DIR}/logitech-battery-tray"

# 6. Install scalable application icon
if [ -f "${REPO_DIR}/icons/battery-full-blue.svg" ]; then
    cp -f "${REPO_DIR}/icons/battery-full-blue.svg" "${ICON_DIR}/logitech-battery-tray.svg"
    echo "Installed application icon: ${ICON_DIR}/logitech-battery-tray.svg"
fi

# 7. Install desktop menu launcher
cat > "${DESKTOP_DIR}/logitech-battery-tray.desktop" <<DESKTOP_EOF
[Desktop Entry]
Type=Application
Name=Logitech Battery
GenericName=Logitech Battery Monitor
Comment=Logitech wireless mouse and device battery monitor tray application
Exec=logitech-battery-tray
Icon=logitech-battery-tray
Terminal=false
Categories=Utility;Qt;
Keywords=logitech;battery;mouse;tray;wireless;hid;
StartupNotify=false
DESKTOP_EOF
chmod 644 "${DESKTOP_DIR}/logitech-battery-tray.desktop"
echo "Installed desktop menu launcher: ${DESKTOP_DIR}/logitech-battery-tray.desktop"

# 8. Configure autostart if requested
if [ "$ENABLE_AUTOSTART" = true ]; then
    cp -f "${DESKTOP_DIR}/logitech-battery-tray.desktop" "${AUTOSTART_DIR}/logitech-battery-tray.desktop"
    echo "Enabled autostart on boot: ${AUTOSTART_DIR}/logitech-battery-tray.desktop"
fi

# 9. Check / setup USB udev permissions
UDEV_RULE_FILE="/etc/udev/rules.d/99-logitech-wheel.rules"
has_udev_rule() {
    [ -f "/etc/udev/rules.d/99-logitech-wheel.rules" ] || \
    [ -f "/etc/udev/rules.d/42-logitech-unify-permissions.rules" ] || \
    [ -f "/usr/lib/udev/rules.d/42-logitech-unify-permissions.rules" ]
}

if ! has_udev_rule; then
    if [ "$SETUP_UDEV" = true ]; then
        echo "Installing udev rule for Logitech HID++ permissions..."
        echo 'KERNEL=="hidraw*", SUBSYSTEM=="hidraw", ATTRS{idVendor}=="046d", MODE="0666"' | sudo tee "${UDEV_RULE_FILE}" >/dev/null
        sudo udevadm control --reload-rules
        sudo udevadm trigger
        echo "Udev rule installed and reloaded."
    elif [ -t 0 ]; then
        read -r -p "Install udev rule for Logitech receiver permissions? (requires sudo) [y/N]: " udev_ans || true
        if [[ "${udev_ans,,}" =~ ^(y|yes)$ ]]; then
            echo 'KERNEL=="hidraw*", SUBSYSTEM=="hidraw", ATTRS{idVendor}=="046d", MODE="0666"' | sudo tee "${UDEV_RULE_FILE}" >/dev/null
            sudo udevadm control --reload-rules
            sudo udevadm trigger
            echo "Udev rule installed and reloaded."
        else
            echo "Notice: Remember to setup Logitech hidraw udev permissions if your device cannot be read without root."
        fi
    else
        echo "Notice: To allow reading Logitech receiver devices without root, install the udev rule:"
        echo '  echo '"'"'KERNEL=="hidraw*", SUBSYSTEM=="hidraw", ATTRS{idVendor}=="046d", MODE="0666"'"'"' | sudo tee /etc/udev/rules.d/99-logitech-wheel.rules'
        echo '  sudo udevadm control --reload-rules && sudo udevadm trigger'
    fi
else
    echo "Logitech HID++ udev permissions rule detected."
fi

# 10. Refresh desktop and icon caches
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
echo "Installation complete."
echo "You can launch the application by running: logitech-battery-tray"
echo "or by selecting 'Logitech Battery' from your application menu."
