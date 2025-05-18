from typing import Union, List
import re
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

    # def find_vendor_by_name_or_alias(self, search_str: str):
    #     """
    #     Finds a vendor by matching the input string against the 'name' field or any value in the 'aliases' array.
    #     """
    #     return self.vendors.find_one({
    #         "$or": [
    #             {"name": search_str},
    #             {"aliases": search_str}
    #         ]
    #     })

    def find_vendor_by_name_or_alias(self, search_str: str):
        return self.vendors.find_one({
            "$or": [
                {"name": {"$regex": f"^{re.escape(search_str)}$", "$options": "i"}},
                {"aliases": {"$regex": f"^{re.escape(search_str)}$", "$options": "i"}}
            ]
            })

    def find_vendor_by_firefly_account_id(self, account_id):
        return self.vendors.find_one({
            "firefly_account_id": account_id
        })

    def delete_vendor_by_firefly_account_id(self, account_id):
        """
        Deletes a vendor from the database by Firefly account ID.
        
        Args:
            account_id: The Firefly account ID of the vendor to delete.
            
        Returns:
            The delete result object.
        """
        return self.vendors.delete_one({
            "firefly_account_id": account_id
        })
        
    def get_all_firefly_account_ids(self) -> List[str]:
        """
        Returns a list of all Firefly account IDs in the database.
        
        Returns:
            A list of strings, where each string is a Firefly account ID.
        """
        result = self.vendors.find({"firefly_account_id": {"$exists": True}}, {"firefly_account_id": 1})
        return [vendor["firefly_account_id"] for vendor in result if vendor.get("firefly_account_id")]
        
    def delete_vendor_by_firefly_account_id(self, account_id):
        """
        Deletes a vendor from the database by Firefly account ID.
        
        Args:
            account_id: The Firefly account ID of the vendor to delete.
            
        Returns:
            The delete result object.
        """
        return self.vendors.delete_one({
            "firefly_account_id": account_id
        })
        
    def get_all_firefly_account_ids(self) -> List[str]:
        """
        Returns a list of all Firefly account IDs in the database.
        
        Returns:
            A list of strings, where each string is a Firefly account ID.
        """
        result = self.vendors.find({"firefly_account_id": {"$exists": True}}, {"firefly_account_id": 1})
        return [vendor["firefly_account_id"] for vendor in result if vendor.get("firefly_account_id")]

    def vendor_has_alias(self, vendor_name: str, alias: str) -> bool:
        """
        Checks if the vendor with the given name already has the specified alias.
        """
        vendor = self.vendors.find_one(
            {"name": vendor_name, "aliases": alias}
        )
        return vendor is not None

    def count_vendors(self) -> int:
        """
        Returns the total number of vendors in the database.
        """
        return self.vendors.count_documents({})

    def count_aliases(self) -> int:
        """
        Returns the total number of aliases across all vendors in the database.
        """
        pipeline = [
            {"$project": {"aliases": 1}},
            {"$unwind": "$aliases"},
            {"$group": {"_id": None, "count": {"$sum": 1}}}
        ]
        result = list(self.vendors.aggregate(pipeline))
        return result[0]["count"] if result else 0

