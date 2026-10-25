"""Guard the public 1/2 numbering at the CLI/hardware boundary."""
from contextlib import nullcontext, redirect_stderr, redirect_stdout
import io
import unittest
from unittest.mock import patch

from pi_setting.common import connector_name
from pi_setting.config_cli import build_parser, main
from pi_setting.test_cli import build_parser as test_parser


MODE = {'width': 480, 'height': 480, 'refresh': 60.0, 'preferred': True, 'current': True}


class NumberingTests(unittest.TestCase):
    def test_readonly_modes_match_linux_connector_number(self):
        available = {'HDMI-A-1': {'modes': [dict(MODE, width=480)]},
                     'HDMI-A-2': {'modes': [dict(MODE, width=800, height=800)]}}
        for number, expected in ((1, '480x480'), (2, '800x800')):
            with self.subTest(number=number), patch('pi_setting.config_cli.outputs.outputs', return_value=available), \
                 redirect_stdout(io.StringIO()) as printed:
                self.assertEqual(main(['modes', '--port', str(number)]), 0)
                self.assertIn(expected, printed.getvalue())

    def test_mutating_commands_convert_once_and_preserve_existing_saved_keys(self):
        for number in (1, 2):
            internal = number-1
            for action in ('set', 'auto', 'apply'):
                argv = [action, '--port', str(number), '--save']
                if action == 'set':
                    argv += ['--mode', '480x480@60']
                elif action == 'apply':
                    argv += ['--profile', 'lontium-720']
                with self.subTest(number=number, action=action), \
                     patch('pi_setting.config_cli.root_required') as elevate, \
                     patch('pi_setting.config_cli.store.locked', return_value=nullcontext()), \
                     patch('pi_setting.config_cli.edid.raw_edid', return_value=b'original') as raw, \
                     patch('pi_setting.config_cli.edid.visible_edid', return_value=b'original') as visible, \
                     patch('pi_setting.config_cli.edid.identity', return_value='screen-identity'), \
                     patch('pi_setting.config_cli.edid.corrected', return_value=b'corrected'), \
                     patch('pi_setting.config_cli.override_bytes', return_value=b''), \
                     patch('pi_setting.config_cli.change_override') as override, \
                     patch('pi_setting.config_cli.outputs.set_mode', return_value=MODE) as output, \
                     patch('pi_setting.config_cli.saved_update') as save, \
                     redirect_stdout(io.StringIO()) as printed:
                    self.assertEqual(main(argv), 0)
                    self.assertEqual(elevate.call_args.args[0], argv)
                    raw.assert_called_once_with(internal)
                    self.assertEqual(output.call_args.args[0], internal)
                    self.assertEqual(save.call_args.args[0], internal)
                    if action == 'auto':
                        override.assert_called_once_with(internal, b'')
                        self.assertIsNone(save.call_args.args[1])
                    elif action == 'apply':
                        override.assert_called_once_with(internal, b'corrected')
                    else:
                        visible.assert_called_once_with(internal)
                    self.assertIn(f'Screen {number} | {connector_name(internal)}', printed.getvalue())

    def test_both_parsers_accept_only_one_and_two(self):
        for number in (1, 2):
            self.assertEqual(build_parser().parse_args(['modes', '--port', str(number)]).port, number)
            self.assertEqual(test_parser().parse_args(['white', '--screen', str(number)]).screen, number)
        for number in ('0', '3', '-1'):
            for parser, argv in ((build_parser(), ['modes', '--port', number]),
                                 (test_parser(), ['white', '--screen', number])):
                with self.subTest(number=number, argv=argv), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                    parser.parse_args(argv)
                self.assertEqual(error.exception.code, 2)
