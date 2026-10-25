from contextlib import nullcontext, redirect_stdout
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pi_setting import boot, edid
from pi_setting.common import UserError
from pi_setting.config_cli import main


def strip_edid():
    """Synthetic unit identity, public controller descriptors and tested timings."""
    data = bytearray(256)
    data[:8] = bytes.fromhex('00ffffffffffff00')
    data[8:12] = bytes.fromhex('328d5e04')
    data[12:16] = b'TEST'
    data[18:20] = bytes((1, 3))
    data[54:72] = edid.STRIP_ORIGINAL
    data[72:90] = edid.STRIP_SECOND
    data[90:108] = b'\x00\x00\x00\xfc\x00ZL480\n       '
    data[126] = 1
    data[128:131] = bytes.fromhex('02031f')
    for offset in (0, 128):
        data[offset+127] = (-sum(data[offset:offset+127])) % 256
    return bytes(data)


def rechecksum(data):
    data = bytearray(data)
    for offset in (0, 128):
        data[offset+127] = (-sum(data[offset:offset+127])) % 256
    return bytes(data)


RAW = strip_edid()
MODE = {'width': 420, 'height': 960, 'refresh': 60.0}


class StripEDIDTests(unittest.TestCase):
    def test_only_clock_and_base_checksum_change(self):
        fixed = edid.corrected(RAW, edid.STRIP_PROFILE)
        self.assertTrue(edid.valid(RAW) and edid.valid(fixed))
        changes = {i for i, (before, after) in enumerate(zip(RAW, fixed)) if before != after}
        self.assertEqual(changes, {54, 55, 127})
        self.assertEqual(int.from_bytes(fixed[54:56], 'little')*10000/(540*1000), 60.0)
        self.assertEqual(fixed[56:127], RAW[56:127])
        self.assertEqual(fixed[128:], RAW[128:])
        self.assertEqual(edid.corrected(fixed, edid.STRIP_PROFILE), fixed)
        self.assertEqual(edid.identity(fixed), edid.identity(RAW))

    def test_names_vendor_structure_and_exact_timing_are_all_required(self):
        for offset in (8, 54, 56, 63, 74, 95, 129):
            changed = bytearray(RAW)
            changed[offset] ^= 1
            with self.subTest(offset=offset):
                self.assertFalse(edid.profile_matches(rechecksum(changed), edid.STRIP_PROFILE))
        self.assertFalse(edid.profile_matches(RAW[:-1], edid.STRIP_PROFILE))
        broken = bytearray(RAW);broken[-1] ^= 1
        self.assertFalse(edid.profile_matches(broken, edid.STRIP_PROFILE))

    def test_different_unit_serial_is_preserved_without_broadening_other_checks(self):
        another = bytearray(RAW);another[12:16] = b'UNIT'
        another = rechecksum(another)
        self.assertEqual(edid.corrected(another, edid.STRIP_PROFILE)[12:16], b'UNIT')
        self.assertNotEqual(edid.identity(another), edid.identity(RAW))

    def test_profile_does_not_claim_to_distinguish_touch_variants(self):
        self.assertTrue(edid.PROFILES[edid.STRIP_PROFILE]['confirmation_required'])
        with self.assertRaisesRegex(UserError, 'non-touch sample'):
            edid.validate_profile_use(edid.STRIP_PROFILE)
        edid.validate_profile_use(edid.STRIP_PROFILE, True)
        with self.assertRaises(UserError):
            edid.validate_profile_use(edid.STRIP_PROFILE, 'true')

    def test_zl480_name_alone_and_360_resolution_do_not_match(self):
        for timing in (edid.STRIP_SECOND, bytes.fromhex('400b687810c028303214040400804700001e')):
            changed = bytearray(RAW);changed[54:72] = timing
            changed = rechecksum(changed)
            self.assertFalse(edid.profile_matches(changed, edid.STRIP_PROFILE))
            with self.assertRaises(UserError):
                edid.corrected(changed, edid.STRIP_PROFILE)


