from odoo import api, fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    invoice_note_zero_tax = fields.Char("Invoice Notes (For Zero Tax)")

    @api.model
    def get_values(self):
        res = super(ResConfigSettings, self).get_values()
        res['invoice_note_zero_tax'] = self.env['ir.config_parameter'].sudo().get_param('setu_auto_validate_invoice.invoice_note_zero_tax')
        return res

    @api.model
    def set_values(self):
        self.env['ir.config_parameter'].sudo().set_param('setu_auto_validate_invoice.invoice_note_zero_tax', self.invoice_note_zero_tax or False)
        super(ResConfigSettings, self).set_values()
