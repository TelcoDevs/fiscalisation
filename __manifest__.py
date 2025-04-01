# -*- coding: utf-8 -*-
{
    'name': 'ZIMRA Fiscalisation',
    'summary': 'Fiscal Device Integration',
    'category': 'Accounting',
    'author': 'TELCO',
    'website': 'live.telco.co.zw',
    'version': '16.0.1.0.0',
    'depends': ['base', 'account', 'contacts', 'product'],

    "data": [
        "security/fiscalisation_groups.xml",
        "security/ir.model.access.csv",
        "views/fiscal_device_views.xml",
        "views/templates.xml",
        "views/account_move_views.xml",
        "reports/report_invoice.xml"
    ],
    # only loaded in demonstration mode
    'external_dependencies': {
        'python': ['requests', 'qrcode']
    },
    'demo': [
        'demo/demo.xml',
    ],
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}

