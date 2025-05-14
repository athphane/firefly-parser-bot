import requests

from app import FIREFLY_BASE_URL, FIREFLY_API_KEY
from app.firefly.models.parsed_transaction_message import ParsedTransactionMessage


class FireflyApi:
    def __init__(self):
        self.base_url = FIREFLY_BASE_URL
        self.api_url = self.base_url + '/api/v1'
        self.api_key = FIREFLY_API_KEY

    def construct_url(self, endpoint: str):
        """
        Construct the full URL for the API endpoint
        :param endpoint: API endpoint
        :return: Full URL
        """
        return f"{self.api_url}/{endpoint}"

    def get_json(self, endpoint: str, params: dict = None):
        """
        Get JSON data from Firefly API
        :param endpoint: API endpoint
        :param params: Query parameters
        :return: JSON data
        """
        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json'
        }

        if params:
            response = requests.get(self.construct_url(endpoint), headers=headers, params=params)
        else:
            response = requests.get(self.construct_url(endpoint), headers=headers)

        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f"Error: {response.status_code} - {response.text}")

    def about(self):
        """
        Get information about the Firefly API
        :return: JSON data
        """
        return self.get_json('about')

    def about_user(self):
        """
        Get information about the user
        :return: JSON data
        """
        return self.get_json('about/user')

    def transactions(self):
        """
        Get transactions
        :return: JSON data
        """
        return self.get_json('transactions')

    def accounts_autocomplete(self, query: str):
        """
        Get account autocomplete
        :param query: Query string
        :return: JSON data
        """
        params = {
            'query': query,
            'limit': 20
        }

        return self.get_json('autocomplete/accounts', params)

    def transactions_from_account(self, account_id: str):
        """
        Get transactions from a specific account
        :param account_id:
        :return:
        """
        return self.get_json(f"/accounts/{account_id}/transactions")

    def create_transaction(self, parsed_transaction: ParsedTransactionMessage):
        destination_account = parsed_transaction.get_first_similar_account_name()

        transaction_data = {
            'type':  'withdrawal',
            'date':  parsed_transaction.getDate().toIso8601String(),
            'amount':  parsed_transaction.amount,
            'description':  parsed_transaction.getPossibleTransactionDescription(),
            'source_id':  config('firefly-iii.default_account_id'),
            'category_id':  parsed_transaction.getFirstPossibleCategoryId(),
            'tags':  ['powered-by-groq'],
            'notes':  parsed_transaction.raw_transaction_message ? "Raw transaction message: $parsed_transaction.raw_transaction_message": null,
        }

        pass
