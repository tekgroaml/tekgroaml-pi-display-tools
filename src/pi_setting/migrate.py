"""Recognize and migrate the older hash-based 720 display compatibility helper."""
import ast
from pathlib import Path
import re
import shutil
from . import edid, store
from .common import run

SERVICE = 'pi-hdmi-720-compat.service'


def recognized_helper(text):
    """Identify the supported helper layout without embedding any unit's EDID hash.

    This only classifies an existing root-owned helper for backup/disable; its
    contents are never imported or executed. Unknown helpers stay untouched.
    """
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return False
    if ast.get_docstring(tree) != 'Apply the minimal Pi 4 timing correction to the known 720x720 monitor at boot.':
        return False
    constants = {}
    functions = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            if isinstance(node.value, ast.Constant):
                constants[node.targets[0].id] = node.value.value
        elif isinstance(node, ast.FunctionDef):
            functions[node.name] = node
    if not all(isinstance(constants.get(name), str) and re.fullmatch(r'[0-9a-f]{64}', constants[name])
               for name in ('ORIGINAL_HASH', 'FIXED_HASH')):
        return False
    if not {'compatible_edid', 'main'} <= functions.keys():
        return False
    profile = functions['compatible_edid']
    expected_assignment = ast.dump(ast.parse('corrected[63] = 6').body[0])
    if not any(ast.dump(node) == expected_assignment for node in ast.walk(profile)):
        return False
    values = {node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)}
    return {'/sys/class/drm', '/sys/kernel/debug/dri', 'edid_override', '720x720'} <= values


def main():
    legacy = Path('/usr/local/sbin/pi-hdmi-720-compat')
    unit = Path('/etc/systemd/system')/SERVICE
    if not legacy.is_file() or not unit.is_file():
        return
    text = legacy.read_text()
    if not recognized_helper(text):
        print('Unrecognized legacy helper left unchanged; check for conflicting display managers.')
        return
    record = store.STATE/'legacy.json'
    if not record.exists():
        store.STATE.mkdir(parents=True, exist_ok=True)
        enabled = run(['systemctl', 'is-enabled', SERVICE], check=False).returncode == 0
        store.atomic_json(record, {'enabled': enabled})
        shutil.copyfile(legacy, store.STATE/'legacy-helper.py')
        shutil.copyfile(unit, store.STATE/'legacy-service.txt')
    run(['systemctl', 'disable', SERVICE], check=False)
    config = store.load()
    for port in (0, 1):
        try:
            raw = edid.raw_edid(port)
        except Exception:
            continue
        if edid.compatible(raw) and str(port) not in config['ports']:
            config['ports'][str(port)] = {'identity': edid.identity(raw), 'mode': '720x720@60.004',
                                          'profile': edid.PROFILE}
    store.atomic_json(store.CONFIG, config)
    print('Legacy 720 service backed up and disabled; matching attached screens migrated.')


if __name__ == '__main__':
    main()
