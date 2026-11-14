"""Shared isolated configuration for tests; no production credentials or services."""

import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

TEST_RUNTIME = TemporaryDirectory()
TEST_ROOT = Path(TEST_RUNTIME.name)
TEST_CONFIG = TEST_ROOT / "config.ini"
TEST_CONFIG.write_text(
    """[pyrogram]
api_id = 1
api_hash = test
bot_token = 1:test
admins = 1

[mongo]
url = localhost:27017
username = test
password = test
db_name = test

[firefly]
url = https://firefly.example
api_key = test
default_account_id = 1
request_timeout = 1

[ai]
groq_api_key = test
model = test
max_concurrency = 2
""",
    encoding="utf-8",
)
os.environ["FIREFLY_PARSER_CONFIG"] = str(TEST_CONFIG)
os.environ["FIREFLY_PARSER_WORKDIR"] = str(TEST_ROOT / "workdir")
os.environ["FIREFLY_PARSER_LOG_DIR"] = str(TEST_ROOT / "logs")
for name in ('GROQ_API_KEY', 'GROQ_MODEL', 'OPENROUTER_API_KEY', 'OPENROUTER_MODEL', 'AI_MAX_CONCURRENCY'):
    os.environ.pop(name, None)
os.environ['AI_PROVIDER'] = 'groq'


class FakeCompletion:
    def __init__(self, content):
        self.choices = [SimpleNamespace(message=SimpleNamespace(content=content))]

    def model_dump_json(self, indent=2):
        return json.dumps({"choices": []}, indent=indent)
