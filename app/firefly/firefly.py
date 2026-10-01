import requests
import logging
import re
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from app import (
    FIREFLY_API_KEY,
    FIREFLY_BASE_URL,
    FIREFLY_ERROR_ON_DUPLICATE,
    FIREFLY_REQUEST_TIMEOUT,
)
from app.models.transaction_models import Account, Budget, Category, Bill

LOGS = logging.getLogger(__name__)


class FireflyApi:
    def __init__(self):
        self.base_url = FIREFLY_BASE_URL.rstrip('/')
        self.api_url = self.base_url + '/api/v1'
        self.api_key = FIREFLY_API_KEY
        self.timeout = FIREFLY_REQUEST_TIMEOUT
        self.session = requests.Session()
        self.session.headers.update({
            'Accept': 'application/json',
            'Authorization': f'Bearer {self.api_key}',
        })
        retry_policy = Retry(
            total=3,
            connect=3,
            read=3,
            status=3,
            backoff_factor=0.5,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({'GET', 'PUT'}),
            respect_retry_after_header=True,
        )
        adapter = HTTPAdapter(max_retries=retry_policy)
        self.session.mount('https://', adapter)
        self.session.mount('http://', adapter)

    @staticmethod
    def _response_json(response: requests.Response, success_codes: tuple[int, ...]):
        if response.status_code not in success_codes:
            # Keep diagnostics useful without sending an arbitrarily large HTML
            # error page back through Telegram.
            body = response.text.strip()[:1000]
            raise RuntimeError(
                f"Firefly API returned HTTP {response.status_code}: {body or 'empty response'}"
            )
        if response.status_code == 204:
            return None
        try:
            return response.json()
        except requests.exceptions.JSONDecodeError as error:
            raise RuntimeError(
                f"Firefly API returned invalid JSON for HTTP {response.status_code}."
            ) from error

    def construct_url(self, endpoint: str):
        """
        Construct the full URL for the API endpoint
        :param endpoint: API endpoint
        :return: Full URL
        """
        return f"{self.api_url}/{endpoint.lstrip('/')}"

    def get_json(self, endpoint: str, params: dict = None):
        """
        Get JSON data from Firefly API
        :param endpoint: API endpoint
        :param params: Query parameters
        :return: JSON data
        """
        response = self.session.get(
            self.construct_url(endpoint),
            params=params,
            timeout=self.timeout,
        )

        return self._response_json(response, (200,))

    def get_all_pages(self, endpoint: str, params: dict = None) -> list[dict]:
        """Fetch every page from a Firefly collection endpoint."""
        page_params = dict(params or {})
        page_params.setdefault('limit', 100)
        page = 1
        items = []

        while True:
            page_params['page'] = page
            response = self.get_json(endpoint, page_params)
            if not isinstance(response, dict) or not isinstance(response.get('data'), list):
                raise RuntimeError(f"Firefly returned an invalid collection for {endpoint}.")
            items.extend(response['data'])
            pagination = response.get('meta', {}).get('pagination', {})
            try:
                total_pages = max(1, int(pagination.get('total_pages') or 1))
            except (TypeError, ValueError) as error:
                raise RuntimeError(f"Firefly returned invalid pagination for {endpoint}.") from error
            if page >= total_pages:
                return items
            page += 1

    def transaction_show_url(self, transaction_id: str):
        """
        Get the URL to show a transaction in Firefly.
        :param transaction_id: The ID of the transaction.
        :return: The URL to show the transaction.
        """
        return f"{self.base_url}/transactions/show/{transaction_id}"

    def post_json(self, endpoint: str, payload: dict):
        """
        Send a POST request to the Firefly API.
        :param endpoint: API endpoint
        :param payload: JSON payload
        :return: Response JSON or raises an exception on failure.
        """
        url = self.construct_url(endpoint)

        response = self.session.post(url, json=payload, timeout=self.timeout)

        return self._response_json(response, (200, 201))

    def put_json(self, endpoint: str, payload: dict):
        """
        Send a PUT request to the Firefly API.
        :param endpoint: API endpoint
        :param payload: JSON payload
        :return: Response JSON or raises an exception on failure.
        """
        url = self.construct_url(endpoint)
        response = self.session.put(url, json=payload, timeout=self.timeout)

        return self._response_json(response, (200, 204))

    def post_file(self, endpoint: str, file_path: str):
        """
        Send a POST request with a file to the Firefly API.
        :param endpoint: API endpoint
        :param file_path: Path to the file to upload
        :return: Response JSON or raises an exception on failure.
        """
        url = self.construct_url(endpoint)
        with open(file_path, 'rb') as file:
            response = self.session.post(
                url, data=file, headers={'Content-Type': 'application/octet-stream'},
                timeout=self.timeout,
            )

        return self._response_json(response, (200, 201, 204))

    def create_attachment(self, transaction_id: str, filename: str):
        """
        Create an attachment object for a transaction.
        :param transaction_id: The ID of the transaction to attach the file to.
        :param filename: The name of the file to attach.
        :return: Response JSON with the created attachment details.
        """
        payload = {
            "filename": filename,
            "attachable_type": "TransactionJournal",
            "attachable_id": transaction_id
        }
        return self.post_json('attachments', payload)

    def upload_attachment_file(self, attachment_id: str, file_path: str):
        """
        Upload the actual file content for an attachment.
        :param attachment_id: The ID of the attachment.
        :param file_path: The path to the file to upload.
        :return: Response JSON or raises an exception on failure.
        """
        endpoint = f"attachments/{attachment_id}/upload"
        return self.post_file(endpoint, file_path)

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

    def accounts(self, account_type: str, get_all: bool = False):
        params = {
            'type': account_type,
            'limit': 20
        }

        if get_all:
            return self.get_all_pages('accounts', params)
        response = self.get_json(endpoint='accounts', params=params)
        return response.get('data', [])

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
        account = self.get_json(f"accounts/{account_id}")
        try:
            current_notes = account['data']['attributes'].get('notes') or ''
        except (KeyError, TypeError) as error:
            raise RuntimeError("Firefly returned invalid account details.") from error
        payload = {"notes": self._merge_alias_notes(current_notes, aliases)}
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

    @classmethod
    def _merge_alias_notes(cls, notes: str, aliases: list[str]) -> str:
        """Replace the bot-managed alias block without destroying user notes."""
        marker_pattern = re.compile(
            r"(?:^|\n)\*START:ALIASES\*.*?\*END:ALIASES\*(?:\n|$)",
            re.DOTALL,
        )
        preserved_notes = marker_pattern.sub("\n", notes or '').strip()
        alias_notes = cls._generate_alias_notes(aliases)
        return "\n\n".join(part for part in (preserved_notes, alias_notes) if part)

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
        return self._named_resources('budgets', Budget)

    def get_categories(self) -> list[Category]:
        """
        Get all categories
        :return: JSON data
        """
        return self._named_resources('categories', Category)

    def get_bills(self) -> list[Bill]:
        """
        Get all bills
        :return: JSON data
        """
        return self._named_resources('bills', Bill)

    def _named_resources(self, endpoint: str, model_type):
        resources = []
        for resource in self.get_all_pages(endpoint):
            try:
                resources.append(model_type(
                    id=str(resource['id']),
                    name=str(resource['attributes']['name']),
                ))
            except (KeyError, TypeError):
                LOGS.warning("Skipping malformed Firefly %s resource", endpoint)
        return resources

    def get_asset_accounts(self) -> list[Account]:
        """
        Get all asset accounts
        :return: List of Account objects
        """
        accounts_data = self.accounts(account_type='asset', get_all=True)
        asset_accounts = []
        for account in accounts_data:
            try:
                asset_accounts.append(Account(
                    id=account['id'],
                    name=account['attributes']['name']
                ))
            except KeyError:
                continue
        return asset_accounts

    def get_revenue_accounts(self) -> list[Account]:
        """
        Get all revenue accounts
        :return: List of Account objects
        """
        accounts_data = self.accounts(account_type='revenue', get_all=True)
        revenue_accounts = []
        for account in accounts_data:
            try:
                revenue_accounts.append(Account(
                    id=account['id'],
                    name=account['attributes']['name']
                ))
            except KeyError:
                continue
        return revenue_accounts

    def create_incoming_transaction(
            self,
            revenue_account_id: str,
            asset_account_id: str,
            amount: str,
            description: str,
            date: str
    ) -> dict:
        """
        Create an incoming money transaction.

        Args:
            revenue_account_id: Firefly revenue account ID to use as source.
            asset_account_id: Firefly asset account ID to use as destination.
            amount: Amount being received.
            description: Short transaction description.
            date: ISO formatted transaction date.

        Returns:
            Firefly API response JSON.
        """
        payload = {
            "transactions": [
                {
                    "type": "deposit",
                    "date": date,
                    "amount": amount,
                    "description": description,
                    "source_id": revenue_account_id,
                    "destination_id": asset_account_id
                }
            ],
            "apply_rules": True,
            "fire_webhooks": False,
            "error_if_duplicate_hash": FIREFLY_ERROR_ON_DUPLICATE,
        }

        return self.post_json('transactions', payload=payload)

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
