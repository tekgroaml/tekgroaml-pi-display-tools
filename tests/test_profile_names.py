from contextlib import redirect_stdout, nullcontext
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pi_setting import boot, edid
from pi_setting.common import UserError
from pi_setting.config_cli import build_parser, main
from test_logic import SAMPLE
from test_strip_profile import RAW


class ProfileNameTests(unittest.TestCase):
    def test_canonical_names_follow_size_resolution_refresh_driver(self):
        self.assertEqual(edid.PROFILE, '4.0inch-720x720-60hz-wks-lontium-semi')
        self.assertEqual(edid.STRIP_PROFILE, '6.2inch-420x960-60hz-ltm-zl480')
        for name, item in edid.PROFILES.items():
            prefix = f'{item["size_inches"]}inch-{item["resolution"]}-60hz-'
            self.assertEqual(name, prefix+item['driver_slug'])
            self.assertTrue(item['customer_name'] and item['customer_name_cn'])
            self.assertIn('reported', item)
            self.assertIn('repaired', item)

    def test_aliases_are_accepted_without_changing_repair_or_identity(self):
        for old, canonical in edid.PROFILE_ALIASES.items():
            raw = SAMPLE if canonical == edid.PROFILE else RAW
            self.assertEqual(edid.canonical_profile(old), canonical)
            self.assertEqual(edid.corrected(raw, old), edid.corrected(raw, canonical))
            self.assertTrue(edid.profile_matches(raw, old))
            self.assertEqual(edid.identity(raw), edid.identity(edid.corrected(raw, old)))
            args = build_parser().parse_args(['apply', '--port', '1', '--profile', old])
            self.assertEqual(args.profile, canonical)

    def test_device_card_numbers_agree_with_encoded_original_and_repaired_timings(self):
        for profile, raw in ((edid.PROFILE, SAMPLE), (edid.STRIP_PROFILE, RAW)):
            for field, data in (('reported', raw), ('repaired', edid.corrected(raw, profile))):
                with self.subTest(profile=profile, field=field):
                    dtd = data[54:72]
                    width = dtd[2]+((dtd[4] >> 4) << 8)
                    height = dtd[5]+((dtd[7] >> 4) << 8)
                    hblank = dtd[3]+((dtd[4] & 15) << 8)
                    vblank = dtd[6]+((dtd[7] & 15) << 8)
                    hfront = dtd[8]+((dtd[11] >> 6) << 8)
                    hsync = dtd[9]+(((dtd[11] >> 4) & 3) << 8)
                    vfront = (dtd[10] >> 4)+(((dtd[11] >> 2) & 3) << 4)
                    vsync = (dtd[10] & 15)+((dtd[11] & 3) << 4)
                    clock = int.from_bytes(dtd[:2], 'little')*10000
                    info = edid.PROFILES[profile][field]
                    self.assertEqual(info['mode'], f'{width}x{height}')
                    self.assertEqual(info['pixel_clock_mhz'], clock/1e6)
                    self.assertAlmostEqual(info['refresh_hz'], clock/((width+hblank)*(height+vblank)), places=5)
                    self.assertEqual(info['horizontal_front_sync_back'], [hfront, hsync, hblank-hfront-hsync])
                    self.assertEqual(info['vertical_front_sync_back'], [vfront, vsync, vblank-vfront-vsync])

    def test_old_guarded_alias_still_requires_confirmation(self):
        with self.assertRaises(UserError):
            edid.validate_profile_use('ltm-420x960-60')
        self.assertEqual(edid.validate_profile_use('ltm-420x960-60', True), edid.STRIP_PROFILE)

    def test_profiles_json_and_text_show_customer_card_and_aliases(self):
        with redirect_stdout(io.StringIO()) as result:
            self.assertEqual(main(['profiles', '--json']), 0)
        card = json.loads(result.getvalue())
        self.assertEqual(card['aliases']['lontium-720'], edid.PROFILE)
        self.assertEqual(card['profiles'][edid.STRIP_PROFILE]['reported']['pixel_clock_mhz'], 28.0)
        with redirect_stdout(io.StringIO()) as result:
            self.assertEqual(main(['profiles']), 0)
        for name, item in edid.PROFILES.items():
            self.assertIn(name, result.getvalue())
            self.assertIn(item['customer_name_cn'], result.getvalue())

    def test_existing_saved_aliases_restore_on_boot(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory);(path/'status').write_text('connected')
            for old, canonical in edid.PROFILE_ALIASES.items():
                raw = SAMPLE if canonical == edid.PROFILE else RAW
                item = {'profile': old, 'identity': edid.identity(raw), 'profile_confirmed': True}
                with self.subTest(old=old), \
                     patch('pi_setting.boot.store.load', return_value={'ports': {'0': item}}), \
                     patch('pi_setting.boot.edid.connector', return_value=path), \
                     patch('pi_setting.boot.edid.raw_edid', return_value=raw), \
                     patch('pi_setting.boot.store.locked', return_value=nullcontext()), \
                     patch('pi_setting.boot.change_override') as change,redirect_stdout(io.StringIO()):
                    self.assertEqual(boot.main(), 0)
                    change.assert_called_once_with(0, edid.corrected(raw, canonical), desktop=False)

    def test_existing_saved_guarded_alias_preserves_confirmation_when_resaved(self):
        fixed = edid.corrected(RAW, edid.STRIP_PROFILE)
        item = {'profile': 'ltm-420x960-60', 'identity': edid.identity(RAW), 'profile_confirmed': True}
        mode = {'width': 420, 'height': 960, 'refresh': 60.0}
        with patch('pi_setting.config_cli.root_required'), \
             patch('pi_setting.config_cli.store.locked', return_value=nullcontext()), \
             patch('pi_setting.config_cli.edid.raw_edid', return_value=RAW), \
             patch('pi_setting.config_cli.edid.visible_edid', return_value=fixed), \
             patch('pi_setting.config_cli.override_bytes', return_value=fixed), \
             patch('pi_setting.config_cli.store.load', return_value={'ports': {'0': item}}), \
             patch('pi_setting.config_cli.outputs.set_mode', return_value=mode), \
             patch('pi_setting.config_cli.saved_update') as save,redirect_stdout(io.StringIO()):
            self.assertEqual(main(['set', '--port', '1', '--mode', '420x960@60', '--save']), 0)
            self.assertEqual(save.call_args.args[1]['profile'], edid.STRIP_PROFILE)
            self.assertTrue(save.call_args.args[1]['profile_confirmed'])
