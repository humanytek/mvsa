from datetime import timedelta
from datetime import datetime
from calendar import monthrange
import logging

from odoo import models, fields, api, _
from odoo.tools import float_is_zero

_logger = logging.getLogger(__name__)
import pdb

class AccountInvoice(models.Model):
    _inherit = 'account.invoice'

    @api.depends('realization_move_ids')
    def _compute_realization_move_ids_nbr(self):
        for inv in self:
            inv.realization_move_ids_nbr = len(inv.realization_move_ids)

    realization_move_ids_nbr = fields.Integer(
        compute='_compute_realization_move_ids_nbr',
        string='# of Realization Entries',
        help='Quantity of Realization Entries this Invoice has')
    realization_move_ids = fields.One2many(
        'account.move',
        'realization_invoice_id',
        string='Realization Entries',
        readonly=True,
        help='Realization Journal Entries for this Invoice')

    # pylint:disable=duplicate-code
    @api.multi
    def action_view_realization_move(self):

        action = {
            'name': _('Realization Entries'),
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'target': 'current',
        }

        realization_move_ids = self.realization_move_ids.ids
        action['view_mode'] = 'tree,form'
        action['domain'] = [('id', 'in', realization_move_ids)]

        if len(realization_move_ids) == 1:
            action['res_id'] = realization_move_ids[0]
            action['view_mode'] = 'form'
        return action

    @api.model
    def _get_query_for_taxes(self, date):
        # /!\ NOTE: Invoice created at `date` will not be included. Why?
        # Because it does not make sense to reevaluate something that I just
        # created on that date. It is the mindset that on that date the rate
        # does not vary.
        # /!\ NOTE: We will use the move_id.date in the invoice which is the
        # actual accounting date.
        query = self._cr.mogrify(
            """
            UNION
            SELECT
                ai.id,
                aml.account_id,
                aml.partner_id,
                ((aml.amount_currency * (
                    COALESCE((
                    SELECT r.rate FROM res_currency_rate r
                    WHERE r.currency_id = aml.company_currency_id AND
                        r.name <= %s AND (
                            r.company_id IS NULL
                            OR r.company_id = aml.company_id)
                    ORDER BY r.company_id, r.name
                    DESC LIMIT 1), 1) /
                    COALESCE((
                    SELECT r.rate FROM res_currency_rate r
                    WHERE r.currency_id = aml.currency_id AND
                        r.name <= %s AND (
                            r.company_id IS NULL
                            OR r.company_id = aml.company_id)
                    ORDER BY r.company_id, r.name
                    DESC LIMIT 1), 1))
                )::decimal(12,2) - (
                aml.balance::decimal(12,2) +
                (COALESCE((
                    SELECT SUM(aml2.balance)
                    FROM account_move_line aml2
                    INNER JOIN account_move am
                            ON am.realization_invoice_id = ai.id
                            AND aml2.move_id = am.id
                    WHERE aml.account_id = aml2.account_id
                        AND aml2.currency_id IS NOT NULL)
                    , 0))::decimal(12,2))) AS fx
            FROM account_invoice ai
            INNER JOIN account_invoice_tax ait ON ait.invoice_id = ai.id
            INNER JOIN account_move_line aml ON aml.move_id = ai.move_id
                AND ait.account_id = aml.account_id
                AND ait.tax_id = aml.tax_line_id
                AND aml.currency_id IS NOT NULL
            INNER JOIN account_move am2 ON am2.id = ai.move_id
            INNER JOIN res_company rc ON rc.id = ai.company_id
                AND ai.currency_id != rc.currency_id
            WHERE ai.state = 'open'
                AND am2.date < %s
                AND ai.id IN %s
            """, [date, date, date, tuple(self.ids)])
        return query

    @api.model
    def _get_query_for_payable_receivable(self, date):
        # /!\ NOTE: This Query needs improvement this is considering that an
        # invoice will always bear one payable/receivable line.
        # /!\ NOTE: Invoice created at `date` will not be included. Why?
        # Because it does not make sense to reevaluate something that I just
        # created on that date. It is the mindset that on that date the rate
        # does not vary.
        # /!\ NOTE: We will use the move_id.date in the invoice which is the
        # actual accounting date.
        # pylint:disable=duplicate-code
        query = self._cr.mogrify(
            """
            SELECT
                ai.id,
                aml.account_id,
                aml.partner_id,
                ((aml.amount_currency * (
                    COALESCE((
                    SELECT r.rate FROM res_currency_rate r
                    WHERE r.currency_id = aml.company_currency_id AND
                        r.name <= %s AND (
                            r.company_id IS NULL
                            OR r.company_id = aml.company_id)
                    ORDER BY r.company_id, r.name
                    DESC LIMIT 1), 1) /
                    COALESCE((
                    SELECT r.rate FROM res_currency_rate r
                    WHERE r.currency_id = aml.currency_id AND
                        r.name <= %s AND (
                            r.company_id IS NULL
                            OR r.company_id = aml.company_id)
                    ORDER BY r.company_id, r.name
                    DESC LIMIT 1), 1))
                )::decimal(12,2) - (
                aml.balance::decimal(12,2) +
                (COALESCE((
                    SELECT SUM(aml2.balance)
                    FROM account_move_line aml2
                    INNER JOIN account_move am
                            ON am.realization_invoice_id = ai.id
                            AND aml2.move_id = am.id
                    WHERE ai.account_id = aml2.account_id
                        AND aml2.currency_id IS NOT NULL)
                    , 0))::decimal(12,2))) AS fx
            FROM account_invoice ai
            INNER JOIN account_move_line aml ON aml.move_id = ai.move_id
                AND ai.account_id = aml.account_id
                AND aml.currency_id IS NOT NULL
            INNER JOIN account_move am2 ON am2.id = ai.move_id
            INNER JOIN res_company rc ON rc.id = ai.company_id
                AND ai.currency_id != rc.currency_id
            WHERE ai.state = 'open'
                AND am2.date < %s
                AND ai.id IN %s
            """, [date, date, date, tuple(self.ids)])
        return query

    @api.model
    def _prepare_realization_entries(self, res, date):

        base_line = {
            'name': '%s - [%s]' % (res['label'], res['account_id']),
            'partner_id': res.setdefault('partner_id', False),
            'currency_id': res['currency_id'],
            'amount_currency': 0.0,
            'date': res['date'],
        }
        debit_line = base_line.copy()
        credit_line = base_line.copy()

        if res['fx'] > 0:
            debit_account_id = res['journal_id'].default_credit_account_id.id
            credit_account_id = res['account_id']
        else:
            debit_account_id = res['account_id']
            credit_account_id = res['journal_id'].default_debit_account_id.id

        debit_line.update({
            'debit': 0.0,
            'credit': abs(res['fx']),
            'account_id': debit_account_id,
        })

        credit_line.update({
            'debit': abs(res['fx']),
            'credit': 0.0,
            'account_id': credit_account_id,
        })

        return [(0, 0, debit_line), (0, 0, credit_line)]

    @api.multi
    def _remove_previous_revaluation(self, date):
        # /!\ NOTE: self includes several invoices, We are going to remove
        # their realization entries. Which ones:
        # - Only Open Invoices.
        # - Only Invoices whose Accounting Date is minor than Request Date.
        # Now of those realization that the invoices have we are going to
        # remove only those that:
        # - Are within Same Year and Month, i.e. Realization Entry Date =
        # '2018-11-20' and Realization Request Date = '2018-11-28', then
        # Realization will be removed. There should be only one realization per
        # month.
        # - Are after the Request Date, i.e. Realization Entry Date =
        # '2018-12-15' and Realization Request Date = '2018-11-28', then
        # Realization will be removed.

        move_ids = (
            self.filtered(lambda x: x.state == 'open' and (x.date or x.date_invoice) < date)  # noqa
            .mapped('realization_move_ids')
            .filtered(lambda x:
                      (x.date.month, x.date.year) == (date.month, date.year) or
                      x.date >= date))

        if not move_ids:
            move_ids = (
            self.filtered(lambda x: x.state == 'open' and (x.date or x.date_invoice) < date)  # noqa
            .mapped('realization_move_ids')
            .filtered(lambda x:x.date <= date))

            move_line_ids = (move_ids.mapped('line_ids').filtered(lambda x:x.reconciled == True))
            move_ids = move_line_ids.mapped('move_id')

        move_ids.mapped('line_ids').remove_move_reconcile()
        move_ids.button_cancel()

        for m in move_ids:
            if m.not_delete_to_realization == False:
                m.unlink()
        return

    @api.multi
    def create_realization_entries(self, date):
        _logger.info('Entering method `create_realization_entries`')
        if not self.ids:
            return

        date = date if date else fields.Date.today()
        if isinstance(date, str):
            date = fields.Date.to_date(date)

        self._remove_previous_revaluation(date)

        query = self._get_query_for_payable_receivable(date)
        
        query += self._get_query_for_taxes(date)

        _logger.info('Beginning Query Execution `create_realization_entries`')
        self._cr.execute(query)
        _logger.info('Ending Query Execution `create_realization_entries`')

        dict_vals = {}
        for res in self._cr.dictfetchall():
            inv = self.with_context(prefetch_fields=False).browse(res['id'])
            rounding = inv.company_id.currency_id.rounding

            # /!\ NOTE: some caching could be needed here
            if float_is_zero(res['fx'], precision_rounding=rounding):
                continue

            res['label'] = _('Monetary Revaluation at %s on %s') % (
                fields.Date.to_string(date), inv.move_id.name)
            res['journal_id'] = (
                inv.company_id.realization_journal_id or
                inv.company_id.currency_exchange_journal_id)
            res['currency_id'] = inv.currency_id.id
            res['date'] = date

            vals = self._prepare_realization_entries(res, date)

            if not dict_vals.get(res['id']):
                dict_vals[res['id']] = {
                    'journal_id': res['journal_id'].id,
                    'ref': res['label'],
                    'date': res['date'],
                    'realization_invoice_id': inv.id,
                    'line_ids': [],
                }

            dict_vals[res['id']]['line_ids'] += vals
            not_delete = True
            date_value = date
            date_value = date_value.replace(day = monthrange(date_value.year, date_value.month)[1])

            if date == date_value:
                dict_vals[res['id']]['not_delete_to_realization'] = not_delete

        _logger.info('Creating Entries `create_realization_entries`')
        for base_move in dict_vals.values():
            self.env['account.move'].create(base_move)

        _logger.info('Exiting method `create_realization_entries`')
        return

    @api.model
    def cron_monthly_realization(self):
        """This method will check if today is the first day of the month and
        then it will run the realization process with yesterday's date"""

        date = fields.Date.today()
        if date.day != 1:
            _logger.info('Not yet 1st of month `cron_monthly_realization`')
            return False

        date -= timedelta(days=1)

        _logger.info('Processing 1st of month `cron_monthly_realization`')
        self.process_realization(date)
        return True

    @api.model
    def process_realization(self, date=None):
        _logger.info('Entering method `process_realization`')
        # /!\ NOTE: Maybe this is not running in Odoo Enterprise Edition
        if "run_update_currency" in dir(self.env['res.company']):
            self.env['res.company'].run_update_currency()

        date = date if date else fields.Date.today()
        if isinstance(date, str):
            date = fields.Date.to_date(date)

        # /!\ NOTE: Optimize search with a query where company_id.currency_id
        # != invoice.currency_id
        self._cr.execute(
            """
            SELECT ai.id
            FROM account_invoice ai
            INNER JOIN res_company rc ON rc.id = ai.company_id
            INNER JOIN account_move am ON am.id = ai.move_id
            WHERE ai.state = 'open'
            AND ai.currency_id != rc.currency_id
            AND am.date < %s
            """, (date,))
        invoice_ids = [x[0] for x in self._cr.fetchall()]
        if not invoice_ids:
            _logger.info('No invoices found - method `process_realization`')
            return
        (self
         .with_context(prefetch_fields=False)
         .browse(invoice_ids)
         .create_realization_entries(date))
        _logger.info('Exiting method `process_realization`')
        return

    @api.multi
    def action_cancel(self):
        move_ids = self.mapped('realization_move_ids')
        if not move_ids:
            return super(AccountInvoice, self).action_cancel()
        move_ids.mapped('line_ids').remove_move_reconcile()
        move_ids.button_cancel()
        move_ids.unlink()
        return super(AccountInvoice, self).action_cancel()
