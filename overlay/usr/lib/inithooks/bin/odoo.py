"""Set Odoo Admin Password
Option:
    --pass=    unless provided, will ask interactively
"""

import re
import sys
import getopt
import os

import crypt
import random
import hashlib
import configparser

import subprocess
from libinithooks.dialog_wrapper import Dialog
from pgsqlconf import PostgreSQL
from passlib.context import CryptContext

import psycopg2

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
        "Do you want to use a custom database name? (yes/no):"
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

            # Check if the database exists and drop it (force lowercase for comparison)
            cursor.execute("SELECT 1 FROM pg_database WHERE lower(datname) = %s;", ('TurnkeylinuxExample',))
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
        "Is this provisioning for production? (yes/no):"
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
        "Do you want to install OCA localization modules? (yes/no):"
    ).strip().lower()

    if install_localization == "yes":
        # List of available localization modules
        available_modules = [
            "austria", "argentina", "brazil", "belgium", "bulgaria", "belarus", 
            "chile", "croacia", "costa-rica", "colombia", "china", "canada", 
            "cambodia", "ecuador", "ethiopia", "estonia", "france", "finland", 
            "germany", "greece", "italy", "iran", "ireland", "indonesia", 
            "india", "japan", "mexico", "morocco", "macedonia", "portugal", 
            "poland", "peru", "romania", "russia", "spain", "switzerland", 
            "slovenia", "thailand", "turkey", "taiwan", "usa", "united-kingdom", 
            "uruguay", "ukraine", "venezuela", "vietnam"
        ]

        selected_modules = []
        while True:
            module = d.get_input(
                "Select Localization Module",
                f"Enter the name of a localization module to install from the list:\n\n"
                f"  austria   |  argentina   |   brazil    |  belgium\n"
                f"----------------------------------------------------\n" 
                f"  bulgaria  |   belarus    |    chile    |  croacia\n"
                f"----------------------------------------------------\n"
                f" costa-rica |  colombia    |    china    |  canada\n"
                f"----------------------------------------------------\n"
                f"  cambodia  |   ecuador    |  ethiopia   |  estonia\n"
                f"----------------------------------------------------\n"
                f"   france   |   finland    |   germany   |  greece\n"
                f"----------------------------------------------------\n"
                f"   italy    |     iran     |   ireland   |  indonesia\n"
                f"----------------------------------------------------\n"
                f"   india    |    japan     |    mexico   |  morocco\n"
                f"----------------------------------------------------\n"
                f"  macedonia |   portugal   |    poland   |  peru\n"     
                f"----------------------------------------------------\n"
                f"   romania  |    russia    |    spain    |  switzerland\n"
                f"----------------------------------------------------\n"
                f"  slovenia  |   thailand   |    turkey   |  taiwan\n"
                f"----------------------------------------------------\n"
                f"     usa    |united-kingdom|    uruguay  |  ukraine\n"
                f"----------------------------------------------------\n"
                f"  venezuela |    vietnam   |             |     \n"
                f"----------------------------------------------------\n\n"
                f"Enter 'done' when you have finished selecting modules:"
            ).strip().lower()

            if module == 'done':
                break
            elif module in available_modules:
                selected_modules.append(module)
            else:
                print("Invalid module name. Please enter a valid module name or 'done' to finish.")

        # Install selected modules (you may need to adapt the installation process depending on your System, this is a simple example in GIT for Odoo)
        original_directory = os.getcwd()  # Store the original turnkey-init working directory

        # Create a new directory for custom addons
        custom_addons_directory = '/usr/lib/python3/dist-packages/odoo/custom-addons'
        if not os.path.exists(custom_addons_directory):
            os.makedirs(custom_addons_directory)

        # Cloning the selected modules
        for module in selected_modules:
            print(f"Cloning {module} from GitHub...")
            subprocess.run(["git", "clone", f"https://github.com/oca/l10n-{module}", f"/usr/lib/python3/dist-packages/odoo/l10n/{module}"])

            # Change the current working directory to the cloned module directory
            module_directory = f"/usr/lib/python3/dist-packages/odoo/l10n/{module}"
            os.chdir(module_directory)

            # Check if oca_dependencies.txt exists in the module directory
            oca_dependencies_file = os.path.join(module_directory, "oca_dependencies.txt")
            if os.path.isfile(oca_dependencies_file):
                with open(oca_dependencies_file, 'r') as oca_deps:
                    lines = oca_deps.readlines()
                    addons_list = [line.strip() for line in lines[1:] if line.strip()]  # Ignore the first line (usually a comment)

                    # Clone and install addons specified in oca_dependencies.txt
                    for addon in addons_list:
                        print(f"Cloning {addon} addon from GitHub...")
                        addon_repo_url = f"https://github.com/oca/{addon}"
                        addon_directory = os.path.join(custom_addons_directory, addon)

                        if not os.path.exists(addon_directory):
                            subprocess.run(["git", "clone", addon_repo_url, addon_directory])
                        else:
                            print(f"{addon} addon already exists in custom addons directory.")

                        # Change the current working directory to the cloned addon directory
                        os.chdir(addon_directory)

                        # Check if requirements.txt exists in the addon directory
                        addon_requirements_file = os.path.join(addon_directory, "requirements.txt")
                        if os.path.isfile(addon_requirements_file):
                            print(f"Installing requirements for {addon} addon...")
                            # Install the requirements using pip3
                            subprocess.run(["pip3", "install", "-r", addon_requirements_file, "--break-system-packages"])
                        else:
                            print(f"No requirements.txt found for {addon} addon.")
        
        # Update the Odoo configuration file with the new addons_path
        config = configparser.ConfigParser()
        config.read('/etc/odoo/odoo.conf')
        
        if 'options' not in config:
            config.add_section('options')
        
        # Create a list to store the addons paths
        addons_paths = []
        
        # Add the default addons path
        addons_paths.append('/usr/lib/python3/dist-packages/odoo/addons')
        
        # Add the path for the selected localization modules
        for module in selected_modules:
            module_path = f"/usr/lib/python3/dist-packages/odoo/l10n/{module}"
            addons_paths.append(module_path)
        
        # Add the path for custom addons (dependencies)
        custom_addons_directory = '/usr/lib/python3/dist-packages/odoo/custom-addons'
        for addon in addons_list:
            addon_path = os.path.join(custom_addons_directory, addon)
            addons_paths.append(addon_path)
        
        # Set the addons_path in the configuration
        config.set('options', 'addons_path', ','.join(addons_paths))
        
        # Save the updated configuration
        with open('/etc/odoo/odoo.conf', 'w') as configfile:
            config.write(configfile)
        
                
        # Change back to the previous working directory
        os.chdir(original_directory)

        ##Going back to original program    
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


        # Add the path for custom addons (dependencies)
        custom_addons_directory = '/usr/lib/python3/dist-packages/odoo/custom-addons'
        for addon in addons_list:
            addon_path = os.path.join(custom_addons_directory, addon)
            addons_paths.append(addon_path)

        # Set the addons_path in the configuration
        config.set('options', 'addons_path', ','.join(addons_paths))

        # Save the updated configuration
        with open('/etc/odoo/odoo.conf', 'w') as configfile:
            config.write(configfile)


        # Change back to the previous working directory
        os.chdir(original_directory)

        ##Going back to original program    
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
