from bson import ObjectId
from pyrogram import filters
from pyrogram.enums import ChatAction
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, ForceReply

from app import FireflyParserBot, TELEGRAM_ADMINS
from app.database.vendorsdb import VendorsDB
from app.firefly.firefly import FireflyApi

VENDORS_PER_PAGE = 10


@FireflyParserBot.on_message(filters.private & filters.user(TELEGRAM_ADMINS) & filters.command(["vendors"]), group=1)
async def list_vendors(_, message: Message):
    await message.reply_chat_action(ChatAction.TYPING)
    # Extract query from the command (everything after /vendors)
    query = message.text.split(maxsplit=1)[1] if len(message.text.split(maxsplit=1)) > 1 else ""
    page = 1
    await send_vendors_list(message, page, query)
    await message.stop_propagation()


async def send_vendors_list(message_or_callback, page: int, query: str):
    db = VendorsDB()
    filter_ = {}
    if query:
        # Case-insensitive search in name or aliases
        filter_ = {
            "$or": [
                {"name": {"$regex": query, "$options": "i"}},
                {"aliases": {"$regex": query, "$options": "i"}}
            ]
        }
    total_vendors = db.vendors.count_documents(filter_)
    vendors_cursor = db.vendors.find(filter_).sort("name", 1).skip((page - 1) * VENDORS_PER_PAGE).limit(
        VENDORS_PER_PAGE)
    vendors = list(vendors_cursor)

    if not vendors:
        text = f"No vendors found for query: '{query}'" if query else "No vendors found."
        await message_or_callback.reply(text)
        return

    text = f"Vendors (Page {page})"
    if query:
        text += f" | Query: '{query}'"
    text += ":\n"
    for idx, vendor in enumerate(vendors, start=1 + (page - 1) * VENDORS_PER_PAGE):
        text += f"{idx}. {vendor.get('name', 'Unnamed')}\n"

    # Buttons for each vendor
    buttons = []
    for idx, vendor in enumerate(vendors, start=1 + (page - 1) * VENDORS_PER_PAGE):
        buttons.append([
            InlineKeyboardButton(
                f"✏️ {idx}",
                callback_data=f"view_vendor:{vendor['_id']}"
            )
        ])

    # Pagination row
    max_page = (total_vendors + VENDORS_PER_PAGE - 1) // VENDORS_PER_PAGE
    nav_buttons = []
    if page > 1:
        nav_buttons.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"vendors_page:{page - 1}:{query}"))
    if page < max_page:
        nav_buttons.append(InlineKeyboardButton("Next ➡️", callback_data=f"vendors_page:{page + 1}:{query}"))
    if nav_buttons:
        buttons.append(nav_buttons)

    markup = InlineKeyboardMarkup(buttons)

    if isinstance(message_or_callback, Message):
        await message_or_callback.reply(text, reply_markup=markup)
    else:
        await message_or_callback.edit_message_text(text, reply_markup=markup)


@FireflyParserBot.on_callback_query(filters.regex(r"^do_nothing"))
async def do_nothing_callback(_, callback_query: CallbackQuery):
    await callback_query.answer()


@FireflyParserBot.on_callback_query(filters.regex(r"^vendors_page:(\d+):(.*)$"))
async def vendors_page_callback(_, callback_query: CallbackQuery):
    # The query may be empty, so use maxsplit=2 and join back if needed
    parts = callback_query.data.split(":", 2)
    page = int(parts[1])
    query = parts[2] if len(parts) > 2 else ""
    await send_vendors_list(callback_query, page, query)
    await callback_query.answer()


@FireflyParserBot.on_message(filters.private & filters.user(TELEGRAM_ADMINS) & filters.command(["syncvendors"]),
                             group=1)
