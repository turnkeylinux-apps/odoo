#!/usr/bin/python3
"""Set Odoo admin/master password

Option:
    --pass=     unless provided, will ask interactively
"""

import os
import sys
import getopt
import subprocess

from libinithooks import inithooks_cache
from libinithooks.dialog_wrapper import Dialog
from passlib.context import CryptContext

def usage(s=None):
    if s:
        print("Error:", s, file=sys.stderr, **kwargs)
    print("Syntax: %s [options]" % sys.argv[0], file=sys.stderr)
    print(__doc__, file=sys.stderr)
    sys.exit(1)

def main():
    try:
        opts, args = getopt.gnu_getopt(sys.argv[1:], "h", ['help', 'pass='])
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
            "Odoo Password",
            "Enter new password for the Odoo 'admin' account and database management.",
        )

    hash = CryptContext(schemes=['pbkdf2_sha512']).hash(password)

    db_name = os.environ.get("POSTGRES_DB", "odoo")
    db_user = os.environ.get("POSTGRES_USER", "odoo")

    stmts = ["UPDATE res_users SET password='%s' WHERE id=2;" % (hash)]
    for stmt in stmts:
        _ = subprocess.run(["podman", "exec", "db", "psql", "-U", db_user, db_name, "-c", stmt])

    config = "/etc/odoo/odoo.conf"
    _ = subprocess.run(["sed", "-ri", 's|^admin_passwd.*$|admin_passwd = %s|' % (hash), config])

    print("Restarting services; please wait...")
    _ = subprocess.run(['podman', 'restart', 'odoo'])

if __name__ == "__main__":
    main()
