import unittest
from pi_setting.touch import TouchTest, TARGETS
from pi_setting.test_cli import build_parser


class TouchTests(unittest.TestCase):
    def test_targets_require_touch_down_at_the_target(self):
        state = TouchTest()
        for index, (x, y) in enumerate(TARGETS):
            state.event('begin', index, x*480, y*480, 480, 480)
            state.event('end', index, x*480, y*480, 480, 480)
        self.assertEqual(state.summary()['targets_hit'], 5)
        self.assertEqual(state.count, 5)
        self.assertFalse(state.active)

    def test_drag_does_not_count_as_another_tap_or_hit(self):
        state = TouchTest()
        state.event('begin', 'finger', 100, 120, 480, 480)
        state.event('update', 'finger', 240, 240, 480, 480)
        state.event('end', 'finger', 240, 240, 480, 480)
        self.assertEqual(state.count, 1)
        self.assertEqual(state.hits, set())
        self.assertEqual(len(state.trails[0]), 2)

    def test_reset_and_touch_cancel(self):
        state = TouchTest()
        state.event('begin', 'a', 240, 240, 480, 480)
        state.event('cancel', 'a', 0, 0, 480, 480)
        self.assertFalse(state.active)
        self.assertEqual(state.last, (240, 240))
        state.event('begin', 'b', 240, 340, 480, 480)
        self.assertEqual(state.count, 0)
        self.assertIsNone(state.last)
        self.assertFalse(state.hits)

    def test_targets_fit_round_screens_and_scale_with_size(self):
        for width, height in ((480,480), (800,800)):
            state = TouchTest()
            for index, (x, y) in enumerate(TARGETS):
                state.event('begin', index, x*width, y*height, width, height)
            self.assertEqual(len(state.hits), 5)

    def test_command(self):
        args = build_parser().parse_args(['touch', '--screen', '2'])
        self.assertEqual((args.action, args.screen), ('touch', 2))

    def test_emulated_pointer_is_not_misreported_as_native_touch(self):
        state = TouchTest()
        state.event('begin', 'pointer', 240, 240, 480, 480, 'pointer_or_emulated')
        self.assertEqual(state.summary()['input_counts'], {'native_touch': 0, 'pointer_or_emulated': 1})
        self.assertEqual(state.summary()['last_input'], 'pointer_or_emulated')
