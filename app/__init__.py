# Logging at the start to catch everything
import logging
import os
from configparser import ConfigParser
from logging.handlers import TimedRotatingFileHandler

from app.fireflybot import FireflyParserBot

# Logging
os.makedirs('logs', exist_ok=True)
log_handlers = [logging.StreamHandler()]
file_logging_error = None
try:
    log_handlers.insert(
        0,
        TimedRotatingFileHandler(
            'logs/app.log',
            when="midnight",
            encoding='utf-8',
            backupCount=10,
        ),
    )
except OSError as error:
    file_logging_error = error

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=log_handlers,
)
LOGS = logging.getLogger(__name__)
if file_logging_error:
    LOGS.warning(
        "File logging is unavailable; continuing with console logging: %s",
        file_logging_error,
    )

__version__ = '1.0.0'
__author__ = 'athphane'

# Read from config file
config = ConfigParser()
if not config.read('config.ini'):
    raise RuntimeError("Missing config.ini. Copy config.ini.example and configure it before starting the bot.")

# Telegram Config
TELEGRAM_API_ID = config.get('pyrogram', 'api_id')
TELEGRAM_API_HASH = config.get('pyrogram', 'api_hash')
TELEGRAM_BOT_TOKEN = config.get('pyrogram', 'bot_token')
try:
    TELEGRAM_ADMINS = [
        int(admin.strip())
        for admin in config.get('pyrogram', 'admins').split(',')
        if admin.strip()
    ]
except ValueError as error:
    raise RuntimeError("pyrogram.admins must be a comma-separated list of Telegram user IDs.") from error
if not TELEGRAM_ADMINS:
    raise RuntimeError("pyrogram.admins must contain at least one Telegram user ID.")

# MongoDB Config
MONGO_URL = config.get('mongo', 'url')
MONGO_USERNAME = config.get('mongo', 'username')
MONGO_PASSWORD = config.get('mongo', 'password')
MONGO_DB_NAME = config.get('mongo', 'db_name', fallback='firefly_sms_parser')
MONGO_DB_AUTH_SOURCE = config.get('mongo', 'auth_source', fallback='').strip() or None

# Firefly Config
FIREFLY_BASE_URL = config.get('firefly', 'url')
FIREFLY_API_KEY = config.get('firefly', 'api_key')
FIREFLY_DEFAULT_ACCOUNT_ID = config.getint('firefly', 'default_account_id')
FIREFLY_REQUEST_TIMEOUT = config.getfloat('firefly', 'request_timeout', fallback=30.0)

GROQ_API_KEY = config.get('ai', 'groq_api_key')
GROQ_MODEL = config.get('ai', 'model', fallback='qwen/qwen3.8-27b').strip()
if not GROQ_MODEL:
    raise RuntimeError("ai.model must not be blank.")

FireflyParserBot = FireflyParserBot(__version__, api_id=TELEGRAM_API_ID, api_hash=TELEGRAM_API_HASH,
                                    bot_token=TELEGRAM_BOT_TOKEN)
