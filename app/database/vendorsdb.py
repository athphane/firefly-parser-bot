from typing import Union
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
        
        Args:
            vendor_name: The name of the vendor to add the alias to
            alias: The alias to add
            
        Returns:
            The updated vendor document
        """
        # Check if alias already exists (exact or normalized match)
        if self.vendor_has_alias(vendor_name, alias):
            # If it already exists, just return the vendor without changes
            return self.vendors.find_one({"name": vendor_name})
        
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
        """
        Finds a vendor by matching the input string against the 'name' field or any value in the 'aliases' array.
        Uses both regex and string cleaning approaches to handle special characters.
        
        Args:
            search_str: The search string (vendor name or alias)
            
        Returns:
            The matching vendor document or None if not found
        """
        if not search_str:
            return None
            
        # Try 1: Exact match with case insensitivity (using regex)
        vendor = self.vendors.find_one({
            "$or": [
                {"name": {"$regex": f"^{re.escape(search_str)}$", "$options": "i"}},
                {"aliases": {"$regex": f"^{re.escape(search_str)}$", "$options": "i"}}
            ]
        })
        
        if vendor:
            return vendor
        
        # Try 2: Compare cleaned strings to handle special characters
        cleaned_search = self.clean_string_for_match(search_str)
        if not cleaned_search:  # If cleaning removed everything meaningful
            return None
            
        # Get all vendors to compare cleaned strings
        all_vendors = list(self.vendors.find({}))
        
        for vendor in all_vendors:
            # Compare cleaned name
            vendor_name = vendor.get('name', '')
            if self.clean_string_for_match(vendor_name) == cleaned_search:
                return vendor
                
            # Compare cleaned aliases
            for alias in vendor.get('aliases', []):
                if self.clean_string_for_match(alias) == cleaned_search:
                    return vendor
                    
        return None

    def find_vendor_by_firefly_account_id(self, account_id):
        return self.vendors.find_one({
            "firefly_account_id": account_id
        })

    def clean_string_for_match(self, input_string: str) -> str:
        """
        Cleans a string for comparison by converting to lowercase and removing non-alphanumeric characters.
        """
        if not isinstance(input_string, str):
            return ""
        # Convert to lowercase and remove non-alphanumeric characters
        cleaned_string = re.sub(r'[^a-z0-9]', '', input_string.lower())
        return cleaned_string

    def get_all_firefly_account_ids(self) -> list:
        """
        Returns a list of all unique firefly_account_id values from the vendors collection.
        """
        return self.vendors.distinct("firefly_account_id")

    def vendor_has_alias(self, vendor_name: str, alias: str) -> bool:
        """
        Checks if a vendor already has a specific alias, considering both exact and cleaned string matches.
        """
        vendor = self.find_vendor_by_title(vendor_name)
        if not vendor:
            return False

        existing_aliases = vendor.get('aliases', [])
        cleaned_new_alias = self.clean_string_for_match(alias)

        for existing_alias in existing_aliases:
            if existing_alias == alias or self.clean_string_for_match(existing_alias) == cleaned_new_alias:
                return True
        return False

    def delete_vendor_by_firefly_account_id(self, account_id: int):
        """
        Deletes a vendor by its Firefly account ID.
        """
        return self.vendors.delete_one({"firefly_account_id": account_id})

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
            {"$unwind": "$aliases"},
            {"$count": "totalAliases"}
        ]
        result = list(self.vendors.aggregate(pipeline))
        return result[0]["totalAliases"] if result else 0

    

