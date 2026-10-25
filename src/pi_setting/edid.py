"""EDID identification and the narrowly matched, tested Lontium profile."""
import ctypes
import fcntl
import hashlib
import os
from pathlib import Path

from .common import UserError, connector_name

ORIGINAL = bytes.fromhex('ac0dd05c20d047202e05250cd0d02200001e')
EARLY = bytes.fromhex('ac0dd05c20d047202e06250cd0d02200001e')
FIXED = bytes.fromhex('0e0fd05c20d047202e06250cd0d02200001e')
PROFILE = 'lontium-720'


def valid(data):
    return (len(data) >= 128 and len(data) % 128 == 0 and data[:8] == bytes.fromhex('00ffffffffffff00')
            and len(data) == 128 * (1 + data[126])
            and all(sum(data[i:i+128]) % 256 == 0 for i in range(0, len(data), 128)))


def compatible(data):
    if not valid(data) or len(data) != 128 or data[8:12] != bytes.fromhex('5d734600'):
        return False
    names = [data[i+5:i+18].strip(b' \n\x00') for i in (54, 72, 90, 108)
             if data[i:i+5] == b'\x00\x00\x00\xfc\x00']
    return b'Lontium Semi' in names and data[54:72] in (ORIGINAL, EARLY, FIXED)


def normalized(data):
    if compatible(data):
        b = bytearray(data)
        b[54:72] = ORIGINAL
        b[127] = (-sum(b[:127])) % 256
        return bytes(b)
    return data


def identity(data):
    if not valid(data):
        raise UserError('EDID is missing or invalid; refusing to bind a saved configuration.')
    return hashlib.sha256(normalized(data)).hexdigest()


def corrected(data):
    if not compatible(data):
        raise UserError('This screen does not match the verified lontium-720 controller/timing profile.')
    b = bytearray(data)
    b[54:72] = FIXED
    b[127] = (-sum(b[:127])) % 256
    return bytes(b)


def connector(port):
    matches = sorted(Path('/sys/class/drm').glob(f'card*-{connector_name(port)}'))
    if len(matches) != 1:
        raise UserError(f'Cannot uniquely locate {connector_name(port)}; is the KMS driver active?')
    return matches[0]


def override_path(port):
    path = connector(port)
    card, name = path.name.split('-', 1)
    return Path('/sys/kernel/debug/dri') / card[4:] / name / 'edid_override'


def visible_edid(port):
    return (connector(port) / 'edid').read_bytes()


def raw_edid(port):
    """Read DDC EEPROM using a read-offset transaction, never programming data."""
    path = connector(port)
    if (path / 'status').read_text().strip() != 'connected':
        raise UserError(f'{connector_name(port)} is disconnected.')
    ddc = path / 'ddc'
    if not ddc.exists():
        raise UserError('No DDC adapter: cannot verify the physically attached display.')
    device = Path('/dev') / ddc.resolve().name

    class Message(ctypes.Structure):
        _fields_ = [('addr', ctypes.c_uint16), ('flags', ctypes.c_uint16),
                    ('len', ctypes.c_uint16), ('buf', ctypes.POINTER(ctypes.c_uint8))]

    class Request(ctypes.Structure):
        _fields_ = [('msgs', ctypes.POINTER(Message)), ('nmsgs', ctypes.c_uint32)]

    fd = os.open(device, os.O_RDWR)
    try:
        offset = (ctypes.c_uint8 * 1)(0)
        data = (ctypes.c_uint8 * 128)()
        messages = (Message * 2)(Message(0x50, 0, 1, offset), Message(0x50, 1, 128, data))
        request = Request(messages, 2)
        fcntl.ioctl(fd, 0x0707, request)
        result = bytes(data)
        if result[126]:
            # Base block identity is not enough when extension blocks carry modes.
            # Reading up to 256 bytes avoids changing the E-DDC segment pointer.
            if result[126] != 1:
                raise UserError('More than one EDID extension: this DDC reader does not support that screen yet.')
            offset[0] = 128
            fcntl.ioctl(fd, 0x0707, request)
            result += bytes(data)
        if not valid(result):
            raise UserError('Monitor returned an invalid EDID checksum or length.')
        return result
    finally:
        os.close(fd)
