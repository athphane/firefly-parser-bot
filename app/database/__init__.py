import pymongo

from app import MONGO_URL, MONGO_USERNAME, MONGO_PASSWORD, MONGO_DB_NAME


def database():
    """Created Database connection"""
    client = pymongo.MongoClient(
        MONGO_URL,
        username=MONGO_USERNAME,
        password=MONGO_PASSWORD
    )
    db = client[MONGO_DB_NAME]
    return db
