# Gemini Project Analysis: firefly-parser-bot

This document outlines the key components and functionality of the `firefly-parser-bot` project.

## Project Overview

The `firefly-parser-bot` is a Python-based Telegram bot designed to streamline personal finance tracking by integrating with [Firefly III](https://www.firefly-iii.org/), a popular open-source financial manager. The bot's primary function is to parse transaction details from SMS messages (typically from banks) and automatically create corresponding transaction records in a user's Firefly III instance via its API.

## Core Functionality

The bot's workflow is as follows:

1.  **Receive SMS:** A user forwards a transaction SMS from their bank to the Telegram bot.
2.  **Parse Transaction:** The bot uses a sophisticated parsing plugin (`transaction_parser.py`) to extract key information from the SMS text, such as:
    *   Transaction amount
    *   Currency
    *   Vendor/Merchant name
    *   Transaction type (debit/credit)
3.  **Vendor Matching:** The bot queries a local database (`vendorsdb.py`) to map the parsed vendor/merchant name to a pre-configured Firefly III asset account. This allows for consistent and accurate categorization of expenses.
4.  **Create Transaction:** Using the parsed data, the bot communicates with the user's Firefly III instance via the `firefly.py` module, which acts as an API client.
5.  **API Interaction:** The `firefly.py` module sends a request to the Firefly III API to create a new transaction with the details gathered in the previous steps.
6.  **User Feedback:** The bot provides feedback to the user on Telegram, confirming the successful creation of the transaction or reporting any errors.

## Key Modules and Components

*   **`app/fireflybot.py`**: The main application entry point. It initializes the `python-telegram-bot` framework, loads all plugins from the `app/plugins/` directory, and starts the bot's event loop.

*   **`app/plugins/`**: This directory contains the core, modular features of the bot. Each file represents a different command or functionality.
    *   **`transaction_parser.py`**: The most critical plugin. It contains the logic for parsing SMS messages to extract transaction data.
    *   **`vendors.py`**: Handles the management of the vendor list, allowing users to add, remove, or list vendors.
    *   **`start.py` & `help.py`**: Basic plugins for user onboarding and assistance.

*   **`app/firefly/firefly.py`**: A dedicated module for all interactions with the Firefly III API. It abstracts the complexities of making API calls, handling authentication, and formatting data for the API endpoints. It uses the `requests` library for HTTP communication.

*   **`app/database/vendorsdb.py`**: This module manages a local database (likely SQLite) to store a mapping between keywords found in SMS messages and the corresponding vendor (asset account) in Firefly III. This is crucial for correctly assigning transactions.

*   **`config.ini.example`**: An example configuration file that outlines the necessary settings for the bot, including:
    *   Telegram Bot API Token
    *   Firefly III instance URL and API credentials
    *   Database settings
    *   Default currency and other operational parameters.

*   **`requirements.txt`**: Lists the project's Python dependencies, which include:
    *   `python-telegram-bot`: For the Telegram bot functionality.
    *   `requests`: For making HTTP requests to the Firefly III API.
    *   `python-dotenv`: For managing environment variables and secrets.

## How to Run the Bot

1.  Install dependencies from `requirements.txt`.
2.  Create a `config.ini` file based on `config.ini.example` and fill in the required API tokens and URLs.
3.  Run the bot using `python -m app`.

This analysis provides a solid foundation for understanding the project's architecture and codebase, which will be useful for any future development, debugging, or feature implementation tasks.