async def sync_vendors(_, message: Message):
    await message.reply("Syncing vendors. Please wait...")
    await message.reply_chat_action(ChatAction.TYPING)

    try:
        accounts = FireflyApi().accounts('expense', True)
    except Exception as e:
        await message.reply(f"Failed to fetch accounts from Firefly: {e}")
        return

    new_vendors = 0
    new_aliases = 0
    skipped = 0
    deleted_vendors = 0
    
    # Get all Firefly account IDs from the database
    db = VendorsDB()
    db_account_ids = set(db.get_all_firefly_account_ids())
    firefly_account_ids = set()

    for account in accounts:
        account_id = account['id']
        firefly_account_ids.add(account_id)
        attributes = account['attributes']
        notes: str = attributes.get('notes', '')

        if (notes is not None) and ('***NOT A VENDOR***' in notes):
            print(f"Skipping vendor {attributes.get('name', account_id)}")
            skipped += 1
            continue

        vendor = db.find_vendor_by_firefly_account_id(account_id)
        if not vendor:
            vendor = db.add_vendor(
                name=attributes.get('name', ''),
                description=attributes.get('description', ''),
                firefly_account_id=account_id
            )
            print(f"New vendor added: {attributes.get('name', '')}")
            new_vendors += 1

        aliases = extract_aliases(notes)
        for alias in aliases:
            # Avoid duplicate aliases
            if not db.vendor_has_alias(attributes.get('name', ''), alias):
                db.add_alias_to_vendor(
                    vendor_name=attributes.get('name', ''),
                    alias=alias
                )
                print(f"New alias added: {alias} to vendor {attributes.get('name', '')}")
                new_aliases += 1
    
    # Delete vendors that are in the database but not in Firefly
    vendors_to_delete = db_account_ids - firefly_account_ids
    for account_id in vendors_to_delete:
        vendor = db.find_vendor_by_firefly_account_id(account_id)
        if vendor:
            vendor_name = vendor.get('name', 'Unknown')
            print(f"Deleting vendor no longer in Firefly: {vendor_name}")
            db.delete_vendor_by_firefly_account_id(account_id)
            deleted_vendors += 1

    # Get total vendors and aliases in the DB
    total_vendors = db.count_vendors()
    total_aliases = db.count_aliases()

    await message.reply(
        f"Sync complete!\n"
        f"New vendors added: {new_vendors}\n"
        f"New aliases added: {new_aliases}\n"
        f"Vendors deleted: {deleted_vendors}\n"
        f"Vendors skipped: {skipped}\n\n"
        f"Total vendors in DB: {total_vendors}\n"
        f"Total aliases in DB: {total_aliases}"
    )
    
    await message.stop_propagation()


def extract_aliases(notes: str) -> list[str]:
    """
    Extracts aliases from a string of notes, delimited by *START:ALIASES* and *END:ALIASES*.

    Args:
        notes: The string containing the notes.

    Returns:
        A list of strings, where each string is an alias.  Returns an empty list if no aliases are found or if `notes` is None.
    """
    if not notes:
        return []

    start_marker = "*START:ALIASES*"
    end_marker = "*END:ALIASES*"

    try:
        start_index = notes.index(start_marker) + len(start_marker)
        end_index = notes.rindex(end_marker)  # Use rindex for the *last* occurrence
        aliases_block = notes[start_index:end_index]
    except ValueError:  # Handle cases where markers are missing
        return []

    aliases = [alias.strip() for alias in aliases_block.split("\n") if alias.strip()]  # List comprehension for

    return aliases


@FireflyParserBot.on_callback_query(filters.regex(r"^view_vendor:(.+)$"))
async def view_vendor_callback(_, callback_query: CallbackQuery):
    vendor_id = callback_query.data.split(":", 1)[1]
    db = VendorsDB()
    vendor = db.vendors.find_one({"_id": ObjectId(vendor_id)})

    if not vendor:
        await callback_query.answer("Vendor not found.", show_alert=True)
        return

    name = vendor.get("name", "Unnamed")
    firefly_id = vendor.get("firefly_account_id", "N/A")
    aliases = vendor.get("aliases", [])
    aliases_text = "\n".join([f"- {alias}" for alias in aliases]) if aliases else "(none)"

    text = (
        f"Vendor Details:\n"
        f"Name: <b>{name}</b>\n"
        f"Firefly ID: <code>{firefly_id}</code>\n"
        f"Aliases:\n{aliases_text}\n\n"
    )
    
    buttons = [
        [
            InlineKeyboardButton("✏️ Edit Name", callback_data=f"edit_vendor_name:{vendor_id}"),
        ],
        [
            InlineKeyboardButton("🔗 Manage Aliases", callback_data=f"manage_aliases:{vendor_id}")
        ],
        [
            InlineKeyboardButton("🔙 Back to Vendors", callback_data=f"back_to_vendors")
        ]
    ]

    markup = InlineKeyboardMarkup(buttons)
    
    # Always edit the current message, regardless of context
    await callback_query.message.edit_text(text, reply_markup=markup)
    await callback_query.answer()


