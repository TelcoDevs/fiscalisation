# -*- coding: utf-8 -*-
{
    'name': 'ZIMRA Fiscalisation',
    'summary': 'Fiscal Device Integration',
    'description': """
ZIMRA Fiscalisation
===================

This module provides integration with fiscal devices to ensure compliance with ZIMRA fiscalisation requirements.
It allows for auto-management of fiscal device tokens and regular device status checks.
    """,
    'category': 'Accounting',
    'version': '18.0.1.0.0',
    'author': 'TELCO',
    'website': 'https://live.telco.co.zw',
    'license': 'OPL-1',
    'depends': [
        'base',
        'account',
        'mail',
        'contacts',
        'product'
    ],
    'data': [
        'security/fiscalisation_groups.xml',
        'security/ir.model.access.csv',
        'views/fiscal_device_views.xml',
        'views/templates.xml',
        'views/account_move_views.xml',
        'reports/report_invoice.xml',
        'data/cron_data.xml',
        'views/res_partner_view.xml',
        'views/product_view.xml'
    ],
    'demo': [
        'demo/demo.xml',
    ],
    'external_dependencies': {
        'python': ['requests', 'qrcode'],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
    'images': [
        # 'static/description/banner.png',
    ],
    # 'price': 0.0,
    # 'currency': 'USD',
    # 'live_test_url': 'https://live.telco.co.zw',
    'support': 'customer-care@teamtelco.co.zw',
}
