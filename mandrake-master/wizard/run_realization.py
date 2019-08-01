from odoo import models, fields, api


class ExpectedDateWizard(models.TransientModel):
    _name = 'realization.date.wizard'
    _description = 'Running the realization process'

    realization_date = fields.Date(
        default=lambda self: fields.Date.today(),
        help='Date used to compute the realization to invoices selected')

    @api.multi
    def compute_realization(self):
        active_ids = self._context.get('active_ids')
        active_model = self._context.get('active_model')

        if not active_ids or active_model not in ('account.invoice',
                                                  'account.account'):
            return False
        methods = {
            'account.invoice': lambda a: a.filtered(
                lambda a: a.state == 'open'
                and a.date < self.realization_date),
            'account.account': lambda a: a}

        records = self.env[active_model].browse(active_ids)

        methods[active_model](records).create_realization_entries(
            self.realization_date)
        return True
