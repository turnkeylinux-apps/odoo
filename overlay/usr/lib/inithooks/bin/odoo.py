#!/usr/bin/python3
"""Configure Odoo: passwords, database name, demo data & OCA localization

Options:
    --pass=      Odoo master password & 'admin' account password
                 unless provided, will ask interactively
                 (prefer the ODOO_PASS env var - see below)
    --dbname=    Odoo database name - must match [A-Za-z][A-Za-z0-9_-]*
                 default: the database currently set in odoo.conf
                 in interactive mode, will ask
    --demo=      load demo data when initializing a new database (yes|no)
                 default: no - only applies when a new database is created
    --l10n=      comma-separated OCA localization repos to download, e.g.
                 'brazil,spain' (see https://github.com/OCA?q=l10n) or
                 'none' (default: none)

Environment:
    ODOO_PASS    same as --pass; preferred as it avoids exposing the
                 password via /proc/<pid>/cmdline (world readable)

Non-interactive mode (password provided): no dialog is ever shown and
unset options fall back to safe defaults, so pre-seeded/Hub deployments
keep working with only APP_PASS set.
"""

import os
import re
import sys
import getopt
import subprocess
import configparser

from passlib.context import CryptContext

try:
    from libinithooks.dialog_wrapper import Dialog
except ImportError:
    from dialog_wrapper import Dialog

from pgsqlconf import PostgreSQL

CONF_FILE = '/etc/odoo/odoo.conf'
DEFAULT_DB = 'TurnkeylinuxExample'
ODOO_HOME = '/var/lib/odoo'
CORE_ADDONS = '/usr/lib/python3/dist-packages/odoo/addons'
CUSTOM_ADDONS_DIR = '/opt/odoo/custom-addons'
OCA_BRANCH = '18.0'
# hard cap on the oca_dependencies.txt chain - stops a runaway/hostile
# dependency graph from cloning indefinitely at firstboot
MAX_OCA_REPOS = 50

DB_NAME_RE = re.compile(r'^[A-Za-z][A-Za-z0-9_-]*$')
# OCA repo names reachable via oca_dependencies.txt are third party
# content: only ever accept a bare, relative repo name
REPO_NAME_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]*$')

OCA_L10N = [
    'argentina', 'austria', 'belarus', 'belgium', 'brazil', 'bulgaria',
    'cambodia', 'canada', 'chile', 'china', 'colombia', 'costa-rica',
    'croatia', 'ecuador', 'estonia', 'ethiopia', 'finland', 'france',
    'germany', 'greece', 'india', 'indonesia', 'iran', 'ireland', 'italy',
    'japan', 'macedonia', 'mexico', 'morocco', 'netherlands', 'norway',
    'peru', 'poland', 'portugal', 'romania', 'russia', 'slovenia', 'spain',
    'switzerland', 'taiwan', 'thailand', 'turkey', 'ukraine',
    'united-kingdom', 'uruguay', 'usa', 'venezuela', 'vietnam',
]


def usage(s=None):
    if s:
        print("Error:", s, file=sys.stderr)
    print("Syntax: %s [options]" % sys.argv[0], file=sys.stderr)
    print(__doc__, file=sys.stderr)
    sys.exit(1)


def warn(msg):
    print(f"WARNING: {msg}", file=sys.stderr)


def fatal(msg):
    print(f"FATAL: {msg}", file=sys.stderr)
    sys.exit(1)


def service(action, name):
    # 'service' rather than systemctl - lxc/ovz may not run systemd
    subprocess.run(['service', name, action], check=False)


def run_as(user, args):
    return subprocess.run(
        ['runuser', '-u', user, '--'] + args, capture_output=True, text=True)


def pg_command(args):
    return run_as('postgres', args)


def db_exists(name):
    result = pg_command(
        ['psql', '-tAc',
         "SELECT 1 FROM pg_database WHERE datname = '{}'".format(name)])
    if result.returncode != 0:
        fatal(f"could not query PostgreSQL: {result.stderr.strip()}")
    return result.stdout.strip() == '1'


def is_odoo_database(name):
    """True if name looks like an initialized Odoo database."""
    result = pg_command(
        ['psql', '-d', name, '-tAc',
         "SELECT 1 FROM information_schema.tables"
         " WHERE table_name = 'res_users'"])
    return result.returncode == 0 and result.stdout.strip() == '1'


def init_database(db_name, demo):
    """Create db_name (owned by odoo) and initialize it with the base
    module, with or without demo data. Odoo must be stopped."""
    result = pg_command(['createdb', '-O', 'odoo', db_name])
    if result.returncode != 0:
        warn(f"createdb {db_name} failed: {result.stderr.strip()}")
        return False
    cmd = ['odoo', '--config', CONF_FILE, '--database', db_name,
           '--init', 'base', '--stop-after-init', '--workers=0']
    if not demo:
        cmd.append('--without-demo=all')
    result = run_as('odoo', cmd)
    if result.returncode != 0:
        warn(f"initializing database {db_name} failed:"
             f" {result.stderr.strip()[-500:]}")
        # leave no half-initialized database behind - it would be
        # mistaken for a valid one on the next turnkey-init run
        pg_command(['dropdb', '--if-exists', db_name])
        return False
    return True


