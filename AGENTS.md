# AGENTS.md

## Quick commands (verified)
- Install deps: `pip install -r requirements.txt`
- Run bot locally: `python -m app`
- Run with Docker services: `docker compose up --build` (starts app + MongoDB)
- There is no configured lint/typecheck/test toolchain in repo config.

## Config + runtime gotchas
- `app/__init__.py` reads `config.ini` at import time; most modules import `app`, so missing/invalid config fails early.
- `TELEGRAM_ADMINS` is parsed as comma-separated ints with no fallback; blank or non-numeric values crash startup.
- Logging writes to `logs/app.log` via `TimedRotatingFileHandler`; ensure `logs/` exists for local non-Docker runs.
- Local DB connection ignores `mongo.auth_source` from `config.ini`; only URL/username/password/db_name are used in `app/database/__init__.py`.

## Real entrypoints and structure
- Process entrypoint is `app/__main__.py` -> `FireflyParserBot.run()`.
- Bot client is configured in `app/fireflybot.py` with Pyrogram plugin autoload from `app/plugins` and `workdir="./workdir"`.
- Transaction creation/parsing flow is centered in:
  - `app/plugins/transaction_parser.py` (Telegram handlers)
  - `app/plugins/transaction_utils.py` (LLM extraction helpers)
  - `app/models/parsed_transaction_message.py` (Firefly transaction payload + submit)
- Firefly API wrapper lives in `app/firefly/firefly.py`; prefer extending `FireflyApi` over ad-hoc `requests` calls.
- Vendor mapping persistence is Mongo-backed in `app/database/vendorsdb.py`.

## Handler-order conventions (easy to break)
- Command handlers use low groups (mostly `group=1`); generic text/photo transaction parsing is in `group=100`.
- Reply/interactive flows rely on propagation control (`stop_propagation`) and in-memory contexts on `FireflyParserBot` attributes.
- When adding new text/reply handlers, keep them ahead of `group=100` parser handlers or explicitly stop propagation, or user replies may be parsed as transactions.

## Known maintenance note
- `vendor_test.py` is a standalone script, not a test framework suite; treat it as manual smoke-check code.
