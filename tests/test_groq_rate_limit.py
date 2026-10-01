import json
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from groq import RateLimitError

# Reuse the suite's isolated configuration before importing the application.
from tests import support as test_core
from app import FireflyParserBot
from app.groq_rate_limit import DAY, MINUTE, GroqRateLimiter
from app.plugins import transaction_utils


class FakeClock:
    def __init__(self):
        self.now = 1_000_000.0
        self.waits = []

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.waits.append(seconds)
        self.now += seconds


class GroqRateLimitTests(unittest.TestCase):
    def setUp(self):
        self.runtime = TemporaryDirectory()
        self.addCleanup(self.runtime.cleanup)
        self.path = Path(self.runtime.name) / 'usage.json'
        self.clock = FakeClock()

    def limiter(self, rpm=30, tpm=8000, tpd=200000):
        return GroqRateLimiter(
            rpm, tpm, tpd, self.path,
            clock=self.clock.time, sleep=self.clock.sleep,
        )

    @staticmethod
    def completion(tokens):
        return SimpleNamespace(usage=SimpleNamespace(total_tokens=tokens))

    def test_dispatcher_has_one_worker(self):
        self.assertEqual(FireflyParserBot.workers, 1)

    def test_request_window_waits_before_third_call(self):
        limiter = self.limiter(rpm=2)
        starts = []

        def request():
            starts.append(self.clock.time())
            return self.completion(10)

        for _ in range(3):
            limiter.run(request, 100)
        self.assertEqual(starts, [1_000_000, 1_000_000, 1_000_000 + MINUTE])

    def test_minute_budget_reserves_maximum_output(self):
        limiter = self.limiter(tpm=1000)
        limiter.run(lambda: self.completion(400), 700)
        limiter.run(lambda: self.completion(400), 700)
        self.assertEqual(self.clock.waits, [MINUTE])

    def test_actual_usage_releases_unused_reservation(self):
        limiter = self.limiter(tpm=1000)
        for _ in range(4):
            limiter.run(lambda: self.completion(100), 700)
        self.assertEqual(self.clock.waits, [])
        limiter.run(lambda: self.completion(100), 700)
        self.assertEqual(self.clock.waits, [MINUTE])

    def test_daily_budget_survives_restart(self):
        limiter = self.limiter(tpd=1000)
        limiter.run(lambda: self.completion(400), 700)
        restarted = self.limiter(tpd=1000)
        restarted.run(lambda: self.completion(400), 700)
        self.assertEqual(self.clock.waits, [DAY])

    def test_failed_call_keeps_reservation(self):
        limiter = self.limiter(tpm=1000)

        def failed():
            raise RuntimeError('Connection lost after sending')

        with self.assertRaises(RuntimeError):
            limiter.run(failed, 700)
        self.limiter(tpm=1000).run(lambda: self.completion(100), 700)
        self.assertEqual(self.clock.waits, [MINUTE])

    def test_long_request_usage_expires_from_completion_time(self):
        limiter = self.limiter(tpm=1000)

        def request():
            self.clock.now += 50
            return self.completion(400)

        limiter.run(request, 700)
        limiter.run(lambda: self.completion(400), 700)
        self.assertEqual(self.clock.waits, [MINUTE])

    @staticmethod
    def rate_limit_error(headers):
        return RateLimitError(
            'Rate limited', response=httpx.Response(
                429, headers=headers,
                request=httpx.Request('POST', 'https://api.groq.com'),
            ), body=None,
        )

    def test_429_honors_retry_after_and_counts_each_attempt(self):
        limiter = self.limiter()
        starts = []

        def request():
            starts.append(self.clock.time())
            if len(starts) == 1:
                raise self.rate_limit_error({'retry-after': '120'})
            return self.completion(100)

        limiter.run(request, 700)
        self.assertEqual(starts, [1_000_000, 1_000_121])
        self.assertEqual([entry[1] for entry in limiter.entries], [700, 100])

    def test_429_retries_are_bounded_and_cooldown_is_persisted(self):
        limiter = self.limiter()
        calls = []

        def request():
            calls.append(self.clock.time())
            raise self.rate_limit_error({'retry-after': '120'})

        with self.assertRaises(RateLimitError):
            limiter.run(request, 700)
        self.assertEqual(len(calls), 3)
        self.limiter().run(lambda: self.completion(100), 700)
        self.assertEqual(self.clock.waits, [121, 121, 121])

    def test_oversized_request_is_rejected_before_send(self):
        for reservation in (1001, 0):
            with self.assertRaises(ValueError):
                self.limiter(tpm=1000).run(lambda: self.fail('Must not send'), reservation)
        self.assertFalse(self.path.exists())

    def test_corrupt_state_fails_closed(self):
        self.path.write_text(json.dumps({'entries': 'invalid', 'blocked_until': 0}))
        with self.assertRaises(RuntimeError):
            self.limiter()

    def test_calls_from_different_threads_are_serial(self):
        limiter = self.limiter()
        first_entered = threading.Event()
        second_entered = threading.Event()
        release = threading.Event()

        def first():
            first_entered.set()
            if not release.wait(2):
                raise RuntimeError('Test request was not released')
            return self.completion(100)

        def second():
            second_entered.set()
            return self.completion(100)

        with ThreadPoolExecutor(max_workers=2) as executor:
            first_result = executor.submit(limiter.run, first, 700)
            self.assertTrue(first_entered.wait(2))
            second_result = executor.submit(limiter.run, second, 700)
            try:
                self.assertFalse(second_entered.wait(0.05))
            finally:
                release.set()
            first_result.result(timeout=2)
            second_result.result(timeout=2)

    def test_text_and_image_extraction_share_limiter_without_sdk_retries(self):
        with patch.object(transaction_utils, 'Groq') as client_type, patch.object(
            transaction_utils, 'GROQ_RATE_LIMITER'
        ) as limiter:
            completion = test_core.FakeCompletion(json.dumps({
                'date': '01/01/26', 'time': '12:00:00', 'currency': 'MVR',
                'amount': 10, 'location': 'Shop', 'reference_no': '123',
            }))
            client_type.return_value.__enter__.return_value.chat.completions.create.return_value = completion
            limiter.run.side_effect = lambda request, tokens: request()
            text_result = transaction_utils.extract_transaction_details_from_text('Bank alert')
            image_path = Path(self.runtime.name) / 'receipt.jpg'
            image_path.write_bytes(b'test image')
            image_result = transaction_utils.extract_transaction_details_from_image(str(image_path))
            self.assertIsNone(text_result.error)
            self.assertIsNone(image_result.error)
            self.assertEqual(limiter.run.call_count, 2)
            for call in client_type.call_args_list:
                self.assertEqual(call.kwargs['max_retries'], 0)
            image_reservation = limiter.run.call_args_list[1].args[1]
            expected = (
                64 + len(transaction_utils.get_system_message_for_image().encode('utf-8'))
                + transaction_utils.GROQ_IMAGE_TOKENS
                + transaction_utils.GROQ_MAX_COMPLETION_TOKENS
            )
            self.assertEqual(image_reservation, expected)


if __name__ == '__main__':
    unittest.main()
