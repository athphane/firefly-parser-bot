import requests

from app import FIREFLY_BASE_URL, FIREFLY_API_KEY
from app.models.transaction_models import Budget, Category


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
        
    def transaction_show_url(self, transaction_id: str):
        """
        Get the URL to show a transaction in Firefly.
        :param transaction_id: The ID of the transaction.
        :return: The URL to show the transaction.
        """
        return f"{self.base_url}/transactions/show/{transaction_id}"

    def post_json(self, endpoint: str, payload: dict, debug: bool = False):
        """
        Send a POST request to the Firefly API.
        :param debug:
        :param endpoint: API endpoint
        :param payload: JSON payload
        :return: Response JSON or raises an exception on failure.
        """
        url = self.construct_url(endpoint)

        headers = {
            'Accept': 'application/json',
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {self.api_key}'
        }

        response = requests.post(url, headers=headers, json=payload)

        if debug:
            return response

        if response.status_code in (200, 201):
            return response.json()
        else:
            raise Exception(f"POST request failed: {response.status_code} - {response.text}")

    def put_json(self, endpoint: str, payload: dict):
        """
        Send a PUT request to the Firefly API.
        :param endpoint: API endpoint
        :param payload: JSON payload
        :return: Response JSON or raises an exception on failure.
        """
        url = self.construct_url(endpoint)
        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json'
        }
        response = requests.put(url, headers=headers, json=payload)

        if response.status_code in (200, 204):
            return response.json() if response.status_code == 200 else {"message": "Request successful"}
        else:
            raise Exception(f"PUT request failed: {response.status_code} - {response.text}")

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

    def accounts(self, account_type: str, get_all: bool = False):
        params = {
            'type': account_type,
            'limit': 20
        }

        response = self.get_json(endpoint='accounts', params=params)

        if not get_all:
            try:
                return response['data']
            except KeyError:
                return []

        accounts = response['data']
        current_page = response['meta']['pagination']['current_page'] or 1
        total_pages = response['meta']['pagination']['total_pages'] or 1

        while current_page < total_pages:
            current_page += 1
            params['page'] = current_page

            response = self.get_json(endpoint='accounts', params=params)
            accounts += response['data']

        return accounts

    def update_account_name(self, account_id: int, new_name: str):
        """
        Update the name of an account in Firefly.
        :param account_id: The Firefly account ID.
        :param new_name: The new name for the account.
        :return: Response JSON or raises an exception on failure.
        """
        payload = {"name": new_name}
        return self.put_json(f"accounts/{account_id}", payload)

    def update_account_aliases(self, account_id: int, aliases: list[str]):
        """
        Update the aliases of an account in Firefly.
        :param account_id: The Firefly account ID.
        :param aliases: The list of aliases to set for the account.
        :return: Response JSON or raises an exception on failure.
        """
        payload = {"notes": self._generate_alias_notes(aliases)}
        return self.put_json(f"accounts/{account_id}", payload)

    @staticmethod
    def _generate_alias_notes(aliases: list[str]) -> str:
        """
        Generate the notes field content for Firefly, embedding aliases.
        :param aliases: List of aliases.
        :return: A formatted string containing aliases.
        """
        if not aliases:
            return ""
        aliases_block = "\n".join(aliases)
        return f"*START:ALIASES*\n{aliases_block}\n*END:ALIASES*"

    def get_transactions_from_account(self, account_id: str):
        """
        Get transactions from a specific account
        :param account_id: The Firefly account ID.
        :return: JSON data
        """
        return self.get_json(f"accounts/{account_id}/transactions")

    def get_budgets(self) -> list[Budget]:
        """
        Get all budgets
        :return: JSON data
        """
        response = self.get_json('budgets')
        budgets = []
        for budget in response['data']:
            budgets.append(Budget(
                id=budget['id'],
                name=budget['attributes']['name']
            ))
        return budgets

    def get_categories(self) -> list[Category]:
        """
        Get all categories
        :return: JSON data
        """
        response = self.get_json('categories')
        categories = []
        for category in response['data']:
            categories.append(Category(
                id=category['id'],
                name=category['attributes']['name']
            ))
        return categories

    def update_transaction(self, transaction_id: str, payload: dict):
        """
        Update a transaction
        :param transaction_id: The ID of the transaction to update.
        :param payload: JSON payload with the fields to update (e.g., {'transactions[0][budget_id]': '123'}).
        :return: Response JSON or raises an exception on failure.
        """
        return self.put_json(f"transactions/{transaction_id}", payload)

    def get_recent_transactions(self, limit: int = 10):
        """
        Get recent transactions
        :param limit: The number of recent transactions to retrieve.
        :return: JSON data
        """
        params = {
            'limit': limit,
            'sort': 'date',
            'order': 'desc'
        }
        return self.get_json('transactions', params)
