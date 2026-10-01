# Logging at the start to catch everything
import logging
import math
import os
from configparser import ConfigParser, Error as ConfigError
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from decimal import Decimal, InvalidOperation

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = Path(os.environ.get("FIREFLY_PARSER_CONFIG", BASE_DIR / "config.ini")).expanduser()
WORKDIR = Path(os.environ.get("FIREFLY_PARSER_WORKDIR", BASE_DIR / "workdir")).expanduser()
LOG_DIR = Path(os.environ.get("FIREFLY_PARSER_LOG_DIR", BASE_DIR / "logs")).expanduser()

# Logging
log_handlers = [logging.StreamHandler()]
file_logging_error = None
try:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_handlers.insert(
        0,
        TimedRotatingFileHandler(
            LOG_DIR / 'app.log',
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
config = ConfigParser(interpolation=None)
try:
    loaded_config = config.read(CONFIG_PATH)
except (OSError, ConfigError) as error:
    raise RuntimeError(f"Could not read configuration from {CONFIG_PATH}: {error}") from error
if not loaded_config:
    raise RuntimeError(
        f"Missing {CONFIG_PATH}. Copy config.ini.example and configure it before starting the bot."
    )

# Telegram Config
TELEGRAM_API_ID = config.getint('pyrogram', 'api_id')
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
if not math.isfinite(FIREFLY_REQUEST_TIMEOUT) or FIREFLY_REQUEST_TIMEOUT <= 0:
    raise RuntimeError("firefly.request_timeout must be greater than zero.")
FIREFLY_ERROR_ON_DUPLICATE = config.getboolean(
    'firefly', 'error_on_duplicate', fallback=True
)

LOCAL_CURRENCY = config.get('exchange_rates', 'local_currency', fallback='MVR').strip().upper()
if not LOCAL_CURRENCY:
    raise RuntimeError("exchange_rates.local_currency must not be blank.")
EXCHANGE_RATES = {LOCAL_CURRENCY: Decimal('1')}
# Preserve the historical MVR defaults for existing configurations. New
# installations expose them explicitly in config.ini.example.
if LOCAL_CURRENCY == 'MVR':
    EXCHANGE_RATES.update({
        'USD': Decimal('15.42'),
        'EUR': Decimal('16.20'),
    })
if config.has_section('exchange_rates'):
    for currency, raw_rate in config.items('exchange_rates'):
        currency = currency.strip().upper()
        if currency == 'LOCAL_CURRENCY':
            continue
        try:
            rate = Decimal(raw_rate.strip())
        except InvalidOperation as error:
            raise RuntimeError(f"exchange_rates.{currency} must be a valid number.") from error
        if not rate.is_finite() or rate <= 0:
            raise RuntimeError(f"exchange_rates.{currency} must be greater than zero.")
        if currency == LOCAL_CURRENCY and rate != 1:
            raise RuntimeError("The exchange rate for the local currency must be 1.")
        EXCHANGE_RATES[currency] = rate

GROQ_API_KEY = config.get('ai', 'groq_api_key')
GROQ_MODEL = config.get('ai', 'model', fallback='qwen/qwen3.8-27b').strip()
if not GROQ_MODEL:
    raise RuntimeError("ai.model must not be blank.")
GROQ_REQUESTS_PER_MINUTE = config.getint('ai', 'requests_per_minute', fallback=30)
GROQ_TOKENS_PER_MINUTE = config.getint('ai', 'tokens_per_minute', fallback=8000)
GROQ_TOKENS_PER_DAY = config.getint('ai', 'tokens_per_day', fallback=200000)
GROQ_IMAGE_TOKENS = config.getint('ai', 'image_tokens', fallback=2048)
for setting, value in (
    ('requests_per_minute', GROQ_REQUESTS_PER_MINUTE),
    ('tokens_per_minute', GROQ_TOKENS_PER_MINUTE),
    ('tokens_per_day', GROQ_TOKENS_PER_DAY),
    ('image_tokens', GROQ_IMAGE_TOKENS),
):
    if value < 1:
        raise RuntimeError(f"ai.{setting} must be at least 1.")

# Import after configuration is loaded. FireflyParserBotClient imports `app`
# for runtime settings, so importing it above would create a circular import.
from app.fireflybot import FireflyParserBot as FireflyParserBotClient  # noqa: E402

FireflyParserBot = FireflyParserBotClient(
    __version__,
    api_id=TELEGRAM_API_ID,
    api_hash=TELEGRAM_API_HASH,
    bot_token=TELEGRAM_BOT_TOKEN,
)
