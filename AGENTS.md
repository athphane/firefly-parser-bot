# AGENTS.md

## Quick commands (verified)
- Install deps: `pip install -r requirements.txt`
- Run bot locally: `python -m app`
- Run with Docker services: `docker compose up --build` (starts app + MongoDB)
- Run tests: `python -m unittest discover -s tests -v`
- There is no configured lint/typecheck toolchain in repo config.

## Config + runtime gotchas
- `app/__init__.py` reads `config.ini` at import time; most modules import `app`, so missing/invalid config fails early.
- `TELEGRAM_ADMINS` requires at least one comma-separated integer ID; invalid/empty lists fail with a configuration error.
- Logging creates `logs/` and writes `logs/app.log` via `TimedRotatingFileHandler`, falling back to console logging if the directory is unwritable.
- `config.ini`, `logs/`, and `workdir/` default to repository-relative paths and support `FIREFLY_PARSER_*` environment overrides. Startup creates the session directory.
- Local DB authentication honors `mongo.auth_source`; use `admin` for the bundled Docker MongoDB root user.

## Real entrypoints and structure
- Process entrypoint is `app/__main__.py` -> `FireflyParserBot.run()`.
- Bot client is configured in `app/fireflybot.py` with Pyrogram plugin autoload from `app/plugins`, a configured session directory, and `AI_MAX_CONCURRENCY` dispatcher workers (defaults: Groq 1, OpenRouter 4; `[ai] max_concurrency` fallback).
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
- Run tests with `venv/bin/python -m unittest discover -s tests -v` when `python` is unavailable. Tests use isolated configuration and mocked external services.
- Receipt attachments use transaction journal IDs; transaction links use group IDs. Upload file bodies as raw binary, never multipart.
- Customization only supports groups with one split. Edit groups with multiple splits directly in Firefly to avoid dropping other splits.
