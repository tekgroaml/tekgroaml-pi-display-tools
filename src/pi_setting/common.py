"""Desktop session discovery and checked subprocess execution."""
import os
from pathlib import Path
import pwd
import subprocess


class UserError(Exception):
    pass


def run(args, *, env=None, timeout=20, check=True):
    proc = subprocess.run(args, env=env, text=True, capture_output=True, timeout=timeout)
    if check and proc.returncode:
        raise UserError(proc.stderr.strip() or proc.stdout.strip() or f"Command failed: {args[0]}")
    return proc


def desktop_user():
    if os.getuid() != 0:
        return pwd.getpwuid(os.getuid())
    uid = os.environ.get("SUDO_UID")
    if uid and int(uid) > 0:
        return pwd.getpwuid(int(uid))
    candidates = []
    for socket in Path('/run/user').glob('*/wayland-*'):
        if socket.is_socket():
            candidates.append(int(socket.parent.name))
    candidates = sorted(set(candidates))
    if len(candidates) != 1:
        raise UserError("Cannot uniquely identify a logged-in Wayland user. Run from that user's SSH session.")
    return pwd.getpwuid(candidates[0])


def desktop_env():
    user = desktop_user()
    runtime = Path('/run/user') / str(user.pw_uid)
    sockets = sorted(p for p in runtime.glob('wayland-*') if p.is_socket())
    if not sockets:
        raise UserError("No Wayland desktop is running for this user (logged out or at the login screen). "
                        "SSH is still connected. Log in to the desktop first. "
                        "If desktop autologin is enabled, run sudo systemctl restart lightdm "
                        "to restart the desktop; this closes existing graphical applications.")
    wanted = os.environ.get('WAYLAND_DISPLAY')
    socket = next((p for p in sockets if p.name == wanted), None)
    if socket is None:
        if len(sockets) != 1:
            raise UserError("Multiple Wayland sessions found. Set WAYLAND_DISPLAY to the intended session's socket name.")
        socket = sockets[0]
    env = dict(os.environ, HOME=user.pw_dir, USER=user.pw_name, LOGNAME=user.pw_name,
               XDG_RUNTIME_DIR=str(runtime), WAYLAND_DISPLAY=socket.name,
               DBUS_SESSION_BUS_ADDRESS=f'unix:path={runtime}/bus', GDK_BACKEND='wayland')
    return user, env


def desktop_run(args, **kwargs):
    user, env = desktop_env()
    if os.getuid() == 0:
        prefix = ['runuser', '-u', user.pw_name, '--', 'env']
        prefix += [f'{key}={env[key]}' for key in ('HOME', 'XDG_RUNTIME_DIR', 'WAYLAND_DISPLAY',
                                                  'DBUS_SESSION_BUS_ADDRESS', 'GDK_BACKEND')]
        return run(prefix + list(args), **kwargs)
    return run(list(args), env=env, **kwargs)


def connector_name(port):
    return f'HDMI-A-{int(port) + 1}'


def root_required(argv, executable):
    if os.getuid() != 0:
        os.execvp('sudo', ['sudo', str(executable)] + list(argv))
