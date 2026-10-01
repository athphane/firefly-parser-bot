import pymongo
from functools import lru_cache

from app import MONGO_DB_AUTH_SOURCE, MONGO_DB_NAME, MONGO_PASSWORD, MONGO_URL, MONGO_USERNAME


@lru_cache(maxsize=1)
def mongo_client() -> pymongo.MongoClient:
    """Return one process-wide, thread-safe MongoDB connection pool."""
    options = {
        "serverSelectionTimeoutMS": 10_000,
    }
    # Blank credentials support unauthenticated servers and credentials in URI.
    if MONGO_USERNAME:
        options.update(username=MONGO_USERNAME, password=MONGO_PASSWORD)
    if MONGO_DB_AUTH_SOURCE:
        options["authSource"] = MONGO_DB_AUTH_SOURCE

    return pymongo.MongoClient(MONGO_URL, **options)


def database():
    """Return the configured application database."""
    return mongo_client()[MONGO_DB_NAME]
