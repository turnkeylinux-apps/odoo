#!/usr/bin/python3

"""Set Odoo Admin Password
Option:
    --pass=    unless provided, will ask interactively
"""

import configparser
import getopt
import os
import subprocess
import sys

from libinithooks.dialog_wrapper import Dialog

ODOO_DIST_PACKAGES = '/usr/lib/python3/dist-packages'
ODOO_CONFIG = '/etc/odoo/odoo.conf'
ODOO_HOME = '/var/lib/odoo'
ODOO_DATA_DIR = f'{ODOO_HOME}/.local/share/Odoo'
ODOO_XDG_DATA_HOME = f'{ODOO_HOME}/.local/share'
ODOO_PASSWORD_ENV = 'TURNKEY_ODOO_ADMIN_PASSWORD'


def set_example_admin_password(database, password):
    """Set the example administrator password through Odoo's ORM."""
    environment = os.environ.copy()
    environment[ODOO_PASSWORD_ENV] = password
    script = f"""\
import os
password = os.environ.pop({ODOO_PASSWORD_ENV!r})
admin = env.ref('base.user_admin')
admin.write({{'password': password}})
env.cr.commit()
"""
    subprocess.run(
        [
            '/usr/sbin/runuser', '-u', 'odoo', '--', '/usr/bin/odoo',
            'shell', f'--config={ODOO_CONFIG}', f'--database={database}',
            '--no-http',
        ],
        input=script,
        text=True,
        env=environment,
        check=True,
    )


def load_odoo_config():
    """Load Odoo without resolving this inithook as the ``odoo`` module."""
    script = os.path.realpath(__file__)
    script_dir = os.path.dirname(script)
    sys.path[:] = [
        path for path in sys.path
        if os.path.realpath(path or os.curdir) != script_dir
    ]
    sys.path.insert(0, ODOO_DIST_PACKAGES)

    loaded = sys.modules.get('odoo')
    if loaded and os.path.realpath(getattr(loaded, '__file__', '')) == script:
        del sys.modules['odoo']

    from odoo.tools import config
    return config


def set_odoo_config_context():
    """Resolve Odoo's user-scoped defaults below its service account home."""
    os.environ['HOME'] = ODOO_HOME
    os.environ['XDG_DATA_HOME'] = ODOO_XDG_DATA_HOME


def assert_persisted_data_dir():
    """Fail firstboot unless the serialized data directory is Odoo-owned."""
    persisted = configparser.RawConfigParser()
    if not persisted.read(ODOO_CONFIG):
        raise RuntimeError(f'cannot read Odoo configuration: {ODOO_CONFIG}')

    data_dir = persisted.get('options', 'data_dir', fallback=None)
    if data_dir != ODOO_DATA_DIR:
        raise RuntimeError(
            f'unexpected Odoo data_dir in {ODOO_CONFIG}: {data_dir!r}'
        )


def usage(s=None):
    if s:
        print("Error:", s, file=sys.stderr)
    print("Syntax: %s [options]" % sys.argv[0], file=sys.stderr)
    print(__doc__, file=sys.stderr)
    sys.exit(1)


def main():
    try:
        opts, args = getopt.gnu_getopt(sys.argv[1:], "h",
                                       ['help', 'pass='])
    except getopt.GetoptError as e:
        usage(e)

    if args:
        usage("unexpected positional arguments")

    password = os.environ.pop("APP_PASS", "")
    for opt, val in opts:
        if opt in ('-h', '--help'):
            usage()
        elif opt == '--pass':
            password = val

    if not password:
        d = Dialog('TurnKey Linux - First boot configuration')
        password = d.get_password(
            "Odoo Database Management & example 'admin' Password",
            "Enter new password for Odoo Database Management - create/delete/manage Odoo DBs. "
                "This password will also login to 'admin' account of default/example Odoo.",
            blacklist=['\\', '/'])

    # The hook runs as root, but Odoo must derive and persist user-scoped paths
    # from the same home as its supervised service and subprocesses.
    set_odoo_config_context()
    config = load_odoo_config()

    default_db = 'TurnkeylinuxExample'
    set_example_admin_password(default_db, password)

    config.parse_config([f'--config={ODOO_CONFIG}'])
    config['data_dir'] = ODOO_DATA_DIR
    config.set_admin_password(password)
    config.save(['admin_passwd', 'data_dir'])
    assert_persisted_data_dir()
    subprocess.run(['chown', 'root:odoo', ODOO_CONFIG], check=True)
    subprocess.run(['chmod', '0640', ODOO_CONFIG], check=True)

    # restart odoo to apply updated password
    subprocess.run(['systemctl', 'restart', 'odoo.service'], check=True)


if __name__ == "__main__":
    main()
