# Firefly Parser Bot

## Overview

The `firefly-parser-bot` is a Python-based Telegram bot designed to automate the process of tracking personal finances by integrating with [Firefly III](https://www.firefly-iii.org/), a powerful open-source financial manager. This bot allows you to effortlessly log your transactions by simply forwarding SMS messages from your bank directly to the bot. It parses the transaction details and creates corresponding records in your Firefly III instance via its API.

## Features

*   **SMS Transaction Parsing:** Automatically extracts key information like amount, currency, vendor, and transaction type from bank SMS messages.
*   **Firefly III Integration:** Seamlessly creates new transactions in your Firefly III instance.
*   **Vendor Mapping:** Maps parsed vendor names to Firefly III expense accounts for accurate categorization.
*   **Telegram Interface:** Interact with the bot directly through Telegram for convenience and real-time feedback.
*   **Extensible Plugin System:** Modular design allows for easy addition of new parsing rules or functionalities.

## How it Works

1.  **Forward SMS:** You forward a transaction SMS from your bank to the Telegram bot.
2.  **Parse & Extract:** The bot utilizes a sophisticated parsing engine (`transaction_parser.py`) to identify and extract crucial details from the SMS text.
3.  **Categorize & Map:** It queries a local database (`vendorsdb.py`) to match the extracted vendor/merchant name with your defined Firefly III expense accounts.
4.  **Create Transaction:** The bot then communicates with your Firefly III instance via its API (`firefly.py`) to create a new transaction record.
5.  **Confirmation:** You receive instant feedback on Telegram, confirming the successful creation of the transaction or notifying you of any issues.

## Setup and Installation

To get the Firefly Parser Bot up and running, follow these steps:

### Prerequisites

*   A running instance of [Firefly III](https://www.firefly-iii.org/).
*   A Telegram Bot Token (obtainable from BotFather on Telegram).
*   Python 3.12 or higher.
*   MongoDB (included when using Docker Compose).
*   A Groq or OpenRouter API key.

### Installation Steps

1.  **Clone the Repository:**
    ```bash
    git clone https://github.com/your-username/firefly-parser-bot.git
    cd firefly-parser-bot
    ```

2.  **Install Dependencies:**
    It's recommended to use a virtual environment.
    ```bash
    python -m venv venv
    source venv/bin/activate  # On Windows, use `venv\Scripts\activate`
    pip install -r requirements.txt
    ```

3.  **Configure the Bot:**
    Copy the example configuration file and fill in your details:
    ```bash
    cp config.ini.example config.ini
    ```
    Open `config.ini` and update the following sections:
    *   `[pyrogram]`: Add your Telegram API credentials, bot token, and comma-separated admin user IDs.
    *   `[mongo]`: Configure the MongoDB connection and optional authentication source.
    *   `[firefly]`: Provide your Firefly III URL, API key, default account, and request timeout.
    *   `[exchange_rates]`: Configure the local currency and local-currency value of each supported foreign currency. Unknown currencies are rejected instead of being recorded at a false 1:1 rate.
    *   `[ai]`: Configure the selected AI provider as described below. Existing Groq configurations continue to work.

4.  **Run the Bot:**
    ```bash
    python -m app
    ```
    Your bot should now be running and accessible via Telegram.

    The bot resolves `config.ini`, `logs/`, and `workdir/` relative to the
    repository directory, so it can be launched from another working directory.
    Set `FIREFLY_PARSER_CONFIG`, `FIREFLY_PARSER_WORKDIR`, or
    `FIREFLY_PARSER_LOG_DIR` to override those locations.

    AI concurrency is configurable with `AI_MAX_CONCURRENCY` or `[ai] max_concurrency`.
    Without an explicit setting, Groq defaults to one call and OpenRouter to four.
    The same setting controls Telegram update workers, so multiple messages can
    make progress together. With values above one, replies and transaction
    creation can finish out of order. Set it to `1` for sequential processing.
    Text and receipt extraction share the concurrency cap.

    When using Groq, text and receipt extraction also share a rate limiter. Before each
    attempt it reserves a conservative input estimate plus the maximum output,
    then replaces that reservation with the completion's reported token usage.
    Calls wait until both the minute and daily budgets have room. Daily usage
    uses a rolling 24-hour window; reaching that budget can delay queued
    Groq calls until earlier usage expires. Oversized messages are rejected without
    calling Groq. Waits are recorded in the application log.

    Usage and cooldowns are saved in `workdir/groq-rate-limit.json`, so keep
    that file across restarts. Run one bot instance with this state directory.
    Other applications using the same Groq organization can still consume its
    shared limits. On a 429 response, the bot honors `Retry-After` and retries
    through the limiter, up to three total attempts
    ([Groq rate limit documentation](https://console.groq.com/docs/rate-limits)).
    Existing configurations receive the default rate budgets automatically.
    The `max_concurrency` setting is supported again; raising it still respects
    Groq's request and token budgets.

### AI provider selection

Set `AI_PROVIDER` to `groq` or `openrouter` in the process environment and restart
the bot to switch providers. It defaults to `groq`. Environment variables take
precedence over `config.ini`; only the selected provider needs credentials and a
model. Other bot settings still come from `config.ini`.

| Environment variable | Config fallback | Purpose |
| --- | --- | --- |
| `AI_PROVIDER` | Defaults to `groq` | Select `groq` or `openrouter` |
| `AI_MAX_CONCURRENCY` | `[ai] max_concurrency` | Positive integer; defaults to `1` for Groq, `4` for OpenRouter |
| `GROQ_API_KEY` | `[ai] groq_api_key` | Groq API key |
| `GROQ_MODEL` | `[ai] model` | Groq model; defaults to `qwen/qwen3.8-27b` |
| `OPENROUTER_API_KEY` | `[ai] openrouter_api_key` | OpenRouter API key |
| `OPENROUTER_MODEL` | `[ai] openrouter_model` | Required OpenRouter model ID, including its provider prefix |

For example, after setting `OPENROUTER_API_KEY` securely in your environment:

```bash
export AI_PROVIDER=openrouter
export OPENROUTER_MODEL=openai/gpt-4o-mini
export AI_MAX_CONCURRENCY=8
python -m app
```

Restart the bot after changing concurrency. Omit `AI_MAX_CONCURRENCY` to use the
config value or the provider default.

Choose an OpenRouter model that supports JSON output and, for receipt extraction,
image input. The same model handles text and receipts. OpenRouter requests use
its [OpenAI-compatible API](https://openrouter.ai/docs/guides/community/openai-sdk)
and require a provider endpoint supporting the requested parameters. Each attempt
has a 60-second timeout, with up to two SDK retries for temporary failures,
including rate limits. No Groq request/token budgets or usage files are used for
OpenRouter. OpenRouter and upstream provider limits, credits, and billing still
apply; linking a Groq key through OpenRouter does not remove that key's limits.

For Groq, set `AI_PROVIDER=groq` and optionally `GROQ_API_KEY` and `GROQ_MODEL`.
Its `[ai]` rate limits default to `requests_per_minute = 30`,
`tokens_per_minute = 8000`, and `tokens_per_day = 200000`. Set `image_tokens`
for your model's receipt image cost; the default is `2048` for
`qwen/qwen3.8-27b` ([Groq vision documentation](https://console.groq.com/docs/vision)).

Docker Compose passes the same environment variables to the app container.
Export them before starting or recreating it:

```bash
docker compose up -d --build app
```

Recreate the container after changing environment variables; `docker compose restart`
does not update the container environment. Credentials and model IDs can also be
kept in `config.ini`, with only `AI_PROVIDER` set in the environment.

### Docker runtime permissions

For the bundled Compose stack, set `[mongo]` `url = mongodb:27017` and
`auth_source = admin` in `config.ini`. The `mongodb` service name stays the
same when the container is renamed. The network also retains the legacy
`firefly_parser_bot_mongodb` alias for existing configurations. If logs report
name resolution failures for that old hostname, update the URL and run
`docker compose restart app` to reload the configuration.

MongoDB data is stored in the Compose `mongo-data` volume. Keep this volume
across rebuilds; `docker compose down -v` removes it.

When upgrading an existing installation that used MongoDB's anonymous volume,
back it up before recreating the database container. Stop the bot, export the
database, then restore it into the new named volume:

```bash
docker compose stop app
docker compose exec -T mongodb mongodump --username admin --password password --authenticationDatabase admin --archive > mongo-backup.archive
docker compose up -d --wait mongodb
docker compose exec -T mongodb mongorestore --username admin --password password --authenticationDatabase admin --archive < mongo-backup.archive
```

Use your configured MongoDB credentials if they differ from the bundled defaults.
Keep the backup until you have verified the restored vendor mappings.

Start or rebuild the Compose services with:

```bash
docker compose up -d --build
```

The container entrypoint starts as root to make the mounted `workdir/`, `logs/`,
and `downloads/` directories and existing files writable by the `app` user
(UID/GID 1000). It then switches to that user before starting the bot. This
repairs ownership left by earlier containers and preserves the Telegram session,
SQLite journal files, logs, and Groq usage state. Runtime path overrides for
`FIREFLY_PARSER_WORKDIR` and `FIREFLY_PARSER_LOG_DIR` are also honored.

If you override the container user, prepare the mounted directories and files
for that user on the host; startup cannot repair ownership without root access.

Transaction customization supports groups containing one transaction split.
Edit groups with multiple splits directly in Firefly III. Amount edits preserve
the journal ID and foreign currency, and reject amounts that round to zero.
Receipt attachments use the journal ID and Firefly's binary upload endpoint.
Income confirmations expire after a successful Firefly write even if Telegram
cannot display the result; retries after a failed request reuse the original date
for duplicate protection.

### Tests

Run the automated unit tests without requiring live Telegram, MongoDB, Firefly,
or AI provider connections:

```bash
python -m unittest discover -s tests -v
```

## Project Structure

*   `app/__main__.py`: Process entry point (`python -m app`).
*   `app/fireflybot.py`: Telegram bot initialization.
*   `app/groq_rate_limit.py`: Persistent request and token budgets for Groq.
*   `app/plugins/`: Contains modular functionalities (e.g., `transaction_parser.py`, `vendors.py`).
*   `app/firefly/firefly.py`: Handles all interactions with the Firefly III API.
*   `app/database/vendorsdb.py`: Manages the local vendor mapping database.
*   `config.ini.example`: Example configuration file.
*   `requirements.txt`: Lists all Python dependencies.

## Contributing

Contributions are welcome! Please feel free to open issues or submit pull requests.

## License

This project is licensed under the GNU General Public License v3.0 - see the LICENSE file for details.
