# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.
{
    'name': 'Auto Create Sale Order Invoice',
    'version': '12.0',
    'category': 'stock',
    'summary': """Auto Create sale order invoice after validating the delivery order""",
    'website': 'http://www.setuconsulting.com',
    'support': 'support@setuconsulting.com',
    'description': """
        Auto Create sale order invoice after validating the delivery order
    """,
    'author': 'Setu Consulting',
    'license': 'OPL-1',
    'sequence': 20,
    'depends': ['stock_account', 'sale_stock', 'l10n_mx_edi', 'website_sale'],
    'data': [
        'views/res_config_settings.xml',
        # 'views/sale_order.xml',
        # 'views/website_template_payment_way.xml',
    ],
    'application': True,
}
