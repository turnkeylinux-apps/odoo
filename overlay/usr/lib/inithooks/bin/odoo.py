#!/usr/bin/python3
"""Set Odoo 18 admin password and master password

Option:
    --pass=     unless provided, will ask interactively
"""

import sys
import getopt
import subprocess

from passlib.context import CryptContext
from dialog_wrapper import Dialog
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

    password = ""
    for opt, val in opts:
        if opt in ('-h', '--help'):
            usage()
        elif opt == '--pass':
            password = val

    if not password:
        d = Dialog('TurnKey Linux - First boot configuration')
        password = d.get_password(
            "Odoo Database Management & example 'admin' Password",
            "Enter new password for Odoo Database Management "
            "- create/delete/manage Odoo DBs. "
            "This password will also login to 'admin' account "
            "of default/example Odoo.",
            blacklist=['\\', '/'])

    processed_password = CryptContext(['pbkdf2_sha512']).hash(password)

    default_db = 'TurnkeylinuxExample'
    default_db_exists = True

    try:
        p = PostgreSQL(default_db)
        p.execute("UPDATE res_users SET password='{}' WHERE id=2".format(
            processed_password).encode('utf8'))
    except subprocess.CalledProcessError as e:
        default_db_exists = False
        print(f"Default DB ({default_db}) not found "
              "- skipping setting password for that")

    conf_file = '/etc/odoo/odoo.conf'
    subprocess.run([
        'sed', '-i',
        's|^admin_passwd.*|admin_passwd = {}|'.format(password),
        conf_file
    ], check=True)

    subprocess.run(['systemctl', 'restart', 'odoo'], check=True)


if __name__ == "__main__":
    main()
