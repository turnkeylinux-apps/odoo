Odoo - From ERP to CRM, eCommerce to CMS
==========================================

`Odoo`_ is an all-in-one business management suite of mobile-friendly web
apps that integrates everything you need to grow your business: CRM,
website content management, project management, human resources,
accounting, invoicing and more. Odoo apps integrate seamlessly to
provide a full-featured open source ERP, but can also be used
stand-alone. Python programmers can develop their own app modules, or
choose from an array of free open source such as those provided by `OCA`_;
or paid commercial ones.

This appliance includes all the standard features in `TurnKey Core`_:

- Odoo configurations for TurnKey v18.x:

  - **Odoo v18** installed from official Odoo 18.0 nightly apt
    repository.
  - Includes modules from base install of Odoo.

- **Security note**: Updates to Odoo are available via standard
  ``apt-get upgrade`` from the Odoo nightly repository.

- SSL support out of the box.
- `Adminer`_ administration frontend for PostgreSQL (listening on
  port 12322 - uses SSL).
- Webmin modules for configuring Apache2, PostgreSQL and Postfix.
- Custom addons directory at ``/opt/odoo/custom-addons``.
- WebSocket support for Odoo 18 live chat and notifications.

**First boot configuration**

Beyond the password, first boot (``turnkey-init``) lets you:

- **Choose the database name** - keep the default
  (``TurnkeylinuxExample``) or enter a new name. A new name initializes
  a fresh database and removes the unused example database.
- **Choose demo data** - when a new database is initialized you can load
  Odoo demo data (choose "No" for production).
- **Download OCA localization addons** - e.g. ``brazil``, ``spain``.
  Selected `OCA`_ ``l10n-*`` repos (18.0 branch) are cloned into
  ``/opt/odoo/custom-addons``, their python requirements installed and
  registered in ``addons_path``; the addons then show up in the Odoo
  Apps menu, ready to install per database. Requires internet access.

For unattended/pre-seeded deployments (e.g. TurnKey Hub) the same
options can be pre-seeded via ``inithooks.conf``::

    export APP_PASS=SecretPassword1!
    export ODOO_DB_NAME=production
    export ODOO_DEMO=no
    export ODOO_L10N=brazil

Unset options fall back to safe defaults (example database, no demo
data, no extra addons), so existing Hub deployments keep working
unchanged.

**To create a new Odoo Database (i.e. site)**

To create a new Odoo DB, the Odoo config file needs to be edited and the
Odoo service restarted.

Overview of process:
1. Edit /etc/odoo/odoo.conf

   * change value of "db_name" from "TurnkeylinuxExample" to your desired DB
     name

2. Restart odoo.service::

       systemctl restart odoo

3. Reload Odoo login screen in your browser and you should be good to go

**Notice for special Odoo Localization**

Localization (l10n) addons can be downloaded at first boot (see above)
or at any time by re-running ``turnkey-init``. Some localizations may
need additional PIP packages and system libs - ``requirements.txt`` of
each selected OCA repo is installed automatically, but please check your
localization's documentation on `OCA`_ for extra system dependencies.

Credentials *(passwords set at first boot)*
--------------------------------------------

**Note**: the Odoo password set at firstboot applies to both the Odoo
admin account (example app) AND the masterpassword - however these can be
changed individually after firstboot.

- Webmin, SSH: username **root**
- PostgreSQL, Adminer: username **postgres**
- Odoo Master Account: **admin**

.. _Odoo: https://www.odoo.com/
.. _TurnKey Core: https://www.turnkeylinux.org/core
.. _Adminer: https://www.adminer.org/
.. _OCA: https://github.com/OCA