def set_odoo_admin_password(db_name, hashed_password):
    assert DB_NAME_RE.match(db_name)
    try:
        p = PostgreSQL(db_name)
        p.execute("UPDATE res_users SET password='{}'"
                  " WHERE login='admin'".format(hashed_password)
                  .encode('utf8'))
        return True
    except subprocess.CalledProcessError:
        warn(f"could not set 'admin' password in database {db_name}")
        return False


def within_custom_addons(path):
    base = os.path.realpath(CUSTOM_ADDONS_DIR)
    target = os.path.realpath(path)
    return target.startswith(base + os.sep)


def clone_oca_repo(repo, branch=OCA_BRANCH):
    """Clone https://github.com/OCA/<repo> into CUSTOM_ADDONS_DIR.
    Returns the addons path or None. Never fatal."""
    if not REPO_NAME_RE.match(repo):
        warn(f"ignoring OCA repo with unsafe name: {repo!r}")
        return None
    dest = os.path.join(CUSTOM_ADDONS_DIR, repo)
    if not within_custom_addons(dest):
        warn(f"ignoring OCA repo escaping {CUSTOM_ADDONS_DIR}: {repo!r}")
        return None
    if os.path.isdir(dest):
        print(f"{dest} already exists - skipping clone")
        return dest
    result = run_as('odoo', [
        'env', f'HOME={ODOO_HOME}',
        'git', 'clone', '--depth', '1', '--branch', branch, '--',
        f"https://github.com/OCA/{repo}", dest])
    if result.returncode != 0:
        warn(f"cloning OCA/{repo} ({branch}) failed:"
             f" {result.stderr.strip()}")
        return None
    return dest


def install_repo_requirements(repo_dir):
    requirements = os.path.join(repo_dir, 'requirements.txt')
    if not os.path.isfile(requirements):
        return
    result = subprocess.run(
        ['pip3', 'install', '--break-system-packages', '-r', requirements],
        capture_output=True, text=True)
    if result.returncode != 0:
        warn(f"pip requirements install failed for {repo_dir}:"
             f" {result.stderr.strip()[-300:]}")


def parse_oca_dependencies(repo_dir):
    """Parse OCA oca_dependencies.txt: 'repo_name [url] [branch]' lines.
    Repo names are third party content - only bare names are accepted."""
    deps_file = os.path.join(repo_dir, 'oca_dependencies.txt')
    deps = []
    if not os.path.isfile(deps_file):
        return deps
    with open(deps_file) as fob:
        for line in fob:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            name = line.split()[0]
            if not REPO_NAME_RE.match(name):
                warn(f"{deps_file}: ignoring unsafe dependency {name!r}")
                continue
            deps.append(name)
    return deps


def install_l10n_repos(selections):
    """Clone OCA l10n repos plus their OCA dependencies into
    CUSTOM_ADDONS_DIR. Returns list of addons paths to register.
    Best-effort: failures are warnings, never fatal to firstboot."""
    if not selections:
        return []
    os.makedirs(CUSTOM_ADDONS_DIR, exist_ok=True)
    subprocess.run(['chown', 'odoo:odoo', CUSTOM_ADDONS_DIR], check=False)
    addons_paths = []
    to_install = [f"l10n-{name}" for name in selections]
    seen = set()
    while to_install:
        if len(seen) >= MAX_OCA_REPOS:
            warn(f"reached the {MAX_OCA_REPOS} OCA repo limit -"
                 f" skipping: {', '.join(sorted(set(to_install)))}")
            break
        repo = to_install.pop(0)
        if repo in seen:
            continue
        seen.add(repo)
        dest = clone_oca_repo(repo)
        if not dest:
            continue
        install_repo_requirements(dest)
        addons_paths.append(dest)
        to_install.extend(parse_oca_dependencies(dest))
    if addons_paths:
        subprocess.run(
            ['chown', '-R', 'odoo:odoo', CUSTOM_ADDONS_DIR], check=False)
    return addons_paths


def read_conf():
    config = configparser.ConfigParser(interpolation=None)
    config.read(CONF_FILE)
    return config


def configured_db_name():
    return read_conf().get(
        'options', 'db_name', fallback=DEFAULT_DB) or DEFAULT_DB


def update_odoo_conf(db_name, hashed_password, extra_addons_paths):
    config = read_conf()
    if 'options' not in config:
        config.add_section('options')
    config.set('options', 'db_name', db_name)
    config.set('options', 'admin_passwd', hashed_password)
    current = config.get('options', 'addons_path',
                         fallback=f"{CORE_ADDONS},{CUSTOM_ADDONS_DIR}")
    paths = [p.strip() for p in current.split(',') if p.strip()]
    for path in extra_addons_paths:
        if path not in paths:
            paths.append(path)
    config.set('options', 'addons_path', ','.join(paths))
    with open(CONF_FILE, 'w') as fob:
        config.write(fob)
    # holds the master password hash and the postgres password
    subprocess.run(['chown', 'odoo:odoo', CONF_FILE], check=False)
    subprocess.run(['chmod', '0640', CONF_FILE], check=False)


