# Logging at the start to catch everything
import logging
from configparser import ConfigParser
from logging.handlers import TimedRotatingFileHandler

from app.fireflybot import FireflyParserBot

# Logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        TimedRotatingFileHandler('logs/app.log', when="midnight", encoding=None,
                                 delay=False, backupCount=10),
        logging.StreamHandler()
    ]
)
LOGS = logging.getLogger(__name__)

__version__ = '1.0.0'
__author__ = 'athphane'

# Read from config file
config = ConfigParser()
config.read('config.ini')

# Telegram Config
TELEGRAM_API_ID = config.get('pyrogram', 'api_id')
TELEGRAM_API_HASH = config.get('pyrogram', 'api_hash')
TELEGRAM_BOT_TOKEN = config.get('pyrogram', 'bot_token')
TELEGRAM_ADMINS = config.get('pyrogram', 'admins').split(',')
TELEGRAM_ADMINS = [int(x) for x in TELEGRAM_ADMINS]

# MongoDB Config
MONGO_URL = config.get('mongo', 'url')
MONGO_USERNAME = config.get('mongo', 'username')
MONGO_PASSWORD = config.get('mongo', 'password')
MONGO_DB_NAME = config.get('mongo', 'db_name', fallback='firefly_sms_parser')
MONGO_DB_AUTH_SOURCE = config.get('mongo', 'auth_source')

# Firefly Config
FIREFLY_BASE_URL = config.get('firefly', 'url')
FIREFLY_API_KEY = config.get('firefly', 'api_key')
FIREFLY_DEFAULT_ACCOUNT_ID = config.getint('firefly', 'default_account_id')

GROQ_API_KEY = config.get('ai', 'groq_api_key')

FireflyParserBot = FireflyParserBot(__version__, api_id=TELEGRAM_API_ID, api_hash=TELEGRAM_API_HASH,
                                    bot_token=TELEGRAM_BOT_TOKEN)
