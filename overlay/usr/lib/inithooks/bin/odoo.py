#!/usr/bin/python3

"""Set Odoo Admin Password
Option:
    --pass=    unless provided, will ask interactively
"""

import re
import sys
import getopt

import crypt
import random
import hashlib
import configparser

import subprocess
from libinithooks.dialog_wrapper import Dialog
from pgsqlconf import PostgreSQL
from passlib.context import CryptContext

def usage(s=None):
    if s:
        print("Error:", s, file=sys.stderr)
    print("Syntax: %s [options]" % sys.argv[0], file=sys.stderr)
    print(__doc__, file=sys.stderr)
    sys.exit(1)

def main():
    try:
        opts, args = getopt.gnu_getopt(sys.argv[1:], "h", ['help', 'pass=', 'dbname='])
    except getopt.GetoptError as e:
        usage(e)

    password = ""
    db_name = ""
    for opt, val in opts:
        if opt in ('-h', '--help'):
            usage()
        elif opt == '--pass':
            password = val
        elif opt == '--dbname':
            db_name = val

    d = Dialog('TurnKey Linux - First boot configuration')
    if not password:
        password = d.get_password(
            "Odoo Database Management & 'admin' Password",
            "Enter new password for Odoo Database Management and 'admin' account:",
            blacklist=['\\', '/'])
    
    custom_db_name = d.get_input(
        "Use Custom Database Name?",
        "Do you want to use a custom database name? (yes/no):",
        default="no"
    ).strip().lower()
    
    if custom_db_name == "yes":
        db_name = d.get_input(
            "Odoo Database Name",
            "Enter the name for the Odoo database:"
        )

        # Remove the default "TurnkeylinuxExample" database
        try:
            conn = psycopg2.connect(
                dbname="template1",  # Connect to the template1 database
                user="postgres",     # PostgreSQL superuser
                password=password,   # Use the provided superuser password
                host="localhost",
                port="5432",
            )
            conn.autocommit = True  # Enable autocommit to execute DROP DATABASE
            cursor = conn.cursor()

            # Check if the database exists and drop it
            cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s;", ('TurnkeylinuxExample',))
            if cursor.fetchone():
                cursor.execute("DROP DATABASE TurnkeylinuxExample;")
                print("Default database 'TurnkeylinuxExample' removed.")

            cursor.close()
            conn.close()
        except Exception as e:
            print(f"Error removing default database: {e}")
            sys.exit(1)
    else:
        db_name = "TurnkeylinuxExample"  # Default database name

    provisioning_type = d.get_input(
        "Provisioning Type",
        "Is this provisioning for production? (yes/no):",
        default="no"
    ).strip().lower()

    # Check if the user provided a custom database name
    if not db_name:
        if provisioning_type == "yes":
            db_name = "production_db"  # Default production database name
        else:
            db_name = "development_db"  # Default development database name

    # Update the Odoo configuration file with the new database name and without_demo option
    config = configparser.ConfigParser()
    config.read('/etc/odoo/odoo.conf')

    if 'options' not in config:
        config.add_section('options')
    config.set('options', 'db_name', db_name)

    if provisioning_type == "yes":
        # Set without_demo to True for production provisioning
        config.set('options', 'without_demo', 'True')

    with open('/etc/odoo/odoo.conf', 'w') as configfile:
        config.write(configfile)

    # Prompt the user to install OCA localization modules
    install_localization = d.get_input(
        "Install OCA Localization Modules?",
        "Do you want to install OCA localization modules? (yes/no):",
        default="no"
    ).strip().lower()

    if install_localization == "yes":
        # List of available localization modules
        available_modules = [
            "l10n-brazil",
            "l10n-italy",
            # Add more localization modules here
        ]

        # Prompt the user to choose modules to install
        selected_modules = d.checklist("Select Localization Modules to Install", choices=[
            (module, "", False) for module in available_modules
        ])

        # Install selected modules (you may need to adapt the installation process)
        for module in selected_modules:
            print(f"Installing {module}...")
            # Implement the module installation here

    # Create the PostgreSQL database using the provided superuser password
    try:
        conn = psycopg2.connect(
            dbname="template1",  # Connect to the template1 database
            user="postgres",     # PostgreSQL superuser
            password=password,   # Use the provided superuser password
            host="localhost",
            port="5432",
        )
        conn.autocommit = True  # Enable autocommit to execute CREATE DATABASE
        cursor = conn.cursor()

        # Check if the database already exists
        cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s;", (db_name,))
        if cursor.fetchone():
            print(f"Database '{db_name}' already exists. Skipping database creation.")
        else:
            cursor.execute(f"CREATE DATABASE {db_name};")
            print(f"Database '{db_name}' created successfully.")

        cursor.close()
        conn.close()
    except Exception as e:
        print(f"Error creating database: {e}")
        sys.exit(1)

    processed_password = CryptContext(['pbkdf2_sha512']).hash(password)

    default_db = 'TurnkeylinuxExample'
    default_db_exists = True
    try:
        p = PostgreSQL(default_db)
        p.execute("UPDATE res_users SET password='{}' WHERE id=2".format(
            processed_password).encode('utf8'))
    except subprocess.CalledProcessError as e:
        default_db_exists = False
        print(f"Default DB ({default_db}) not found - skipping setting password for that")

    sys.path.insert(0, '/usr/lib/python3/dist-packages')
    import odoo
    odoo.tools.config.parse_config(['--config=/etc/odoo/odoo.conf'])
    odoo.tools.config.set_admin_password(password)
    odoo.tools.config.save()

    # restart odoo to apply updated password
    subprocess.run(['systemctl', 'restart', 'odoo'])

    if not default_db_exists:
        sys.exit(1)

if __name__ == "__main__":
    main()
