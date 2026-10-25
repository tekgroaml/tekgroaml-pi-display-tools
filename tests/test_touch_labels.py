import unittest
from pi_setting.touch_labels import build_rules


class TouchLabelTests(unittest.TestCase):
    def test_labels_follow_confirmed_pairs_not_usb_path_order(self):
        ports = {'0': {'by_path': 'platform-usb-0:1.3:1.0-event'},
                 '1': {'by_path': 'platform-usb-0:1.1:1.0-event'}}
        lines = build_rules(ports).splitlines()
        self.assertIn('1.3:1.0"', lines[1])
        self.assertIn('USB-TOUCH-1', lines[1])
        self.assertIn('1.1:1.0"', lines[2])
        self.assertIn('USB-TOUCH-2', lines[2])
        swapped = build_rules({'0': ports['1'], '1': ports['0']}).splitlines()
        self.assertIn('1.1:1.0"', swapped[1])
        self.assertIn('USB-TOUCH-1', swapped[1])

    def test_rejects_duplicate_missing_or_unsafe_pairs(self):
        for ports in ({'0': {'by_path': 'usb-event'}},
                      {'0': {'by_path': 'usb-event'}, '1': {'by_path': 'usb-event'}},
                      {'0': {'by_path': 'usb-event'}, '1': {'by_path': 'bad"-event'}}):
            with self.assertRaises(ValueError):
                build_rules(ports)
