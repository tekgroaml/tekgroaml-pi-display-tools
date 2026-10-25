"""Narrow EDID timing profiles; EDID identity is not a physical panel model."""
import ctypes
import fcntl
import hashlib
import os
from pathlib import Path

from .common import UserError, connector_name

ORIGINAL = bytes.fromhex('ac0dd05c20d047202e05250cd0d02200001e')
EARLY = bytes.fromhex('ac0dd05c20d047202e06250cd0d02200001e')
FIXED = bytes.fromhex('0e0fd05c20d047202e06250cd0d02200001e')
PROFILE = '4.0inch-720x720-60hz-wks-lontium-semi'
STRIP_PROFILE = '6.2inch-420x960-60hz-ltm-zl480'
STRIP_ORIGINAL = bytes.fromhex('f00aa47810c028303214040400804700001e')
STRIP_FIXED = bytes.fromhex('a80ca47810c028303214040400804700001e')
STRIP_SECOND = bytes.fromhex('5007e07810e0281032140404232000202020')
PROFILES = {
    PROFILE: {'mode': '720x720@60', 'confirmation_required': False,
              'customer_name': '4.0-inch 720x720 square touchscreen',
              'customer_name_cn': '4.0英寸 720×720 方形触摸屏',
              'size_inches': '4.0', 'resolution': '720x720', 'touch': True,
              'driver_label': 'WKS / Lontium Semi', 'driver_slug': 'wks-lontium-semi',
              'reported': {'manufacturer_product_hex': '5d734600', 'edid_bytes': 128,
                           'mode': '720x720', 'pixel_clock_mhz': 35.0, 'refresh_hz': 54.492349,
                           'horizontal_front_sync_back': [46, 5, 41],
                           'vertical_front_sync_back': [50, 5, 16]},
              'repaired': {'mode': '720x720', 'pixel_clock_mhz': 38.54, 'refresh_hz': 60.003861,
                           'horizontal_front_sync_back': [46, 6, 40],
                           'vertical_front_sync_back': [50, 5, 16]},
              'problem': 'No accepted HDMI mode on Pi 4; picture flicker after only fixing odd horizontal sync.',
              'scope': 'Validated touch sample only; actual manufacturer part number is not inferred from EDID.',
              'description': 'WKS/Lontium 720x720 timing correction; ~60.004Hz; EDID match required.'},
    STRIP_PROFILE: {'mode': '420x960@60', 'confirmation_required': True,
                   'customer_name': '6.2-inch 420x960 strip touchscreen (verified input mode)',
                   'customer_name_cn': '6.2英寸 420×960 长条触摸屏（已验证输入模式）',
                   'size_inches': '6.2', 'resolution': '420x960', 'touch': True,
                   'driver_label': 'LTM / ZL480', 'driver_slug': 'ltm-zl480',
                   'reported': {'manufacturer_product_hex': '328d5e04', 'edid_bytes': 256,
                                'mode': '420x960', 'pixel_clock_mhz': 28.0, 'refresh_hz': 51.851852,
                                'horizontal_front_sync_back': [50, 20, 50],
                                'vertical_front_sync_back': [16, 4, 20]},
                   'repaired': {'mode': '420x960', 'pixel_clock_mhz': 32.4, 'refresh_hz': 60.0,
                                'horizontal_front_sync_back': [50, 20, 50],
                                'vertical_front_sync_back': [16, 4, 20]},
                   'problem': 'Touch sample flicker/incomplete image with original ~51.85Hz timing.',
                   'scope': 'Native panel resolution/part number unconfirmed. Non-touch sample with identical EDID remains unresolved.',
                   'description': 'Known 6.2-inch touch sample: 28 -> 32.4MHz, 420x960@60; '
                                  'same EDID also appeared on an unresolved non-touch sample. '
                                  'Requires --confirm-profile; no automatic model identification.'},
}
PROFILE_ALIASES = {'lontium-720': PROFILE, 'ltm-420x960-60': STRIP_PROFILE}


def canonical_profile(name):
    if name in PROFILES:
        return name
    if name in PROFILE_ALIASES:
        return PROFILE_ALIASES[name]
    raise UserError(f'Unknown compatibility profile: {name}')


def profile_names(name):
    canonical = canonical_profile(name)
    return (canonical, *(alias for alias, target in PROFILE_ALIASES.items() if target == canonical))


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


def profile_matches(data, profile):
    try:
        profile = canonical_profile(profile)
    except UserError:
        return False
    if profile == PROFILE:
        return compatible(data)
    if profile != STRIP_PROFILE or not valid(data) or len(data) != 256:
        return False
    names = [data[i+5:i+18].strip(b' \n\x00') for i in (54, 72, 90, 108)
             if data[i:i+5] == b'\x00\x00\x00\xfc\x00']
    return (data[8:12] == bytes.fromhex('328d5e04') and b'ZL480' in names
            and data[54:72] in (STRIP_ORIGINAL, STRIP_FIXED)
            and data[72:90] == STRIP_SECOND and data[128:131] == bytes.fromhex('02031f'))


def matching_profile(data):
    return next((profile for profile in PROFILES if profile_matches(data, profile)), None)


def validate_profile_use(profile, confirmed=False):
    profile = canonical_profile(profile)
    if PROFILES[profile]['confirmation_required'] and confirmed is not True:
        raise UserError(f'{profile} cannot identify touch/non-touch variants from EDID. '
                        'Read the product guide and explicitly add --confirm-profile; '
                        'the non-touch sample was NOT fixed by this timing.')
    return profile


def normalized(data):
    profile = matching_profile(data)
    if profile:
        b = bytearray(data)
        b[54:72] = ORIGINAL if profile == PROFILE else STRIP_ORIGINAL
        b[127] = (-sum(b[:127])) % 256
        return bytes(b)
    return data


def identity(data):
    if not valid(data):
        raise UserError('EDID is missing or invalid; refusing to bind a saved configuration.')
    return hashlib.sha256(normalized(data)).hexdigest()


def corrected(data, profile=PROFILE):
    profile = canonical_profile(profile)
    if not profile_matches(data, profile):
        raise UserError(f'This screen does not match the verified {profile} controller/timing profile.')
    b = bytearray(data)
    b[54:72] = FIXED if profile == PROFILE else STRIP_FIXED
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
