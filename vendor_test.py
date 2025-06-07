# Simple test script for vendor matching with special characters
from app.database.vendorsdb import VendorsDB

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
    
    print("Testing string sanitization:")
    for test in test_cases:
        sanitized = db.sanitize_for_match(test)
        print(f"  Original: '{test}'")
        print(f"  Sanitized: '{sanitized}'")
        print()

if __name__ == "__main__":
    test_sanitize()
