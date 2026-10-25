import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from pi_setting import edid, outputs, store
from pi_setting.common import UserError, connector_name
from pi_setting.config_cli import build_parser as config_parser, restore_saved, change_override
from pi_setting.test_cli import build_parser as test_parser

def synthetic_edid():
    """Synthetic identity with the public controller/timing profile; no unit serial."""
    data = bytearray(128)
    data[:8] = bytes.fromhex('00ffffffffffff00')
    data[8:12] = bytes.fromhex('5d734600')
    data[12:16] = b'TEST'
    data[16:20] = bytes([1, 30, 1, 3])
    data[54:72] = edid.ORIGINAL
    data[90:108] = b'\x00\x00\x00\xfc\x00Lontium Semi\n'
    data[127] = (-sum(data[:127])) % 256
    return bytes(data)


SAMPLE = synthetic_edid()
RANDR = '''HDMI-A-2 "WKS Lontium Semi TEST (HDMI-A-2)"
  Enabled: yes
  Modes:
    720x720 px, 60.004002 Hz (preferred, current)
    720x720 px, 59.939999 Hz
  Position: 480,0
  Transform: normal
  Scale: 1.000000
HDMI-A-1 "LTM ZL480 (HDMI-A-1)"
  Enabled: yes
  Modes:
    480x480 px, 60.000000 Hz (preferred, current)
  Position: 0,0
  Transform: normal
  Scale: 1.000000
'''


def checksum(data):
    result = bytearray(data)
    result[127] = (-sum(result[:127])) % 256
    return bytes(result)


class EDIDTests(unittest.TestCase):
    def test_working_timing_and_canonical_identity(self):
        fixed = edid.corrected(SAMPLE)
        self.assertTrue(edid.valid(fixed))
        self.assertEqual(fixed[54:72], edid.FIXED)
        self.assertEqual(edid.identity(fixed), edid.identity(SAMPLE))
        self.assertEqual(edid.corrected(fixed), fixed)
        self.assertAlmostEqual(int.from_bytes(fixed[54:56], 'little')*10000/(812*791), 60.004, places=3)

    def test_unit_specific_serials_are_preserved_but_identity_changes(self):
        another = bytearray(SAMPLE)
        another[12:16] = b'1234'
        another = checksum(another)
        self.assertEqual(edid.corrected(another)[12:16], b'1234')
        self.assertNotEqual(edid.identity(another), edid.identity(SAMPLE))

    def test_unknown_or_malformed_edids_are_rejected(self):
        for offset in (8, 54, 63, 95):
            wrong = bytearray(SAMPLE)
            wrong[offset] ^= 1
            self.assertFalse(edid.compatible(checksum(wrong)))
        broken = bytearray(SAMPLE)
        broken[127] ^= 1
        self.assertFalse(edid.compatible(broken))
        self.assertFalse(edid.valid(SAMPLE[:-1]))
        with self.assertRaises(UserError):
            edid.identity(b'')


class ModeTests(unittest.TestCase):
    def test_output_order_does_not_change_port_mapping(self):
        result = outputs.parse_outputs(RANDR)
        self.assertEqual(result[connector_name(0)]['modes'][0]['width'], 480)
        self.assertEqual(result[connector_name(1)]['position'], [480, 0])

    def test_nearest_refresh_and_unsupported_mode(self):
        modes = outputs.parse_outputs(RANDR)['HDMI-A-2']['modes']
        self.assertAlmostEqual(outputs.match_mode(modes, '720x720@60')['refresh'], 60.004002)
        for value in ('800x800@60', '720x720@75', '720; reboot', '720x720'):
            with self.assertRaises(UserError):
                outputs.match_mode(modes, value)

    def test_disabled_output_without_modes(self):
        result = outputs.parse_outputs('HDMI-A-2 "New screen"\n  Enabled: no\n')
        self.assertEqual(result['HDMI-A-2']['modes'], [])
        self.assertFalse(result['HDMI-A-2']['enabled'])


class PersistenceTests(unittest.TestCase):
    def test_auto_waits_for_desktop_mode_enumeration(self):
        # KMS may temporarily expose an empty modes file while lightdm is stopped.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            port = root/'connector'
            port.mkdir()
            (port/'status').write_text('connected')
            (port/'modes').write_text('')
            override = root/'edid_override'
            override.write_bytes(b'')
            output = {'HDMI-A-2': {'modes': [{'width': 800, 'height': 800}]}}
            with patch('pi_setting.config_cli.edid.connector', return_value=port), \
                 patch('pi_setting.config_cli.edid.override_path', return_value=override), \
                 patch('pi_setting.config_cli.edid.visible_edid', return_value=SAMPLE), \
                 patch('pi_setting.config_cli.store.STATE', root/'state'), \
                 patch('pi_setting.config_cli.outputs.outputs', return_value=output), \
                 patch('pi_setting.config_cli.run', return_value=SimpleNamespace(returncode=0)) as systemctl, \
                 patch('pi_setting.config_cli.record_override') as record:
                change_override(1, b'')
                record.assert_called_once_with(1, b'')
                self.assertIn((['systemctl', 'start', 'display-manager.service'],),
                              [c.args for c in systemctl.call_args_list])

    def test_atomic_json_and_changed_screen_skip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'nested/config.json'
            value = {'version': 1, 'ports': {'1': {'identity': 'old', 'mode': '720x720@60'}}}
            store.atomic_json(path, value)
            self.assertEqual(store.load(path), value)
            self.assertEqual(list(path.parent.iterdir()), [path])
        with patch('pi_setting.config_cli.store.load', return_value=value), \
             patch('pi_setting.config_cli.edid.visible_edid', return_value=SAMPLE), \
             patch('pi_setting.config_cli.outputs.set_mode') as apply:
            restore_saved()
            apply.assert_not_called()

    def test_saved_mode_only_restores_for_matching_identity(self):
        value = {'version': 1, 'ports': {'1': {'identity': edid.identity(SAMPLE), 'mode': '720x720@60'}}}
        mode = {'width': 720, 'height': 720, 'refresh': 60.004002}
        with patch('pi_setting.config_cli.store.load', return_value=value), \
             patch('pi_setting.config_cli.edid.visible_edid', return_value=edid.corrected(SAMPLE)), \
             patch('pi_setting.config_cli.outputs.set_mode', return_value=mode) as apply:
            restore_saved()
            apply.assert_called_once_with(1, '720x720@60')


class CommandTests(unittest.TestCase):
    def test_config_contract(self):
        args = config_parser().parse_args(['set', '--port', '1', '--mode', '800x800@60', '--save'])
        self.assertEqual((args.port, args.mode, args.save), (1, '800x800@60', True))
        args = config_parser().parse_args(['auto', '--port', '0'])
        self.assertFalse(args.save)
        args = config_parser().parse_args(['apply', '--port', '1', '--profile', 'lontium-720'])
        self.assertEqual(args.profile, edid.PROFILE)

    def test_color_contract(self):
        args = test_parser().parse_args(['cycle', '--interval', '5', '--screen', '2'])
        self.assertEqual((args.interval, args.screen), (5, 2))
        self.assertIsNone(test_parser().parse_args(['white']).screen)


if __name__ == '__main__':
    unittest.main()
