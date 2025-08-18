# Qwen Project Rules: firefly-parser-bot

This document outlines special rules and guidelines for Qwen when working with the `firefly-parser-bot` project.

## Project Overview

The `firefly-parser-bot` is a Python-based Telegram bot that integrates with Firefly III to automatically create transaction records from bank SMS notifications.

## Special Rules

1. **NEVER run `python -m app`**: This command is not valid for this project. The correct way to run the bot is using `python -m app` or directly executing the main module.

2. **Image Attachment Feature**: When an image is used for OCR to extract transaction details, the image should be saved as an attachment to the transaction record in Firefly III. This feature has been implemented by:
   - Adding attachment methods to the Firefly API class
   - Modifying the ParsedTransactionMessage class to handle image attachments
   - Updating the transaction parser to pass image paths when creating transactions from OCR

## Core Components

* **`app/fireflybot.py`**: Main application entry point
* **`app/plugins/transaction_parser.py`**: Parses SMS messages and images to extract transaction data
* **`app/firefly/firefly.py`**: Firefly III API client
* **`app/models/parsed_transaction_message.py`**: Handles transaction creation logic
* **`app/database/vendorsdb.py`**: Manages vendor mappings

## Testing

The project does not currently have pytest tests. Syntax checking can be done with `python -m py_compile` on individual files.