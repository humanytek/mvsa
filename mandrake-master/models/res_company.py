from odoo import models, fields


class ResCompany(models.Model):
    _inherit = "res.company"

    realization_journal_id = fields.Many2one(
        comodel_name='account.journal',
        domain=[('type', '=', 'general')],
        help='Journal where realization entries will be booked',
    )
