"""Parse the Bookworm wlr-randr text API and apply only advertised modes."""
import re
from .common import UserError, connector_name, desktop_run

MODE = re.compile(r'^(\d+)x(\d+)@(\d+(?:\.\d+)?)(?:Hz)?$')


def parse_outputs(text):
    outputs = {}
    current = None
    for line in text.splitlines():
        match = re.match(r'^(\S+)\s+"(.*)"$', line)
        if match:
            current = {'name': match[1], 'description': match[2], 'enabled': False,
                       'modes': [], 'position': [0, 0], 'scale': 1.0, 'transform': 'normal'}
            outputs[match[1]] = current
        elif current is not None:
            field = line.strip()
            if field.startswith('Enabled:'):
                current['enabled'] = field.split(':', 1)[1].strip() == 'yes'
            elif field.startswith('Position:'):
                current['position'] = [int(n) for n in field.split(':', 1)[1].strip().split(',')]
            elif field.startswith('Scale:'):
                current['scale'] = float(field.split(':', 1)[1])
            elif field.startswith('Transform:'):
                current['transform'] = field.split(':', 1)[1].strip()
            else:
                mode = re.match(r'(\d+)x(\d+) px, ([\d.]+) Hz(.*)', field)
                if mode:
                    current['modes'].append({'width': int(mode[1]), 'height': int(mode[2]),
                                             'refresh': float(mode[3]), 'preferred': 'preferred' in mode[4],
                                             'current': 'current' in mode[4]})
    return outputs


def outputs():
    return parse_outputs(desktop_run(['wlr-randr']).stdout)


def format_mode(mode):
    return f"{mode['width']}x{mode['height']}@{mode['refresh']:.6f}"


def match_mode(modes, requested):
    match = MODE.fullmatch(requested)
    if not match:
        raise UserError('Mode must look like 800x800@60.')
    width, height, rate = int(match[1]), int(match[2]), float(match[3])
    candidates = [m for m in modes if m['width'] == width and m['height'] == height
                  and abs(m['refresh'] - rate) <= 0.100001]
    if not candidates:
        raise UserError(f'Mode {requested} is not advertised by this screen. Use screen-config modes first.')
    return min(candidates, key=lambda m: abs(m['refresh'] - rate))


def set_mode(port, requested=None):
    name = connector_name(port)
    output = outputs().get(name)
    if output is None or not output['modes']:
        raise UserError(f'{name} has no usable modes.')
    if requested:
        mode = match_mode(output['modes'], requested)
    else:
        mode = next((m for m in output['modes'] if m['preferred']), output['modes'][0])
    args = ['wlr-randr', '--output', name, '--on', '--mode', format_mode(mode)]
    desktop_run(['wlr-randr', '--dryrun'] + args[1:])
    desktop_run(args)
    observed = outputs().get(name, {})
    active = next((m for m in observed.get('modes', []) if m['current']), None)
    if not observed.get('enabled') or active is None or (active['width'], active['height']) != (mode['width'], mode['height']) or abs(active['refresh']-mode['refresh']) > 0.1:
        raise UserError(f'{name}: requested mode was not confirmed by the compositor.')
    return active
