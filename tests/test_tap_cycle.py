import unittest

from pi_setting.touch import TapCycle
from pi_setting.test_cli import build_parser


class TapCycleTests(unittest.TestCase):
    def test_black_white_red_order_and_repeated_cycles(self):
        state = TapCycle()
        self.assertEqual(state.color, 'black')
        for expected in ('white', 'red', 'black', 'white', 'red', 'black'):
            state.event('begin', 'finger')
            self.assertEqual(state.color, expected)
            state.event('end', 'finger')
        self.assertEqual(state.summary()['switches'], 6)

    def test_hold_drag_duplicate_down_and_release_do_not_double_switch(self):
        state = TapCycle()
        state.event('begin', 'finger')
        state.event('begin', 'finger')
        for _ in range(200):
            state.event('update', 'finger')
        state.event('end', 'finger')
        state.event('end', 'finger')
        self.assertEqual(state.color, 'white')
        self.assertEqual(state.switches, 1)

    def test_all_fingers_must_lift_before_next_gesture(self):
        state = TapCycle()
        state.event('begin', 'one')
        state.event('begin', 'two')
        state.event('end', 'one')
        state.event('begin', 'three')
        self.assertEqual(state.switches, 1)
        state.event('end', 'two')
        state.event('cancel', 'three')
        state.event('begin', 'four')
        self.assertEqual(state.color, 'red')

    def test_independent_screens_and_restart(self):
        first, second = TapCycle(), TapCycle()
        first.event('begin', 'a')
        self.assertEqual((first.color, second.color), ('white', 'black'))
        self.assertEqual(TapCycle().color, 'black')

    def test_pointer_emulation_works_and_is_separately_identified(self):
        state = TapCycle()
        state.event('begin', 'pointer', 'pointer_or_emulated')
        state.event('update', 'pointer', 'pointer_or_emulated')
        state.event('end', 'pointer', 'pointer_or_emulated')
        self.assertEqual(state.color, 'white')
        self.assertEqual(state.summary()['input_counts'], {'native_touch': 0, 'pointer_or_emulated': 1})

    def test_interval_is_not_part_of_tap_cycle_contract(self):
        args = build_parser().parse_args(['tap-cycle', '--screen', '2'])
        self.assertEqual((args.action, args.screen), ('tap-cycle', 2))
        self.assertFalse(hasattr(args, 'interval'))
