"""Check configuration validation in fresh processes without external services."""

import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from tests.support import TEST_CONFIG


class ConfigurationTests(unittest.TestCase):
    def launch(self, config_text):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / 'config.ini'
            config.write_text(config_text, encoding='utf-8')
            environment = dict(os.environ, FIREFLY_PARSER_CONFIG=str(config),
                               FIREFLY_PARSER_WORKDIR=str(root / 'sessions'),
                               FIREFLY_PARSER_LOG_DIR=str(root / 'logs'))
            result = subprocess.run(
                [sys.executable, '-c', 'from app import WORKDIR; assert WORKDIR.is_dir()'],
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