@FireflyParserBot.on_callback_query(filters.regex(r"^delete_alias:(.+?):(.+)$"))
async def delete_alias_callback(_, callback_query: CallbackQuery):
    vendor_id, alias_index_str = callback_query.data.split(":", 2)[1:]
    db = VendorsDB()
    vendor = db.vendors.find_one({"_id": ObjectId(vendor_id)})

    if not vendor:
        await callback_query.answer("Vendor not found.", show_alert=True)
        return
        
    # Get aliases list and convert the index to integer
    aliases = vendor.get("aliases", [])
    try:
        alias_index = int(alias_index_str)
        if alias_index < 0 or alias_index >= len(aliases):
            await callback_query.answer("Invalid alias index.", show_alert=True)
            return
        alias = aliases[alias_index]
    except (ValueError, IndexError):
        await callback_query.answer("Invalid alias index.", show_alert=True)
        return

    db.vendors.update_one({"_id": ObjectId(vendor_id)}, {"$pull": {"aliases": alias}})
    firefly_id = vendor.get("firefly_account_id")

    # Sync aliases with Firefly
    if firefly_id:
        updated_aliases = aliases.copy()
        updated_aliases.remove(alias)
        try:
            FireflyApi().update_account_aliases(firefly_id, updated_aliases)
        except Exception as e:
            await callback_query.answer(f"Alias deleted locally, but failed to sync with Firefly: {e}", show_alert=True)
            return

    await callback_query.answer(f"Alias '{alias}' deleted.")

    # Refresh the aliases display in the same message
    vendor = db.vendors.find_one({"_id": ObjectId(vendor_id)})  # Refresh vendor data
    await update_aliases_view(callback_query, vendor)


@FireflyParserBot.on_callback_query(filters.regex(r"^add_alias:(.+)$"))
async def add_alias_callback(_, callback_query: CallbackQuery):
    vendor_id = callback_query.data.split(":", 1)[1]
    vendor = VendorsDB().vendors.find_one({"_id": ObjectId(vendor_id)})

    text = (
        f"Send the new alias for <b>{vendor.get('name')}</b> as a reply to this message."
    )
    reply_msg = await callback_query.message.reply(
        text,
        reply_markup=ForceReply(selective=True)
    )
    FireflyParserBot._add_alias_context = {
        "user_id": callback_query.from_user.id,
        "vendor_id": vendor_id,
        "message_id": callback_query.message.id,
        "reply_message_id": reply_msg.id  # Store the ID of this ForceReply message
    }
    await callback_query.answer()


