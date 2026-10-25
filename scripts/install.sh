#!/bin/bash
set -euo pipefail
if [ "${EUID}" -ne 0 ]; then
    echo "Run: sudo bash scripts/install.sh" >&2
    exit 1
fi
case "${1:-}" in
    ""|--no-deps) ;;
    *) echo "Usage: sudo bash scripts/install.sh [--no-deps]" >&2; exit 2 ;;
esac
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
model="$(tr -d '\0' </proc/device-tree/model)"
case "$model" in
    "Raspberry Pi 4 Model B"*) ;;
    *) echo "Validated platform is Raspberry Pi 4 Model B only." >&2; exit 1 ;;
esac
. /etc/os-release
if [ "${VERSION_CODENAME:-}" != "bookworm" ] || [ "$(getconf LONG_BIT)" != 64 ]; then
    echo "Use Raspberry Pi OS Bookworm Desktop 64-bit; other systems are not validated." >&2
    exit 1
fi
if [ "${1:-}" != --no-deps ]; then
    apt-get update
    apt-get install -y python3 python3-gi python3-cairo python3-gi-cairo gir1.2-gtk-3.0 gir1.2-gtklayershell-0.1 wlr-randr
fi
/usr/bin/python3 - <<'PY'
import gi
gi.require_version('Gtk', '3.0')
gi.require_version('GtkLayerShell', '0.1')
from gi.repository import Gtk, GtkLayerShell
import cairo
PY
command -v wlr-randr >/dev/null
if [ -L /opt/pi-setting ]; then
    echo "Refusing to install into a symlinked /opt/pi-setting." >&2
    exit 1
fi
BACKUP_DIR="/var/lib/pi-setting/install-backups/$(date +%Y%m%d-%H%M%S)"
install -d -m 755 "$BACKUP_DIR" /etc/pi-setting /var/lib/pi-setting /opt/pi-setting /usr/local/bin
if [ -f /etc/pi-setting/config.json ]; then
    cp -p /etc/pi-setting/config.json "$BACKUP_DIR/config.json"
fi
if [ "$SOURCE_DIR" != /opt/pi-setting ]; then
    if [ -d /opt/pi-setting/src ]; then
        cp -a /opt/pi-setting/src "$BACKUP_DIR/previous-src"
    fi
    cp -R "$SOURCE_DIR/src" "$SOURCE_DIR/bin" "$SOURCE_DIR/docs" "$SOURCE_DIR/scripts" "$SOURCE_DIR/systemd" "$SOURCE_DIR/desktop" /opt/pi-setting/
fi
chown -R root:root /opt/pi-setting
find /opt/pi-setting -type d -exec chmod 755 {} +
find /opt/pi-setting -type f -exec chmod 644 {} +
chmod 755 /opt/pi-setting/bin/screen-config /opt/pi-setting/bin/screen-test
for name in screen-config screen-test; do
    if [ -e "/usr/local/bin/$name" ] && [ ! -L "/usr/local/bin/$name" ]; then
        echo "Refusing to overwrite existing /usr/local/bin/$name." >&2
        exit 1
    fi
    if [ -L "/usr/local/bin/$name" ] && [ "$(readlink "/usr/local/bin/$name")" != "/opt/pi-setting/bin/$name" ]; then
        echo "Refusing to replace another application's command symlink: $name." >&2
        exit 1
    fi
    ln -sfn "/opt/pi-setting/bin/$name" "/usr/local/bin/$name"
done
install -m 644 "$SOURCE_DIR/systemd/pi-setting-boot.service" /etc/systemd/system/pi-setting-boot.service
install -d -m 755 /etc/xdg/autostart
install -m 644 "$SOURCE_DIR/desktop/pi-setting-restore.desktop" /etc/xdg/autostart/pi-setting-restore.desktop
PYTHONPATH=/opt/pi-setting/src /usr/bin/python3 -m pi_setting.migrate
systemctl daemon-reload
systemd-analyze verify /etc/systemd/system/pi-setting-boot.service
systemctl enable pi-setting-boot.service
echo "Installed. Backup: $BACKUP_DIR"
echo "Run as the desktop user: screen-config list"
echo "Start testing: screen-test pattern ; stop with: screen-test stop"
echo "No reboot or desktop restart was performed by this installer."
