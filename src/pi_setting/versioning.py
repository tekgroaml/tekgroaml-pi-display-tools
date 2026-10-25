"""Stable release comparison and configuration compatibility without executing old code."""
import ast
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re

VERSION_PATTERN = re.compile(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\Z')
APP_ROOT = Path(__file__).resolve().parents[2]
PAYLOAD_DIRS = ('bin', 'src', 'scripts', 'systemd', 'desktop', 'docs')
PAYLOAD_FILES = ('VERSION.json', 'README.md', 'CHANGELOG.md', 'PUBLISHING.md')


def version_tuple(value):
    if not isinstance(value, str) or not VERSION_PATTERN.fullmatch(value):
        raise ValueError(f'Expected a stable MAJOR.MINOR.PATCH version, got {value!r}')
    return tuple(int(part) for part in value.split('.'))


@dataclass(frozen=True)
class Release:
    version: str
    command_version: int
    config_versions: dict
    minimum_upgrade_version: str

    @classmethod
    def load(cls, root):
        data = json.loads((Path(root)/'VERSION.json').read_text())
        if not isinstance(data, dict) or type(data.get('format')) is not int or data['format'] != 1:
            raise ValueError('Unsupported release metadata format')
        version_tuple(data.get('version'))
        version_tuple(data.get('minimum_upgrade_version'))
        if version_tuple(data['minimum_upgrade_version']) > version_tuple(data['version']):
            raise ValueError('Minimum upgrade version exceeds the release version')
        if type(data.get('command_version')) is not int or data['command_version'] < 1:
            raise ValueError('Invalid command interface version')
        configs = data.get('config_versions')
        if not isinstance(configs, dict) or set(configs) != {'display', 'touch', 'runtime'}:
            raise ValueError('Release must describe display/touch/runtime configuration versions')
        if any(type(value) is not int or value < 1 for value in configs.values()):
            raise ValueError('Invalid configuration version')
        return cls(data['version'], data['command_version'], configs, data['minimum_upgrade_version'])


def installed_version(root):
    root = Path(root)
    if not root.exists():
        return None
    if (root/'VERSION.json').exists():
        return Release.load(root).version
    # Existing 1.0/2.0 installations only had a literal __version__. Never
    # import installed code as root to find its version.
    init = root/'src/pi_setting/__init__.py'
    if not init.is_file():
        raise ValueError('Existing installation has no recognized version; refusing to overwrite it')
    try:
        tree = ast.parse(init.read_text())
    except SyntaxError as error:
        raise ValueError('Installed version file contains invalid Python syntax') from error
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
            if any(isinstance(target, ast.Name) and target.id == '__version__' for target in node.targets):
                value = node.value.value
                version_tuple(value)
                return value
    raise ValueError('Cannot safely identify the installed application version')


def payload_paths(root):
    root = Path(root)
    for folder in PAYLOAD_DIRS:
        directory = root/folder
        if not directory.is_dir() or directory.is_symlink():
            raise ValueError(f'Missing or symlinked application directory: {folder}')
        for path in sorted(directory.rglob('*')):
            if '__pycache__' in path.parts or path.suffix in ('.pyc', '.pyo'):
                continue
            if path.is_symlink():
                raise ValueError(f'Symlinks are not supported in release payload: {path.relative_to(root)}')
            if path.is_file():
                yield path
    for name in PAYLOAD_FILES:
        path = root/name
        if not path.is_file() or path.is_symlink():
            raise ValueError(f'Missing or symlinked release file: {name}')
        yield path


def payload_digest(root):
    root = Path(root)
    digest = hashlib.sha256()
    for path in payload_paths(root):
        digest.update(str(path.relative_to(root)).encode())
        digest.update(b'\0')
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def configuration_check(config_dir, state_dir, release):
    files = {'display': Path(config_dir)/'config.json',
             'touch': Path(config_dir)/'touch-map.json',
             'runtime': Path(state_dir)/'runtime.json'}
    observed = {}
    for name, path in files.items():
        if not path.exists():
            observed[name] = None
            continue
        if path.is_symlink():
            raise ValueError(f'Refusing symlinked configuration: {path}')
        data = json.loads(path.read_text())
        if not isinstance(data, dict):
            raise ValueError(f'Invalid {name} configuration object')
        version = data.get('version')
        if type(version) is not int or version != release.config_versions[name]:
            raise ValueError(f'{name} configuration version {version!r} is incompatible with '
                             f'target format {release.config_versions[name]}; no migration is available')
        if not isinstance(data.get('ports'), dict):
            raise ValueError(f'Invalid {name} ports configuration')
        observed[name] = version
    return observed


def plan_upgrade(current, release, *, reinstall=False, allow_major=False):
    target = version_tuple(release.version)
    if current is None:
        return {'action': 'install', 'allowed': True, 'reason': 'No existing application installation'}
    previous = version_tuple(current)
    if target < previous:
        return {'action': 'downgrade', 'allowed': False, 'reason': 'Downgrades are not supported'}
    if target == previous:
        return {'action': 'reinstall' if reinstall else 'noop', 'allowed': True,
                'reason': 'Explicit repair reinstall' if reinstall else 'This application version is already installed'}
    if previous < version_tuple(release.minimum_upgrade_version):
        return {'action': 'unsupported', 'allowed': False, 'reason': 'Installed version is below the supported upgrade floor'}
    major = target[0] != previous[0]
    return {'action': 'major-upgrade' if major else 'upgrade', 'allowed': not major or allow_major,
            'reason': 'Major upgrades require --allow-major and review of CHANGELOG.md' if major and not allow_major
                      else 'Application upgrade supported; configuration formats are checked separately'}


RELEASE = Release.load(APP_ROOT)
APP_VERSION = RELEASE.version