@FireflyParserBot.on_message(filters.private & filters.user(TELEGRAM_ADMINS), group=10)
async def handle_add_alias_reply(_, message: Message):
    ctx = getattr(FireflyParserBot, "_add_alias_context", None)
    if not ctx or ctx["user_id"] != message.from_user.id:
        return
    db = VendorsDB()

    vendor = db.vendors.find_one({"_id": ObjectId(ctx["vendor_id"])})
    vendor_name = vendor.get('name')
    alias = message.text.strip()
    
    # Try to delete the ForceReply message to clean up the chat
    try:
        if "reply_message_id" in ctx:
            await message.chat.delete_messages(ctx["reply_message_id"])
    except Exception:
        pass  # Ignore if we can't delete it
        
    if alias and not db.vendor_has_alias(vendor_name, alias):
        db.add_alias_to_vendor(vendor_name, alias)
        firefly_id = vendor.get("firefly_account_id")

        # Sync aliases with Firefly
        if firefly_id:
            updated_aliases = vendor.get("aliases", [])
            updated_aliases.append(alias)
            try:
                FireflyApi().update_account_aliases(firefly_id, updated_aliases)
            except Exception as e:
                await message.reply(f"Alias added locally, but failed to sync with Firefly: {e}")
                FireflyParserBot._add_alias_context = None
                await message.stop_propagation()
                return

        status_msg = await message.reply(f"✅ Alias '<code>{alias}</code>' added to <b>{vendor_name}</b>.")
        
        # Refresh the vendor view after a short delay
        vendor = db.vendors.find_one({"_id": ObjectId(ctx["vendor_id"])})
        
        # Update the original message with the new aliases list
        try:
            original_message = await message.chat.get_messages(ctx["message_id"])
            await update_aliases_view(original_message, vendor)
            
            # Delete the status message after a short delay to clean up the chat
            import asyncio
            await asyncio.sleep(2)
            await status_msg.delete()
        except Exception:
            pass  # Ignore if we can't update/delete
    else:
        await message.reply("Alias is empty or already exists.")
    
    FireflyParserBot._add_alias_context = None
    await message.stop_propagation()


@FireflyParserBot.on_callback_query(filters.regex(r"^manage_aliases:(.+)$"))
async def manage_aliases_callback(_, callback_query: CallbackQuery):
    vendor_id = callback_query.data.split(":", 1)[1]
    db = VendorsDB()
    vendor = db.vendors.find_one({"_id": ObjectId(vendor_id)})

    if not vendor:
        await callback_query.answer("Vendor not found.", show_alert=True)
        return

    await update_aliases_view(callback_query, vendor)
    await callback_query.answer()


@FireflyParserBot.on_callback_query(filters.regex(r"^edit_vendor_name:(.+)$"))
async def edit_vendor_name_callback(_, callback_query: CallbackQuery):
    vendor_id = callback_query.data.split(":", 1)[1]
    db = VendorsDB()
    vendor = db.vendors.find_one({"_id": ObjectId(vendor_id)})

    if not vendor:
        await callback_query.answer("Vendor not found.", show_alert=True)
        return

    name = vendor.get("name", "Unnamed")
    text = f"Send the new name for <b>{name}</b> as a reply to this message."
    reply_msg = await callback_query.message.reply(
        text,
        reply_markup=ForceReply(selective=True)
    )
    FireflyParserBot._edit_vendor_name_context = {
        "user_id": callback_query.from_user.id,
        "vendor_id": vendor_id,
        "message_id": callback_query.message.id,
        "reply_message_id": reply_msg.id  # Store the ID of this ForceReply message
    }
    await callback_query.answer()


