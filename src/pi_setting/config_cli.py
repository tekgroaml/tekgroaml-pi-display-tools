"""screen-config: mutations run with sudo, rendering stays in the desktop session."""
import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from . import edid, outputs, store
from .common import UserError, connector_name, root_required, run


def build_parser():
    parser = argparse.ArgumentParser(prog='screen-config', description='Per-port Raspberry Pi HDMI configuration')
    commands = parser.add_subparsers(dest='action', required=True)
    commands.add_parser('list', help='Show current output and saved configuration')
    commands.add_parser('profiles', help='List verified compatibility profiles')
    for action in ('modes', 'set', 'auto', 'apply'):
        command = commands.add_parser(action)
        command.add_argument('--port', type=int, choices=(1, 2), required=True,
                             help='1=HDMI-A-1 (board HDMI0); 2=HDMI-A-2 (board HDMI1)')
        if action != 'modes':
            command.add_argument('--save', action='store_true', help='Persist for this port and this display identity')
        if action == 'set':
            command.add_argument('--mode', required=True, help='Example: 800x800@60')
        if action == 'apply':
            command.add_argument('--profile', choices=(edid.PROFILE,), required=True)
    restore = commands.add_parser('restore', help='Restore saved modes in the logged-in desktop')
    restore.add_argument('--wait', type=int, default=0)
    return parser


def saved_update(port, item):
    data = store.load()
    if item is None:
        data['ports'].pop(str(port), None)
    else:
        data['ports'][str(port)] = item
    store.atomic_json(store.CONFIG, data)


def override_bytes(port):
    path = edid.override_path(port)
    return path.read_bytes() if path.exists() else b''


def owned_override(port, data):
    if not data:
        return True
    state = store.load(store.STATE / 'runtime.json')
    record = state['ports'].get(str(port), {})
    recorded = record.get('override_hash') == hashlib.sha256(data).hexdigest()
    # Support the exact compatibility profile from this project's earlier session.
    legacy = edid.compatible(data) and data[54:72] in (edid.FIXED, edid.EARLY)
    return recorded or legacy


def record_override(port, data):
    state = store.load(store.STATE / 'runtime.json')
    if data:
        state['ports'][str(port)] = {'override_hash': hashlib.sha256(data).hexdigest()}
    else:
        state['ports'].pop(str(port), None)
    store.atomic_json(store.STATE / 'runtime.json', state)


def change_override(port, replacement, *, desktop=True):
    """Re-probe with a managed override, rolling back on failure."""
    previous = override_bytes(port)
    if not owned_override(port, previous):
        raise UserError('Unrecognized EDID override on this port; refusing to remove another tool\'s configuration.')
    if previous == replacement and replacement:
        return
    path = edid.connector(port)
    archive = store.STATE / 'backups' / (datetime.now().strftime('%Y%m%d-%H%M%S-%f') + f'-port{port}')
    archive.mkdir(parents=True)
    (archive / 'previous-override.edid').write_bytes(previous)
    (archive / 'visible.edid').write_bytes(edid.visible_edid(port))
    was_active = desktop and run(['systemctl', 'is-active', 'display-manager.service'], check=False).returncode == 0
    if was_active:
        run(['systemctl', 'stop', 'display-manager.service'])
    try:
        edid.override_path(port).write_bytes(replacement or b'reset')
        (path / 'status').write_text('detect\n')
    except Exception:
        edid.override_path(port).write_bytes(previous or b'reset')
        (path / 'status').write_text('detect\n')
        raise
    finally:
        if was_active:
            run(['systemctl', 'start', 'display-manager.service'])
    if desktop:
        for _ in range(30):
            try:
                current = outputs.outputs().get(connector_name(port), {})
                if current.get('modes'):
                    record_override(port, replacement)
                    return
            except UserError:
                pass
            time.sleep(0.4)
        if was_active:
            run(['systemctl', 'stop', 'display-manager.service'])
        try:
            edid.override_path(port).write_bytes(previous or b'reset')
            (path / 'status').write_text('detect\n')
        finally:
            if was_active:
                run(['systemctl', 'start', 'display-manager.service'])
        raise UserError('Desktop did not expose valid modes; the previous override was restored.')
    else:
        record_override(port, replacement)


