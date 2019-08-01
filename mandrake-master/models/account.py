from datetime import timedelta
import logging

from odoo import models, fields, api, _

_logger = logging.getLogger(__name__)


class AccountAccount(models.Model):
    _inherit = "account.account"

    @api.depends('realization_move_ids')
    def _compute_realization_move_ids_nbr(self):
        for rec in self:
            rec.realization_move_ids_nbr = len(rec.realization_move_ids)

    realizable_account = fields.Boolean(
        help='When wizard for Monetary Realization is run this account will '
        'be considere for realization')
    realization_move_ids_nbr = fields.Integer(
        compute='_compute_realization_move_ids_nbr',
        string='# of Realization Entries',
        help='Quantity of Realization Entries this Account has')
    realization_move_ids = fields.One2many(
        'account.move',
        'realization_account_id',
        string='Realization Entries',
        readonly=True,
        help='Realization Journal Entries for this Account')

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
    def _get_query_for_accounts(self, date):
        # /|\ NOTE: Improve this part of the code
        account_ids = self.ids
        query = self._cr.mogrify(
            """
            WITH fx_table AS (SELECT
                aa.id AS id,
                aa.company_id,
                SUM(aml.amount_currency)::numeric(12,2)  AS amount_currency,
                ((SUM(aml.amount_currency) * (
                    COALESCE((
                    SELECT r.rate FROM res_currency_rate r
                    WHERE r.currency_id = rc2.currency_id AND
                        r.name <= %s AND (
                            r.company_id IS NULL
                            OR r.company_id = aa.company_id)
                    ORDER BY r.company_id, r.name
                    DESC LIMIT 1), 1) /
                    COALESCE((
                    SELECT r.rate FROM res_currency_rate r
                    WHERE r.currency_id = aa.currency_id AND
                        r.name <= %s AND (
                            r.company_id IS NULL
                            OR r.company_id = aa.company_id)
                    ORDER BY r.company_id, r.name
                    DESC LIMIT 1), 1)))::numeric(12,2) -
                SUM(aml.balance)::numeric(12,2)
                ) AS fx
            FROM account_move_line aml
            INNER JOIN account_account aa ON aml.account_id = aa.id
            INNER JOIN res_company rc2 ON aa.company_id = rc2.id
            WHERE
                aml.date <= %s AND aa.id IN %s
            GROUP BY
                rc2.currency_id, aa.company_id, aa.id)
            SELECT * FROM fx_table WHERE ABS(fx) >= 0.01
            """, [date, date, date, tuple(account_ids)])
        return query

    @api.multi
    def _remove_previous_revaluation(self, date):
        move_ids = self.mapped('realization_move_ids').filtered(
            lambda x: (x.date.month, x.date.year) == (date.month, date.year) or
            x.date >= date)
        move_ids.button_cancel()
        move_ids.unlink()
        return

    @api.multi
    def create_realization_entries(self, date):
        _logger.info('Entering method `create_realization_entries`')
        if not self.ids:
            return

        date = date if date else fields.Date.today()
        if isinstance(date, str):
            date = fields.Date.to_date(date)

        # /!\ NOTE: We want to avoid that someone bypasses the check in
        # cron-job that avoids reevaluating accounts that do not bear any
        # multi-currency journal items.
        self._cr.execute(
            """
            SELECT DISTINCT aa.id
            FROM account_account aa
            INNER JOIN res_company rc ON rc.id = aa.company_id
            INNER JOIN account_move_line aml ON aml.account_id = aa.id
            WHERE
                aa.realizable_account = TRUE
                AND aa.currency_id != rc.currency_id
                AND aa.currency_id IS NOT NULL
                AND (
                    aa.deprecated = FALSE OR
                    aa.deprecated IS NULL)
                AND aml.currency_id IS NOT NULL
                AND aml.date <= %s
                AND aa.id IN %s
            """, (date, tuple(self.ids)))
        account_ids = [x[0] for x in self._cr.fetchall()]
        if not account_ids:
            return
        self.browse(account_ids)._create_realization_entries(date)

    @api.model
    def _create_realization_entries(self, date):

        self._remove_previous_revaluation(date)

        query = self._get_query_for_accounts(date)
        _logger.info('Beginning Query Execution `_create_realization_entries`')
        self._cr.execute(query)
        _logger.info('Ending Query Execution `_create_realization_entries`')

        dict_vals = {}
        for res in self._cr.dictfetchall():
            acc = self.with_context(prefetch_fields=False).browse(res['id'])

            res['label'] = _('Monetary Revaluation at %s on [%s] %s') % (
                fields.Date.to_string(date), acc.code, acc.name)
            res['journal_id'] = (
                acc.company_id.realization_journal_id or
                acc.company_id.currency_exchange_journal_id)
            res['currency_id'] = acc.currency_id.id
            res['date'] = date
            res['account_id'] = res['id']

            vals = self.env['account.invoice']._prepare_realization_entries(res, date)  # noqa

            if not dict_vals.get(res['id']):
                dict_vals[res['id']] = {
                    'journal_id': res['journal_id'].id,
                    'ref': res['label'],
                    'date': res['date'],
                    'realization_account_id': acc.id,
                    'line_ids': [],
                }

            dict_vals[res['id']]['line_ids'] += vals

        _logger.info('Creating Entries `_create_realization_entries`')
        for base_move in dict_vals.values():
            self.env['account.move'].create(base_move)

        _logger.info('Exiting method `_create_realization_entries`')
        return

    # pylint:disable=duplicate-code
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

        self._cr.execute(
            """
            SELECT DISTINCT aa.id
            FROM account_account aa
            INNER JOIN res_company rc ON rc.id = aa.company_id
            INNER JOIN account_move_line aml ON aml.account_id = aa.id
            WHERE
                aa.realizable_account = TRUE
                AND aa.currency_id != rc.currency_id
                AND aa.currency_id IS NOT NULL
                AND (
                    aa.deprecated = FALSE OR
                    aa.deprecated IS NULL)
                AND aml.currency_id IS NOT NULL
                AND aml.date <= %s
            """, (date,))
        account_ids = [x[0] for x in self._cr.fetchall()]
        if not account_ids:
            _logger.info('No accounts found - method `process_realization`')
            return
        (self
         .with_context(prefetch_fields=False)
         .browse(account_ids)
         .create_realization_entries(date))
        _logger.info('Exiting method `process_realization`')
        return
