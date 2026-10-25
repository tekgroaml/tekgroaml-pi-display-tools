from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pi_setting.app_cli import build_parser, version_info, main as app_main
from pi_setting.common import UserError
from pi_setting.installer import Paths, Transaction, inspect, install
from pi_setting.versioning import (Release, configuration_check, installed_version,
                                   payload_digest, plan_upgrade, version_tuple)


def make_release(root, version='2.1.0'):
    for directory in ('bin', 'src', 'scripts', 'systemd', 'desktop', 'docs'):
        (root/directory).mkdir(parents=True, exist_ok=True)
    metadata = {'format': 1, 'version': version, 'command_version': 2,
                'minimum_upgrade_version': '1.0.0',
                'config_versions': {'display': 1, 'touch': 1, 'runtime': 1}}
    (root/'VERSION.json').write_text(json.dumps(metadata))
    for name in ('README.md', 'CHANGELOG.md', 'PUBLISHING.md'):
        (root/name).write_text(version+'\n')
    for name in ('screen-config', 'screen-test', 'pi-setting'):
        (root/'bin'/name).write_text('#!/usr/bin/python3\n')
    (root/'systemd/pi-setting-boot.service').write_text('[Service]\nExecStart=/usr/bin/true\n')
    (root/'desktop/pi-setting-restore.desktop').write_text('[Desktop Entry]\n')
    return Release.load(root)


def make_legacy(root, version='2.0.0'):
    folder=root/'src/pi_setting'
    folder.mkdir(parents=True)
    (folder/'__init__.py').write_text(f'__version__ = {version!r}\nraise RuntimeError("must never execute")\n')


class VersionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.source=self.root/'source'
        self.release=make_release(self.source)
        self.paths=Paths(self.root/'system')

    def tearDown(self):
        self.tmp.cleanup()

    def test_numeric_ordering_and_invalid_version_inputs(self):
        self.assertGreater(version_tuple('2.10.0'),version_tuple('2.9.99'))
        for value in ('02.1.0','2.1','v2.1.0','2.1.0-beta','2.1.0\n',None):
            with self.subTest(value=value),self.assertRaises(ValueError):version_tuple(value)

    def test_upgrade_decisions_include_noop_major_downgrade_and_floor(self):
        self.assertEqual(plan_upgrade(None,self.release)['action'],'install')
        self.assertEqual(plan_upgrade('2.0.0',self.release)['action'],'upgrade')
        self.assertEqual(plan_upgrade('2.1.0',self.release)['action'],'noop')
        self.assertEqual(plan_upgrade('2.1.0',self.release,reinstall=True)['action'],'reinstall')
        self.assertFalse(plan_upgrade('1.0.0',self.release)['allowed'])
        self.assertTrue(plan_upgrade('1.0.0',self.release,allow_major=True)['allowed'])
        self.assertFalse(plan_upgrade('2.2.0',self.release,allow_major=True,reinstall=True)['allowed'])
        self.assertFalse(plan_upgrade('0.9.0',self.release,allow_major=True)['allowed'])

    def test_legacy_version_read_does_not_execute_old_code(self):
        make_legacy(self.paths.app)
        self.assertEqual(installed_version(self.paths.app),'2.0.0')
        self.assertEqual(inspect(self.source,self.paths)['action'],'upgrade')

    def test_unrecognized_old_installation_is_not_overwritten(self):
        self.paths.app.mkdir(parents=True)
        with self.assertRaisesRegex(ValueError,'no recognized version'):
            inspect(self.source,self.paths)

    def test_schema_rejected_before_any_application_write(self):
        make_legacy(self.paths.app)
        self.paths.config.mkdir(parents=True)
        for version in (2,True,None):
            (self.paths.config/'touch-map.json').write_text(json.dumps({'version':version,'ports':{}}))
            with self.subTest(version=version),self.assertRaisesRegex(ValueError,'incompatible'):
                inspect(self.source,self.paths)
            self.assertEqual(installed_version(self.paths.app),'2.0.0')

    def test_supported_config_and_missing_files(self):
        self.paths.config.mkdir(parents=True)
        (self.paths.config/'config.json').write_text('{"version":1,"ports":{"0":{"example":true}}}')
        observed=configuration_check(self.paths.config,self.paths.state,self.release)
        self.assertEqual(observed,{'display':1,'touch':None,'runtime':None})

    def test_payload_fingerprint_excludes_bytecode_but_detects_real_changes(self):
        before=payload_digest(self.source)
        cache=self.source/'src/__pycache__';cache.mkdir()
        (cache/'example.pyc').write_bytes(b'private compiler cache')
        self.assertEqual(before,payload_digest(self.source))
        (self.source/'src/module.py').write_text('print("changed")')
        self.assertNotEqual(before,payload_digest(self.source))

    def test_source_symlink_is_rejected(self):
        (self.source/'src/linked.py').symlink_to(self.source/'README.md')
        with self.assertRaisesRegex(ValueError,'Symlinks'):
            payload_digest(self.source)

    def test_changed_same_version_requires_new_release_number(self):
        make_release(self.paths.app)
        self.paths.state.mkdir(parents=True)
        self.paths.receipt.write_text(json.dumps({'format':1,'version':'2.1.0','payload_sha256':payload_digest(self.paths.app)}))
        (self.source/'README.md').write_text('same version but different content')
        with self.assertRaisesRegex(ValueError,'same release version has different content'):
            inspect(self.source,self.paths,reinstall=True)

    def test_modified_installed_files_require_explicit_same_release_repair(self):
        make_release(self.paths.app)
        self.paths.state.mkdir(parents=True)
        self.paths.receipt.write_text(json.dumps({'format':1,'version':'2.1.0','payload_sha256':payload_digest(self.paths.app)}))
        (self.paths.app/'bin/screen-test').write_text('modified locally')
        with self.assertRaisesRegex(ValueError,'was modified'):inspect(self.source,self.paths)
        self.assertEqual(inspect(self.source,self.paths,reinstall=True)['action'],'reinstall')

    def test_transaction_failure_restores_old_application_settings_and_links(self):
        make_legacy(self.paths.app)
        self.paths.config.mkdir(parents=True)
        (self.paths.config/'touch-map.json').write_text('{"version":1,"ports":{}}')
        self.paths.commands.mkdir(parents=True)
        link=self.paths.commands/'screen-test'
        link.symlink_to(self.paths.app/'bin/screen-test')
        transaction=Transaction(self.paths,self.source,payload_digest(self.source))
        transaction.prepare();transaction.switch()
        self.assertEqual(installed_version(self.paths.app),'2.1.0')
        (self.paths.config/'touch-map.json').write_text('bad update')
        transaction.rollback()
        self.assertEqual(installed_version(self.paths.app),'2.0.0')
        self.assertEqual((self.paths.config/'touch-map.json').read_text(),'{"version":1,"ports":{}}')
        self.assertTrue(link.is_symlink())
        self.assertFalse(self.paths.receipt.exists())

    def test_source_change_during_staging_is_detected_without_touching_old_app(self):
        make_legacy(self.paths.app)
        expected=payload_digest(self.source)
        (self.source/'README.md').write_text('changed after comparison')
        transaction=Transaction(self.paths,self.source,expected)
        with self.assertRaisesRegex(ValueError,'Source changed'):transaction.prepare()
        self.assertEqual(installed_version(self.paths.app),'2.0.0')
        self.assertIsNone(transaction.stage)

    def test_installer_failure_automatically_rolls_back(self):
        make_legacy(self.paths.app)
        def fail_verify(args,**kwargs):
            if args[0]=='systemd-analyze':raise UserError('injected unit verification failure')
            from types import SimpleNamespace
            return SimpleNamespace(returncode=0,stdout='',stderr='')
        with patch('pi_setting.installer.Paths',return_value=self.paths), \
             patch('pi_setting.installer.os.getuid',return_value=0), \
             patch('pi_setting.installer.check_platform'), \
             patch('pi_setting.installer.service_state',return_value={'active':False,'enabled':False}), \
             patch('pi_setting.installer.capture_test',return_value=(None,{})), \
             patch('pi_setting.installer.restore_test',return_value=[]), \
             patch('pi_setting.installer.restore_services') as services, \
             patch('pi_setting.installer.run',side_effect=fail_verify),redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(UserError,'previous application/configuration restored'):
                install(self.source,no_deps=True)
            services.assert_called_once()
        self.assertEqual(installed_version(self.paths.app),'2.0.0')
        self.assertFalse(self.paths.receipt.exists())
        results=list((self.paths.state/'install-backups').glob('*/result.json'))
        self.assertEqual(json.loads(results[0].read_text())['result'],'rolled-back')

    def test_success_writes_receipt_and_same_version_is_a_noop(self):
        make_legacy(self.paths.app)
        self.paths.config.mkdir(parents=True)
        config=self.paths.config/'config.json'
        config.write_text('{"version":1,"ports":{"0":{"kept":true}}}')
        from types import SimpleNamespace
        with patch('pi_setting.installer.Paths',return_value=self.paths), \
             patch('pi_setting.installer.os.getuid',return_value=0), \
             patch('pi_setting.installer.check_platform'), \
             patch('pi_setting.installer.service_state',return_value={'active':False,'enabled':False}), \
             patch('pi_setting.installer.capture_test',return_value=(None,{})), \
             patch('pi_setting.installer.restore_test',return_value=[]), \
             patch('pi_setting.installer.run',return_value=SimpleNamespace(returncode=0,stdout='')) as calls, \
             redirect_stdout(io.StringIO()):
            install(self.source,no_deps=True)
            calls.reset_mock()
            self.assertEqual(install(self.source,no_deps=True)['action'],'noop')
            calls.assert_not_called()
        receipt=json.loads(self.paths.receipt.read_text())
        self.assertEqual(receipt['version'],'2.1.0')
        self.assertEqual(receipt['previous_version'],'2.0.0')
        self.assertEqual(receipt['payload_sha256'],payload_digest(self.paths.app))
        self.assertTrue((Path(receipt['backup_dir'])/'previous-app').exists())
        self.assertEqual(json.loads(config.read_text())['ports']['0'],{'kept':True})
        self.assertTrue((self.paths.commands/'pi-setting').is_symlink())
        self.assertEqual(self.paths.app.stat().st_mode & 0o777,0o755)
        self.assertEqual(version_info(self.paths)['integrity'],'ok')

    def test_cli_requires_an_explicit_downloaded_source(self):
        args=build_parser().parse_args(['upgrade','--source',str(self.source),'--allow-major','--no-deps'])
        self.assertTrue(args.allow_major and args.no_deps)
        self.assertEqual(args.source,self.source)

    def test_uninstalled_command_links_require_explicit_repair(self):
        make_release(self.paths.app)
        plan=inspect(self.source,self.paths)
        self.assertEqual(plan['action'],'repair-needed')
        self.assertFalse(plan['allowed'])
        self.assertEqual(inspect(self.source,self.paths,reinstall=True)['action'],'reinstall')

    def test_upgrade_cli_cannot_bypass_policy_by_running_an_older_installer(self):
        (self.source/'scripts/install.sh').write_text('#!/bin/bash\nexit 0\n')
        for decision in ({'allowed':False,'action':'downgrade'}, {'allowed':True,'action':'noop'}):
            with self.subTest(decision=decision), patch('pi_setting.app_cli.inspect',return_value=decision), \
                 patch('pi_setting.app_cli.subprocess.run') as execute,redirect_stdout(io.StringIO()):
                result=app_main(['upgrade','--source',str(self.source)])
                self.assertEqual(result,0 if decision['allowed'] else 2)
                execute.assert_not_called()

    def test_unknown_receipt_format_is_rejected(self):
        make_release(self.paths.app)
        self.paths.state.mkdir(parents=True)
        self.paths.receipt.write_text('{"format":2,"version":"2.1.0"}')
        with self.assertRaisesRegex(ValueError,'receipt format'):
            inspect(self.source,self.paths)

    def test_malformed_configuration_objects_are_rejected_cleanly(self):
        self.paths.config.mkdir(parents=True)
        (self.paths.config/'config.json').write_text('[]')
        with self.assertRaisesRegex(ValueError,'configuration object'):
            inspect(self.source,self.paths)
