#!/usr/bin/python3
"""Optional setup; identify screen/USB pairs by real taps before running."""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import pwd
import subprocess
import sys
import xml.etree.ElementTree as ET


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--screen1-device', required=True, help='Confirmed raw touch device for screen 1 / HDMI-A-1 (board HDMI0)')
    parser.add_argument('--screen2-device', required=True, help='Confirmed raw touch device for screen 2 / HDMI-A-2 (board HDMI1)')
    parser.add_argument('--user', required=True, help='Graphical desktop user')
    args = parser.parse_args()
    if os.getuid() != 0:
        parser.error('Run with sudo after confirming physical screen to input-device correspondence.')
    user = pwd.getpwnam(args.user)
    if user.pw_uid == 0:
        parser.error('The desktop user must not be root.')
    root = Path(__file__).resolve().parents[1]
    if not Path('/opt/pi-setting/src/pi_setting/touch_relay.py').exists():
        parser.error('Install or copy the updated project into /opt/pi-setting first.')
    sys.path.insert(0, str(root/'src'))
    from pi_setting.versioning import RELEASE
    from pi_setting.touch_labels import build_rules
    from evdev import InputDevice, ecodes
    config = {'version': RELEASE.config_versions['touch'], 'user': args.user, 'ports': {}}
    for port, name in enumerate((args.screen1_device, args.screen2_device)):
        source = InputDevice(name)
        try:
            if ecodes.INPUT_PROP_DIRECT not in source.input_props():
                parser.error(f'{name} is not a touchscreen.')
            links = [p for p in Path('/dev/input/by-path').glob('*-event*')
                     if p.resolve() == Path(name).resolve()]
            if len(links) != 1:
                parser.error(f'Cannot uniquely resolve the physical USB path for {name}.')
            config['ports'][str(port)] = {'by_path': links[0].name,
                                         'vendor': source.info.vendor, 'product': source.info.product}
        finally:
            source.close()
    if config['ports']['0']['by_path'] == config['ports']['1']['by_path']:
        parser.error('Each screen requires a different touch controller.')
    label_rules = build_rules(config['ports'])
    rule = Path('/etc/udev/rules.d/99-pi-setting-usb-touch-labels.rules')
    rc = Path(user.pw_dir)/'.config/labwc/rc.xml'
    if rc.is_symlink():
        parser.error('Please resolve the symlinked labwc configuration before applying this optional setup.')
    ET.register_namespace('', 'http://openbox.org/3.4/rc')
    if rc.exists():
        tree = ET.parse(rc)
    else:
        tree = ET.ElementTree(ET.Element('{http://openbox.org/3.4/rc}openbox_config'))
    base = tree.getroot()
    ns = base.tag.split('}')[0]+'}' if base.tag.startswith('{') else ''
    for item in list(base):
        if item.tag == ns+'touch' and item.get('deviceName', '').startswith('PiSetting Touch HDMI'):
            base.remove(item)
    for port in (0, 1):
        ET.SubElement(base, ns+'touch', {'deviceName': f'PiSetting Touch HDMI{port}',
                                       'mapToOutput': f'HDMI-A-{port+1}', 'mouseEmulation': 'no'})
    backup = Path('/var/lib/pi-setting/backups')/(datetime.now().strftime('%Y%m%d-%H%M%S')+'-touch-relay')
    backup.mkdir(parents=True)
    saved = Path('/etc/pi-setting/touch-map.json')
    if saved.exists():
        (backup/'previous-touch-map.json').write_bytes(saved.read_bytes())
    if rc.exists():
        (backup/'labwc-rc.xml').write_bytes(rc.read_bytes())
    if rule.exists():
        (backup/rule.name).write_bytes(rule.read_bytes())
    rc.parent.mkdir(parents=True, exist_ok=True)
    tree.write(rc, encoding='utf-8', xml_declaration=True)
    os.chown(rc, user.pw_uid, user.pw_gid)
    os.chown(rc.parent, user.pw_uid, user.pw_gid)
    saved.parent.mkdir(parents=True, exist_ok=True)
    saved.write_text(json.dumps(config, indent=2)+'\n')
    rule.parent.mkdir(parents=True, exist_ok=True)
    rule.write_text(label_rules)
    subprocess.run(['udevadm', 'control', '--reload-rules'], check=True)
    # Remove old labels before retriggering: swaps must not retain stale links.
    for number in (1, 2):
        alias = Path(f'/dev/input/USB-TOUCH-{number}')
        if alias.is_symlink():
            alias.unlink()
    for entry in config['ports'].values():
        event = (Path('/dev/input/by-path')/entry['by_path']).resolve().name
        subprocess.run(['udevadm', 'trigger', '--action=change',
                        f'/sys/class/input/{event}'], check=True)
    subprocess.run(['udevadm', 'settle'], check=True)
    for port, entry in config['ports'].items():
        number = int(port)+1
        alias = Path(f'/dev/input/USB-TOUCH-{number}')
        source = Path('/dev/input/by-path')/entry['by_path']
        if not alias.exists() or alias.resolve() != source.resolve():
            raise RuntimeError(f'USB label verification failed: {alias}')
        print(f'{alias} -> {entry["by_path"]} -> HDMI-A-{number}')
    unit = Path('/etc/systemd/system/pi-setting-touch.service')
    unit.write_bytes((root/'systemd/pi-setting-touch.service').read_bytes())
    subprocess.run(['systemctl', 'daemon-reload'], check=True)
    subprocess.run(['systemd-analyze', 'verify', str(unit)], check=True)
    subprocess.run(['systemctl', 'enable', 'pi-setting-touch.service'], check=True)
    subprocess.run(['systemctl', 'restart', 'pi-setting-touch.service'], check=True)
    print(f'Configured USB-path mapping. Backup: {backup}')
    print('Reload the desktop compositor via SIGHUP, then run screen-test touch.')


if __name__ == '__main__':
    main()
