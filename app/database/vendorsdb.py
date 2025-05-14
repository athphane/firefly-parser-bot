from typing import Union

from pymongo import ReturnDocument

from app.database import database


class VendorsDB:
    def __init__(self):
        self.vendors = database()["vendors"]

    def find_vendor_by_title(self, title: str):
        return self.vendors.find_one({"name": title})

    def exists(self, title: str):
        return bool(self.find_vendor_by_title(title))

    def add_vendor(
            self,
            name: str,
            description: Union[str, None] = None,
            firefly_account_id: Union[int, None] = None,
    ):
        return self.vendors.insert_one(
            {
                "name": name,
                "description": description,
                "firefly_account_id": firefly_account_id,
            }
        )

    def add_alias_to_vendor(self, vendor_name: str, alias: str):
        """
        Adds an alias to the vendor's 'aliases' JSON column (list).
        Ensures that a duplicate alias will NOT be added to the record.
        Creates the 'aliases' field if it does not exist.
        """
        # $addToSet ensures no duplicates are added to the array
        return self.vendors.find_one_and_update(
            {"name": vendor_name},
            {"$addToSet": {"aliases": alias}},
            return_document=ReturnDocument.AFTER
        )

    def find_vendor_by_name_or_alias(self, search_str: str):
        """
        Finds a vendor by matching the input string against the 'name' field or any value in the 'aliases' array.
        """
        return self.vendors.find_one({
            "$or": [
                {"name": search_str},
                {"aliases": search_str}
            ]
        })

    def find_vendor_by_firefly_account_id(self, account_id):
        return self.vendors.find_one({
            "firefly_account_id": account_id
        })

