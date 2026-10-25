"""Version-aware installation with staged payloads, backups and failure rollback."""
import argparse
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

from .common import UserError, desktop_env, desktop_run, run
from .store import atomic_json
from .versioning import (APP_ROOT, PAYLOAD_DIRS, PAYLOAD_FILES, Release,
                         configuration_check, installed_version, payload_digest, plan_upgrade)


@dataclass
class Paths:
    root: Path = Path('/')

    @property
    def app(self): return self.root/'opt/pi-setting'
    @property
    def state(self): return self.root/'var/lib/pi-setting'
    @property
    def config(self): return self.root/'etc/pi-setting'
    @property
    def commands(self): return self.root/'usr/local/bin'
    @property
    def units(self): return self.root/'etc/systemd/system'
    @property
    def autostart(self): return self.root/'etc/xdg/autostart/pi-setting-restore.desktop'
    @property
    def receipt(self): return self.state/'installation.json'


def inspect(source, paths=None, *, reinstall=False, allow_major=False):
    paths = paths or Paths()
    source = Path(source).resolve()
    release = Release.load(source)
    digest = payload_digest(source)
    if any(path.is_symlink() for path in (paths.app, paths.config, paths.receipt)):
        raise ValueError('Refusing symlinked installation/configuration metadata')
    current = installed_version(paths.app)
    plan = plan_upgrade(current, release, reinstall=reinstall, allow_major=allow_major)
    configs = configuration_check(paths.config, paths.state, release)
    if paths.receipt.exists():
        receipt = json.loads(paths.receipt.read_text())
        if not isinstance(receipt, dict) or type(receipt.get('format')) is not int or receipt['format'] != 1:
            raise ValueError('Unsupported installation receipt format')
        if receipt.get('version') != current:
            raise ValueError('Installation receipt disagrees with installed application version')
        if current == release.version and receipt.get('payload_sha256') != digest:
            raise ValueError('The same release version has different content; publish a new version instead')
        if payload_digest(paths.app) != receipt.get('payload_sha256') and not (reinstall and current == release.version):
            raise ValueError('Installed application was modified; preserve changes before upgrading '
                             '(--reinstall can repair the identical recorded release)')
    if plan['action'] == 'noop':
        names = ('screen-config', 'screen-test', 'pi-setting')
        if any(not (paths.commands/name).is_symlink() or
               os.readlink(paths.commands/name) != str(paths.app/'bin'/name) for name in names):
            plan = {'action': 'repair-needed', 'allowed': False,
                    'reason': 'Same version is present but command links are missing; use --reinstall'}
    return dict(plan, installed_version=current, target_version=release.version,
                command_version=release.command_version, config_versions=configs,
                source_sha256=digest, source=str(source))


@contextmanager
def installation_lock(paths):
    paths.state.mkdir(parents=True, exist_ok=True)
    with (paths.state/'install.lock').open('a') as stream, (paths.state/'config.lock').open('a') as config:
        fcntl.flock(stream, fcntl.LOCK_EX)
        fcntl.flock(config, fcntl.LOCK_EX)
        yield


