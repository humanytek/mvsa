# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import http, _
from odoo.http import request
from odoo.addons.website_sale.controllers.main import WebsiteSale

class WebsitePaymentWay(WebsiteSale):

    def _get_shop_payment_values(self, order, **kwargs):
        values = super(WebsitePaymentWay, self)._get_shop_payment_values(order, **kwargs)
        payment_method_rec = request.env['l10n_mx_edi.payment.method'].sudo().search([])
        values['payment_method_rec'] = payment_method_rec
        return values

    @http.route('/shop/payment/validate', type='http', auth="public", website=True, sitemap=False)
    def payment_validate(self, transaction_id=None, sale_order_id=None, **post):
        return super(WebsitePaymentWay, self).payment_validate(transaction_id, sale_order_id, **post)
