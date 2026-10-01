from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Union
import logging
import os

from app import (
    EXCHANGE_RATES,
    FIREFLY_DEFAULT_ACCOUNT_ID,
    FIREFLY_ERROR_ON_DUPLICATE,
    LOCAL_CURRENCY,
)
from app.database.vendorsdb import VendorsDB
from app.firefly.firefly import FireflyApi

LOGS = logging.getLogger(__name__)


class ParsedTransactionMessage:
    def __init__(
            self,
            date: str,
            time: str,
            currency: str,
            amount: str | int | float | Decimal,
            location: str,
            reference_no: str,
            card: Union[None, str] = None,
            approval_code: Union[None, str] = None,
            raw_transaction_message: Union[None, str] = None
    ):
        self.card = card
        self.date = date
        self.time = time
        self.currency = currency.strip().upper()
        try:
            self.amount = Decimal(str(amount).replace(',', ''))
        except (InvalidOperation, TypeError, ValueError) as error:
            raise ValueError("Transaction amount must be a valid number.") from error
        if not self.amount.is_finite() or self.amount <= 0:
            raise ValueError("Transaction amount must be greater than zero.")
        self.location = location
        self.approval_code = approval_code
        self.reference_no = reference_no
        self.raw_transaction_message = raw_transaction_message

    @staticmethod
    def make(data):
        return ParsedTransactionMessage(
            card=data.get('card'),
            date=data['date'],
            time=data['time'],
            currency=data['currency'],
            amount=data['amount'],
            location=data['location'],
            approval_code=data.get('approval_code'),
            reference_no=data['reference_no'],
            raw_transaction_message=data.get('raw_transaction_message')
        )

    def get_currency(self):
        return self.currency

    def is_foreign_transaction(self):
        return self.get_currency() != LOCAL_CURRENCY

    def exchange_rate(self) -> Decimal:
        try:
            return EXCHANGE_RATES[self.currency]
        except KeyError as error:
            raise ValueError(
                f"No exchange rate is configured for {self.currency}."
            ) from error

    def get_amount(self) -> Decimal:
        return self.amount

    def local_amount(self) -> Decimal:
        return (self.get_amount() * self.exchange_rate()).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP
        )

    def get_date(self):
        datetime_string = f"{self.date} {self.time}"
        formats = (
            '%d/%m/%Y %H:%M:%S',
            '%d/%m/%Y %H:%M',
            '%d/%m/%y %H:%M:%S',
            '%d/%m/%y %H:%M',
            '%Y-%m-%d %H:%M:%S',
            '%Y-%m-%d %H:%M',
        )
        for date_format in formats:
            try:
                return datetime.strptime(datetime_string, date_format)
            except ValueError:
                continue
        LOGS.error("Could not parse transaction date/time: %r", datetime_string)
        return None

    def get_similar_account(self, default_name: bool = False):
        """
        Tries to find a matching vendor account for the transaction location.

        Args:
            default_name: If True and no match is found, returns the title-cased location.

        Returns:
            The Firefly account ID if a vendor match is found,
            the title-cased location if default_name is True and no match is found,
            or None if no match is found and default_name is False.
        """
        # Log the location we're trying to match
        LOGS.info(f"Looking for vendor match: '{self.location}'")

        # Try to find a matching vendor
        vendor_db = VendorsDB()
        similar_account = vendor_db.find_vendor_by_name_or_alias(self.location)

        if similar_account is None:
            # Log that we didn't find a match
            cleaned = vendor_db.clean_string_for_match(self.location)
            LOGS.info(f"No vendor match found for: '{self.location}' (cleaned: '{cleaned}')")

            if default_name:
                return self.location.title()
            else:
                return None
        else:
            # Log that we found a match
            vendor_name = similar_account.get('name')
            vendor_id = similar_account.get('firefly_account_id')
            LOGS.info(f"Vendor match found: '{vendor_name}' (ID: {vendor_id}) for '{self.location}'")

            try:
                account_id = int(vendor_id)
                if account_id <= 0:
                    raise ValueError("Invalid account ID")
                return account_id
            except (TypeError, ValueError):
                LOGS.warning("Vendor %r has no valid Firefly account ID", vendor_name)
                return self.location.title() if default_name else None

    @staticmethod
    def _defaults_from_transactions(raw_transactions: dict) -> tuple[str, Union[str, None]]:
        """Infer description and category from the newest usable transaction."""
        description = None
        category_id = None
        for raw_transaction in raw_transactions.get('data', []):
            inner_transactions = raw_transaction.get('attributes', {}).get('transactions', [])
            for transaction in inner_transactions:
                if description is None and transaction.get('description'):
                    description = transaction['description']
                if category_id is None and transaction.get('category_id') is not None:
                    category_id = transaction['category_id']
                if description is not None and category_id is not None:
                    return description, category_id
        return description or 'ADD DESCRIPTION TO THIS TRANSACTION', category_id

    def create_transaction_on_firefly(self, is_receipt: bool = False, image_path: str = None):
        destination_account = self.get_similar_account(default_name=True)
        transaction_date = self.get_date()
        if transaction_date is None:
            raise ValueError(f"Invalid transaction date or time: {self.date} {self.time}")

        description = 'ADD DESCRIPTION TO THIS TRANSACTION'
        category_id = None
        api = FireflyApi()
        if isinstance(destination_account, int):
            try:
                history = api.get_transactions_from_account(destination_account)
                description, category_id = self._defaults_from_transactions(history)
            except Exception as error:
                LOGS.warning("Failed to infer transaction defaults: %s", error)
        # Only use system tags
        tags = ['powered-by-groq']
        if is_receipt:
            tags += ['from-receipt', 'ocr']
        transaction_data = {
            'type': 'withdrawal',
            'date': transaction_date.isoformat(),
            'amount': format(self.get_amount(), 'f'),
            'description': description,
            'source_id': FIREFLY_DEFAULT_ACCOUNT_ID,
            'currency_code': LOCAL_CURRENCY,
            'category_id': category_id,
            'tags': tags,
            'notes': f'Raw transaction message: {self.raw_transaction_message}' if self.raw_transaction_message else None,
        }
        if isinstance(destination_account, str):
            transaction_data['destination_name'] = destination_account
        if isinstance(destination_account, int):
            transaction_data['destination_id'] = destination_account
        if self.is_foreign_transaction():
            transaction_data['amount'] = str(self.local_amount())
            transaction_data['foreign_currency_code'] = self.get_currency()
            transaction_data['foreign_amount'] = format(self.get_amount(), 'f')
        payload = {
            "transactions": [transaction_data],
            "apply_rules":              True,
            "fire_webhooks":            False,
            "error_if_duplicate_hash": FIREFLY_ERROR_ON_DUPLICATE,
        }
        response = api.post_json('transactions', payload=payload)

        # If we have an image and the transaction was created successfully, attach the image
        if image_path:
            try:
                transaction_id = response['data']['attributes']['transactions'][0]['transaction_journal_id']
                self._attach_image_to_transaction(api, transaction_id, image_path)
            except Exception:
                LOGS.exception("Failed to attach image to transaction")

        return response

    def _attach_image_to_transaction(
        self,
        api: FireflyApi,
        transaction_id: str,
        image_path: str,
    ):
        """
        Attach an image to a transaction in Firefly.
        :param transaction_id: The ID of the transaction to attach the image to.
        :param image_path: The path to the image file to attach.
        """
        if not os.path.exists(image_path):
            raise FileNotFoundError(f"Image file not found: {image_path}")

        # Get the filename from the path
        filename = os.path.basename(image_path)

        # Create the attachment object
        attachment_response = api.create_attachment(transaction_id, filename)
        attachment_id = attachment_response['data']['id']

        # Upload the actual file
        api.upload_attachment_file(attachment_id, image_path)

        LOGS.info(f"Successfully attached image {filename} to transaction {transaction_id}")