class StripCommandTests(unittest.TestCase):
    def test_missing_confirmation_stops_before_any_hardware_read_or_mutation(self):
        with patch('pi_setting.config_cli.root_required') as elevate, \
             patch('pi_setting.config_cli.edid.raw_edid') as read, \
             patch('pi_setting.config_cli.change_override') as change:
            self.assertEqual(main(['apply', '--port', '1', '--profile', edid.STRIP_PROFILE]), 1)
            elevate.assert_not_called();read.assert_not_called();change.assert_not_called()

    def test_confirmed_apply_and_saved_acknowledgement(self):
        fixed = edid.corrected(RAW, edid.STRIP_PROFILE)
        with patch('pi_setting.config_cli.root_required'), \
             patch('pi_setting.config_cli.store.locked', return_value=nullcontext()), \
             patch('pi_setting.config_cli.edid.raw_edid', return_value=RAW), \
             patch('pi_setting.config_cli.override_bytes', return_value=b''), \
             patch('pi_setting.config_cli.change_override') as change, \
             patch('pi_setting.config_cli.outputs.set_mode', return_value=MODE) as mode, \
             patch('pi_setting.config_cli.saved_update') as save, redirect_stdout(io.StringIO()):
            self.assertEqual(main(['apply', '--port', '1', '--profile', edid.STRIP_PROFILE,
                                   '--confirm-profile', '--save']), 0)
            change.assert_called_once_with(0, fixed)
            mode.assert_called_once_with(0, '420x960@60')
            self.assertEqual(save.call_args.args[1]['profile_confirmed'], True)
            self.assertEqual(save.call_args.args[1]['identity'], edid.identity(RAW))

    def test_identical_manual_trial_override_can_be_adopted_only_after_confirmation(self):
        fixed = edid.corrected(RAW, edid.STRIP_PROFILE)
        with patch('pi_setting.config_cli.root_required'), \
             patch('pi_setting.config_cli.store.locked', return_value=nullcontext()), \
             patch('pi_setting.config_cli.edid.raw_edid', return_value=RAW), \
             patch('pi_setting.config_cli.override_bytes', return_value=fixed), \
             patch('pi_setting.config_cli.record_override') as record, \
             patch('pi_setting.config_cli.change_override'), \
             patch('pi_setting.config_cli.outputs.set_mode', return_value=MODE), redirect_stdout(io.StringIO()):
            self.assertEqual(main(['apply', '--port', '1', '--profile', edid.STRIP_PROFILE,
                                   '--confirm-profile']), 0)
            record.assert_called_once_with(0, fixed)

    def test_set_save_cannot_bypass_guarded_profile_acknowledgement(self):
        fixed = edid.corrected(RAW, edid.STRIP_PROFILE)
        with patch('pi_setting.config_cli.root_required'), \
             patch('pi_setting.config_cli.store.locked', return_value=nullcontext()), \
             patch('pi_setting.config_cli.edid.raw_edid', return_value=RAW), \
             patch('pi_setting.config_cli.edid.visible_edid', return_value=fixed), \
             patch('pi_setting.config_cli.override_bytes', return_value=fixed), \
             patch('pi_setting.config_cli.store.load', return_value={'ports': {}}), \
             patch('pi_setting.config_cli.outputs.set_mode') as mode, \
             patch('pi_setting.config_cli.saved_update') as save:
            self.assertEqual(main(['set', '--port', '1', '--mode', '420x960@60', '--save']), 1)
            mode.assert_not_called();save.assert_not_called()

    def test_wrong_mode_result_failure_restores_prior_override(self):
        with patch('pi_setting.config_cli.root_required'), \
             patch('pi_setting.config_cli.store.locked', return_value=nullcontext()), \
             patch('pi_setting.config_cli.edid.raw_edid', return_value=RAW), \
             patch('pi_setting.config_cli.override_bytes', return_value=b''), \
             patch('pi_setting.config_cli.owned_override', return_value=True), \
             patch('pi_setting.config_cli.change_override') as change, \
             patch('pi_setting.config_cli.outputs.set_mode', side_effect=UserError('output rejected')):
            self.assertEqual(main(['apply', '--port', '1', '--profile', edid.STRIP_PROFILE,
                                   '--confirm-profile']), 1)
            self.assertEqual(change.call_args_list[-1].args, (0, b''))

    def test_confirmed_profile_still_refuses_unknown_edid_before_override(self):
        unknown = bytearray(RAW);unknown[8] ^= 1
        with patch('pi_setting.config_cli.root_required'), \
             patch('pi_setting.config_cli.store.locked', return_value=nullcontext()), \
             patch('pi_setting.config_cli.edid.raw_edid', return_value=rechecksum(unknown)), \
             patch('pi_setting.config_cli.change_override') as change:
            self.assertEqual(main(['apply', '--port', '1', '--profile', edid.STRIP_PROFILE,
                                   '--confirm-profile']), 1)
            change.assert_not_called()

    def test_mode_save_preserves_an_existing_identity_bound_confirmation(self):
        fixed = edid.corrected(RAW, edid.STRIP_PROFILE)
        saved = {'profile': edid.STRIP_PROFILE, 'profile_confirmed': True, 'identity': edid.identity(RAW)}
        with patch('pi_setting.config_cli.root_required'), \
             patch('pi_setting.config_cli.store.locked', return_value=nullcontext()), \
             patch('pi_setting.config_cli.edid.raw_edid', return_value=RAW), \
             patch('pi_setting.config_cli.edid.visible_edid', return_value=fixed), \
             patch('pi_setting.config_cli.override_bytes', return_value=fixed), \
             patch('pi_setting.config_cli.store.load', return_value={'ports': {'0': saved}}), \
             patch('pi_setting.config_cli.outputs.set_mode', return_value=MODE), \
             patch('pi_setting.config_cli.saved_update') as save, redirect_stdout(io.StringIO()):
            self.assertEqual(main(['set', '--port', '1', '--mode', '420x960@60', '--save']), 0)
            self.assertTrue(save.call_args.args[1]['profile_confirmed'])

    def test_desktop_restore_does_not_bypass_missing_confirmation(self):
        from pi_setting.config_cli import restore_saved
        saved = {'profile': edid.STRIP_PROFILE, 'identity': edid.identity(RAW), 'mode': '420x960@60'}
        with patch('pi_setting.config_cli.store.load', return_value={'ports': {'0': saved}}), \
             patch('pi_setting.config_cli.edid.visible_edid', return_value=edid.corrected(RAW, edid.STRIP_PROFILE)), \
             patch('pi_setting.config_cli.outputs.set_mode') as mode:
            restore_saved()
            mode.assert_not_called()


