import pymongo

from app import MONGO_DB_AUTH_SOURCE, MONGO_DB_NAME, MONGO_PASSWORD, MONGO_URL, MONGO_USERNAME


def database():
    """Created Database connection"""
    options = {
        "username": MONGO_USERNAME,
        "password": MONGO_PASSWORD,
    }
    if MONGO_DB_AUTH_SOURCE:
        options["authSource"] = MONGO_DB_AUTH_SOURCE

    client = pymongo.MongoClient(MONGO_URL, **options)
    db = client[MONGO_DB_NAME]
    return db
