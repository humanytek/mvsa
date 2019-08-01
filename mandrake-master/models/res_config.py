from odoo import models, fields


class AccountConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    realization_journal_id = fields.Many2one(
        related='company_id.realization_journal_id',
        comodel_name='account.journal',
        domain=[('type', '=', 'general')],
        readonly=False,
        help='Journal where realization entries will be booked',
    )