def list_outputs():
    current = outputs.outputs()
    saved = store.load()
    for port in (0, 1):
        output = current.get(connector_name(port), {})
        try:
            connected = (edid.connector(port) / 'status').read_text().strip()
            override = str(len(override_bytes(port))) + ' bytes'
        except (OSError, UserError):
            connected, override = 'unknown', 'unavailable without sudo'
        active = next((m for m in output.get('modes', []) if m['current']), None)
        print(f"Screen {port+1} (--port {port+1} / --screen {port+1}) | {connector_name(port)} | board HDMI{port} | {connected}")
        print('  Name:', output.get('description', '(not exposed by compositor)'))
        print('  Enabled:', output.get('enabled', False), '| Mode:', outputs.format_mode(active) if active else 'none')
        print('  EDID override:', override)
        item = saved['ports'].get(str(port))
        print('  Saved:', json.dumps(item, ensure_ascii=False) if item else 'none')
    print('EDID names/physical sizes may be inaccurate; actual inch size is not inferred.')


def restore_saved(wait=0):
    deadline = time.monotonic() + max(0, wait)
    config = store.load()
    pending = dict(config['ports'])
    while pending:
        for key, item in list(pending.items()):
            try:
                port = int(key)
                screen = edid.visible_edid(port)
                if not screen:
                    continue
                if not store.matches(item, edid.identity(screen)):
                    print(f'HDMI{port}: different screen; saved mode skipped.')
                    pending.pop(key)
                    continue
                result = outputs.set_mode(port, item.get('mode'))
                print(f'HDMI{port}: restored {outputs.format_mode(result)}')
                pending.pop(key)
            except (OSError, UserError) as error:
                if time.monotonic() >= deadline:
                    print(f'HDMI{key}: restore skipped: {error}', file=sys.stderr)
                    pending.pop(key)
        if not pending or time.monotonic() >= deadline:
            break
        time.sleep(1)


def main(argv=None):
    arguments = sys.argv[1:] if argv is None else argv
    args = build_parser().parse_args(arguments)
    try:
        if args.action in ('set', 'auto', 'apply'):
            root_required(arguments, Path(__file__).resolve().parents[2] / 'bin/screen-config')
        if hasattr(args, 'port'):
            # Public numbering follows HDMI-A-1/2 and screen-test. Keep the
            # existing zero-based hardware/config keys unchanged internally.
            args.port -= 1
        if args.action == 'list':
            list_outputs()
        elif args.action == 'profiles':
            print('lontium-720: verified WKS/Lontium 720x720 board, ~60.004Hz; matching EDID required.')
        elif args.action == 'modes':
            output = outputs.outputs().get(connector_name(args.port), {})
            for mode in output.get('modes', []):
                print(outputs.format_mode(mode), 'preferred' if mode['preferred'] else '', 'current' if mode['current'] else '')
            if not output.get('modes'):
                print('No accepted modes. Check HDMI connection or the verified profile.')
        elif args.action == 'restore':
            restore_saved(args.wait)
        else:
            with store.locked():
                actual = edid.raw_edid(args.port)
                screen_id = edid.identity(actual)
                profile = None
                if args.action == 'set':
                    if edid.identity(edid.visible_edid(args.port)) != screen_id:
                        raise UserError('Stale EDID override: run screen-config auto --port N before setting a mode.')
                    result = outputs.set_mode(args.port, args.mode)
                    # Retain a managed compatibility override when saving a mode on it.
                    active_override = override_bytes(args.port)
                    if active_override and edid.compatible(active_override):
                        profile = edid.PROFILE
                elif args.action == 'auto':
                    change_override(args.port, b'')
                    result = outputs.set_mode(args.port)
                else:
                    fixed = edid.corrected(actual)
                    change_override(args.port, fixed)
                    result = outputs.set_mode(args.port, '720x720@60')
                    profile = args.profile
                if args.save:
                    saved_update(args.port, None if args.action == 'auto' else {
                        'identity': screen_id, 'mode': outputs.format_mode(result), 'profile': profile})
                print(f'Screen {args.port+1} | {connector_name(args.port)} | board HDMI{args.port}: '
                      f'{outputs.format_mode(result)}; ' + ('saved' if args.save else 'temporary'))
        return 0
    except (UserError, OSError, ValueError, subprocess.TimeoutExpired) as error:
        print(f'screen-config: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
