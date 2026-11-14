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

AI_PROVIDER = os.environ.get('AI_PROVIDER', 'groq').strip().lower()
if AI_PROVIDER not in ('groq', 'openrouter'):
    raise RuntimeError("AI_PROVIDER must be either 'groq' or 'openrouter'.")
AI_PROVIDER_NAME = {'groq': 'Groq', 'openrouter': 'OpenRouter'}[AI_PROVIDER]

# Environment variables override config.ini, including explicitly blank values.
GROQ_API_KEY = os.environ.get('GROQ_API_KEY', config.get('ai', 'groq_api_key', fallback='')).strip()
GROQ_MODEL = os.environ.get('GROQ_MODEL', config.get('ai', 'model', fallback='qwen/qwen3.8-27b')).strip()
OPENROUTER_API_KEY = os.environ.get(
    'OPENROUTER_API_KEY', config.get('ai', 'openrouter_api_key', fallback='')
).strip()
OPENROUTER_MODEL = os.environ.get(
    'OPENROUTER_MODEL', config.get('ai', 'openrouter_model', fallback='')
).strip()
if AI_PROVIDER == 'groq':
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY (or ai.groq_api_key) must not be blank when AI_PROVIDER=groq.")
    if not GROQ_MODEL:
        raise RuntimeError("GROQ_MODEL (or ai.model) must not be blank when AI_PROVIDER=groq.")
else:
    if not OPENROUTER_API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY (or ai.openrouter_api_key) must not be blank when AI_PROVIDER=openrouter.")
    if not OPENROUTER_MODEL:
        raise RuntimeError("OPENROUTER_MODEL (or ai.openrouter_model) must not be blank when AI_PROVIDER=openrouter.")


def _groq_limit(setting, default):
    # Inactive Groq settings must not prevent OpenRouter from starting.
    if AI_PROVIDER != 'groq':
        return default
    try:
        value = config.getint('ai', setting, fallback=default)
    except ValueError as error:
        raise RuntimeError(f"ai.{setting} must be an integer.") from error
    if value < 1:
        raise RuntimeError(f"ai.{setting} must be at least 1.")
    return value


GROQ_REQUESTS_PER_MINUTE = _groq_limit('requests_per_minute', 30)
GROQ_TOKENS_PER_MINUTE = _groq_limit('tokens_per_minute', 8000)
GROQ_TOKENS_PER_DAY = _groq_limit('tokens_per_day', 200000)
GROQ_IMAGE_TOKENS = _groq_limit('image_tokens', 2048)

# Import after configuration is loaded. FireflyParserBotClient imports `app`
# for runtime settings, so importing it above would create a circular import.
from app.fireflybot import FireflyParserBot as FireflyParserBotClient  # noqa: E402

FireflyParserBot = FireflyParserBotClient(
    __version__,
    api_id=TELEGRAM_API_ID,
    api_hash=TELEGRAM_API_HASH,
    bot_token=TELEGRAM_BOT_TOKEN,
)
