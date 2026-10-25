"""Generate cable labels from confirmed screen pairs, never USB enumeration order."""
import re


def build_rules(ports):
    if set(ports) != {'0', '1'}:
        raise ValueError('Two confirmed screen/USB pairs are required')
    paths = [ports[str(port)]['by_path'] for port in (0, 1)]
    if len(set(paths)) != 2:
        raise ValueError('Each screen requires a different USB path')
    rules = ['# USB cable labels paired with confirmed HDMI-A-1/2 outputs.']
    for number, path in enumerate(paths, 1):
        if not re.fullmatch(r'[A-Za-z0-9_.:-]+-event', path):
            raise ValueError('Unsupported USB input path')
        rules.append('SUBSYSTEM=="input", KERNEL=="event*", '
                     'ENV{ID_INPUT_TOUCHSCREEN}=="1", '
                     f'ENV{{ID_PATH}}=="{path[:-6]}", '
                     f'SYMLINK+="input/USB-TOUCH-{number}"')
    return '\n'.join(rules)+'\n'
