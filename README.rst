Odoo - From ERP to CRM, eCommerce to CMS
========================================

`Odoo`_ is an all-in-one business management suite of mobile-friendly web
apps that integrates everything you need to grow your business: CRM,
website content management, project management, human resources,
accounting, invoicing and more. Odoo apps integrate seamlessly to
provide a full-featured open source ERP, but can also be used
stand-alone. Python programmers can develop their own app modules, or
choose from an array of free open source such as those provided by OCA_;
or paid commercial ones.

This appliance includes all the standard features in `TurnKey Core`_:

- Odoo configurations for TurnKey v19.x:

    - Odoo 19 Community installed from Odoo's official package repository.
    - Includes modules from base install of Odoo.

- **Security note**: Odoo application updates require supervision and are not
  configured to install automatically. Check the official daily channel with
  ``odoo-update --check``, back up the database, then apply the selected APT
  update.

- SSL support out of the box.
- `Adminer`_ administration frontend for PostgreSQL (listening on
  port 12322 - uses SSL).
- Webmin modules for configuring Apache2, PostgreSQL and Postfix.

Creating another Odoo database
------------------------------

Choose a non-default password for the new database administrator, then use
Odoo 19's database command to create and initialize the database::

    read -rsp 'New Odoo database administrator password: ' ODOO_DB_ADMIN_PASSWORD
    printf '\n'
    runuser -u odoo -- odoo db -c /etc/odoo/odoo.conf init example \
        --password "$ODOO_DB_ADMIN_PASSWORD"
    unset ODOO_DB_ADMIN_PASSWORD

Do not use Odoo's default ``admin`` password.

Add the new name to the comma-separated ``db_name`` setting in
``/etc/odoo/odoo.conf``, then restart Odoo::

    systemctl restart odoo

The database command also provides ``drop``, ``dump``, and ``load`` operations.

**Notice for special Odoo Localization**

In case you run a L10n Odoo Localization you will need other PIP Packages
and Libs installed on your system, please check your localization support on
OCA_.

Credentials *(passwords set at first boot)*
-------------------------------------------

**Note**: the Odoo password set at firstboot applies to both the Odoo
admin account (example app) AND the masterpassword  - however these can be
changed individually after firstboot.

-  Webmin, SSH: username **root**
-  PostgreSQL, Adminer: username **postgres**
-  Odoo Master Account: **admin**

.. _Odoo: https://www.odoo.com/
.. _TurnKey Core: https://www.turnkeylinux.org/core
.. _Adminer: https://www.adminer.org/
.. _OCA: https://github.com/OCA
