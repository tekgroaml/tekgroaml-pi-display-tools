#!/bin/bash
set -euo pipefail
if [ "${EUID}" -ne 0 ]; then
    echo "Run: sudo bash scripts/uninstall.sh" >&2
    exit 1
fi
echo "Stop the test first with screen-test stop as the desktop user."
systemctl disable --now pi-setting-boot.service || true
if [ -f /etc/systemd/system/pi-setting-touch.service ]; then
    systemctl disable --now pi-setting-touch.service
    rm -f /etc/systemd/system/pi-setting-touch.service
    /usr/bin/python3 - <<'PY'
import json
from pathlib import Path
import pwd
import xml.etree.ElementTree as ET
saved=Path('/etc/pi-setting/touch-map.json')
if saved.exists():
    user=pwd.getpwnam(json.loads(saved.read_text())['user'])
    rc=Path(user.pw_dir)/'.config/labwc/rc.xml'
    if rc.exists() and not rc.is_symlink():
        ET.register_namespace('', 'http://openbox.org/3.4/rc')
        tree=ET.parse(rc)
        for entry in list(tree.getroot()):
            if entry.tag.split('}')[-1]=='touch' and entry.get('deviceName', '').startswith('PiSetting Touch HDMI'):
                tree.getroot().remove(entry)
        tree.write(rc,encoding='utf-8',xml_declaration=True)
PY
fi
rm -f /etc/systemd/system/pi-setting-boot.service /etc/xdg/autostart/pi-setting-restore.desktop
for name in screen-config screen-test pi-setting; do
    if [ "$(readlink "/usr/local/bin/$name" || true)" = "/opt/pi-setting/bin/$name" ]; then
        rm -f "/usr/local/bin/$name"
    fi
done
if [ -f /var/lib/pi-setting/legacy.json ] && [ -f /etc/systemd/system/pi-hdmi-720-compat.service ]; then
    /usr/bin/python3 - <<'PY'
import json
from pathlib import Path
import subprocess
state=json.loads(Path('/var/lib/pi-setting/legacy.json').read_text())
if state.get('enabled'):
    subprocess.run(['systemctl', 'enable', 'pi-hdmi-720-compat.service'], check=True)
PY
fi
systemctl daemon-reload
echo "Startup configuration removed. Code, settings and backups are retained."
echo "Reboot to clear any runtime display override: sudo reboot"
echo "To restore the same application version later, install with --reinstall."
