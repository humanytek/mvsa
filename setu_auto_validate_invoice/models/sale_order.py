from odoo import models, fields, api, _

class SaleOrder(models.Model):
    _inherit = 'sale.order'

    # l10n_mx_edi_payment_method_id = fields.Many2one('l10n_mx_edi.payment.method',
    #                                                 string='Payment Way')

    def _prepare_invoice(self):
        vals = super(SaleOrder, self)._prepare_invoice()
        if self._context.get('picking_id'):
            payment_method = self.env['l10n_mx_edi.payment.method'].search([('name', '=', 'Transferencia electrónica de fondos')])
            vals.update({'l10n_mx_edi_usage': 'G01',
                         'l10n_mx_edi_payment_method_id': payment_method and payment_method.id})
        return vals

    def action_invoice_create(self):
        res = super(SaleOrder, self).action_invoice_create()
        invoice_note = self.env['ir.config_parameter'].sudo(). \
                           get_param('setu_auto_validate_invoice.invoice_note_zero_tax') or False
        if invoice_note:
            invoices = self.env['account.invoice'].browse(res)
            for invoice in invoices:
                if 0.0 in invoice.tax_line_ids.mapped('amount'):
                    self.env['account.invoice.line'].create({'name': invoice_note,
                                                             'display_type': 'line_note',
                                                             'invoice_id': invoice.id})
        return res

class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    @api.multi
    def _prepare_invoice_line(self, qty):
        if self._context.get('picking_id'):
            picking_id = self.env['stock.picking'].browse(self._context.get('picking_id'))
            stock_move = picking_id.move_lines.filtered(lambda x:x.sale_line_id.id == self.id)
            if stock_move:
                qty = stock_move.quantity_done or 0.0
        vals = super(SaleOrderLine, self)._prepare_invoice_line(qty)
        return vals

