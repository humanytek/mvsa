from odoo import fields
from odoo.tools.pycompat import izip
from odoo.addons.account.tests.test_reconciliation import AccountingTestCase
from odoo.tests import tagged


@tagged('post_install', '-at_install')
class TestMandrake(AccountingTestCase):

    def setUp(self):
        super(TestMandrake, self).setUp()
        self.account_obj = self.env['account.account']
        self.invoice_model = self.env['account.invoice']
        self.invoice_line_obj = self.env['account.invoice.line']
        self.acc_bank_stmt_model = self.env['account.bank.statement']
        self.acc_bank_stmt_line_model = self.env['account.bank.statement.line']
        self.res_currency_model = self.registry('res.currency')
        self.rate_model = self.env['res.currency.rate']
        self.am_obj = self.env['account.move']
        self.aml_obj = self.env['account.move.line'].with_context(
            check_move_validity=False)

        self.partner_agrolait = self.env.ref("base.res_partner_2")
        self.currency_usd_id = self.env.ref("base.USD").id
        self.currency_eur_id = self.env.ref("base.EUR").id
        self.company = self.env.ref('base.main_company')
        self.product = self.env.ref("product.product_product_4")

        self.bank_journal_eur = self.env['account.journal'].create({
            'name': 'Bank EUR',
            'type': 'bank',
            'code': 'BNK69',
            'currency_id': self.currency_eur_id})
        self.bank_account_eur = self.bank_journal_eur.default_debit_account_id

        self.bank_journal_usd = self.env['account.journal'].create({
            'name': 'Bank US',
            'type': 'bank',
            'code': 'BNK68'})
        self.bank_account = self.bank_journal_usd.default_debit_account_id

        self.diff_income_account = (
            self.env['res.users'].browse(self.env.uid)
            .company_id.income_currency_exchange_account_id)
        self.diff_expense_account = (
            self.env['res.users'].browse(self.env.uid)
            .company_id.expense_currency_exchange_account_id)

        self.inbound_payment_method = (
            self.env['account.payment.method'].create({
                'name': 'inbound',
                'code': 'IN',
                'payment_type': 'inbound',
            }))

        self.equity_account = self.account_obj.create({
            'name': 'EQT',
            'code': 'EQT',
            'user_type_id':
            self.env.ref('account.data_account_type_equity').id,
            'company_id': self.company.id,
        })

        self.expense_account = self.account_obj.create({
            'name': 'EXP',
            'code': 'EXP',
            'user_type_id':
            self.env.ref('account.data_account_type_expenses').id,
            'company_id': self.company.id,
        })
        # cash basis intermediary account
        self.tax_waiting_account = self.account_obj.create({
            'name': 'TAX_WAIT',
            'code': 'TWAIT',
            'user_type_id':
            self.env.ref('account.data_account_type_current_liabilities').id,
            'reconcile': True,
            'company_id': self.company.id,
        })
        # cash basis final account
        self.tax_final_account = self.account_obj.create({
            'name': 'TAX_TO_DEDUCT',
            'code': 'TDEDUCT',
            'user_type_id':
            self.env.ref('account.data_account_type_current_assets').id,
            'company_id': self.company.id,
        })
        self.tax_base_amount_account = self.account_obj.create({
            'name': 'TAX_BASE',
            'code': 'TBASE',
            'user_type_id':
            self.env.ref('account.data_account_type_current_assets').id,
            'company_id': self.company.id,
        })

        # Journals
        self.purchase_journal = self.env['account.journal'].create({
            'name': 'purchase',
            'code': 'PURCH',
            'type': 'purchase',
        })

        self.cash_basis_journal = self.company.tax_cash_basis_journal_id
        self.fx_journal = self.company.currency_exchange_journal_id

        # Tax Cash Basis
        self.tax_cash_basis = self.env['account.tax'].create({
            'name': 'cash basis 16%',
            'type_tax_use': 'purchase',
            'company_id': self.company.id,
            'amount': 16,
            'account_id': self.tax_waiting_account.id,
            'tax_exigibility': 'on_payment',
            'cash_basis_account_id': self.tax_final_account.id,
            'cash_basis_base_account_id': self.tax_base_amount_account.id,
        })

        self.nov_21 = fields.Date.to_date('2018-11-21')
        self.nov_29 = fields.Date.to_date('2018-11-29')
        self.nov_30 = fields.Date.to_date('2018-11-30')
        self.dec_20 = fields.Date.to_date('2018-12-20')
        self.dec_31 = fields.Date.to_date('2018-12-31')
        self.jan_01 = fields.Date.to_date('2019-01-01')

        self.delete_journal_data()

        self.user_billing = self.env['res.users'].with_context(no_reset_password=True).create({  # noqa
            'name': 'User billing mx',
            'login': 'mx_billing_user',
            'email': 'mx_billing_user@yourcompany.com',
            'company_id': self.company.id,
            'groups_id': [(6, 0, [self.ref('account.group_account_invoice')])]
        })

        self.register_payments_model = self.env['account.register.payments']
        self.payment_method_manual_out = self.env.ref(
            'account.account_payment_method_manual_out')
        self.payment_method_manual_in = self.env.ref(
            'account.account_payment_method_manual_in')

        self.env.user.company_id.write({'currency_id': self.ref('base.MXN')})

        self.create_rates()

    def delete_journal_data(self):
        """Delete journal data
        delete all journal-related data, so a new currency can be set.
        """

        # 1. Reset to draft invoices and moves, so some records may be deleted
        company = self.company
        moves = self.am_obj.search(
            [('company_id', '=', company.id)])
        moves.write({'state': 'draft'})
        invoices = self.invoice_model.search([('company_id', '=', company.id)])
        invoices.write({'state': 'draft', 'move_name': False})

        # 2. Delete related records
        models_to_clear = [
            'account.move.line', 'account.invoice',
            'account.payment', 'account.bank.statement', 'res.currency.rate']
        for model in models_to_clear:
            records = self.env[model].search([('company_id', '=', company.id)])
            records.unlink()
        self.am_obj.search([]).unlink()

    def create_rates(self):
        dates = (self.nov_21, self.nov_29, self.nov_30, self.dec_20,
                 self.dec_31, self.jan_01)

        rates = (20.1550, 20.4977, 20.4108, 20.1277, 19.6829, 19.6566)
        for name, rate in izip(dates, rates):
            self.rate_model.create({
                'currency_id': self.currency_eur_id,
                'company_id': self.company.id,
                'name': name,
                'rate': 1/rate})

    def create_payment(self, invoice, pay_date, amount, journal):
        payment_method_id = self.payment_method_manual_out.id
        if invoice.type == 'in_invoice':
            payment_method_id = self.payment_method_manual_in.id

        ctx = {'active_model': 'account.invoice', 'active_ids': [invoice.id]}
        currency = journal.currency_id or self.company.currency_id
        register_payments = self.register_payments_model.with_context(
            ctx).create({
                'payment_date': pay_date,
                'payment_method_id': payment_method_id,
                'journal_id': journal.id,
                'currency_id': currency.id,
                'communication': invoice.number,
                'amount': amount,
            })

        return register_payments.create_payments()

    def create_account(self, code, name, user_type_id=False):
        """This account is created to use like cash basis account and only
        it will be filled when there is payment
        """
        account_ter = self.account_model.create({
            'name': name,
            'code': code,
            'user_type_id': user_type_id or self.user_type_id.id,
        })
        return account_ter

    def create_invoice(
            self, amount, date_invoice, inv_type='out_invoice',
            currency_id=None):
        if currency_id is None:
            currency_id = self.usd.id
        invoice = self.invoice_model.with_env(
            self.env(user=self.user_billing)).create({
                'partner_id': self.partner_agrolait.id,
                'type': inv_type,
                'currency_id': currency_id,
                'date_invoice': date_invoice,
            })

        self.create_invoice_line(invoice, amount)
        invoice.invoice_line_ids.write(
            {'invoice_line_tax_ids': [(6, None, [self.tax_cash_basis.id])]})

        invoice.refresh()

        # validate invoice
        invoice.compute_taxes()
        invoice.action_invoice_open()

        return invoice

    def create_invoice_line(self, invoice_id, price_unit):
        self.product.sudo().write({'default_code': 'PR01'})
        invoice_line = self.invoice_line_obj.new({
            'product_id': self.product.id,
            'invoice_id': invoice_id,
            'quantity': 1,
        })
        invoice_line._onchange_product_id()
        invoice_line_dict = invoice_line._convert_to_write({
            name: invoice_line[name] for name in invoice_line._cache})
        invoice_line_dict['price_unit'] = price_unit
        self.invoice_line_obj.create(invoice_line_dict)

    def test_001_create(self):

        cash_am_ids = self.am_obj.search(
            [('journal_id', '=', self.cash_basis_journal.id)])

        self.assertEquals(
            len(cash_am_ids), 0, 'There should be no journal entry')

        invoice_id = self.create_invoice(
            5301, self.nov_21.strftime('%Y-%m-%d'),
            inv_type='in_invoice',
            currency_id=self.currency_eur_id)

        self.create_payment(
            invoice_id, self.dec_20, 6149.16, self.bank_journal_eur)

        cash_am_ids = self.am_obj.search(
            [('journal_id', '=', self.cash_basis_journal.id)])

        self.assertEquals(
            len(cash_am_ids), 1, 'There should be One journal entry')

        self.assertEquals(
            invoice_id.realization_move_ids.date, self.dec_20,
            'Wrong Realization entry date')

        self.assertEquals(
            len(invoice_id.realization_move_ids), 1,
            'There should be One Realization entry')

    def test_002_create(self):
        """ Test 002
        Having issued an invoice at date Nov-21-2018 as:

        Accounts         Amount Currency         Debit(EUR)       Credit(EUR)
        ---------------------------------------------------------------------
        Expenses            5,301.00 USD         106,841.65              0.00
        Taxes                 848.16 USD          17,094.66              0.00
            Payables       -6,149.16 USD               0.00        123,936.31

        On Nov-30-2018 user issues an FX Journal Entry as required by law:

        Accounts         Amount Currency         Debit(EUR)       Credit(EUR)
        ---------------------------------------------------------------------
        FX Losses               0.00 USD           1,570.91             0.00
            Payables            0.00 USD               0.00         1,570.91

        On Dec-20-2018 user issues an FX Journal Entry as payment is done:

        Accounts         Amount Currency         Debit(EUR)       Credit(EUR)
        ---------------------------------------------------------------------
        Payables                0.00 USD           1,740.54             0.00
            FX Gains            0.00 USD               0.00         1,740.54
        """

        cash_am_ids = self.am_obj.search(
            [('journal_id', '=', self.cash_basis_journal.id)])

        self.assertEquals(
            len(cash_am_ids), 0, 'There should be no journal entry')

        invoice_id = self.create_invoice(
            5301, self.nov_21.strftime('%Y-%m-%d'),
            inv_type='in_invoice',
            currency_id=self.currency_eur_id)

        # /!\ NOTE: No realization entries must be created at this date
        invoice_id.create_realization_entries('2000-01-01')
        self.assertEquals(
            invoice_id.realization_move_ids_nbr, 0,
            'There should be no Realization entry')

        invoice_id.create_realization_entries('2000-01-01')
        self.assertEquals(
            invoice_id.realization_move_ids_nbr, 0,
            'There should be no Realization entry')

        invoice_id.create_realization_entries(self.nov_30)
        self.assertEquals(
            len(invoice_id.realization_move_ids), 1,
            'There should be One Realization entry')

        action = invoice_id.action_view_realization_move()
        self.assertEquals(
            action.get('res_id'), invoice_id.realization_move_ids[0].id,
            'There should be One Realization entry')

        pay_vals = self.create_payment(
            invoice_id, self.dec_20, 6149.16, self.bank_journal_eur)
        self.assertEquals(
            len(invoice_id.realization_move_ids), 2,
            'There should be Two Realization entries')

        action = invoice_id.action_view_realization_move()
        self.assertEquals(
            action.get('domain'),
            [('id', 'in', invoice_id.realization_move_ids.ids)],
            'There should be Two Realization entries')

        self.assertEquals(
            min(invoice_id.mapped('realization_move_ids.date')), self.nov_30,
            'Wrong Realization entry date')
        self.assertEquals(
            max(invoice_id.mapped('realization_move_ids.date')), self.dec_20,
            'Wrong Realization entry date')

        aml_nov_30 = (
            invoice_id
            .mapped('realization_move_ids.line_ids')
            .filtered(
                lambda x:
                x.account_id.internal_type in ('receivable', 'payable') and
                x.date == self.nov_30))
        self.assertEquals(
            aml_nov_30.credit, 1570.91, 'Wrong Credit on Reevaluation')

        aml_dec_20 = (
            invoice_id
            .mapped('realization_move_ids.line_ids')
            .filtered(
                lambda x:
                x.account_id.internal_type in ('receivable', 'payable') and
                x.date == self.dec_20))
        self.assertEquals(
            aml_dec_20.debit, 1740.54, 'Wrong Debit on Reevaluation')

        pay_aml_dec_20 = (
            self.env['account.payment'].browse(pay_vals.get('res_id'))
            .move_line_ids.filtered(
                lambda x:
                x.account_id.internal_type in ('receivable', 'payable') and
                x.date == self.dec_20))
        self.assertEquals(
            pay_aml_dec_20.debit, 123767.89, 'Wrong Debit on Reevaluation')

        inv_aml_nov_21 = (
            invoice_id.mapped('move_id.line_ids')
            .filtered(
                lambda x:
                x.account_id.internal_type in ('receivable', 'payable') and
                x.date == self.nov_21))
        self.assertEquals(
            inv_aml_nov_21.full_reconcile_id, aml_nov_30.full_reconcile_id,
            'Reconciliations shall be equal - FX 01')
        self.assertEquals(
            inv_aml_nov_21.full_reconcile_id, aml_dec_20.full_reconcile_id,
            'Reconciliations shall be equal - FX 02')
        self.assertEquals(
            inv_aml_nov_21.full_reconcile_id, pay_aml_dec_20.full_reconcile_id,
            'Reconciliations shall be equal - Payment')

        cash_am_ids = self.am_obj.search(
            [('journal_id', '=', self.cash_basis_journal.id)])

        self.assertEquals(
            len(cash_am_ids), 1, 'There should be One journal entry')

    def test_003_create(self):

        cash_am_ids = self.am_obj.search(
            [('journal_id', '=', self.cash_basis_journal.id)])

        self.assertEquals(
            len(cash_am_ids), 0, 'There should be no journal entry')

        invoice_id = self.create_invoice(
            5301, self.nov_21.strftime('%Y-%m-%d'),
            inv_type='in_invoice',
            currency_id=self.currency_eur_id)

        invoice_id.create_realization_entries(self.nov_30)
        self.assertEquals(
            len(invoice_id.realization_move_ids), 1,
            'There should be One Realization entry')
        self.assertEquals(
            invoice_id.mapped('realization_move_ids.date')[0], self.nov_30,
            'Dates should be equal')

        invoice_id.mapped('realization_move_ids.journal_id').sudo().write({
            'update_posted': True})

        invoice_id.create_realization_entries(self.nov_29)
        self.assertEquals(
            len(invoice_id.realization_move_ids), 1,
            'There should be One Realization entry')
        self.assertEquals(
            invoice_id.mapped('realization_move_ids.date')[0], self.nov_29,
            'Dates should be equal')

        aml_nov_29 = (
            invoice_id
            .mapped('realization_move_ids.line_ids')
            .filtered(
                lambda x:
                x.account_id.internal_type in ('receivable', 'payable') and
                x.date == self.nov_29))

        invoice_id.create_realization_entries('2018-11-01')
        self.assertTrue(
            aml_nov_29.exists(),
            'Realization on Date Previous to Accounting Date on the Invoice is not possible')  # noqa

    def test_004_create(self):

        cash_am_ids = self.am_obj.search(
            [('journal_id', '=', self.cash_basis_journal.id)])

        self.assertEquals(
            len(cash_am_ids), 0, 'There should be no journal entry')

        invoice_id = self.create_invoice(
            5301, self.nov_21.strftime('%Y-%m-%d'),
            inv_type='in_invoice',
            currency_id=self.currency_eur_id)

        invoice_id.create_realization_entries(self.nov_30)
        self.assertEquals(
            len(invoice_id.realization_move_ids), 1,
            'There should be One Realization entry')
        self.assertEquals(
            invoice_id.mapped('realization_move_ids.date')[0], self.nov_30,
            'Dates should be equal')

    def test_005_create(self):

        cash_am_ids = self.am_obj.search(
            [('journal_id', '=', self.cash_basis_journal.id)])

        self.assertEquals(
            len(cash_am_ids), 0, 'There should be no journal entry')

        invoice_id = self.create_invoice(
            5301, self.nov_21.strftime('%Y-%m-%d'),
            inv_type='in_invoice',
            currency_id=self.currency_eur_id)

        invoice_id.process_realization('2018-11-30')
        self.assertEquals(
            len(invoice_id.realization_move_ids), 1,
            'There should be One Realization entry')
        self.assertEquals(
            invoice_id.mapped('realization_move_ids.date')[0], self.nov_30,
            'Dates should be equal')

        invoice_id.journal_id.sudo().write({'update_posted': True})
        invoice_id.mapped('realization_move_ids.journal_id').sudo().write({
            'update_posted': True})

        invoice_id.action_cancel()
        self.assertEquals(
            len(invoice_id.realization_move_ids), 0,
            'There should be No Realization entries')

    def test_006_create(self):

        cash_am_ids = self.am_obj.search(
            [('journal_id', '=', self.cash_basis_journal.id)])

        self.assertEquals(
            len(cash_am_ids), 0, 'There should be no journal entry')

        invoice_id = self.create_invoice(
            5301, self.nov_21.strftime('%Y-%m-%d'),
            inv_type='in_invoice',
            currency_id=self.currency_eur_id)

        invoice_id.cron_monthly_realization()
        todo = 1 if fields.Date.today().day == 1 else 0
        self.assertEquals(
            len(invoice_id.realization_move_ids), todo,
            'There should be %s Realization entry' % ('One' if todo else 'No'))

    def test_007_create(self):

        cash_am_ids = self.am_obj.search(
            [('journal_id', '=', self.cash_basis_journal.id)])

        self.assertEquals(
            len(cash_am_ids), 0, 'There should be no journal entry')

        invoice_id = self.create_invoice(
            5301, self.nov_21.strftime('%Y-%m-%d'),
            inv_type='in_invoice',
            currency_id=self.currency_eur_id)

        invoice_id.create_realization_entries('2018-11-21')
        self.assertEquals(
            len(invoice_id.realization_move_ids), 0,
            'On Same Day There are no Realization entries')

    def test_008_create(self):

        cash_am_ids = self.am_obj.search(
            [('journal_id', '=', self.cash_basis_journal.id)])

        self.assertEquals(
            len(cash_am_ids), 0, 'There should be no journal entry')

        invoice_id = self.create_invoice(
            5301, self.nov_21.strftime('%Y-%m-%d'),
            inv_type='in_invoice',
            currency_id=self.currency_eur_id)

        self.invoice_model.create_realization_entries(self.nov_30)
        fx_am_ids = self.am_obj.search(
            [('journal_id', '=', self.fx_journal.id)])

        self.assertEquals(
            len(fx_am_ids), 0,
            'On Empty Object does not create Realization entries')

        self.assertEquals(
            len(invoice_id.realization_move_ids), 0,
            'There should be No Realization entries')

    def test_101_account_realization(self):
        """ - Test 101
        Company's Currency EUR

        Having made a bank deposit at date Nov-21-2018 as:

        Accounts         Amount Currency         Debit(EUR)       Credit(EUR)
        ---------------------------------------------------------------------
        Bank                6,149.16 USD         123,936.31              0.00
            Equity         -6,149.16 USD               0.00        123,936.31

        On Nov-30-2018 user issues an FX Journal Entry as:

        Accounts         Amount Currency         Debit(EUR)       Credit(EUR)
        ---------------------------------------------------------------------
        Bank                    0.00 USD           1.572.12             0.00
            FX Gains            0.00 USD               0.00         1.572.12

        So Bank balance at November 30th is: EUR 125,508.43 = USD 6,149.16

        On Dec-20-2018 user issues an FX Journal Entry as:

        Accounts         Amount Currency         Debit(EUR)       Credit(EUR)
        ---------------------------------------------------------------------
        FX Losses               0.00 USD           1.740.54             0.00
            Bank                0.00 USD               0.00         1.740.54

        So Bank balance at December 20th is: EUR 123,767.89 = USD 6,149.16
        """

        company = self.env.ref('base.main_company')
        company.country_id = self.ref('base.us')
        company.tax_cash_basis_journal_id = self.cash_basis_journal

        # Bank Deposit
        bank_move = self.am_obj.create({
            'date': self.nov_21,
            'name': 'Bank Deposit',
            'journal_id': self.bank_journal_eur.id,
        })

        self.aml_obj.create({
            'move_id': bank_move.id,
            'name': 'Equity Item',
            'account_id': self.equity_account.id,
            'credit': 123936.31,
            'amount_currency': -6149.16,
            'currency_id': self.currency_eur_id,
        })
        self.aml_obj.create({
            'move_id': bank_move.id,
            'name': 'Bank Deposit',
            'account_id': self.bank_account_eur.id,
            'debit': 123936.31,
            'amount_currency': 6149.16,
            'currency_id': self.currency_eur_id,
        })
        bank_move.post()

        aml_ids = self.aml_obj.search(
            [('account_id', '=', self.bank_account_eur.id)])

        self.assertEquals(
            sum(aml_ids.mapped('balance')), 123936.31,
            'Incorrect Balance for Account')

        self.assertEquals(
            sum(aml_ids.mapped('amount_currency')), 6149.16,
            'Incorrect Balance for Account')

        self.account_obj.process_realization('2018-11-30')
        self.assertEquals(
            self.bank_account_eur.realization_move_ids_nbr, 0,
            'There should be no journal entry')

        self.account_obj.create_realization_entries(self.nov_30)
        self.assertEquals(
            self.bank_account_eur.realization_move_ids_nbr, 0,
            'There should be no journal entry')

        self.bank_account_eur.write({'realizable_account': True})
        self.bank_account_eur.create_realization_entries(self.nov_30)

        self.assertEquals(
            self.bank_account_eur.realization_move_ids_nbr, 1,
            'There should be One journal entry')

        action = self.bank_account_eur.action_view_realization_move()
        self.assertEquals(
            action.get('res_id'),
            self.bank_account_eur.realization_move_ids[0].id,
            'There should be One Realization entry')

        rev_aml_ids = (
            self.bank_account_eur.realization_move_ids
            .mapped('line_ids')
            .filtered(lambda x: x.account_id == self.bank_account_eur))

        self.assertEquals(
            sum(rev_aml_ids.mapped('debit')), 1572.12,
            'Incorrect Balance for Account')

        aml_ids = self.aml_obj.search(
            [('account_id', '=', self.bank_account_eur.id)])

        self.assertEquals(
            sum(aml_ids.mapped('balance')), 125508.43,
            'Incorrect Balance for Reevaluated Account')

        self.assertEquals(
            sum(aml_ids.mapped('amount_currency')), 6149.16,
            'Incorrect Balance for Account')

        self.bank_account_eur.create_realization_entries(self.dec_20)

        self.assertEquals(
            self.bank_account_eur.realization_move_ids_nbr, 2,
            'There should be Two journal entries')

        rev_aml_ids = (
            self.bank_account_eur.realization_move_ids
            .mapped('line_ids')
            .filtered(lambda x: x.account_id == self.bank_account_eur))

        self.assertEquals(
            sum(rev_aml_ids.mapped('credit')), 1740.54,
            'Incorrect Balance for Account')

        aml_ids = self.aml_obj.search(
            [('account_id', '=', self.bank_account_eur.id)])

        self.assertEquals(
            sum(aml_ids.mapped('balance')), 123767.89,
            'Incorrect Balance for Reevaluated Account')

        self.assertEquals(
            sum(aml_ids.mapped('amount_currency')), 6149.16,
            'Incorrect Balance for Account')

    def test_102_account_realization(self):
        """ - Test 102
        Company's Currency EUR

        Having made a bank deposit at date Nov-21-2018 as:

        Accounts         Amount Currency         Debit(EUR)       Credit(EUR)
        ---------------------------------------------------------------------
        Bank                6,149.16 USD         123,936.31              0.00
            Equity         -6,149.16 USD               0.00        123,936.31

        On Nov-30-2018 user issues an FX Journal Entry as:

        Accounts         Amount Currency         Debit(EUR)       Credit(EUR)
        ---------------------------------------------------------------------
        Bank                    0.00 USD           1.572.12             0.00
            FX Gains            0.00 USD               0.00         1.572.12

        So Bank balance at November 30th is: EUR 125,508.43 = USD 6,149.16

        On Dec-20-2018 user issues an FX Journal Entry as:

        Accounts         Amount Currency         Debit(EUR)       Credit(EUR)
        ---------------------------------------------------------------------
        FX Losses               0.00 USD           1.740.54             0.00
            Bank                0.00 USD               0.00         1.740.54

        So Bank balance at December 20th is: EUR 123,767.89 = USD 6,149.16
        """

        company = self.env.ref('base.main_company')
        company.country_id = self.ref('base.us')
        company.tax_cash_basis_journal_id = self.cash_basis_journal
        self.bank_account_eur.write({'realizable_account': True})

        # Bank Deposit
        bank_move = self.am_obj.create({
            'date': self.nov_21,
            'name': 'Bank Deposit',
            'journal_id': self.bank_journal_eur.id,
        })

        self.aml_obj.create({
            'move_id': bank_move.id,
            'name': 'Equity Item',
            'account_id': self.equity_account.id,
            'credit': 123936.31,
            'amount_currency': -6149.16,
            'currency_id': self.currency_eur_id,
        })
        self.aml_obj.create({
            'move_id': bank_move.id,
            'name': 'Bank Deposit',
            'account_id': self.bank_account_eur.id,
            'debit': 123936.31,
            'amount_currency': 6149.16,
            'currency_id': self.currency_eur_id,
        })
        bank_move.post()

        aml_ids = self.aml_obj.search(
            [('account_id', '=', self.bank_account_eur.id)])

        self.assertEquals(
            sum(aml_ids.mapped('balance')), 123936.31,
            'Incorrect Balance for Account')

        self.assertEquals(
            sum(aml_ids.mapped('amount_currency')), 6149.16,
            'Incorrect Balance for Account')

        self.account_obj.process_realization(self.nov_30)

        self.assertEquals(
            self.bank_account_eur.realization_move_ids_nbr, 1,
            'There should be One journal entry')

        rev_aml_ids = (
            self.bank_account_eur.realization_move_ids
            .mapped('line_ids')
            .filtered(lambda x: x.account_id == self.bank_account_eur))

        self.assertEquals(
            sum(rev_aml_ids.mapped('debit')), 1572.12,
            'Incorrect Balance for Account')

        aml_ids = self.aml_obj.search(
            [('account_id', '=', self.bank_account_eur.id)])

        self.assertEquals(
            sum(aml_ids.mapped('balance')), 125508.43,
            'Incorrect Balance for Reevaluated Account')

        self.assertEquals(
            sum(aml_ids.mapped('amount_currency')), 6149.16,
            'Incorrect Balance for Account')

        self.account_obj.process_realization('2018-12-20')

        self.assertEquals(
            self.bank_account_eur.realization_move_ids_nbr, 2,
            'There should be Two journal entries')

        rev_aml_ids = (
            self.bank_account_eur.realization_move_ids
            .mapped('line_ids')
            .filtered(lambda x: x.account_id == self.bank_account_eur))

        self.assertEquals(
            sum(rev_aml_ids.mapped('credit')), 1740.54,
            'Incorrect Balance for Account')

        aml_ids = self.aml_obj.search(
            [('account_id', '=', self.bank_account_eur.id)])

        self.assertEquals(
            sum(aml_ids.mapped('balance')), 123767.89,
            'Incorrect Balance for Reevaluated Account')

        self.assertEquals(
            sum(aml_ids.mapped('amount_currency')), 6149.16,
            'Incorrect Balance for Account')

    def test_103_account_realization(self):

        company = self.env.ref('base.main_company')
        company.country_id = self.ref('base.us')
        company.tax_cash_basis_journal_id = self.cash_basis_journal
        self.bank_account_eur.write({'realizable_account': True})

        # Bank Deposit
        bank_move = self.am_obj.create({
            'date': self.nov_21,
            'name': 'Bank Deposit',
            'journal_id': self.bank_journal_eur.id,
        })

        self.aml_obj.create({
            'move_id': bank_move.id,
            'name': 'Equity Item',
            'account_id': self.equity_account.id,
            'credit': 123936.31,
            'amount_currency': -6149.16,
            'currency_id': self.currency_eur_id,
        })
        self.aml_obj.create({
            'move_id': bank_move.id,
            'name': 'Bank Deposit',
            'account_id': self.bank_account_eur.id,
            'debit': 123936.31,
            'amount_currency': 6149.16,
            'currency_id': self.currency_eur_id,
        })
        bank_move.post()

        self.account_obj.cron_monthly_realization()
        todo = 1 if fields.Date.today().day == 1 else 0
        am_ids = self.am_obj.search([('realization_account_id', '!=', False)])
        self.assertEquals(
            len(am_ids), todo,
            'There should be %s Realization entry' % ('One' if todo else 'No'))

    def test_104_account_realization_non_realizable_account(self):

        company = self.env.ref('base.main_company')
        company.country_id = self.ref('base.us')
        company.tax_cash_basis_journal_id = self.cash_basis_journal

        # Bank Deposit
        bank_move = self.am_obj.create({
            'date': self.nov_21,
            'name': 'Bank Deposit',
            'journal_id': self.bank_journal_usd.id,
        })

        self.aml_obj.create({
            'move_id': bank_move.id,
            'name': 'Equity Item',
            'account_id': self.equity_account.id,
            'credit': 123936.31,
        })
        self.aml_obj.create({
            'move_id': bank_move.id,
            'name': 'Bank Deposit',
            'account_id': self.bank_account_eur.id,
            'debit': 123936.31,
        })
        bank_move.post()

        aml_ids = self.aml_obj.search(
            [('account_id', '=', self.bank_account_eur.id)])

        self.assertEquals(
            sum(aml_ids.mapped('balance')), 123936.31,
            'Incorrect Balance for Account')

        self.assertEquals(
            sum(aml_ids.mapped('amount_currency')), 6149.10,
            'Incorrect Balance for Account')

        self.bank_account_eur.create_realization_entries(self.nov_30)

        self.assertEquals(
            self.bank_account_eur.realization_move_ids_nbr, 0,
            'There should be no journal entry')

    def test_009_create(self):

        invoice_id = self.create_invoice(
            5301, self.nov_21.strftime('%Y-%m-%d'),
            inv_type='in_invoice',
            currency_id=self.currency_eur_id)

        self.create_payment(
            invoice_id, self.dec_20, 6149.16, self.bank_journal_eur)

        self.assertEquals(
            invoice_id.state, 'paid', 'This invoice should be paid')

        fx_move_before = invoice_id.realization_move_ids

        invoice_id.create_realization_entries(self.dec_31)

        self.assertEquals(
            invoice_id.state, 'paid', 'This invoice should be paid')

        fx_move_after = invoice_id.realization_move_ids

        self.assertEquals(
            fx_move_after, fx_move_before,
            'Realization should not work on paid invoices')

    def test_010_create(self):

        invoice_id = self.create_invoice(
            5301, self.nov_21.strftime('%Y-%m-%d'),
            inv_type='in_invoice',
            currency_id=self.currency_eur_id)

        invoice_id.create_realization_entries(self.dec_20)
        fx_move_before = invoice_id.realization_move_ids
        fx_move_before.sudo().journal_id.write({'update_posted': True})

        invoice_id.sudo().create_realization_entries(self.dec_31)
        fx_move_after = invoice_id.realization_move_ids

        self.assertNotEqual(
            fx_move_after, fx_move_before,
            'For different rates in same month FX Journal must change')

    def test_011_create_from_wizard(self):
        """Computing account realization from wizard"""

        wizard = self.env['realization.date.wizard']

        invoice_id = self.create_invoice(
            5301, self.nov_21.strftime('%Y-%m-%d'),
            inv_type='in_invoice',
            currency_id=self.currency_eur_id)

        record = wizard.with_context(
            {'active_id': invoice_id.id,
             'active_ids': invoice_id.ids,
             'active_model': 'account.invoice'}).create(
                 {'realization_date': self.dec_20})
        record.compute_realization()

        fx_move_before = invoice_id.realization_move_ids
        fx_move_before.sudo().journal_id.write({'update_posted': True})

        record = wizard.with_context(
            {'active_id': invoice_id.id,
             'active_ids': invoice_id.ids,
             'active_model': 'account.invoice'}).create(
                 {'realization_date': self.dec_31})
        record.compute_realization()

        fx_move_after = invoice_id.realization_move_ids

        self.assertNotEqual(
            fx_move_after, fx_move_before,
            'For different rates in same month FX Journal must change')

    def test_012_create_from_wizard(self):
        """Computing account realization from wizard"""

        wizard = self.env['realization.date.wizard']

        # Bank Deposit
        bank_move = self.am_obj.create({
            'date': self.nov_21,
            'name': 'Bank Deposit',
            'journal_id': self.bank_journal_eur.id,
        })

        self.aml_obj.create({
            'move_id': bank_move.id,
            'name': 'Equity Item',
            'account_id': self.equity_account.id,
            'credit': 123936.31,
            'amount_currency': -6149.16,
            'currency_id': self.currency_eur_id,
        })
        self.aml_obj.create({
            'move_id': bank_move.id,
            'name': 'Bank Deposit',
            'account_id': self.bank_account_eur.id,
            'debit': 123936.31,
            'amount_currency': 6149.16,
            'currency_id': self.currency_eur_id,
        })
        bank_move.post()

        self.bank_account_eur.write({'realizable_account': True})

        record = wizard.with_context(
            {'active_id': self.bank_account_eur.id,
             'active_ids': self.bank_account_eur.ids,
             'active_model': 'account.account'}).create(
                 {'realization_date': self.dec_20})
        record.compute_realization()

        self.assertEquals(
            self.bank_account_eur.realization_move_ids_nbr, 1,
            'There should be One journal entry')
