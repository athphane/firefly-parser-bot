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

    for account in accounts:
        account_id = account['id']
        attributes = account['attributes']
        notes: str = attributes.get('notes', '')

        if (notes is not None) and ('***NOT A VENDOR***' in notes):
            print(f"Skipping vendor {attributes.get('name', account_id)}")
            skipped += 1
            continue

        vendor = VendorsDB().find_vendor_by_firefly_account_id(account_id)
        if not vendor:
            vendor = VendorsDB().add_vendor(
                name=attributes.get('name', ''),
                description=attributes.get('description', ''),
                firefly_account_id=account_id
            )
            print(f"New vendor added: {attributes.get('name', '')}")
            new_vendors += 1

        aliases = extract_aliases(notes)
        for alias in aliases:
            # Avoid duplicate aliases
            if not VendorsDB().vendor_has_alias(attributes.get('name', ''), alias):
                VendorsDB().add_alias_to_vendor(
                    vendor_name=attributes.get('name', ''),
                    alias=alias
                )
                print(f"New alias added: {alias} to vendor {attributes.get('name', '')}")
                new_aliases += 1

    # Get total vendors and aliases in the DB
    total_vendors = VendorsDB().count_vendors()
    total_aliases = VendorsDB().count_aliases()

    await message.reply(
        f"Sync complete!\n"
        f"New vendors added: {new_vendors}\n"
        f"New aliases added: {new_aliases}\n"
        f"Vendors skipped: {skipped}\n\n"
        f"Total vendors in DB: {total_vendors}\n"
        f"Total aliases in DB: {total_aliases}"
    )


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
        ]
    ]

    markup = InlineKeyboardMarkup(buttons)
    await callback_query.message.reply(text, reply_markup=markup)
    await callback_query.answer()


@FireflyParserBot.on_callback_query(filters.regex(r"^delete_alias:(.+?):(.+)$"))
async def delete_alias_callback(_, callback_query: CallbackQuery):
    vendor_id, alias = callback_query.data.split(":", 2)[1:]
    db = VendorsDB()
    vendor = db.vendors.find_one({"_id": ObjectId(vendor_id)})

    if not vendor:
        await callback_query.answer("Vendor not found.", show_alert=True)
        return

    db.vendors.update_one({"_id": ObjectId(vendor_id)}, {"$pull": {"aliases": alias}})
    firefly_id = vendor.get("firefly_account_id")

    # Sync aliases with Firefly
    if firefly_id:
        updated_aliases = vendor.get("aliases", [])
        updated_aliases.remove(alias)
        try:
            FireflyApi().update_account_aliases(firefly_id, updated_aliases)
        except Exception as e:
            await callback_query.answer(f"Alias deleted locally, but failed to sync with Firefly: {e}", show_alert=True)
            return

    await callback_query.answer(f"Alias '{alias}' deleted.")

    # Refresh alias list
    await _manage_aliases_callback(callback_query, vendor_id)


@FireflyParserBot.on_callback_query(filters.regex(r"^add_alias:(.+)$"))
async def add_alias_callback(_, callback_query: CallbackQuery):
    vendor_id = callback_query.data.split(":", 1)[1]

    vendor = VendorsDB().vendors.find_one({"_id": ObjectId(vendor_id)})

    text = (
        f"Send the new alias for <b>{vendor.get('name')}</b> as a reply to this message."
    )
    await callback_query.message.reply(
        text,
        reply_markup=ForceReply(selective=True)
    )
    FireflyParserBot._add_alias_context = {
        "user_id": callback_query.from_user.id,
        "vendor_id": vendor_id,
        "message_id": callback_query.message.id
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
                return

        await message.reply(f"Alias '<code>{alias}</code>' added to <b>{vendor_name}</b>.")
    else:
        await message.reply("Alias is empty or already exists.")
    FireflyParserBot._add_alias_context = None
    await message.stop_propagation()


@FireflyParserBot.on_callback_query(filters.regex(r"^manage_aliases:(.+)$"))
async def manage_aliases_callback(_, callback_query: CallbackQuery):
    vendor_id = callback_query.data.split(":", 1)[1]
    await _manage_aliases_callback(callback_query, vendor_id)


async def _manage_aliases_callback(callback_query: CallbackQuery, vendor_id: str):
    db = VendorsDB()
    vendor = db.vendors.find_one({"_id": ObjectId(vendor_id)})

    if not vendor:
        await callback_query.answer("Vendor not found.", show_alert=True)
        return

    name = vendor.get("name", "Unnamed")
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

    for alias in aliases:
        buttons.append([
            InlineKeyboardButton(f"❌ Delete '{alias}'", callback_data=f"delete_alias:{vendor_id}:{alias}")
        ])

    markup = InlineKeyboardMarkup(buttons)
    await callback_query.message.reply(text, reply_markup=markup)
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
    await callback_query.message.reply(
        text,
        reply_markup=ForceReply(selective=True)
    )
    FireflyParserBot._edit_vendor_name_context = {
        "user_id": callback_query.from_user.id,
        "vendor_id": vendor_id,
        "message_id": callback_query.message.id
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

    if new_vendor_name and not db.exists(new_vendor_name):
        db.vendors.update_one({"name": old_vendor_name}, {"$set": {"name": new_vendor_name}})

        # Update the name in Firefly
        firefly_id = vendor.get("firefly_account_id")
        if firefly_id:
            try:
                FireflyApi().update_account_name(firefly_id, new_vendor_name)
                await message.reply(
                    f"Vendor name updated in the database and Firefly from '<code>{old_vendor_name}</code>' "
                    f"to '<code>{new_vendor_name}</code>'."
                )
            except Exception as e:
                await message.reply(
                    f"Vendor name updated in the database, but failed to update in Firefly: {e}"
                )
        else:
            await message.reply(
                f"Vendor name updated in the database from '<code>{old_vendor_name}</code>' "
                f"to '<code>{new_vendor_name}</code>'. Firefly ID not found, so Firefly was not updated."
            )
    else:
        await message.reply("The new name is empty or already exists.")
    FireflyParserBot._edit_vendor_name_context = None

    await message.stop_propagation()
