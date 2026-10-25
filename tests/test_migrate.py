import unittest
from pi_setting.migrate import recognized_helper


def legacy_fixture(serial_marker='a'):
    return '''"""Apply the minimal Pi 4 timing correction to the known 720x720 monitor at boot."""
ORIGINAL_HASH = "ORIGINAL"
FIXED_HASH = "FIXED"
def compatible_edid(data):
    corrected = bytearray(data)
    corrected[63] = 6
    return bytes(corrected)
def main():
    values = ('/sys/class/drm', '/sys/kernel/debug/dri', 'edid_override', '720x720')
'''.replace('"ORIGINAL"', repr(serial_marker * 64)).replace('"FIXED"', repr('b' * 64))


class MigrationTests(unittest.TestCase):
    def test_supported_layout_does_not_bind_to_a_specific_unit_hash(self):
        self.assertTrue(recognized_helper(legacy_fixture('a')))
        self.assertTrue(recognized_helper(legacy_fixture('c')))

    def test_unknown_or_modified_helpers_stay_untouched(self):
        self.assertFalse(recognized_helper('print("not a display helper")'))
        self.assertFalse(recognized_helper('invalid python !!!'))
        self.assertFalse(recognized_helper(legacy_fixture('z')))
        self.assertFalse(recognized_helper(legacy_fixture().replace('corrected[63] = 6', 'corrected[63] = 8')))
        self.assertFalse(recognized_helper(legacy_fixture().replace('edid_override', 'another_interface')))