class StripBootTests(unittest.TestCase):
    def test_boot_requires_saved_acknowledgement(self):
        item = {'profile': edid.STRIP_PROFILE, 'identity': edid.identity(RAW)}
        with patch('pi_setting.boot.store.load', return_value={'ports': {'0': item}}), \
             patch('pi_setting.boot.edid.raw_edid') as read, \
             patch('pi_setting.boot.change_override') as change:
            self.assertEqual(boot.main(), 1)
            read.assert_not_called();change.assert_not_called()

    def test_confirmed_boot_and_wrong_identity_skip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory);(path/'status').write_text('connected')
            for identity in (edid.identity(RAW), 'different-unit'):
                item = {'profile': edid.STRIP_PROFILE, 'identity': identity, 'profile_confirmed': True}
                with self.subTest(identity=identity), \
                     patch('pi_setting.boot.store.load', return_value={'ports': {'0': item}}), \
                     patch('pi_setting.boot.edid.connector', return_value=path), \
                     patch('pi_setting.boot.edid.raw_edid', return_value=RAW), \
                     patch('pi_setting.boot.store.locked', return_value=nullcontext()), \
                     patch('pi_setting.boot.change_override') as change, redirect_stdout(io.StringIO()):
                    self.assertEqual(boot.main(), 0)
                    if identity == edid.identity(RAW):
                        change.assert_called_once_with(0, edid.corrected(RAW, edid.STRIP_PROFILE), desktop=False)
                    else:
                        change.assert_not_called()
