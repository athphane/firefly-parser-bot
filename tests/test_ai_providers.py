"""Exercise OpenRouter's real SDK request/response handling without network calls."""

import base64
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import httpx
from openai import OpenAI

from tests import support
from app.plugins import transaction_parser, transaction_utils
from app.models import parsed_transaction_message


DETAILS = {
    'date': '01/01/26', 'time': '12:00:00', 'currency': 'MVR',
    'amount': 12.5, 'location': 'Shop', 'reference_no': '123',
}


class OpenRouterTests(unittest.TestCase):
    def setUp(self):
        for name, value in (
            ('AI_PROVIDER', 'openrouter'), ('AI_PROVIDER_NAME', 'OpenRouter'),
            ('OPENROUTER_API_KEY', 'router-key'), ('OPENROUTER_MODEL', 'vendor/vision-model'),
        ):
            patcher = patch.object(transaction_utils, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    @staticmethod
    def response(content=None):
        return httpx.Response(200, json={
            'id': 'test-completion', 'object': 'chat.completion', 'created': 1,
            'model': 'vendor/vision-model',
            'choices': [{'index': 0, 'finish_reason': 'stop', 'message': {
                'role': 'assistant', 'content': json.dumps(DETAILS) if content is None else content,
            }}],
        })

    def client(self, handler):
        return patch.object(transaction_utils, 'OpenAI', side_effect=lambda **kwargs: OpenAI(
            **kwargs, http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        ))

    def test_text_and_receipt_use_openrouter_without_groq_or_its_limiter(self):
        requests = []

        def handler(request):
            requests.append(request)
            return self.response()

        with self.client(handler), patch.object(transaction_utils, 'Groq') as groq, patch.object(
            transaction_utils, 'GROQ_RATE_LIMITER'
        ) as limiter, TemporaryDirectory() as directory:
            text_result = transaction_utils.extract_transaction_details_from_text('Bank alert')
            image = Path(directory) / 'receipt.png'
            image.write_bytes(b'receipt bytes')
            image_result = transaction_utils.extract_transaction_details_from_image(str(image))
            groq.assert_not_called()
            limiter.run.assert_not_called()

        for result in (text_result, image_result):
            self.assertIsNone(result.error)
            self.assertEqual(result.details['amount'], Decimal('12.5'))
            self.assertIn('test-completion', result.completion_data)
        self.assertEqual(len(requests), 2)
        for request in requests:
            self.assertEqual(str(request.url), 'https://openrouter.ai/api/v1/chat/completions')
            self.assertEqual(request.headers['authorization'], 'Bearer router-key')
            body = json.loads(request.content)
            self.assertEqual(body['model'], 'vendor/vision-model')
            self.assertEqual(body['response_format'], {'type': 'json_object'})
            self.assertEqual(body['provider'], {'require_parameters': True})
            self.assertNotIn('reasoning_effort', body)
        text_body = json.loads(requests[0].content)
        self.assertEqual(text_body['messages'][1], {'role': 'user', 'content': 'Bank alert'})
        image_body = json.loads(requests[1].content)
        image_url = image_body['messages'][0]['content'][1]['image_url']['url']
        self.assertEqual(image_url, 'data:image/png;base64,' + base64.b64encode(b'receipt bytes').decode())

    def test_rate_limit_is_retried_by_sdk(self):
        requests = []

        def handler(request):
            requests.append(request)
            if len(requests) == 1:
                return httpx.Response(429, headers={'retry-after-ms': '1'}, json={
                    'error': {'message': 'Temporarily rate limited', 'code': 429},
                })
            return self.response()

        with self.client(handler):
            result = transaction_utils.extract_transaction_details_from_text('Bank alert')
        self.assertIsNone(result.error)
        self.assertEqual(len(requests), 2)

    def test_text_and_receipts_share_configured_concurrency_slots(self):
        entered = [threading.Event() for _ in range(3)]
        release = threading.Event()
        lock = threading.Lock()
        calls = []

        def handler(request):
            with lock:
                index = len(calls)
                calls.append(request)
            entered[index].set()
            if not release.wait(2):
                raise RuntimeError('Test request was not released')
            return self.response()

        with self.client(handler), patch.object(
            transaction_utils, 'AI_CALL_SLOTS', threading.BoundedSemaphore(2)
        ), TemporaryDirectory() as directory, ThreadPoolExecutor(max_workers=3) as executor:
            image = Path(directory) / 'receipt.jpg'
            image.write_bytes(b'receipt')
            futures = [
                executor.submit(transaction_utils.extract_transaction_details_from_text, 'First alert'),
                executor.submit(transaction_utils.extract_transaction_details_from_image, str(image)),
            ]
            try:
                self.assertTrue(entered[0].wait(2))
                self.assertTrue(entered[1].wait(2))
                futures.append(executor.submit(transaction_utils.extract_transaction_details_from_text, 'Third alert'))
                self.assertFalse(entered[2].wait(0.05))
            finally:
                release.set()
            for future in futures:
                self.assertIsNone(future.result(timeout=2).error)
        self.assertEqual(len(calls), 3)

    def test_api_errors_become_extraction_errors_for_text_and_receipts(self):
        def handler(request):
            return httpx.Response(402, json={'error': {'message': 'Insufficient credits', 'code': 402}})

        with self.client(handler), TemporaryDirectory() as directory:
            image = Path(directory) / 'receipt.jpg'
            image.write_bytes(b'receipt')
            results = (
                transaction_utils.extract_transaction_details_from_text('Bank alert'),
                transaction_utils.extract_transaction_details_from_image(str(image)),
            )
        for result in results:
            self.assertIsNone(result.details)
            self.assertIsNone(result.completion_data)
            self.assertIn('OpenRouter API error', result.error)
            self.assertIn('Insufficient credits', result.error)

    def test_retries_are_bounded(self):
        requests = []

        def handler(request):
            requests.append(request)
            return httpx.Response(429, headers={'retry-after-ms': '1'}, json={
                'error': {'message': 'Rate limited', 'code': 429},
            })

        with self.client(handler):
            result = transaction_utils.extract_transaction_details_from_text('Bank alert')
        self.assertIsNone(result.details)
        self.assertIn('OpenRouter API error', result.error)
        self.assertEqual(len(requests), 3)

    def test_invalid_json_retains_completion_for_error_report(self):
        with self.client(lambda request: self.response('not json')):
            result = transaction_utils.extract_transaction_details_from_text('Bank alert')
        self.assertIsNone(result.details)
        self.assertIn('JSON', result.error)
        self.assertIn('not json', result.completion_data)
        with patch.object(transaction_parser, 'AI_PROVIDER_NAME', 'OpenRouter'):
            report = transaction_parser.build_error_report('Extraction failed', result)
        self.assertIn('OpenRouter completion data', report)

    def test_firefly_tag_matches_selected_provider(self):
        for provider in ('groq', 'openrouter'):
            with self.subTest(provider=provider), patch.object(
                parsed_transaction_message, 'AI_PROVIDER', provider
            ), patch.object(parsed_transaction_message, 'FireflyApi') as api_type:
                transaction = parsed_transaction_message.ParsedTransactionMessage(
                    '01/01/26', '12:00', 'MVR', '10', 'Shop', 'ref',
                )
                with patch.object(transaction, 'get_similar_account', return_value='Shop'):
                    transaction.create_transaction_on_firefly()
                payload = api_type.return_value.post_json.call_args.kwargs['payload']
                self.assertEqual(payload['transactions'][0]['tags'], [f'powered-by-{provider}'])
