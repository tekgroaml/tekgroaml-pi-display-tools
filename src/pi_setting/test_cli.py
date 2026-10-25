"""SSH-friendly client for a private, per-user GTK test process."""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

from .common import UserError, desktop_env
from . import __version__


def build_parser():
    parser = argparse.ArgumentParser(prog='screen-test', description='Full-screen HDMI color tests')
    parser.add_argument('--version', action='version', version=f'%(prog)s {__version__}')
    commands = parser.add_subparsers(dest='action', required=True)
    for action in ('black', 'white', 'red', 'pattern', 'touch', 'tap-cycle', 'cycle', 'stop'):
        command = commands.add_parser(action)
        command.add_argument('--screen', type=int, choices=(1, 2),
                             help='1=HDMI-A-1 (board HDMI0); 2=HDMI-A-2 (board HDMI1); omitted=all')
        if action == 'touch':
            command.add_argument('--shape', choices=('round', 'rect'), default='round',
                                 help='round=center/cardinal targets; rect=center/corner targets')
        if action == 'cycle':
            command.add_argument('--interval', type=float, default=5)
    commands.add_parser('status')
    return parser


def request(path, message, timeout=5):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(timeout)
        connection.connect(str(path))
        connection.sendall(json.dumps(message).encode() + b'\n')
        chunks = b''
        while b'\n' not in chunks:
            block = connection.recv(4096)
            if not block:
                raise UserError('Test process closed its control connection.')
            chunks += block
            if len(chunks) > 65536:
                raise UserError('Test process returned an oversized response.')
        return json.loads(chunks.split(b'\n', 1)[0])


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        if os.getuid() == 0:
            raise UserError('Run screen-test as the desktop user, without sudo.')
        if args.action == 'cycle' and (not 0.2 <= args.interval <= 86400):
            raise UserError('Cycle interval must be between 0.2 and 86400 seconds.')
        user, env = desktop_env()
        runtime = Path(env['XDG_RUNTIME_DIR']) / 'pi-setting-test'
        runtime.mkdir(mode=0o700, exist_ok=True)
        if runtime.stat().st_uid != os.getuid() or runtime.is_symlink():
            raise UserError('Unsafe runtime directory ownership.')
        runtime.chmod(0o700)
        path = runtime / 'control.sock'
        running = False
        try:
            running = request(path, {'action': 'status'})['ok']
        except (OSError, UserError, ValueError):
            pass
        if not running:
            if args.action in ('status', 'stop'):
                print('No screen test is running.')
                return 0
            with (runtime / 'worker.log').open('a') as log:
                env['PYTHONPATH'] = str(Path(__file__).resolve().parents[1])
                process = subprocess.Popen(['/usr/bin/python3', '-m', 'pi_setting.color_worker', str(runtime)],
                                           env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                           start_new_session=True, close_fds=True)
            for _ in range(60):
                if process.poll() is not None:
                    raise UserError(f'Test process failed to start. See {runtime / "worker.log"}')
                try:
                    if request(path, {'action': 'status'}, timeout=0.3)['ok']:
                        break
                except (OSError, UserError, ValueError):
                    time.sleep(0.1)
            else:
                process.terminate()
                raise UserError(f'Test process startup timed out. See {runtime / "worker.log"}')
        message = {'action': args.action}
        if hasattr(args, 'screen'):
            message['screen'] = args.screen
        if args.action == 'touch':
            message['shape'] = args.shape
        if args.action == 'cycle':
            message['interval'] = args.interval
        response = request(path, message)
        if not response.get('ok'):
            raise UserError(response.get('error', 'Unknown display error'))
        if args.action == 'status':
            print(json.dumps(response['screens'], indent=2, ensure_ascii=False))
        else:
            print(response.get('message', 'OK'))
        return 0
    except (UserError, OSError, ValueError) as error:
        print(f'screen-test: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
