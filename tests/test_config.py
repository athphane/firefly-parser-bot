"""Check configuration validation in fresh processes without external services."""

import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from tests.support import TEST_CONFIG


class ConfigurationTests(unittest.TestCase):
    def launch(self, config_text, *, ai_environment=None, code=None, groq_state=None):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / 'config.ini'
            config.write_text(config_text, encoding='utf-8')
            environment = dict(os.environ, FIREFLY_PARSER_CONFIG=str(config),
                               FIREFLY_PARSER_WORKDIR=str(root / 'sessions'),
                               FIREFLY_PARSER_LOG_DIR=str(root / 'logs'))
            for name in ('AI_PROVIDER', 'GROQ_API_KEY', 'GROQ_MODEL',
                         'OPENROUTER_API_KEY', 'OPENROUTER_MODEL'):
                environment.pop(name, None)
            environment.update(ai_environment or {})
            if groq_state is not None:
                (root / 'sessions').mkdir()
                (root / 'sessions' / 'groq-rate-limit.json').write_text(groq_state)
            result = subprocess.run(
                [sys.executable, '-c', code or 'from app import WORKDIR; assert WORKDIR.is_dir()'],
                env=environment, capture_output=True, text=True, timeout=15,
                cwd=Path(__file__).resolve().parent.parent,
            )
            return result

    def test_percent_in_credentials_and_fresh_session_directory(self):
        result = self.launch(TEST_CONFIG.read_text().replace('password = test', 'password = test%pass'))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_invalid_admin_lists_fail_clearly(self):
        for value in ('', 'invalid'):
            with self.subTest(value=value):
                result = self.launch(TEST_CONFIG.read_text().replace('admins = 1', f'admins = {value}'))
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('pyrogram.admins', result.stderr)

    def test_nonfinite_timeouts_are_rejected(self):
        for value in ('nan', 'inf'):
            with self.subTest(value=value):
                result = self.launch(TEST_CONFIG.read_text().replace('request_timeout = 1', f'request_timeout = {value}'))
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('firefly.request_timeout', result.stderr)

    def test_local_currency_rate_must_equal_one(self):
        result = self.launch(TEST_CONFIG.read_text() + '\n[exchange_rates]\nlocal_currency = USD\nUSD = 15.42\n')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('local currency must be 1', result.stderr)

    def test_existing_config_defaults_to_groq_and_env_overrides_credentials_and_model(self):
        result = self.launch(TEST_CONFIG.read_text(), code=(
            "from app import AI_PROVIDER, GROQ_API_KEY, GROQ_MODEL; "
            "assert (AI_PROVIDER, GROQ_API_KEY, GROQ_MODEL) == ('groq', 'test', 'test')"
        ))
        self.assertEqual(result.returncode, 0, result.stderr)
        result = self.launch(
            TEST_CONFIG.read_text(),
            ai_environment={'AI_PROVIDER': ' GROQ ', 'GROQ_API_KEY': 'env-key', 'GROQ_MODEL': 'env-model'},
            code="from app import GROQ_API_KEY, GROQ_MODEL; assert (GROQ_API_KEY, GROQ_MODEL) == ('env-key', 'env-model')",
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_openrouter_starts_without_any_groq_settings_or_valid_groq_state(self):
        config = TEST_CONFIG.read_text().split('[ai]')[0]
        result = self.launch(
            config,
            ai_environment={'AI_PROVIDER': 'openrouter', 'OPENROUTER_API_KEY': 'router-key',
                            'OPENROUTER_MODEL': 'vendor/vision-model'},
            groq_state='corrupt state',
            code=(
                "from app import AI_PROVIDER, OPENROUTER_API_KEY, OPENROUTER_MODEL; "
                "from app.plugins.transaction_utils import GROQ_RATE_LIMITER; "
                "assert (AI_PROVIDER, OPENROUTER_API_KEY, OPENROUTER_MODEL) == "
                "('openrouter', 'router-key', 'vendor/vision-model'); "
                "assert GROQ_RATE_LIMITER is None"
            ),
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_openrouter_config_fallback_and_environment_precedence(self):
        config = TEST_CONFIG.read_text() + '\nopenrouter_api_key = config-key\nopenrouter_model = config/model\nrequests_per_minute = invalid\n'
        for overrides, expected in (
            ({}, ('config-key', 'config/model')),
            ({'OPENROUTER_API_KEY': 'env-key', 'OPENROUTER_MODEL': 'env/model'}, ('env-key', 'env/model')),
        ):
            with self.subTest(overrides=overrides):
                result = self.launch(
                    config, ai_environment={'AI_PROVIDER': 'openrouter', **overrides},
                    code=f"from app import OPENROUTER_API_KEY, OPENROUTER_MODEL; assert (OPENROUTER_API_KEY, OPENROUTER_MODEL) == {expected!r}",
                )
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_invalid_provider_and_missing_active_settings_fail_clearly(self):
        for environment, expected in (
            ({'AI_PROVIDER': 'unsupported'}, 'AI_PROVIDER'),
            ({'AI_PROVIDER': ''}, 'AI_PROVIDER'),
            ({'GROQ_API_KEY': ''}, 'GROQ_API_KEY'),
            ({'GROQ_MODEL': ' '}, 'GROQ_MODEL'),
            ({'AI_PROVIDER': 'openrouter'}, 'OPENROUTER_API_KEY'),
            ({'AI_PROVIDER': 'openrouter', 'OPENROUTER_API_KEY': 'key'}, 'OPENROUTER_MODEL'),
            ({'AI_PROVIDER': 'openrouter', 'OPENROUTER_API_KEY': 'key', 'OPENROUTER_MODEL': ' '}, 'OPENROUTER_MODEL'),
        ):
            with self.subTest(environment=environment):
                result = self.launch(TEST_CONFIG.read_text(), ai_environment=environment)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(expected, result.stderr)