def parse_l10n(value):
    if value.strip().lower() in ('', 'none'):
        return []
    selections = [item.strip().lower() for item in value.split(',')
                  if item.strip()]
    invalid = [s for s in selections if s not in OCA_L10N]
    if invalid:
        return None
    return selections


def ask_l10n(d):
    if not d.yesno(
            "OCA localization addons",
            "Download OCA (Odoo Community Association) localization"
            " addons for your country?\n\nThey will be made available"
            " for installation via the Odoo Apps menu."
            " Requires internet access."):
        return []
    text = ("Enter a comma separated list of localizations, e.g.:"
            "\n\n    brazil,spain\n\nAvailable options:\n\n"
            + ', '.join(OCA_L10N))
    while True:
        value = d.get_input("OCA localizations", text) or ''
        selections = parse_l10n(value)
        if selections is not None:
            return selections
        d.error(f"Invalid selection: {value!r}\n\nPlease only use names"
                " from the list, separated by commas.")


def ask_db_name(d, current):
    while True:
        value = d.get_input(
            "Odoo database name",
            "Enter the name of the Odoo database.\n\nKeep the current"
            " value to leave the existing database as is. Entering a new"
            " name will initialize a fresh database (and remove the"
            f" unused example database '{DEFAULT_DB}').",
            init=current) or current
        if DB_NAME_RE.match(value):
            return value
        d.error(f"Invalid database name: {value!r}\n\nUse only letters,"
                " digits, '_' or '-'; must start with a letter.")


def main():
    try:
        opts, args = getopt.gnu_getopt(
            sys.argv[1:], "h",
            ['help', 'pass=', 'dbname=', 'demo=', 'l10n='])
    except getopt.GetoptError as e:
        usage(e)

    # pop so the password is not inherited by subprocesses
    password = os.environ.pop('ODOO_PASS', '')
    db_name = ''
    demo = None
    l10n_selections = None
    for opt, val in opts:
        if opt in ('-h', '--help'):
            usage()
        elif opt == '--pass':
            password = val
        elif opt == '--dbname':
            db_name = val
        elif opt == '--demo':
            demo = val
        elif opt == '--l10n':
            l10n_selections = parse_l10n(val)
            if l10n_selections is None:
                usage(f"invalid --l10n: {val}")

    # a pre-seeded password means non-interactive (e.g. Hub deployment):
    # never prompt; unset options use safe defaults
    interactive = not password

    if db_name and not DB_NAME_RE.match(db_name):
        usage(f"invalid --dbname: {db_name}")
    if demo is not None and demo.lower() not in ('yes', 'no'):
        usage(f"invalid --demo (must be yes|no): {demo}")

    # default to the database already in use, not the example one, so
    # re-running turnkey-init never orphans a custom database
    current_db = configured_db_name()

    d = None
    if interactive:
        d = Dialog('TurnKey Linux - First boot configuration')
        password = d.get_password(
            "Odoo Database Management & 'admin' Password",
            "Enter new password for Odoo Database Management -"
            " create/delete/manage Odoo DBs. This password will also"
            " login to the 'admin' account of the Odoo database.",
            blacklist=['\\', '/'])
        if not db_name:
            db_name = ask_db_name(d, current_db)
        if l10n_selections is None:
            l10n_selections = ask_l10n(d)

    db_name = db_name or current_db
    l10n_selections = l10n_selections or []
    hashed_password = CryptContext(['pbkdf2_sha512']).hash(password)

    service('start', 'postgresql')

    create_db = not db_exists(db_name)
    if create_db and interactive and demo is None:
        demo = 'yes' if d.yesno(
            "Demo data",
            f"Load Odoo demo data into the new database '{db_name}'?"
            "\n\nChoose 'No' for production deployments.",
            yes_label="Yes", no_label="No (production)") else 'no'
    with_demo = bool(demo) and demo.lower() == 'yes'

    if create_db:
        service('stop', 'odoo')
        if not init_database(db_name, with_demo):
            service('start', 'odoo')
            fatal(f"could not initialize database {db_name}")
        if db_name != DEFAULT_DB and db_exists(DEFAULT_DB):
            result = pg_command(['dropdb', DEFAULT_DB])
            if result.returncode != 0:
                warn(f"could not remove example database {DEFAULT_DB}:"
                     f" {result.stderr.strip()}")
    else:
        if demo:
            print(f"Database {db_name} already exists"
                  " - ignoring demo data setting")
        if not is_odoo_database(db_name):
            fatal(f"database {db_name} exists but is not an Odoo database"
                  " - refusing to use it")

    admin_password_set = set_odoo_admin_password(db_name, hashed_password)

    extra_addons_paths = install_l10n_repos(l10n_selections)
    update_odoo_conf(db_name, hashed_password, extra_addons_paths)

    service('restart', 'odoo')

    if not admin_password_set:
        sys.exit(1)


if __name__ == "__main__":
    main()
