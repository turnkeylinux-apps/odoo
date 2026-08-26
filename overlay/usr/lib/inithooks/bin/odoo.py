#!/usr/bin/python3

"""Set Odoo Admin Password
Option:
    --pass=    unless provided, will ask interactively
"""

import getopt
import os
import subprocess
import sys

from libinithooks.dialog_wrapper import Dialog
from pgsqlconf import PostgreSQL


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

    sys.path.insert(0, '/usr/lib/python3/dist-packages')
    from odoo.tools import config

    processed_password = config.crypt_context.hash(password)

    default_db = 'TurnkeylinuxExample'
    default_db_exists = True
    try:
        p = PostgreSQL(default_db)
        p.execute("UPDATE res_users SET password='{}' WHERE id=2".format(
            processed_password).encode('utf8'))
    except subprocess.CalledProcessError:
        default_db_exists = False
        print(f"Default DB ({default_db}) not found - skipping its password update")

    config.parse_config(['--config=/etc/odoo/odoo.conf'])
    config.set_admin_password(password)
    config.save()
    subprocess.run(['chown', 'root:odoo', '/etc/odoo/odoo.conf'], check=True)
    subprocess.run(['chmod', '0640', '/etc/odoo/odoo.conf'], check=True)

    # restart odoo to apply updated password
    subprocess.run(['service', 'odoo', 'restart'], check=True)

    if not default_db_exists:
        sys.exit(1)

if __name__ == "__main__":
    main()