@FireflyParserBot.on_message(filters.private & filters.user(TELEGRAM_ADMINS), group=11)
async def handle_edit_vendor_name_reply(_, message: Message):
    ctx = getattr(FireflyParserBot, "_edit_vendor_name_context", None)
    if not ctx or ctx["user_id"] != message.from_user.id:
        return

    db = VendorsDB()
    vendor = db.vendors.find_one({"_id": ObjectId(ctx["vendor_id"])})

    old_vendor_name = vendor.get('name')
    new_vendor_name = message.text.strip()
    
    # Try to delete the ForceReply message to clean up the chat
    try:
        if "reply_message_id" in ctx:
            await message.chat.delete_messages(ctx["reply_message_id"])
    except Exception:
        pass  # Ignore if we can't delete it

    if new_vendor_name and not db.exists(new_vendor_name):
        db.vendors.update_one({"name": old_vendor_name}, {"$set": {"name": new_vendor_name}})

        # Update the name in Firefly
        firefly_id = vendor.get("firefly_account_id")
        status_message = None
        
        if firefly_id:
            try:
                FireflyApi().update_account_name(firefly_id, new_vendor_name)
                status_message = await message.reply(
                    f"✅ Vendor name updated in the database and Firefly from '<code>{old_vendor_name}</code>' "
                    f"to '<code>{new_vendor_name}</code>'."
                )
            except Exception as e:
                status_message = await message.reply(
                    f"⚠️ Vendor name updated in the database, but failed to update in Firefly: {e}"
                )
        else:
            status_message = await message.reply(
                f"✅ Vendor name updated in the database from '<code>{old_vendor_name}</code>' "
                f"to '<code>{new_vendor_name}</code>'. Firefly ID not found, so Firefly was not updated."
            )
    else:
        await message.reply("❌ The new name is empty or already exists.")
        FireflyParserBot._edit_vendor_name_context = None
        await message.stop_propagation()
        return

    # Refresh the vendor in the original message
    try:
        # Get updated vendor data
        updated_vendor = db.vendors.find_one({"_id": ObjectId(ctx["vendor_id"])})
        if updated_vendor:
            # Get the original message
            original_message = await message.chat.get_messages(ctx["message_id"])
            
            # Update the vendor details in the original message
            name = updated_vendor.get("name", "Unnamed")
            firefly_id = updated_vendor.get("firefly_account_id", "N/A")
            aliases = updated_vendor.get("aliases", [])
            aliases_text = "\n".join([f"- {alias}" for alias in aliases]) if aliases else "(none)"

            text = (
                f"Vendor Details:\n"
                f"Name: <b>{name}</b>\n"
                f"Firefly ID: <code>{firefly_id}</code>\n"
                f"Aliases:\n{aliases_text}\n\n"
            )
            
            buttons = [
                [
                    InlineKeyboardButton("✏️ Edit Name", callback_data=f"edit_vendor_name:{ctx['vendor_id']}"),
                ],
                [
                    InlineKeyboardButton("🔗 Manage Aliases", callback_data=f"manage_aliases:{ctx['vendor_id']}")
                ],
                [
                    InlineKeyboardButton("🔙 Back to Vendors", callback_data=f"back_to_vendors")
                ]
            ]

            markup = InlineKeyboardMarkup(buttons)
            await original_message.edit_text(text, reply_markup=markup)
            
            # Delete the status message after a short delay to clean up the chat
            if status_message:
                import asyncio
                await asyncio.sleep(2)
                await status_message.delete()
    except Exception as e:
        print(f"Error updating vendor view: {e}")
    
    FireflyParserBot._edit_vendor_name_context = None
    await message.stop_propagation()


async def update_aliases_view(callback_query_or_message, vendor):
    """
    Updates the message with the aliases view for the given vendor.
    
    Args:
        callback_query_or_message: The CallbackQuery or Message object.
        vendor: The vendor document from the database.
    """
    name = vendor.get("name", "Unnamed")
    vendor_id = str(vendor["_id"])
    aliases = vendor.get("aliases", [])
    aliases_text = "\n".join([f"- {alias}" for alias in aliases]) if aliases else "(none)"

    text = (
        f"Aliases for <b>{name}</b>:\n{aliases_text}"
    )

    buttons = [
        [
            InlineKeyboardButton("➕ Add Alias", callback_data=f"add_alias:{vendor_id}")
        ]
    ]

    for i, alias in enumerate(aliases):
        buttons.append([
            InlineKeyboardButton(f"❌ Delete '{alias}'", callback_data=f"delete_alias:{vendor_id}:{i}")
        ])
        
    # Add a back button
    buttons.append([
        InlineKeyboardButton("🔙 Back to Vendor", callback_data=f"view_vendor:{vendor_id}")
    ])

    markup = InlineKeyboardMarkup(buttons)
    
    # Determine if we're dealing with a callback query or a message
    if hasattr(callback_query_or_message, "message"):
        # It's a callback query
        await callback_query_or_message.message.edit_text(text, reply_markup=markup)
    else:
        # It's a message
        await callback_query_or_message.edit_text(text, reply_markup=markup)


@FireflyParserBot.on_callback_query(filters.regex(r"^back_to_vendors"))
async def back_to_vendors_callback(_, callback_query: CallbackQuery):
    # Just show the vendors list with page 1 and no query
    await send_vendors_list(callback_query, 1, "")
    await callback_query.answer()
