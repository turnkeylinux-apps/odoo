#!/usr/bin/python3
"""Tests for the Odoo firstboot inithook.

Stubs out passlib / dialog_wrapper / pgsqlconf and intercepts subprocess,
so the inithook control flow can be exercised without an appliance:

    python3 tests/test_inithook.py

Covers the pre-seeded (TurnKey Hub) path, the interactive path, database
create/adopt/refuse decisions, failure recovery and the OCA addon
download - including rejection of hostile oca_dependencies.txt entries.
"""
import os
import re
import sys
import types
import shutil
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, os.pardir,
                   'overlay/usr/lib/inithooks/bin/odoo.py')


# --- stub external inithooks/passlib deps -------------------------------
def install_stubs():
    passlib = types.ModuleType('passlib')
    context = types.ModuleType('passlib.context')

    class CryptContext:
        def __init__(self, schemes):
            self.schemes = schemes

        def hash(self, password):
            return '$pbkdf2-sha512$25000$fakehash$for%testing'

    context.CryptContext = CryptContext
    passlib.context = context
    sys.modules['passlib'] = passlib
    sys.modules['passlib.context'] = context

    dw = types.ModuleType('dialog_wrapper')

    class Dialog:
        script = None  # list of answers, consumed in order

        def __init__(self, title):
            self.title = title
            self.asked = []

        def _next(self, kind):
            self.asked.append(kind)
            if not Dialog.script:
                raise AssertionError(f"unexpected dialog: {kind}")
            return Dialog.script.pop(0)

        def get_password(self, *a, **kw):
            return self._next('password')

        def get_input(self, title, text, init=""):
            val = self._next(f'input:{title}')
            return init if val is None else val

        def yesno(self, title, text, **kw):
            return self._next(f'yesno:{title}')

        def error(self, text):
            self.asked.append('error')

    dw.Dialog = Dialog
    sys.modules['dialog_wrapper'] = dw

    pgc = types.ModuleType('pgsqlconf')

    class PostgreSQL:
        executed = []

        def __init__(self, database):
            self.database = database

        def execute(self, sql):
            PostgreSQL.executed.append((self.database, sql.decode()))

    pgc.PostgreSQL = PostgreSQL
    sys.modules['pgsqlconf'] = pgc
    return Dialog, PostgreSQL


Dialog, PostgreSQL = install_stubs()

# import the hook (its filename shadows the odoo package, hence the copy)
_pkg = tempfile.mkdtemp()
shutil.copyfile(SRC, os.path.join(_pkg, 'hook_under_test.py'))
sys.path.insert(0, _pkg)
import hook_under_test as hook  # noqa: E402


class FakeSystem:
    """Fake postgres/odoo/service/git/pip world."""

    def __init__(self, databases=None, odoo_dbs=None):
        self.databases = set(databases or [])
        self.odoo_dbs = set(odoo_dbs if odoo_dbs is not None
                            else self.databases)
        self.calls = []
        self.fail = {}     # substring -> returncode
        self.services = []

    def result(self, rc=0, out='', err=''):
        return types.SimpleNamespace(returncode=rc, stdout=out, stderr=err)

    def __call__(self, args, **kw):
        self.calls.append(list(args))
        joined = ' '.join(args)
        for needle, rc in self.fail.items():
            if needle in joined:
                return self.result(rc, err=f'simulated failure: {needle}')

        if args[0] == 'service':
            self.services.append((args[2], args[1]))
            return self.result()
        if args[0] in ('chown', 'chmod'):
            return self.result()
        if args[0] == 'pip3':
            return self.result()

        if args[:3] == ['runuser', '-u', 'postgres']:
            return self._postgres(args[4:])
        if args[:3] == ['runuser', '-u', 'odoo']:
            return self._odoo(args[4:])
        raise AssertionError(f"unexpected command: {args}")

    def _postgres(self, args):
        if args[0] == 'createdb':
            name = args[-1]
            if name in self.databases:
                return self.result(1, err='already exists')
            self.databases.add(name)
            return self.result()
        if args[0] == 'dropdb':
            name = args[-1]
            self.databases.discard(name)
            self.odoo_dbs.discard(name)
            return self.result()
        if args[0] == 'psql':
            sql = args[-1]
            if 'pg_database' in sql:
                name = re.search(r"datname = '([^']*)'", sql).group(1)
                return self.result(out='1\n' if name in self.databases
                                   else '\n')
            if 'information_schema' in sql:
                name = args[args.index('-d') + 1]
                return self.result(out='1\n' if name in self.odoo_dbs
                                   else '\n')
        raise AssertionError(f"unexpected postgres command: {args}")

    def _odoo(self, args):
        if args[0] == 'odoo':
            db = args[args.index('--database') + 1]
            self.odoo_dbs.add(db)
            return self.result()
        if args[0] == 'env':      # git clone
            dest = args[-1]
            os.makedirs(dest, exist_ok=True)
            return self.result()
        raise AssertionError(f"unexpected odoo command: {args}")


class InithookTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.conf = os.path.join(self.tmp, 'odoo.conf')
        with open(self.conf, 'w') as fob:
            fob.write(
                "[options]\n"
                "admin_passwd = admin\n"
                "db_name = TurnkeylinuxExample\n"
                "db_password = False\n"
                "addons_path = /usr/lib/python3/dist-packages/odoo/addons,"
                "/opt/odoo/custom-addons\n"
                "limit_memory_hard = 2684354560\n")
        self.addons = os.path.join(self.tmp, 'custom-addons')
        hook.CONF_FILE = self.conf
        hook.CUSTOM_ADDONS_DIR = self.addons
        PostgreSQL.executed = []
        Dialog.script = []
        os.environ.pop('ODOO_PASS', None)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_hook(self, argv, system, env=None):
        with mock.patch.object(sys, 'argv', ['odoo.py'] + argv), \
             mock.patch.object(hook.subprocess, 'run', system), \
             mock.patch.dict(os.environ, env or {}):
            hook.main()

    def conf_value(self, key):
        import configparser
        cfg = configparser.ConfigParser(interpolation=None)
        cfg.read(self.conf)
        return cfg.get('options', key, fallback=None)

    # -- non-interactive (Hub) ------------------------------------------
    def test_preseeded_password_only_keeps_example_db(self):
        sysm = FakeSystem(['TurnkeylinuxExample'])
        self.run_hook([], sysm, env={'ODOO_PASS': 'Secret1!'})
        self.assertEqual(self.conf_value('db_name'), 'TurnkeylinuxExample')
        self.assertTrue(
            self.conf_value('admin_passwd').startswith('$pbkdf2-sha512$'))
        self.assertEqual(PostgreSQL.executed[0][0], 'TurnkeylinuxExample')
        self.assertIn("login='admin'", PostgreSQL.executed[0][1])
        # no dialog was constructed, nothing dropped, nothing created
        self.assertFalse(any(c[3:4] == ['createdb'] for c in sysm.calls))

    def test_password_not_leaked_to_argv_or_subprocess_env(self):
        sysm = FakeSystem(['TurnkeylinuxExample'])
        self.run_hook([], sysm, env={'ODOO_PASS': 'Secret1!'})
        self.assertNotIn('ODOO_PASS', os.environ)
        for call in sysm.calls:
            self.assertNotIn('Secret1!', ' '.join(call))

    def test_preseeded_custom_db_initialized_and_example_dropped(self):
        sysm = FakeSystem(['TurnkeylinuxExample'])
        self.run_hook(['--dbname=production', '--demo=no'], sysm,
                      env={'ODOO_PASS': 'Secret1!'})
        self.assertEqual(self.conf_value('db_name'), 'production')
        self.assertIn('production', sysm.databases)
        self.assertNotIn('TurnkeylinuxExample', sysm.databases)
        init = [c for c in sysm.calls if 'odoo' in c and '--init' in c][0]
        self.assertIn('--without-demo=all', init)

    def test_demo_yes_omits_without_demo(self):
        sysm = FakeSystem(['TurnkeylinuxExample'])
        self.run_hook(['--dbname=demo1', '--demo=yes'], sysm,
                      env={'ODOO_PASS': 'Secret1!'})
        init = [c for c in sysm.calls if 'odoo' in c and '--init' in c][0]
        self.assertNotIn('--without-demo=all', init)

    def test_rerun_without_dbname_keeps_custom_db(self):
        """turnkey-init re-run must not orphan the configured database."""
        sysm = FakeSystem(['production'])
        with open(self.conf, 'a') as fob:
            pass
        import configparser
        cfg = configparser.ConfigParser(interpolation=None)
        cfg.read(self.conf)
        cfg.set('options', 'db_name', 'production')
        with open(self.conf, 'w') as fob:
            cfg.write(fob)
        self.run_hook([], sysm, env={'ODOO_PASS': 'Secret1!'})
        self.assertEqual(self.conf_value('db_name'), 'production')
        self.assertFalse(any('createdb' in c for c in sysm.calls))

    def test_existing_non_odoo_db_is_refused(self):
        sysm = FakeSystem(['legacy'], odoo_dbs=[])
        with self.assertRaises(SystemExit) as cm:
            self.run_hook(['--dbname=legacy'], sysm,
                          env={'ODOO_PASS': 'Secret1!'})
        self.assertEqual(cm.exception.code, 1)
        self.assertEqual(self.conf_value('db_name'), 'TurnkeylinuxExample')

    def test_failed_init_restarts_odoo_and_leaves_no_partial_db(self):
        sysm = FakeSystem(['TurnkeylinuxExample'])
        sysm.fail['--init base'] = 1
        with self.assertRaises(SystemExit) as cm:
            self.run_hook(['--dbname=broken'], sysm,
                          env={'ODOO_PASS': 'Secret1!'})
        self.assertEqual(cm.exception.code, 1)
        self.assertNotIn('broken', sysm.databases)
        self.assertIn(('start', 'odoo'), sysm.services)
        self.assertEqual(self.conf_value('db_name'), 'TurnkeylinuxExample')

    def test_invalid_dbname_rejected(self):
        sysm = FakeSystem(['TurnkeylinuxExample'])
        for bad in ['; DROP DATABASE x', '../etc', '1db', 'a b']:
            with self.assertRaises(SystemExit):
                self.run_hook([f'--dbname={bad}'], sysm,
                              env={'ODOO_PASS': 'Secret1!'})

    def test_invalid_l10n_rejected(self):
        sysm = FakeSystem(['TurnkeylinuxExample'])
        with self.assertRaises(SystemExit):
            self.run_hook(['--l10n=narnia'], sysm,
                          env={'ODOO_PASS': 'Secret1!'})

    def test_l10n_clone_registers_addons_path(self):
        sysm = FakeSystem(['TurnkeylinuxExample'])
        self.run_hook(['--l10n=brazil'], sysm, env={'ODOO_PASS': 'Secret1!'})
        clone = [c for c in sysm.calls if 'git' in c][0]
        self.assertEqual(clone[:3], ['runuser', '-u', 'odoo'])
        self.assertIn('--branch', clone)
        self.assertIn('18.0', clone)
        self.assertIn('--', clone[clone.index('clone'):])
        self.assertIn('https://github.com/OCA/l10n-brazil', clone)
        self.assertIn(os.path.join(self.addons, 'l10n-brazil'),
                      self.conf_value('addons_path'))

    def test_l10n_clone_failure_is_not_fatal(self):
        sysm = FakeSystem(['TurnkeylinuxExample'])
        sysm.fail['git clone'] = 128
        self.run_hook(['--l10n=brazil'], sysm, env={'ODOO_PASS': 'Secret1!'})
        self.assertEqual(self.conf_value('db_name'), 'TurnkeylinuxExample')

    def test_hostile_oca_dependency_names_are_ignored(self):
        """The CRITICAL finding: oca_dependencies.txt is third party."""
        sysm = FakeSystem(['TurnkeylinuxExample'])
        repo = os.path.join(self.addons, 'l10n-brazil')

        real_odoo = sysm._odoo

        def odoo_with_deps(args):
            res = real_odoo(args)
            if args[0] == 'env' and args[-1] == repo:
                with open(os.path.join(repo, 'oca_dependencies.txt'),
                          'w') as fob:
                    fob.write('# comment\n'
                              '/etc/cron.d/pwn\n'
                              '../../../etc/cron.d/pwn2\n'
                              '--upload-pack=touch /tmp/pwn\n'
                              'server-tools\n')
            return res

        sysm._odoo = odoo_with_deps
        self.run_hook(['--l10n=brazil'], sysm, env={'ODOO_PASS': 'Secret1!'})
        cloned = [c[-1] for c in sysm.calls if 'git' in c]
        self.assertEqual(
            sorted(cloned),
            sorted([repo, os.path.join(self.addons, 'server-tools')]))
        for path in self.conf_value('addons_path').split(','):
            self.assertFalse(path.startswith('/etc'), path)

    def test_conf_permissions_tightened(self):
        sysm = FakeSystem(['TurnkeylinuxExample'])
        self.run_hook([], sysm, env={'ODOO_PASS': 'Secret1!'})
        self.assertIn(['chmod', '0640', self.conf], sysm.calls)
        self.assertIn(['chown', 'odoo:odoo', self.conf], sysm.calls)

    def test_unrelated_conf_keys_preserved(self):
        sysm = FakeSystem(['TurnkeylinuxExample'])
        self.run_hook([], sysm, env={'ODOO_PASS': 'Secret1!'})
        self.assertEqual(self.conf_value('limit_memory_hard'), '2684354560')

    # -- interactive ------------------------------------------------------
    def test_interactive_full_flow(self):
        sysm = FakeSystem(['TurnkeylinuxExample'])
        Dialog.script = [
            'Secret1!',        # password
            'production',      # db name
            True,              # want l10n?
            'brazil,spain',    # which
            False,             # demo data? -> no (production)
        ]
        self.run_hook([], sysm)
        self.assertEqual(self.conf_value('db_name'), 'production')
        init = [c for c in sysm.calls if 'odoo' in c and '--init' in c][0]
        self.assertIn('--without-demo=all', init)
        self.assertNotIn('TurnkeylinuxExample', sysm.databases)
        self.assertEqual(Dialog.script, [])

    def test_interactive_defaults_to_configured_db(self):
        sysm = FakeSystem(['production'])
        import configparser
        cfg = configparser.ConfigParser(interpolation=None)
        cfg.read(self.conf)
        cfg.set('options', 'db_name', 'production')
        with open(self.conf, 'w') as fob:
            cfg.write(fob)
        Dialog.script = ['Secret1!', None, False]  # None = accept init
        self.run_hook([], sysm)
        self.assertEqual(self.conf_value('db_name'), 'production')
        self.assertIn('production', sysm.databases)

    def test_interactive_rejects_bad_db_name_then_accepts(self):
        sysm = FakeSystem(['TurnkeylinuxExample'])
        Dialog.script = ['Secret1!', '1bad', 'good_db', False, False]
        self.run_hook([], sysm)
        self.assertEqual(self.conf_value('db_name'), 'good_db')

    def test_preseeded_never_prompts(self):
        sysm = FakeSystem(['TurnkeylinuxExample'])
        Dialog.script = []   # any dialog call raises
        self.run_hook(['--dbname=production'], sysm,
                      env={'ODOO_PASS': 'Secret1!'})
        self.assertEqual(self.conf_value('db_name'), 'production')


if __name__ == '__main__':
    unittest.main(verbosity=2)