class Transaction:
    """Filesystem transaction; kept separate so rollback can be tested off-device."""
    def __init__(self, paths, source, digest):
        self.paths, self.source, self.digest = paths, Path(source), digest
        self.backup = None
        self.stage = None
        self.switched = False
        self.had_app = False
        self.snapshots = []

    def prepare(self):
        self.paths.app.parent.mkdir(parents=True, exist_ok=True)
        self.stage = Path(tempfile.mkdtemp(prefix='.pi-setting-stage-', dir=self.paths.app.parent))
        self.stage.chmod(0o755)
        try:
            for folder in PAYLOAD_DIRS:
                shutil.copytree(self.source/folder, self.stage/folder,
                                ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.pyo'))
            for name in PAYLOAD_FILES:
                shutil.copyfile(self.source/name, self.stage/name)
            for path in self.stage.rglob('*'):
                path.chmod(0o755 if path.is_dir() else 0o644)
            for name in ('screen-config', 'screen-test', 'pi-setting'):
                (self.stage/'bin'/name).chmod(0o755)
            if payload_digest(self.stage) != self.digest:
                raise ValueError('Source changed while staging; installation cancelled')
            stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S-%fZ')
            self.backup = self.paths.state/'install-backups'/stamp
            self.backup.mkdir(parents=True)
            targets = [self.paths.config, self.paths.receipt,
                       self.paths.state/'legacy.json', self.paths.state/'legacy-helper.py',
                       self.paths.state/'legacy-service.txt', self.paths.autostart,
                       self.paths.units/'pi-setting-boot.service', self.paths.units/'pi-setting-touch.service']
            targets += [self.paths.units/'graphical.target.wants'/name
                        for name in ('pi-setting-boot.service', 'pi-setting-touch.service')]
            targets += [self.paths.commands/name for name in ('screen-config', 'screen-test', 'pi-setting')]
            for index, target in enumerate(targets):
                exists = target.exists() or target.is_symlink()
                snapshot = self.backup/f'file-{index}'
                if exists:
                    if target.is_symlink(): snapshot.symlink_to(os.readlink(target))
                    elif target.is_dir(): shutil.copytree(target, snapshot, symlinks=True)
                    else: shutil.copy2(target, snapshot)
                self.snapshots.append((target, snapshot, exists))
            atomic_json(self.backup/'files.json', [{'path': str(t), 'snapshot': s.name, 'existed': e}
                                                   for t, s, e in self.snapshots])
        except Exception:
            self.cleanup()
            raise

    def switch(self):
        self.had_app = self.paths.app.exists()
        if self.had_app:
            self.paths.app.rename(self.backup/'previous-app')
        try:
            self.stage.rename(self.paths.app)
            self.stage = None
            self.switched = True
        except Exception:
            if self.had_app:
                (self.backup/'previous-app').rename(self.paths.app)
            raise

    def rollback(self):
        if self.switched:
            shutil.rmtree(self.paths.app)
            if self.had_app:
                (self.backup/'previous-app').rename(self.paths.app)
            self.switched = False
        for target, snapshot, existed in reversed(self.snapshots):
            if target.is_symlink() or target.is_file(): target.unlink()
            elif target.is_dir(): shutil.rmtree(target)
            if existed:
                target.parent.mkdir(parents=True, exist_ok=True)
                if snapshot.is_symlink(): target.symlink_to(os.readlink(snapshot))
                elif snapshot.is_dir(): shutil.copytree(snapshot, target, symlinks=True)
                else: shutil.copy2(snapshot, target)
        self.cleanup()

    def cleanup(self):
        if self.stage is not None and self.stage.exists():
            shutil.rmtree(self.stage)
        self.stage = None


def check_platform():
    model = Path('/proc/device-tree/model').read_bytes().rstrip(b'\0').decode()
    info = dict(line.split('=', 1) for line in Path('/etc/os-release').read_text().splitlines()
                if '=' in line and not line.startswith('#'))
    if not model.startswith('Raspberry Pi 4 Model B') or info.get('VERSION_CODENAME', '').strip('"') != 'bookworm':
        raise UserError('Validated platform: Raspberry Pi 4 Model B, Raspberry Pi OS Bookworm Desktop')
    if run(['getconf', 'LONG_BIT']).stdout.strip() != '64':
        raise UserError('A 64-bit OS is required')


def service_state(name):
    return {'active': run(['systemctl', 'is-active', '--quiet', name], check=False).returncode == 0,
            'enabled': run(['systemctl', 'is-enabled', '--quiet', name], check=False).returncode == 0}


def restore_services(states):
    run(['systemctl', 'daemon-reload'])
    for name, state in states.items():
        if not Path('/etc/systemd/system', name).exists() and name != 'pi-hdmi-720-compat.service':
            continue
        run(['systemctl', 'enable' if state['enabled'] else 'disable', name], check=False)
        if name == 'pi-setting-touch.service':
            run(['systemctl', 'start' if state['active'] else 'stop', name])


def capture_test():
    try:
        from .test_cli import request
        user, env = desktop_env()
        socket = Path(env['XDG_RUNTIME_DIR'])/'pi-setting-test/control.sock'
        result = request(socket, {'action': 'status'})
        return socket, result.get('screens', {})
    except (OSError, ValueError, UserError):
        return None, {}


def stop_test(socket):
    if socket is None:
        return
    from .test_cli import request
    request(socket, {'action': 'stop'})
    for _ in range(50):
        if not socket.exists(): return
        time.sleep(.1)
    raise UserError('Screen test did not exit; update stopped before replacing files')


def restore_test(snapshot):
    failures = []
    for screen, entry in snapshot.items():
        action = entry.get('action')
        if action not in ('black', 'white', 'red', 'pattern', 'touch', 'tap-cycle', 'cycle'):
            continue
        args = ['/usr/local/bin/screen-test', action, '--screen', str(screen)]
        if action == 'cycle': args += ['--interval', str(entry.get('interval') or 5)]
        try:
            desktop_run(args)
        except (OSError, UserError) as error:
            failures.append(str(error))
    return failures


def install(source, *, no_deps=False, reinstall=False, allow_major=False):
    if os.getuid() != 0:
        raise UserError('Installation requires sudo')
    paths = Paths()
    with installation_lock(paths):
        plan = inspect(source, paths, reinstall=reinstall, allow_major=allow_major)
        print(json.dumps(plan, indent=2), flush=True)
        if not plan['allowed']: raise UserError(plan['reason'])
        if plan['action'] == 'noop':
            return plan
        check_platform()
        for name in ('screen-config', 'screen-test', 'pi-setting'):
            command = paths.commands/name
            if command.exists() or command.is_symlink():
                if not command.is_symlink() or os.readlink(command) != str(paths.app/'bin'/name):
                    raise UserError(f'Refusing to replace another application command: {command}')
        if not no_deps:
            run(['apt-get', 'update'], timeout=600)
            run(['apt-get', 'install', '-y', 'python3', 'python3-gi', 'python3-cairo', 'python3-gi-cairo',
                 'gir1.2-gtk-3.0', 'gir1.2-gtklayershell-0.1', 'wlr-randr'], timeout=600)
        run(['/usr/bin/python3', '-c', 'import gi; gi.require_version("Gtk", "3.0"); '
             'gi.require_version("GtkLayerShell", "0.1"); from gi.repository import Gtk, GtkLayerShell; import cairo'])
        run(['wlr-randr', '--help'])
        transaction = Transaction(paths, source, plan['source_sha256'])
        transaction.prepare()
        states = {name: service_state(name) for name in ('pi-setting-boot.service', 'pi-setting-touch.service',
                                                        'pi-hdmi-720-compat.service')}
        had_boot = (paths.units/'pi-setting-boot.service').exists()
        had_touch = (paths.units/'pi-setting-touch.service').exists()
        socket, test = capture_test()
        atomic_json(transaction.backup/'services.json', states)
        atomic_json(transaction.backup/'test.json', test)
        try:
            stop_test(socket)
            if states['pi-setting-touch.service']['active']:
                run(['systemctl', 'stop', 'pi-setting-touch.service'])
            transaction.switch()
            paths.commands.mkdir(parents=True, exist_ok=True)
            for name in ('screen-config', 'screen-test', 'pi-setting'):
                command = paths.commands/name
                command.unlink(missing_ok=True)
                command.symlink_to(paths.app/'bin'/name)
            paths.units.mkdir(parents=True, exist_ok=True)
            shutil.copy2(paths.app/'systemd/pi-setting-boot.service', paths.units/'pi-setting-boot.service')
            if had_touch:
                shutil.copy2(paths.app/'systemd/pi-setting-touch.service', paths.units/'pi-setting-touch.service')
            paths.autostart.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(paths.app/'desktop/pi-setting-restore.desktop', paths.autostart)
            # Run the target release's migration, never the superseded version.
            run(['/usr/bin/env', 'PYTHONDONTWRITEBYTECODE=1', f'PYTHONPATH={paths.app}/src',
                 '/usr/bin/python3', '-m', 'pi_setting.migrate'])
            run(['systemctl', 'daemon-reload'])
            run(['systemd-analyze', 'verify', str(paths.units/'pi-setting-boot.service')])
            if not had_boot or states['pi-setting-boot.service']['enabled']:
                run(['systemctl', 'enable', 'pi-setting-boot.service'])
            if states['pi-setting-touch.service']['active']:
                run(['systemctl', 'start', 'pi-setting-touch.service'])
            release = Release.load(paths.app)
            configuration_check(paths.config, paths.state, release)
            if payload_digest(paths.app) != plan['source_sha256']:
                raise ValueError('Installed payload does not match the staged release')
            receipt = {'format': 1, 'version': release.version, 'command_version': release.command_version,
                       'config_versions': release.config_versions, 'previous_version': plan['installed_version'],
                       'installed_at': datetime.now(timezone.utc).isoformat(), 'payload_sha256': plan['source_sha256'],
                       'backup_dir': str(transaction.backup)}
            atomic_json(paths.receipt, receipt)
        except Exception as error:
            run(['systemctl', 'stop', 'pi-setting-touch.service'], check=False)
            transaction.rollback()
            restore_services(states)
            restore_test(test)
            atomic_json(transaction.backup/'result.json', {'result': 'rolled-back', 'error': str(error)})
            raise UserError(f'Installation failed; previous application/configuration restored. '
                            f'Backup: {transaction.backup}. Cause: {error}') from error
        finally:
            transaction.cleanup()
        failures = restore_test(test)
        atomic_json(transaction.backup/'result.json', {'result': 'success', 'version': plan['target_version'],
                                                      'test_restore_warnings': failures})
        print(f'Installed {plan["target_version"]}; backup: {transaction.backup}', flush=True)
        for warning in failures:
            print('Application updated; test display could not be restored: '+warning, flush=True)
        return dict(plan, backup_dir=str(transaction.backup))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=APP_ROOT)
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--no-deps', action='store_true')
    parser.add_argument('--reinstall', action='store_true')
    parser.add_argument('--allow-major', action='store_true')
    args = parser.parse_args(argv)
    try:
        if args.check:
            plan = inspect(args.source, reinstall=args.reinstall, allow_major=args.allow_major)
            print(json.dumps(plan, indent=2))
            return 0 if plan['allowed'] else 2
        install(args.source, no_deps=args.no_deps, reinstall=args.reinstall, allow_major=args.allow_major)
        return 0
    except (OSError, ValueError, UserError, subprocess.TimeoutExpired) as error:
        print('pi-setting install: '+str(error))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
