"""Regression checks for writes, reply routing, and financial precision."""

import unittest
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from pyrogram import StopPropagation

from tests import support

from app import FireflyParserBot
from app.firefly.firefly import FireflyApi
from app.models.parsed_transaction_message import ParsedTransactionMessage
from app.plugins import incoming_money, transaction_customization as customization
from app.plugins import transaction_parser, transaction_utils, vendors
from app.plugins.foreignsum import fetch_and_process_transactions, generate_and_send_csv
from app.plugins import foreignsum
from tests.test_storage import message


class RegressionTests(unittest.TestCase):


    def test_new_transaction_preserves_other_users_income_flows(self):
        with patch.object(FireflyParserBot, '_incoming_money_contexts', {1: {}, 2: {'state': 'confirm'}}, create=True):
            transaction_parser.clear_reply_contexts(1)
            self.assertEqual(FireflyParserBot._incoming_money_contexts, {2: {'state': 'confirm'}})

    def test_json_amount_retains_decimal_precision(self):
        completion = MagicMock()
        completion.choices = [SimpleNamespace(message=SimpleNamespace(content='''{
            "date":"01/01/26", "time":"12:00", "currency":"MVR",
            "amount":123456789012345.67, "location":"Shop", "reference_no":"x"
        }'''))]
        result = transaction_utils.parse_completion(
            completion, ('date', 'time', 'currency', 'amount', 'location', 'reference_no')
        )
        self.assertEqual(result.details['amount'], Decimal('123456789012345.67'))

    def test_unreadable_receipt_returns_extraction_error(self):
        with patch.object(transaction_utils, 'encode_image', side_effect=OSError('Unreadable')):
            result = transaction_utils.extract_transaction_details_from_image('missing.jpg')
        self.assertIsNone(result.details)
        self.assertIn('Unreadable', result.error)


    def test_receipt_attachment_targets_journal_and_local_currency(self):
        transaction = ParsedTransactionMessage('01/01/26', '12:00', 'MVR', '10', 'Shop', 'x')
        response = {'data': {'id': '90', 'attributes': {
            'transactions': [{'transaction_journal_id': '123'}],
        }}}
        with patch.object(transaction, 'get_similar_account', return_value='Shop'), patch(
            'app.models.parsed_transaction_message.FireflyApi'
        ) as api_type, patch.object(transaction, '_attach_image_to_transaction') as attach:
            api_type.return_value.post_json.return_value = response
            transaction.create_transaction_on_firefly(is_receipt=True, image_path='receipt.jpg')
        attach.assert_called_once_with(api_type.return_value, '123', 'receipt.jpg')
        payload = api_type.return_value.post_json.call_args.kwargs['payload']
        self.assertEqual(payload['transactions'][0]['currency_code'], 'MVR')

    def test_vendor_without_account_id_falls_back_to_name(self):
        transaction = ParsedTransactionMessage('01/01/26', '12:00', 'MVR', '10', 'shop', 'x')
        with patch('app.models.parsed_transaction_message.VendorsDB') as db:
            db.return_value.find_vendor_by_name_or_alias.return_value = {'name': 'Shop', 'firefly_account_id': None}
            self.assertEqual(transaction.get_similar_account(default_name=True), 'Shop')
            self.assertIsNone(transaction.get_similar_account())

    def test_multiple_splits_are_rejected_before_partial_edit(self):
        with self.assertRaisesRegex(ValueError, 'multiple splits'):
            customization.get_inner_transaction({'data': {'attributes': {
                'transactions': [{'amount': '10'}, {'amount': '20'}],
            }}})

    def test_amount_updates_preserve_journal_and_foreign_currency(self):
        payload = customization.transaction_update_payload({
            'transaction_journal_id': '12', 'foreign_currency_id': '3',
            'foreign_currency_code': 'USD',
        }, {'amount': '15.42', 'foreign_amount': '1.00'})
        update = payload['transactions'][0]
        self.assertEqual(update['transaction_journal_id'], '12')
        self.assertEqual(update['foreign_currency_code'], 'USD')
        with self.assertRaises(ValueError):
            customization.money(Decimal('0.001'))
        self.assertEqual(customization.money(Decimal('5.5'), 0), Decimal('6'))

    def test_foreign_summary_converts_source_currency_and_skips_nan(self):
        api = MagicMock()
        api.get_all_pages.return_value = [{'attributes': {'transactions': [{
            'date': '2026-01-01', 'description': 'Shop', 'currency_code': 'USD',
            'amount': '10', 'foreign_currency_code': 'EUR', 'foreign_amount': '9',
        }, {
            'foreign_currency_code': 'USD', 'foreign_amount': 'NaN', 'amount': '1',
        }]}}]
        result = fetch_and_process_transactions(api, datetime(2026, 1, 1), datetime(2026, 1, 31))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].local_amount, Decimal('154.20'))
        self.assertEqual(result[0].usd_equivalent, Decimal('10'))


class HandlerRegressionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        for contexts in customization.REPLY_CONTEXTS.values():
            contexts.clear()
        for contexts in vendors.VENDOR_CONTEXTS.values():
            contexts.clear()
        incoming_money._incoming_money_contexts().clear()

    async def test_empty_foreign_summary_stops_without_reporting_failure(self):
        msg = message(text='/foreignsum Jan 2026')
        status = AsyncMock()
        msg.reply.return_value = status
        msg.stop_propagation.side_effect = StopPropagation
        with patch.object(foreignsum, 'clear_vendor_contexts', new_callable=AsyncMock), patch.object(
            foreignsum, 'fetch_and_process_transactions', return_value=[]
        ):
            with self.assertRaises(StopPropagation):
                await foreignsum.foreign_sum(None, msg)
        status.edit_text.assert_awaited_once()
        self.assertIn('No foreign transactions', status.edit_text.call_args.args[0])

    async def test_invalid_deduction_keeps_prompt_and_propagation_signal(self):
        customization.set_reply_context('deduct_amount', 1, {
            'user_id': 1, 'reply_message_id': 10, 'message_id': 30,
            'transaction_id': '9', 'current_amount': Decimal('10'),
        })
        msg = message(text='15')
        msg.stop_propagation.side_effect = StopPropagation
        client = SimpleNamespace(delete_messages=AsyncMock(), get_messages=AsyncMock())
        with patch.object(customization, 'FireflyApi') as api_type:
            api = api_type.return_value
            api.get_json.return_value = {'data': {'attributes': {'transactions': [{'amount': '10'}]}}}
            with self.assertRaises(StopPropagation):
                await customization.handle_deduct_amount_reply(client, msg)
        api.update_transaction.assert_not_called()
        client.delete_messages.assert_not_awaited()
        self.assertIsNotNone(customization.get_reply_context('deduct_amount', 1))

    async def test_nontext_prompt_replies_are_consumed_without_parsing(self):
        for kind, handler in (
            ('tag', customization.handle_add_tag_reply),
            ('update_amount', customization.handle_update_amount_reply),
            ('deduct_amount', customization.handle_deduct_amount_reply),
        ):
            with self.subTest(kind=kind):
                customization.set_reply_context(kind, 1, {'user_id': 1, 'reply_message_id': 10})
                reply = message(text=None)
                await handler(None, reply)
                reply.stop_propagation.assert_awaited_once()
                self.assertIsNotNone(customization.get_reply_context(kind, 1))
        for kind, handler in (
            ('add_alias', vendors.handle_add_alias_reply),
            ('edit_name', vendors.handle_edit_vendor_name_reply),
        ):
            vendors._set_context(kind, 1, {'user_id': 1, 'reply_message_id': 10})
            reply = message(text=None)
            await handler(None, reply)
            reply.stop_propagation.assert_awaited_once()
        incoming_money._set_context(1, {'state': 'awaiting_amount', 'reply_message_id': 10})
        reply = message(text=None)
        await incoming_money.handle_income_reply(None, reply)
        reply.stop_propagation.assert_awaited_once()


    async def test_field_update_never_writes_a_group_with_multiple_splits(self):
        callback = SimpleNamespace(message=message(), edit_message_text=AsyncMock())
        with patch.object(customization, 'FireflyApi') as api_type:
            api = api_type.return_value
            api.get_json.return_value = {'data': {'attributes': {'transactions': [{}, {}]}}}
            await customization.apply_transaction_field_update(callback, '9', 'budget_id', '1', 'Updated', 'update budget')
        api.update_transaction.assert_not_called()

    def income_callback(self):
        incoming_money._set_context(1, {
            'state': 'confirm', 'message_id': 20, 'revenue_account_id': '1',
            'asset_account_id': '2', 'amount': '10', 'description': 'Income',
            'revenue_account_name': 'Revenue', 'asset_account_name': 'Bank',
        })
        msg = message()
        msg.edit_text = AsyncMock()
        return SimpleNamespace(from_user=SimpleNamespace(id=1), message=msg, answer=AsyncMock())

    async def test_successful_income_write_cannot_be_retried_after_display_failure(self):
        callback = self.income_callback()
        callback.message.edit_text.side_effect = RuntimeError('Telegram unavailable')
        with patch.object(incoming_money, 'FireflyApi') as api_type:
            api = api_type.return_value
            api.create_incoming_transaction.return_value = {'data': {'id': '9', 'attributes': {
                'transactions': [{'amount': '10'}],
            }}}
            await incoming_money.create_income_transaction(None, callback)
            self.assertIsNone(incoming_money._get_context(1))
            await incoming_money.create_income_transaction(None, callback)
            api.create_incoming_transaction.assert_called_once()

    async def test_income_retry_reuses_transaction_date(self):
        callback = self.income_callback()
        with patch.object(incoming_money, 'FireflyApi') as api_type:
            api_type.return_value.create_incoming_transaction.side_effect = RuntimeError('Response lost')
            await incoming_money.create_income_transaction(None, callback)
            await incoming_money.create_income_transaction(None, callback)
            calls = api_type.return_value.create_incoming_transaction.call_args_list
        self.assertEqual(calls[0].kwargs['date'], calls[1].kwargs['date'])

    async def test_csv_export_uses_named_inmemory_document(self):
        msg = SimpleNamespace(reply_document=AsyncMock())
        contents = []
        async def capture(document, **kwargs):
            contents.append((document.name, document.read()))
        msg.reply_document.side_effect = capture
        await generate_and_send_csv(msg, [], datetime(2026, 1, 1), datetime(2026, 1, 31))
        self.assertTrue(contents[0][0].endswith('.csv'))
        self.assertIn(b'foreign_amount', contents[0][1])
