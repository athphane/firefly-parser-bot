# Simple test script for vendor matching with special characters
from app.database.vendorsdb import VendorsDB
import logging

LOGS = logging.getLogger(__name__)

def test_sanitize():
    db = VendorsDB()
    test_cases = [
        "McDonald's",
        "Starbucks*Coffee",
        "amazon.com",
        "BEST-BUY",
        "Burger King & Co.",
        "AT&T Store",
        "Walmart #123",
        "7-Eleven",
        "H&M"
    ]
    
    LOGS.info("Testing string sanitization:")
    for test in test_cases:
        sanitized = db.sanitize_for_match(test)
        LOGS.info(f"  Original: '{test}'")
        LOGS.info(f"  Sanitized: '{sanitized}'")

if __name__ == "__main__":
    test_sanitize()
