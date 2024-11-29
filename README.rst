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

- Odoo configurations for TurnKey v18.x:

    - Odoo v18 installed from Docker Hub.
    - Includes modules from base install of Odoo.

- **Security note**: Updates to Odoo **ARE NOT** configured to install automatically.

- SSL support out of the box.
- `Adminer`_ administration frontend for PostgreSQL (listening on
  port 12322 - uses SSL).
- Webmin modules for configuring PostgreSQL and Postfix.

**Notice for special Odoo Localization**

In case you need an Odoo Localization you might need other `pip` packages
and libs installed in the `odoo` container, please check your localization support
on OCA_.

Credentials *(passwords set at first boot)*
-------------------------------------------

**Note**: the Odoo password set at firstboot applies to both the Odoo
admin account (example app) AND the master password, however these can be
changed individually as per upstream docs_ after firstboot.

-  Webmin, SSH: username **root**
-  PostgreSQL, Adminer: randomly generated (see `/etc/turnkey-podman/.env`)
-  Odoo Master Account: **admin**

.. _Odoo: https://www.odoo.com
.. _TurnKey Core: https://www.turnkeylinux.org/core
.. _Adminer: https://www.adminer.org
.. _OCA: https://github.com/OCA
.. _docs: https://www.odoo.com/documentation
