from odoo import models, fields, api, _

class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def action_done(self):
        res = super(StockPicking, self).action_done()
        if self.picking_type_code == 'outgoing' and self.sale_id:
            self.sale_id.with_context({'picking_id': self.id}).action_invoice_create()
        return res
