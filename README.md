# Firefly SMS Parser

Firefly SMS Parser is a tool designed to extract and process text from SMS messages, including those embedded in images using Optical Character Recognition (OCR) and AI technologies.

## Features

- Extracts text from SMS messages and images
- Utilizes advanced OCR and AI models for high accuracy
- Easy integration into existing workflows
- Automated processing of transaction messages for Firefly III

## Installation

```bash
git clone https://github.com/athphane/firefly-sms-parser.git
cd firefly-sms-parser
pip install -r requirements.txt
```

## Deployment Guide

### Prerequisites

- Docker and Docker Compose installed
- Telegram API credentials (api_id, api_hash)
- Telegram Bot Token
- Firefly III instance with API key
- Groq API key for AI functionality

### Step 1: Configuration Setup

1. Copy the example configuration file to create your own:
   ```bash
   cp config.ini.example config.ini
   ```

2. Edit the config.ini file with your credentials:
   ```ini
   [pyrogram]
   api_id = YOUR_TELEGRAM_API_ID
   api_hash = YOUR_TELEGRAM_API_HASH
   bot_token = YOUR_TELEGRAM_BOT_TOKEN
   admins = COMMA_SEPARATED_TELEGRAM_USER_IDS
   
   [mongo]
   url = firefly_parser_bot_mongodb:27017
   username = admin
   password = password
   db_name = firefly_sms_parser
   auth_source = admin
   
   [firefly]
   url = https://firefly.your-domain.com
   api_key = YOUR_FIREFLY_API_KEY
   default_account_id = YOUR_ACCOUNT_ID
   
   [ai]
   groq_api_key = YOUR_GROQ_API_KEY
   ```

### Step 2: Create Required Directories

Ensure the following directories exist in your project folder:
```bash
mkdir -p workdir logs downloads
```

### Step 3: Deploy with Docker Compose

1. Start the application using Docker Compose:
   ```bash
   docker-compose up -d
   ```

2. To check if the containers are running correctly:
   ```bash
   docker-compose ps
   ```

3. View application logs:
   ```bash
   docker-compose logs -f app
   ```

### Step 4: Interacting with the Bot

1. Start a chat with your bot on Telegram
2. Send SMS screenshots or forward SMS messages to the bot
3. The bot will process the messages and send the data to your Firefly III instance

### Updating the Application

To update the application to the latest version:

```bash
git pull
docker-compose down
docker-compose build --no-cache
docker-compose up -d
```

### Troubleshooting

If you encounter issues:
- Check the logs in the `logs` directory
- Ensure all API keys and tokens are correct in your config.ini
- Verify your MongoDB container is running properly
- Make sure your Firefly III instance is accessible

## Environmental Impact

> **Note:** Each time an image is processed with OCR and AI, it can consume a significant amount of computational power—sometimes more than what a small village in Africa might use in a day. Please use this tool responsibly and be mindful of its energy consumption.

## Contributing

Contributions are welcome! Please open issues or submit pull requests.

## License

This project is licensed under the MIT License.