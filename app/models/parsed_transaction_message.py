import sys
from datetime import datetime
from importlib.metadata import unique_everseen
from typing import Union

from app import FIREFLY_DEFAULT_ACCOUNT_ID
from app.database.vendorsdb import VendorsDB
from app.firefly.firefly import FireflyApi


class ParsedTransactionMessage:
    def __init__(
            self,
            card: str,
            date: str,
            time: str,
            currency: str,
            amount: float,
            location: str,
            approval_code: str,
            reference_no: str,
            raw_transaction_message: Union[None, str] = None
    ):
        self.card = card
        self.date = date
        self.time = time
        self.currency = currency
        self.amount: float = amount
        self.location = location
        self.approval_code = approval_code
        self.reference_no = reference_no
        self.is_receipt = False
        self.raw_transaction_message = raw_transaction_message

    @staticmethod
    def make(data):
        return ParsedTransactionMessage(
            card=data['card'],
            date=data['date'],
            time=data['time'],
            currency=data['currency'],
            amount=data['amount'],
            location=data['location'],
            approval_code=data['approval_code'],
            reference_no=data['reference_no'],
        )

    def get_currency(self):
        return self.currency

    def is_foreign_transaction(self):
        return self.get_currency() != 'MVR'

    def exchange_rate(self) -> float:
        match self.currency:
            case "MVR":
                return 1
            case "USD":
                return 15.42
            case "EUR":
                return 16.20
            case _:
                return 1

    def local_amount(self) -> float:
        return round(self.amount * self.exchange_rate(), 2)

    def getDate(self, is_recept: bool = False):
        if is_recept:
            self.is_receipt = True

        # use %M for minutes, %S for seconds
        date_format = '%d/%m/%Y %H:%M' if self.is_receipt else '%d/%m/%y %H:%M:%S'
        datetime_string = f"{self.date} {self.time}"

        try:
            return datetime.strptime(datetime_string, date_format)
        except ValueError as e:
            print(f"Error parsing date: {e}.  datetime_string: {datetime_string}, format_string: {date_format}")
            return None

    def get_similar_account(self, default_name: bool = False):
        similar_account = VendorsDB().find_vendor_by_name_or_alias(self.location)

        if similar_account is None:
            if default_name:
                return self.location.title()
            else:
                return None

        return int(similar_account.get('firefly_account_id'))

    def get_similar_transaction_descriptions(self):
        first_similar_account_id = self.get_similar_account()

        if first_similar_account_id is None:
            return []

        raw_transactions = FireflyApi().get_transactions_from_account(first_similar_account_id)

        transaction_descriptions = []

        for raw_transaction in raw_transactions['data']:
            inner_transactions = raw_transaction['attributes']['transactions']

            for inner_transaction in inner_transactions:
                transaction_descriptions.append(inner_transaction['description'])

        return transaction_descriptions

    def get_possible_transaction_description(self):
        similar_descriptions = self.get_similar_transaction_descriptions()

        unique_descriptions = []

        for description in similar_descriptions:
            if description not in unique_descriptions:
                unique_descriptions.append(description)

        if len(unique_descriptions) > 1:
            return unique_descriptions[0]
        else:
            return 'ADD DESCRIPTION TO THIS TRANSACTION'

    def get_possible_category(self):
        transaction_categories = []

        if self.get_similar_account() is None:
            return transaction_categories

        raw_transactions = FireflyApi().get_transactions_from_account(self.get_similar_account())

        for raw_transaction in raw_transactions['data']:
            inner_transactions = raw_transaction['attributes']['transactions']

            for inner_transaction in inner_transactions:
                transaction_categories.append(inner_transaction['category_id'])

        categories = list(set(transaction_categories))

        if len(categories) >= 1:
            return categories[0]

        return None

    def create_transaction_on_firefly(self):
        destination_account = self.get_similar_account(default_name=True)

        transaction_data = {
            'type': 'withdrawal',
            'date': self.getDate().isoformat(),
            'amount': self.amount,
            'description': self.get_possible_transaction_description(),
            'source_id': FIREFLY_DEFAULT_ACCOUNT_ID,
            'category_id': self.get_possible_category(),
            'tags': ['powered-by-groq'],
            'notes': f'Raw transaction message: {self.raw_transaction_message}' if self.raw_transaction_message else None,
        }

        if type(destination_account) is str:
            transaction_data['destination_name'] = destination_account

        if type(destination_account) is int:
            transaction_data['destination_id'] = destination_account

        if self.is_foreign_transaction():
            transaction_data['amount'] = self.local_amount()
            transaction_data['foreign_currency'] = self.get_currency()
            transaction_data['foreign_amount'] = self.amount

        payload = {
            "transactions": [transaction_data],
            "apply_rules":              True,
            "fire_webhooks":            False,
            "error_if_duplicate_hash":  False
        }

        print(payload)

        response = FireflyApi().post_json('transactions', payload=payload, debug=True)

        print(response.json())
