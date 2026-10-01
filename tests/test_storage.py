"""Regression checks for Firefly transport and vendor persistence."""

from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from tests import support
import app.database as database_module
from app.database.vendorsdb import VendorsDB
from app.firefly.firefly import FireflyApi
from app.plugins import vendors


def message(user_id=1, text='New alias', reply_id=10):
    return SimpleNamespace(
        id=20, from_user=SimpleNamespace(id=user_id), chat=SimpleNamespace(id=user_id),
        text=text, reply_to_message_id=reply_id, reply=AsyncMock(),
        delete=AsyncMock(), stop_propagation=AsyncMock(), continue_propagation=AsyncMock(),
        _client=SimpleNamespace(delete_messages=AsyncMock(), get_messages=AsyncMock()),
    )



class StorageRegressionTests(unittest.TestCase):
    def test_blank_mongo_credentials_do_not_override_uri_authentication(self):
        database_module.mongo_client.cache_clear()
        self.addCleanup(database_module.mongo_client.cache_clear)
        with patch.object(database_module, 'MONGO_USERNAME', ''), patch.object(
            database_module.pymongo, 'MongoClient'
        ) as client:
            database_module.mongo_client()
        self.assertNotIn('username', client.call_args.kwargs)
        self.assertNotIn('password', client.call_args.kwargs)


    def test_partially_normalized_legacy_vendor_still_matches_aliases(self):
        database = object.__new__(VendorsDB)
        database.vendors = MagicMock()
        database.vendors.find_one.return_value = None
        database.vendors.find.return_value = [{
            'name': 'Renamed Shop', 'normalized_name': 'renamedshop',
            'aliases': ['Original Shop'], 'firefly_account_id': '5',
        }]
        match = database.find_vendor_by_name_or_alias('Original Shop')
        self.assertEqual(match['firefly_account_id'], '5')
        query = database.vendors.find.call_args.args[0]
        self.assertIn({'normalized_aliases': {'$exists': False}}, query['$or'])


    def test_attachment_upload_sends_original_binary_body(self):
        api = object.__new__(FireflyApi)
        api.api_url, api.timeout = 'https://firefly.example/api/v1', 1
        api.session = MagicMock()
        content = b'\xff\xd8receipt\x00\xff'
        captured = {}

        def upload(url, **kwargs):
            captured.update(url=url, body=kwargs['data'].read(), headers=kwargs['headers'])
            self.assertNotIn('files', kwargs)
            return SimpleNamespace(status_code=204)

        api.session.post.side_effect = upload
        with TemporaryDirectory() as directory:
            image = Path(directory) / 'receipt.jpg'
            image.write_bytes(content)
            api.upload_attachment_file('8', str(image))
        self.assertEqual(captured['body'], content)
        self.assertEqual(captured['headers']['Content-Type'], 'application/octet-stream')


    def test_malformed_vendor_snapshot_does_not_touch_database(self):
        with patch.object(vendors, 'VendorsDB') as database:
            with self.assertRaises(ValueError):
                vendors.sync_vendor_records([{'id': '1', 'attributes': {}}])
        database.assert_not_called()



class VendorHandlerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        for contexts in vendors.VENDOR_CONTEXTS.values():
            contexts.clear()

    async def test_vendor_alias_is_written_remotely_then_locally(self):
        vendor_id = '0123456789abcdef01234567'
        vendor = {'_id': vendor_id, 'name': 'Shop', 'firefly_account_id': '5', 'aliases': ['Old']}
        vendors._set_context('add_alias', 1, {
            'user_id': 1, 'vendor_id': vendor_id, 'message_id': 30, 'reply_message_id': 10,
        })
        reply = message()
        writes = []
        with patch.object(vendors, 'VendorsDB') as db_type, patch.object(
            vendors, 'FireflyApi'
        ) as api_type, patch.object(vendors, 'update_aliases_view', new_callable=AsyncMock), patch.object(
            vendors.asyncio, 'sleep', new_callable=AsyncMock
        ):
            db = db_type.return_value
            db.vendors.find_one.return_value = vendor
            db.vendor_has_alias.return_value = False
            api_type.return_value.update_account_aliases.side_effect = lambda *args: writes.append('remote')
            db.add_alias_to_vendor.side_effect = lambda *args: writes.append('local')
            await vendors.handle_add_alias_reply(None, reply)
        self.assertEqual(writes, ['remote', 'local'])
        self.assertEqual(vendor['aliases'], ['Old'])
        reply._client.delete_messages.assert_awaited_with(1, 10)


    async def test_vendor_name_edit_reaches_firefly_and_local_cache(self):
        vendor_id = '0123456789abcdef01234567'
        vendor = {'_id': vendor_id, 'name': 'Shop', 'firefly_account_id': '5', 'aliases': []}
        vendors._set_context('edit_name', 1, {
            'user_id': 1, 'vendor_id': vendor_id, 'message_id': 30, 'reply_message_id': 10,
        })
        reply = message(text='New Shop')
        with patch.object(vendors, 'VendorsDB') as db_type, patch.object(vendors, 'FireflyApi') as api_type, patch.object(
            vendors.asyncio, 'sleep', new_callable=AsyncMock
        ):
            db_type.return_value.vendors.find_one.return_value = vendor
            db_type.return_value.exists.return_value = False
            await vendors.handle_edit_vendor_name_reply(None, reply)
        api_type.return_value.update_account_name.assert_called_once_with('5', 'New Shop')
        db_type.return_value.update_vendor_name.assert_called_once()
