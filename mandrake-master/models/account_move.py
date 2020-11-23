from odoo import models, fields, api


class AccountMove(models.Model):
    _inherit = "account.move"

    realization_invoice_id = fields.Many2one(
        'account.invoice',
        readonly=True,
        help="Invoice for which this Realization has being made")
    realization_account_id = fields.Many2one(
        'account.account',
        readonly=True,
        help="Account for which this Realization has being made")
    not_delete_to_realization = fields.Boolean(string="Not delete to realization")


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    @api.multi
    def reconcile(self, writeoff_acc_id=False, writeoff_journal_id=False):
        if not self:
            return True
        # /!\ NOTE: We are going to call for monetary revaluation on invoices
        # when reconciling
        domain = [
            ('account_id.internal_type', 'in', ('receivable', 'payable'))]
        invoice_ids = self.search(domain + [
            ('invoice_id', '!=', False), ('id', 'in', self.ids)]).mapped('invoice_id')  # noqa
        non_fx_date = self.search(domain + [
            ('move_id.realization_invoice_id', '=', False),
            ('id', 'in', self.ids)], order='date desc', limit=1).mapped('date')

        if invoice_ids and non_fx_date:
            invoice_ids.create_realization_entries(max(non_fx_date))  # noqa
            new_amls = self.search(domain + [
                ('id', 'in', invoice_ids.mapped('realization_move_ids.line_ids').ids)])  # noqa
            return super(AccountMoveLine, self + new_amls).reconcile(
                writeoff_acc_id=writeoff_acc_id,
                writeoff_journal_id=writeoff_journal_id)

        return super(AccountMoveLine, self).reconcile(
            writeoff_acc_id=writeoff_acc_id,
            writeoff_journal_id=writeoff_journal_id)
