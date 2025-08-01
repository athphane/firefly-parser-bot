# Firefly Parser Bot

## Overview

The `firefly-parser-bot` is a Python-based Telegram bot designed to automate the process of tracking personal finances by integrating with [Firefly III](https://www.firefly-iii.org/), a powerful open-source financial manager. This bot allows you to effortlessly log your transactions by simply forwarding SMS messages from your bank directly to the bot. It parses the transaction details and creates corresponding records in your Firefly III instance via its API.

## Features

*   **SMS Transaction Parsing:** Automatically extracts key information like amount, currency, vendor, and transaction type from bank SMS messages.
*   **Firefly III Integration:** Seamlessly creates new transactions in your Firefly III instance.
*   **Vendor Mapping:** Maps parsed vendor names to pre-configured Firefly III asset accounts for accurate categorization.
*   **Telegram Interface:** Interact with the bot directly through Telegram for convenience and real-time feedback.
*   **Extensible Plugin System:** Modular design allows for easy addition of new parsing rules or functionalities.

## How it Works

1.  **Forward SMS:** You forward a transaction SMS from your bank to the Telegram bot.
2.  **Parse & Extract:** The bot utilizes a sophisticated parsing engine (`transaction_parser.py`) to identify and extract crucial details from the SMS text.
3.  **Categorize & Map:** It queries a local database (`vendorsdb.py`) to match the extracted vendor/merchant name with your defined Firefly III asset accounts.
4.  **Create Transaction:** The bot then communicates with your Firefly III instance via its API (`firefly.py`) to create a new transaction record.
5.  **Confirmation:** You receive instant feedback on Telegram, confirming the successful creation of the transaction or notifying you of any issues.

## Setup and Installation

To get the Firefly Parser Bot up and running, follow these steps:

### Prerequisites

*   A running instance of [Firefly III](https://www.firefly-iii.org/).
*   A Telegram Bot Token (obtainable from BotFather on Telegram).
*   Python 3.8 or higher.

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
    *   `[telegram]`: Add your `bot_token`.
    *   `[firefly]`: Provide your `firefly_iii_url` and `firefly_iii_api_token`.
    *   `[database]`: Configure your database settings (e.g., SQLite path).
    *   Adjust other parameters like `default_currency` as needed.

4.  **Run the Bot:**
    ```bash
    python -m app
    ```
    Your bot should now be running and accessible via Telegram.

## Project Structure

*   `app/fireflybot.py`: Main application entry point and Telegram bot initialization.
*   `app/plugins/`: Contains modular functionalities (e.g., `transaction_parser.py`, `vendors.py`).
*   `app/firefly/firefly.py`: Handles all interactions with the Firefly III API.
*   `app/database/vendorsdb.py`: Manages the local vendor mapping database.
*   `config.ini.example`: Example configuration file.
*   `requirements.txt`: Lists all Python dependencies.

## Contributing

Contributions are welcome! Please feel free to open issues or submit pull requests.

## License

This project is licensed under the GNU General Public License v3.0 - see the LICENSE file for details.
