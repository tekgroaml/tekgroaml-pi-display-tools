"""Atomic root-owned configuration and runtime override ownership records."""
import fcntl
import json
import os
from pathlib import Path
import tempfile
from contextlib import contextmanager
from .versioning import RELEASE

CONFIG = Path('/etc/pi-setting/config.json')
STATE = Path('/var/lib/pi-setting')


def load(path=CONFIG):
    if not path.exists():
        kind = 'runtime' if Path(path).name == 'runtime.json' else 'display'
        return {'version': RELEASE.config_versions[kind], 'ports': {}}
    data = json.loads(path.read_text())
    kind = 'runtime' if Path(path).name == 'runtime.json' else 'display'
    if type(data.get('version')) is not int or data.get('version') != RELEASE.config_versions[kind] or not isinstance(data.get('ports'), dict):
        raise ValueError(f'Invalid configuration format: {path}')
    return data


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp, 0o644)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


@contextmanager
def locked():
    STATE.mkdir(parents=True, exist_ok=True)
    with (STATE / 'config.lock').open('a') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        yield


def matches(saved, screen_identity):
    return saved.get('identity') == screen_identity
