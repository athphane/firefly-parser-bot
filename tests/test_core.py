import json
from datetime import datetime
from decimal import Decimal
import unittest


from tests.support import FakeCompletion, TEST_CONFIG, TEST_ROOT

from app.database.vendorsdb import VendorsDB
from app import CONFIG_PATH, FIREFLY_ERROR_ON_DUPLICATE, LOG_DIR, WORKDIR
from app.firefly.firefly import FireflyApi
from app.models.parsed_transaction_message import ParsedTransactionMessage
from app.plugins.foreignsum import calculate_total_usd, fetch_and_process_transactions, parse_arguments
from app.plugins.incoming_money import _parse_amount
from app.plugins.transaction_customization import (
    discard_user_contexts,
    get_reply_context,
    get_inner_transaction,
    money,
    parse_positive_amount,
    set_reply_context,
)
from app.plugins.transaction_utils import parse_completion
from app.plugins.vendors import VENDOR_CONTEXTS, _truncate_utf8, discard_vendor_contexts, extract_aliases


class CoreLogicTests(unittest.TestCase):
    def test_runtime_paths_are_isolated(self):
        self.assertEqual(CONFIG_PATH, TEST_CONFIG)
        self.assertEqual(LOG_DIR, TEST_ROOT / "logs")
        self.assertEqual(WORKDIR, TEST_ROOT / "workdir")

    def test_completion_validation(self):
        required = ("date", "time", "currency", "amount", "location", "reference_no")
        result = parse_completion(FakeCompletion(json.dumps({
            "date": "01/01/26",
            "time": "10:00:00",
            "currency": "MVR",
            "amount": "12.50",
            "location": "Shop",
            "reference_no": "abc",
        })), required)
        self.assertIsNone(result.error)
        self.assertEqual(result.details["amount"], Decimal("12.50"))
        self.assertIsNone(parse_completion(FakeCompletion("null"), required).details)
        blank = json.loads(json.dumps(result.details, default=str))
        blank["location"] = "   "
        self.assertIsNone(parse_completion(FakeCompletion(json.dumps(blank)), required).details)

    def test_exact_amount_parsing_and_rounding(self):
        self.assertEqual(_parse_amount("1,234.50"), "1234.50")
        self.assertEqual(parse_positive_amount("1,234.50"), Decimal("1234.50"))
        self.assertEqual(money(Decimal("1.005")), Decimal("1.01"))
        for invalid in ("0", "-1", "NaN", "Infinity", "not-a-number"):
            with self.assertRaises(ValueError):
                parse_positive_amount(invalid)

    def test_firefly_pagination_does_not_mutate_params(self):
        api = object.__new__(FireflyApi)
        pages = [
            {"data": [{"id": "1"}], "meta": {"pagination": {"total_pages": 2}}},
            {"data": [{"id": "2"}], "meta": {"pagination": {"total_pages": 2}}},
        ]
        calls = []

        def fake_get(_endpoint, params):
            calls.append(dict(params))
            return pages[len(calls) - 1]

        api.get_json = fake_get
        params = {"type": "expense"}
        self.assertEqual([item["id"] for item in api.get_all_pages("accounts", params)], ["1", "2"])
        self.assertEqual(params, {"type": "expense"})
        self.assertEqual([call["page"] for call in calls], [1, 2])

        api.get_json = lambda _endpoint, _params: {"data": {}, "meta": {}}
        with self.assertRaises(RuntimeError):
            api.get_all_pages("accounts")

    def test_named_resources_use_paginated_data(self):
        api = object.__new__(FireflyApi)
        api.get_all_pages = lambda endpoint: [
            {"id": 1, "attributes": {"name": "One"}},
            {"broken": True},
            {"id": 2, "attributes": {"name": "Two"}},
        ]
        self.assertEqual(
            [(budget.id, budget.name) for budget in api.get_budgets()],
            [("1", "One"), ("2", "Two")],
        )

    def test_alias_updates_preserve_unmanaged_firefly_notes(self):
        api = object.__new__(FireflyApi)
        api.get_json = lambda endpoint: {"data": {"attributes": {
            "notes": "Keep this\n\n*START:ALIASES*\nOld\n*END:ALIASES*\nFooter",
        }}}
        captured = {}
        api.put_json = lambda endpoint, payload: captured.update(
            endpoint=endpoint, payload=payload
        )

        api.update_account_aliases("42", ["New", "Another"])

        self.assertEqual(captured["endpoint"], "accounts/42")
        self.assertIn("Keep this", captured["payload"]["notes"])
        self.assertIn("Footer", captured["payload"]["notes"])
        self.assertNotIn("Old", captured["payload"]["notes"])
        self.assertEqual(extract_aliases(captured["payload"]["notes"]), ["New", "Another"])

    def test_foreign_totals_use_decimal_and_all_pages(self):
        api = object.__new__(FireflyApi)
        api.get_all_pages = lambda _endpoint, _params: [{
            "attributes": {"transactions": [{
                "date": "2026-01-01",
                "description": "Test",
                "foreign_currency_code": "usd",
                "foreign_amount": "0.10",
                "amount": "1.542",
            }]},
        }]
        transactions = fetch_and_process_transactions(
            api, datetime(2026, 1, 1), datetime(2026, 1, 31)
        )
        self.assertEqual(calculate_total_usd(transactions), Decimal("0.10"))

    def test_vendor_normalization_aliases_and_callback_limit(self):
        self.assertEqual(VendorsDB.clean_string_for_match(None, " Café-١ "), "café١")
        self.assertEqual(
            extract_aliases("before\n*START:ALIASES*\n One \nOne\nTwo\n*END:ALIASES*"),
            ["One", "Two"],
        )
        self.assertLessEqual(len(_truncate_utf8("😀" * 30, 40).encode("utf-8")), 40)

    def test_contexts_are_isolated_by_user(self):
        set_reply_context("tag", 1, {"value": "one"})
        set_reply_context("tag", 2, {"value": "two"})
        discard_user_contexts(1)
        self.assertIsNone(get_reply_context("tag", 1))
        self.assertEqual(get_reply_context("tag", 2), {"value": "two"})
        discard_user_contexts(2)

        VENDOR_CONTEXTS["add_alias"][1] = {"value": "one"}
        VENDOR_CONTEXTS["add_alias"][2] = {"value": "two"}
        discard_vendor_contexts(1)
        self.assertNotIn(1, VENDOR_CONTEXTS["add_alias"])
        self.assertIn(2, VENDOR_CONTEXTS["add_alias"])
        discard_vendor_contexts(2)

    def test_transaction_defaults(self):
        history = {"data": [{"attributes": {"transactions": [{
            "description": "Lunch", "category_id": "4"
        }]}}]}
        self.assertEqual(
            ParsedTransactionMessage._defaults_from_transactions(history),
            ("Lunch", "4"),
        )

    def test_inner_transaction_validation(self):
        valid = {"data": {"attributes": {"transactions": [{"amount": "1"}]}}}
        self.assertEqual(get_inner_transaction(valid), {"amount": "1"})
        for malformed in ({}, {"data": {}}, {"data": {"attributes": {"transactions": []}}}):
            with self.assertRaises(ValueError):
                get_inner_transaction(malformed)

    def test_transaction_dates_rates_and_unknown_currency(self):
        transaction = ParsedTransactionMessage(
            date="2026-09-09", time="12:34", currency="usd", amount="1.005",
            location="Shop", reference_no="1",
        )
        self.assertEqual(transaction.get_date(), datetime(2026, 9, 9, 12, 34))
        self.assertEqual(transaction.local_amount(), Decimal("15.50"))
        unsupported = ParsedTransactionMessage(
            date="09/09/26", time="12:34:00", currency="GBP", amount="1",
            location="Shop", reference_no="2",
        )
        with self.assertRaises(ValueError):
            unsupported.exchange_rate()

    def test_incoming_transactions_enable_duplicate_protection(self):
        api = object.__new__(FireflyApi)
        captured = {}

        def fake_post(endpoint, payload):
            captured.update(endpoint=endpoint, payload=payload)
            return {"data": {"id": "1"}}

        api.post_json = fake_post
        api.create_incoming_transaction("1", "2", "10", "Test", "2026-01-01T00:00:00Z")
        self.assertTrue(FIREFLY_ERROR_ON_DUPLICATE)
        self.assertTrue(captured["payload"]["error_if_duplicate_hash"])

    def test_foreignsum_rejects_reversed_range(self):
        args = parse_arguments(["/foreignsum", "range", "2026-02-01", "2026-01-01"])
        self.assertIsNotNone(args.error_message)


if __name__ == "__main__":
    unittest.main()
