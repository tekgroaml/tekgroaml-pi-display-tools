"""Application version and local-release upgrade commands; no GUI required."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from . import __version__
from .common import UserError
from .installer import Paths, inspect
from .versioning import RELEASE, configuration_check, installed_version, payload_digest


def build_parser():
    parser = argparse.ArgumentParser(prog='pi-setting', description=__doc__)
    parser.add_argument('--version', action='version', version=f'%(prog)s {__version__}')
    commands = parser.add_subparsers(dest='action', required=True)
    version = commands.add_parser('version', help='Show running/installed versions and configuration formats')
    version.add_argument('--json', action='store_true')
    for action in ('check-update', 'upgrade'):
        command = commands.add_parser(action, help='Compare/install an already downloaded release directory')
        command.add_argument('--source', type=Path, required=True)
        command.add_argument('--reinstall', action='store_true', help='Explicitly repair the same release')
        command.add_argument('--allow-major', action='store_true', help='Accept a reviewed breaking major upgrade')
        if action == 'upgrade':
            command.add_argument('--no-deps', action='store_true')
    return parser


def version_info(paths=None):
    paths = paths or Paths()
    current = installed_version(paths.app)
    info = {'running_version': __version__, 'installed_version': current,
            'command_version': RELEASE.command_version,
            'supported_config_versions': RELEASE.config_versions,
            'observed_config_versions': configuration_check(paths.config, paths.state, RELEASE)}
    if paths.receipt.exists():
        receipt = json.loads(paths.receipt.read_text())
        if not isinstance(receipt, dict) or type(receipt.get('format')) is not int or receipt['format'] != 1:
            raise ValueError('Unsupported installation receipt format')
        info['installed_at'] = receipt.get('installed_at')
        info['previous_version'] = receipt.get('previous_version')
        info['backup_dir'] = receipt.get('backup_dir')
        info['integrity'] = ('ok' if receipt.get('version') == current and
                             receipt.get('payload_sha256') == payload_digest(paths.app) else 'modified')
    else:
        info['integrity'] = 'legacy-unrecorded' if current else 'not-installed'
    return info


def main(argv=None):
    arguments = sys.argv[1:] if argv is None else argv
    args = build_parser().parse_args(arguments)
    try:
        if args.action == 'version':
            info = version_info()
            if args.json:
                print(json.dumps(info, indent=2))
            else:
                print('Application:', info['installed_version'] or 'not installed')
                print('Running code:', info['running_version'])
                print('Command interface:', info['command_version'])
                print('Configuration formats:', json.dumps(info['observed_config_versions']))
                print('Integrity:', info['integrity'])
                if 'installed_at' in info: print('Installed at:', info['installed_at'])
            return 0
        source = args.source.expanduser().resolve()
        if args.action == 'check-update':
            plan = inspect(source, reinstall=args.reinstall, allow_major=args.allow_major)
            print(json.dumps(plan, indent=2))
            return 0 if plan['allowed'] else 2
        plan = inspect(source, reinstall=args.reinstall, allow_major=args.allow_major)
        if not plan['allowed']:
            print(json.dumps(plan, indent=2))
            return 2
        if plan['action'] == 'noop':
            print(json.dumps(plan, indent=2))
            return 0
        # Always use the downloaded target release's installer. Its installer
        # repeats the version and configuration checks under the install lock.
        target = source/'scripts/install.sh'
        if not target.is_file():
            raise UserError('Source is not a complete pi-setting release directory')
        command = ['bash', str(target)]
        for flag in ('reinstall', 'allow_major', 'no_deps'):
            if getattr(args, flag): command.append('--'+flag.replace('_', '-'))
        if os.getuid() != 0: command.insert(0, 'sudo')
        return subprocess.run(command, check=False).returncode
    except (OSError, ValueError, UserError, subprocess.TimeoutExpired) as error:
        print('pi-setting: '+str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
