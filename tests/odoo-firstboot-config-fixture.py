#!/usr/bin/python3

"""Exercise the root-run firstboot hook's Odoo configuration boundary."""

import configparser
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import types
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK_PATH = REPO_ROOT / 'overlay/usr/lib/inithooks/bin/odoo.py'
EXPECTED_HOME = '/var/lib/odoo'
EXPECTED_DATA_DIR = f'{EXPECTED_HOME}/.local/share/Odoo'
PASSWORD = 'fixture password with spaces and $pecial characters'


class FixtureConfig:
    """Minimal configmanager contract with real config-file persistence."""

    def __init__(self):
        self.options = {'data_dir': '/root/.local/share/Odoo'}
        self.config_path = None
        self.save_keys = None

    def parse_config(self, arguments):
        assert os.environ['HOME'] == EXPECTED_HOME
        assert os.environ['XDG_DATA_HOME'] == f'{EXPECTED_HOME}/.local/share'
        assert len(arguments) == 1
        self.config_path = arguments[0].removeprefix('--config=')

        persisted = configparser.RawConfigParser()
        assert persisted.read(self.config_path)
        self.options['data_dir'] = persisted.get('options', 'data_dir')

    def __setitem__(self, key, value):
        self.options[key] = value

    def set_admin_password(self, password):
        assert password == PASSWORD
        self.options['admin_passwd'] = 'fixture-hash'

    def save(self, keys=None):
        self.save_keys = keys
        persisted = configparser.RawConfigParser()
        assert persisted.read(self.config_path)
        for key in keys:
            persisted.set('options', key, self.options[key])
        with open(self.config_path, 'w', encoding='utf-8') as config_file:
            persisted.write(config_file)


def load_hook(fixture_config):
    dialog_wrapper = types.ModuleType('libinithooks.dialog_wrapper')
    dialog_wrapper.Dialog = object
    libinithooks = types.ModuleType('libinithooks')
    libinithooks.dialog_wrapper = dialog_wrapper
    odoo = types.ModuleType('odoo')
    odoo.__file__ = '/usr/lib/python3/dist-packages/odoo/__init__.py'
    odoo.__path__ = []
    tools = types.ModuleType('odoo.tools')
    tools.config = fixture_config
    odoo.tools = tools

    modules = {
        'libinithooks': libinithooks,
        'libinithooks.dialog_wrapper': dialog_wrapper,
        'odoo': odoo,
        'odoo.tools': tools,
    }
    with mock.patch.dict(sys.modules, modules):
        spec = importlib.util.spec_from_file_location(
            'turnkey_odoo_inithook', HOOK_PATH
        )
        hook = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(hook)
    return hook, modules


def main():
    fixture_config = FixtureConfig()
    hook, modules = load_hook(fixture_config)
    calls = []

    def record_run(arguments, **kwargs):
        calls.append((arguments, kwargs))
        if arguments[0] == '/usr/sbin/runuser':
            assert kwargs['env']['HOME'] == EXPECTED_HOME
            assert kwargs['env']['XDG_DATA_HOME'] == \
                f'{EXPECTED_HOME}/.local/share'
            assert PASSWORD not in arguments
        return types.SimpleNamespace(returncode=0)

    with tempfile.TemporaryDirectory(prefix='odoo-firstboot-config.') as work:
        config_path = Path(work) / 'odoo.conf'
        config_path.write_text(
            '[options]\n'
            'data_dir = /root/.local/share/Odoo\n'
            'proxy_mode = True\n',
            encoding='utf-8',
        )
        hook.ODOO_CONFIG = str(config_path)

        environment = {
            'APP_PASS': PASSWORD,
            'HOME': '/root',
            'XDG_DATA_HOME': '/root/.local/share',
        }
        with (
            mock.patch.dict(os.environ, environment, clear=True),
            mock.patch.dict(sys.modules, modules),
            mock.patch.object(sys, 'argv', [str(HOOK_PATH)]),
            mock.patch.object(hook.subprocess, 'run', side_effect=record_run),
        ):
            hook.main()
            assert os.environ['HOME'] == EXPECTED_HOME
            assert os.environ['XDG_DATA_HOME'] == f'{EXPECTED_HOME}/.local/share'

        persisted = configparser.RawConfigParser()
        assert persisted.read(config_path)
        assert persisted.get('options', 'data_dir') == EXPECTED_DATA_DIR
        assert persisted.getboolean('options', 'proxy_mode') is True
        assert '/root' not in config_path.read_text(encoding='utf-8')
        assert fixture_config.save_keys == ['admin_passwd', 'data_dir']

        assert calls[0][0][:4] == [
            '/usr/sbin/runuser', '-u', 'odoo', '--'
        ]
        assert calls[-1][0] == ['systemctl', 'restart', 'odoo.service']

        config_path.write_text(
            '[options]\ndata_dir = /root/.local/share/Odoo\n',
            encoding='utf-8',
        )
        try:
            hook.assert_persisted_data_dir()
        except RuntimeError as error:
            assert 'unexpected Odoo data_dir' in str(error)
        else:
            raise AssertionError('root-derived data_dir did not fail closed')

    print('odoo firstboot config fixture: PASS')


if __name__ == '__main__':
    main()
