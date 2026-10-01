from bson import ObjectId
import asyncio
import html
from pyrogram import filters
from pyrogram.enums import ChatAction
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, ForceReply
import logging
import re

from app import FireflyParserBot, TELEGRAM_ADMINS
from app.database.vendorsdb import VendorsDB
from app.firefly.firefly import FireflyApi

LOGS = logging.getLogger(__name__)

# Layout constants
VENDORS_PER_PAGE = 9  # Maximum vendors per page (3x3 grid)
VENDORS_PER_ROW = 3    # Number of vendors per row
VENDOR_CONTEXTS: dict[str, dict[int, dict]] = {
    "add_alias": {},
    "edit_name": {},
}


def _context(kind: str, user_id: int) -> dict | None:
    return VENDOR_CONTEXTS[kind].get(user_id)


def _set_context(kind: str, user_id: int, context: dict) -> None:
    VENDOR_CONTEXTS[kind][user_id] = context


def discard_vendor_contexts(user_id: int) -> None:
    for contexts in VENDOR_CONTEXTS.values():
        contexts.pop(user_id, None)


def _truncate_utf8(value: str, max_bytes: int) -> str:
    encoded = value.strip().encode('utf-8')[:max_bytes]
    return encoded.decode('utf-8', errors='ignore')


def _html(value) -> str:
    return html.escape(str(value), quote=False)


async def clear_vendor_contexts(message: Message, user_id: int | None = None):
    """
    Clear any existing reply contexts and attempt to delete the ForceReply messages.
    """
    user_id = user_id if user_id is not None else message.from_user.id
    for kind in VENDOR_CONTEXTS:
        ctx = _context(kind, user_id)
        if ctx and "reply_message_id" in ctx:
            try:
                await message._client.delete_messages(message.chat.id, ctx["reply_message_id"])
            except Exception:
                pass
    discard_vendor_contexts(user_id)


@FireflyParserBot.on_message(filters.private & filters.user(TELEGRAM_ADMINS) & filters.command(["vendors"]), group=1)
async def list_vendors(_, message: Message):
    await message.reply_chat_action(ChatAction.TYPING)
    # Clear any existing reply contexts and delete ForceReply messages
    await clear_vendor_contexts(message)

    # Extract query from the command (everything after /vendors)
    query = message.text.split(maxsplit=1)[1] if len(message.text.split(maxsplit=1)) > 1 else ""
    query = _truncate_utf8(query, 40)
    page = 1
    await send_vendors_list(message, page, query)
    await message.stop_propagation()


async def send_vendors_list(message_or_callback, page: int, query: str):
    db = VendorsDB()
    filter_ = {}

    if query:
        # Case-insensitive search in name or aliases
        escaped_query = re.escape(query)
        filter_ = {
            "$or": [
                {"name": {"$regex": escaped_query, "$options": "i"}},
                {"aliases": {"$regex": escaped_query, "$options": "i"}}
            ]
        }

    def fetch_page():
        total = db.vendors.count_documents(filter_)
        cursor = db.vendors.find(filter_).sort("name", 1).skip((page - 1) * VENDORS_PER_PAGE).limit(VENDORS_PER_PAGE)
        return total, list(cursor)

    total_vendors, vendors = await asyncio.to_thread(fetch_page)

    if not vendors:
        text = f"No vendors found for query: '{_html(query)}'" if query else "No vendors found."
        if isinstance(message_or_callback, Message):
            await message_or_callback.reply(text)
        else:
            await message_or_callback.message.edit_text(text)
        return

    # Calculate total pages
    total_pages = (total_vendors + VENDORS_PER_PAGE - 1) // VENDORS_PER_PAGE

    text = f"📋 <b>Vendors</b> (Page {page}/{total_pages})"
    if query:
        text += f" | Search: '<code>{_html(query)}</code>'"
    text += "\n\n"

    # Always show the total count of vendors
    text += f"Found {total_vendors} vendors"
    if total_vendors > VENDORS_PER_PAGE:
        text += f" (showing {len(vendors)} on this page)"
    text += "\n\n"

    # List all vendors on the current page with their number
    for idx, vendor in enumerate(vendors, start=1 + (page - 1) * VENDORS_PER_PAGE):
        text += f"{idx}: {_html(vendor.get('name', 'Unnamed'))}\n"
    text += "\n"

    # Display vendors in a grid layout
    vendors_to_display = vendors[:VENDORS_PER_PAGE]

    # Create buttons in a grid layout (3 per row)
    buttons = []
    current_row = []

    for idx, vendor in enumerate(vendors_to_display, start=1 + (page - 1) * VENDORS_PER_PAGE):
        # Create button with just the index number
        button = InlineKeyboardButton(
            f"{idx}",
            callback_data=f"view_vendor:{vendor['_id']}",
        )

        current_row.append(button)

        # Add 3 buttons per row
        if len(current_row) == VENDORS_PER_ROW:
            buttons.append(current_row)
            current_row = []

    # Add any remaining buttons in the last row
    if current_row:
        buttons.append(current_row)

    # Pagination row with consistent UI
    max_page = (total_vendors + VENDORS_PER_PAGE - 1) // VENDORS_PER_PAGE
    nav_buttons = []

    # Previous button (disabled if on first page)
    if page > 1:
        nav_buttons.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"vendors_page:{page - 1}:{query}"))
    else:
        nav_buttons.append(InlineKeyboardButton("•", callback_data="noop"))

    # Page indicator as a separator
    page_indicator = f"{page}/{max_page}"
    nav_buttons.append(InlineKeyboardButton(page_indicator, callback_data="noop"))

    # Next button (disabled if on last page)
    if page < max_page:
        nav_buttons.append(InlineKeyboardButton("Next ➡️", callback_data=f"vendors_page:{page + 1}:{query}"))
    else:
        nav_buttons.append(InlineKeyboardButton("•", callback_data="noop"))

    # Add navigation row
    buttons.append(nav_buttons)

    markup = InlineKeyboardMarkup(buttons)

    if isinstance(message_or_callback, Message):
        await message_or_callback.reply(text, reply_markup=markup)
    else:
        await message_or_callback.edit_message_text(text, reply_markup=markup)


@FireflyParserBot.on_callback_query(filters.regex(r"^do_nothing$") & filters.user(TELEGRAM_ADMINS))
async def do_nothing_callback(_, callback_query: CallbackQuery):
    await callback_query.answer()


@FireflyParserBot.on_callback_query(filters.regex(r"^noop$") & filters.user(TELEGRAM_ADMINS))
async def noop_callback(_, callback_query: CallbackQuery):
    # Handle no-operation callback for disabled buttons
    await callback_query.answer("This button is not active")


@FireflyParserBot.on_callback_query(filters.regex(r"^vendors_page:(\d+):(.*)$") & filters.user(TELEGRAM_ADMINS))
async def vendors_page_callback(_, callback_query: CallbackQuery):
    # The query may be empty, so use maxsplit=2 and join back if needed
    parts = callback_query.data.split(":", 2)
    page = int(parts[1])
    query = parts[2] if len(parts) > 2 else ""
    # Ensure proper handling of the query parameter
    await send_vendors_list(callback_query, page, query)
    await callback_query.answer()


@FireflyParserBot.on_message(filters.private & filters.user(TELEGRAM_ADMINS) & filters.command(["syncvendors"]),
                             group=1)
async def sync_vendors(_, message: Message):
    # Clear any existing reply contexts and delete ForceReply messages
    await clear_vendor_contexts(message)

    await message.reply("Syncing vendors. Please wait...")
    await message.reply_chat_action(ChatAction.TYPING)

    try:
        accounts = await asyncio.to_thread(FireflyApi().accounts, 'expense', True)
    except Exception as e:
        LOGS.exception("Failed to fetch vendor accounts from Firefly")
        await message.reply("Failed to fetch accounts from Firefly. Check the bot logs for details.")
        await message.stop_propagation()
        return

    try:
        summary = await asyncio.to_thread(sync_vendor_records, accounts)
    except Exception:
        LOGS.exception("Failed to synchronize the vendor database")
        await message.reply("Failed to synchronize vendors. Check the bot logs for details.")
    else:
        await message.reply(summary)

    await message.stop_propagation()


def sync_vendor_records(accounts: list[dict]) -> str:
    """Reconcile vendors in a worker thread using one validated Firefly snapshot."""
    for account in accounts:
        if (not isinstance(account, dict) or not str(account.get('id', '')).isdigit()
                or not isinstance(account.get('attributes'), dict)
                or not isinstance(account['attributes'].get('name'), str)
                or not account['attributes']['name'].strip()
                or not isinstance(account['attributes'].get('notes') or '', str)):
            raise ValueError("Firefly returned invalid vendor account details.")

    new_vendors = 0
    new_aliases = 0
    updated_vendors = 0
    skipped = 0
    deleted_vendors = 0

    # Get all Firefly account IDs from the database
    db = VendorsDB()
    db.ensure_indexes()
    db_account_ids = set(db.get_all_firefly_account_ids())
    firefly_account_ids = set()

    for account in accounts:
        account_id = str(account['id'])
        attributes = account['attributes']
        notes: str = attributes.get('notes', '')

        if (notes is not None) and ('***NOT A VENDOR***' in notes):
            LOGS.info(f"Skipping vendor {attributes.get('name', account_id)}")
            skipped += 1
            continue

        firefly_account_ids.add(account_id)
        aliases = extract_aliases(notes)
        vendor, result = db.sync_vendor(
            account_id=account_id,
            name=attributes.get('name', ''),
            description=attributes.get('description', ''),
            aliases=aliases,
        )
        old_aliases = (vendor.get('aliases') or []) if vendor else []
        new_aliases += len({db.clean_string_for_match(alias) for alias in aliases} - {
            db.clean_string_for_match(alias) for alias in old_aliases
        })
        if vendor is None:
            LOGS.info(f"New vendor added: {attributes.get('name', '')}")
            new_vendors += 1
        elif result.modified_count:
            updated_vendors += 1

    # Delete vendors that are in the database but not in Firefly
    vendors_to_delete = db_account_ids - firefly_account_ids
    for account_id in vendors_to_delete:
        vendor = db.find_vendor_by_firefly_account_id(account_id)
        if vendor:
            vendor_name = vendor.get('name', 'Unknown')
            LOGS.info(f"Deleting vendor no longer in Firefly: {vendor_name}")
            db.delete_vendor_by_firefly_account_id(account_id)
            deleted_vendors += 1

    # Get total vendors and aliases in the DB
    total_vendors = db.count_vendors()
    total_aliases = db.count_aliases()

    return (
        f"Sync complete!\n"
        f"New vendors added: {new_vendors}\n"
        f"Existing vendors updated: {updated_vendors}\n"
        f"New aliases added: {new_aliases}\n"
        f"Vendors deleted: {deleted_vendors}\n"
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

    return list(dict.fromkeys(
        alias.strip() for alias in aliases_block.splitlines() if alias.strip()
    ))


@FireflyParserBot.on_callback_query(filters.regex(r"^view_vendor:[0-9a-fA-F]{24}$") & filters.user(TELEGRAM_ADMINS))
async def view_vendor_callback(_, callback_query: CallbackQuery):
    vendor_id = callback_query.data.split(":", 1)[1]
    db = VendorsDB()
    vendor = await asyncio.to_thread(db.vendors.find_one, {"_id": ObjectId(vendor_id)})

    if not vendor:
        await callback_query.answer("Vendor not found.", show_alert=True)
        return

    name = _html(vendor.get("name", "Unnamed"))
    firefly_id = vendor.get("firefly_account_id", "N/A")
    aliases = vendor.get("aliases", [])
    aliases_text = "\n".join(f"- {_html(alias)}" for alias in aliases) if aliases else "(none)"

    # Generate the Firefly edit URL if we have a valid firefly_account_id
    firefly_edit_url = None
    if firefly_id and firefly_id != "N/A":
        firefly_edit_url = get_firefly_account_edit_url(firefly_id)

    text = (
        f"Vendor Details:\n"
        f"Name: <b>{name}</b>\n"
        f"Firefly ID: <code>{_html(firefly_id)}</code>\n"
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

    # Add a button to edit the vendor in Firefly III if we have a valid URL
    if firefly_edit_url:
        buttons.append([
            InlineKeyboardButton("🔧 Edit in Firefly", url=firefly_edit_url)
        ])

    buttons.append([
        InlineKeyboardButton("🔙 Back to Vendors", callback_data="back_to_vendors")
    ])

    markup = InlineKeyboardMarkup(buttons)

    # Always edit the current message, regardless of context
    await callback_query.message.edit_text(text, reply_markup=markup)
    await callback_query.answer()


@FireflyParserBot.on_callback_query(filters.regex(r"^delete_alias:[0-9a-fA-F]{24}:\d+$") & filters.user(TELEGRAM_ADMINS))
async def delete_alias_callback(_, callback_query: CallbackQuery):
    vendor_id, alias_index_str = callback_query.data.split(":", 2)[1:]
    db = VendorsDB()
    vendor = await asyncio.to_thread(db.vendors.find_one, {"_id": ObjectId(vendor_id)})

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

    firefly_id = vendor.get("firefly_account_id")

    # Firefly is authoritative. Update it before the local cache so a remote
    # failure cannot leave the two stores disagreeing.
    if firefly_id:
        updated_aliases = aliases.copy()
        updated_aliases.remove(alias)
        try:
            await asyncio.to_thread(
                FireflyApi().update_account_aliases,
                firefly_id,
                updated_aliases,
            )
        except Exception as e:
            LOGS.exception("Failed to delete alias from Firefly account %s", firefly_id)
            await callback_query.answer("Failed to delete alias in Firefly.", show_alert=True)
            return

    await asyncio.to_thread(db.vendors.update_one,
        {"_id": ObjectId(vendor_id)},
        {"$pull": {
            "aliases": alias,
            "normalized_aliases": db.clean_string_for_match(alias),
        }},
    )

    await callback_query.answer(f"Alias '{alias}' deleted.")

    # Refresh the aliases display in the same message
    vendor = await asyncio.to_thread(db.vendors.find_one, {"_id": ObjectId(vendor_id)})  # Refresh vendor data
    await update_aliases_view(callback_query, vendor)


@FireflyParserBot.on_callback_query(filters.regex(r"^add_alias:[0-9a-fA-F]{24}$") & filters.user(TELEGRAM_ADMINS))
async def add_alias_callback(_, callback_query: CallbackQuery):
    vendor_id = callback_query.data.split(":", 1)[1]
    vendor = await asyncio.to_thread(VendorsDB().vendors.find_one, {"_id": ObjectId(vendor_id)})

    if not vendor:
        await callback_query.answer("Vendor not found.", show_alert=True)
        return

    text = (
        f"Send the new alias for <b>{_html(vendor.get('name'))}</b> as a reply to this message."
    )
    reply_msg = await callback_query.message.reply(
        text,
        reply_markup=ForceReply(selective=True)
    )
    _set_context("add_alias", callback_query.from_user.id, {
        "user_id": callback_query.from_user.id,
        "vendor_id": vendor_id,
        "message_id": callback_query.message.id,
        "reply_message_id": reply_msg.id  # Store the ID of this ForceReply message
    })
    await callback_query.answer()


def is_reply_to_forcereply(message: Message, context_type: str) -> bool:
    """
    Check if a message is a reply to a ForceReply message.

    Args:
        message: The message to check
        context_type: Either "add_alias" or "edit_name".

    Returns:
        True if the message is a reply to the expected ForceReply, False otherwise
    """
    if not message.reply_to_message_id:
        return False

    ctx = _context(context_type, message.from_user.id)
    if not ctx:
        return False

    # Check if this message is a reply to our ForceReply message
    return ctx.get("reply_message_id") == message.reply_to_message_id




@FireflyParserBot.on_message(filters.private & filters.user(TELEGRAM_ADMINS), group=2)
async def handle_add_alias_reply(_, message: Message):
    # Check if this is a reply to our ForceReply for adding aliases
    if is_reply_to_forcereply(message, "add_alias"):
        # Process the alias addition
        ctx = _context("add_alias", message.from_user.id)
        if ctx and ctx["user_id"] == message.from_user.id:
            if not message.text:
                await message.reply("Please reply with text to this prompt.")
                await message.stop_propagation()
                return
            # Handle the alias addition as before
            db = VendorsDB()
            vendor = await asyncio.to_thread(db.vendors.find_one, {"_id": ObjectId(ctx["vendor_id"])})
            if not vendor:
                VENDOR_CONTEXTS["add_alias"].pop(message.from_user.id, None)
                await message.reply("Vendor no longer exists.")
                await message.stop_propagation()
                return
            vendor_name = vendor.get('name')
            alias = message.text.strip()

            # Try to delete the ForceReply message to clean up the chat
            try:
                if "reply_message_id" in ctx:
                    await message._client.delete_messages(message.chat.id, ctx["reply_message_id"])
            except Exception:
                pass  # Ignore if we can't delete it

            if alias and len(alias) <= 255 and '\n' not in alias and '\r' not in alias and not await asyncio.to_thread(db.vendor_has_alias, vendor_name, alias):
                firefly_id = vendor.get("firefly_account_id")

                # Sync aliases with Firefly
                if firefly_id:
                    updated_aliases = list(vendor.get("aliases") or [])
                    updated_aliases.append(alias)
                    try:
                        await asyncio.to_thread(
                            FireflyApi().update_account_aliases,
                            firefly_id,
                            updated_aliases,
                        )
                    except Exception as e:
                        LOGS.exception("Failed to add alias to Firefly account %s", firefly_id)
                        await message.reply("Failed to add alias in Firefly. Check the bot logs for details.")
                        VENDOR_CONTEXTS["add_alias"].pop(message.from_user.id, None)
                        await message.stop_propagation()
                        return

                await asyncio.to_thread(db.add_alias_to_vendor, vendor_name, alias)

                status_msg = await message.reply(
                    f"✅ Alias '<code>{_html(alias)}</code>' added to <b>{_html(vendor_name)}</b>."
                )

                # Refresh the vendor view after a short delay
                vendor = await asyncio.to_thread(db.vendors.find_one, {"_id": ObjectId(ctx["vendor_id"])}) # Refresh vendor data

                # Update the original message with the new aliases list
                try:
                    original_message = await message._client.get_messages(message.chat.id, ctx["message_id"])
                    await update_aliases_view(original_message, vendor)

                    # Delete the status message after a short delay to clean up the chat
                    await asyncio.sleep(2)
                    await status_msg.delete()
                except Exception:
                    pass  # Ignore if we can't update/delete
            else:
                await message.reply("Alias is empty or already exists.")

            VENDOR_CONTEXTS["add_alias"].pop(message.from_user.id, None)
            await message.stop_propagation()
    # If this is not a reply to our ForceReply, clear contexts and continue
    elif not message.reply_to_message_id:
        await clear_vendor_contexts(message)
        await message.continue_propagation()
    # If this message is a reply but not to our ForceReply, let it propagate to other handlers
    else:
        await message.continue_propagation()


@FireflyParserBot.on_callback_query(filters.regex(r"^manage_aliases:[0-9a-fA-F]{24}$") & filters.user(TELEGRAM_ADMINS))
async def manage_aliases_callback(_, callback_query: CallbackQuery):
    vendor_id = callback_query.data.split(":", 1)[1]
    db = VendorsDB()
    vendor = await asyncio.to_thread(db.vendors.find_one, {"_id": ObjectId(vendor_id)})

    if not vendor:
        await callback_query.answer("Vendor not found.", show_alert=True)
        return

    await update_aliases_view(callback_query, vendor)
    await callback_query.answer()


@FireflyParserBot.on_callback_query(filters.regex(r"^edit_vendor_name:[0-9a-fA-F]{24}$") & filters.user(TELEGRAM_ADMINS))
async def edit_vendor_name_callback(_, callback_query: CallbackQuery):
    vendor_id = callback_query.data.split(":", 1)[1]
    db = VendorsDB()
    vendor = await asyncio.to_thread(db.vendors.find_one, {"_id": ObjectId(vendor_id)})

    if not vendor:
        await callback_query.answer("Vendor not found.", show_alert=True)
        return

    name = vendor.get("name", "Unnamed")
    text = f"Send the new name for <b>{_html(name)}</b> as a reply to this message."
    reply_msg = await callback_query.message.reply(
        text,
        reply_markup=ForceReply(selective=True)
    )
    _set_context("edit_name", callback_query.from_user.id, {
        "user_id": callback_query.from_user.id,
        "vendor_id": vendor_id,
        "message_id": callback_query.message.id,
        "reply_message_id": reply_msg.id  # Store the ID of this ForceReply message
    })
    await callback_query.answer()


@FireflyParserBot.on_message(filters.private & filters.user(TELEGRAM_ADMINS), group=5)
async def handle_edit_vendor_name_reply(_, message: Message):
    # Check if this is a reply to our ForceReply for editing vendor name
    if is_reply_to_forcereply(message, "edit_name"):
        # Process the vendor name edit
        ctx = _context("edit_name", message.from_user.id)
        if ctx and ctx["user_id"] == message.from_user.id:
            if not message.text:
                await message.reply("Please reply with text to this prompt.")
                await message.stop_propagation()
                return
            # Handle the vendor name edit as before
            db = VendorsDB()
            vendor = await asyncio.to_thread(db.vendors.find_one, {"_id": ObjectId(ctx["vendor_id"])})
            if not vendor:
                VENDOR_CONTEXTS["edit_name"].pop(message.from_user.id, None)
                await message.reply("Vendor no longer exists.")
                await message.stop_propagation()
                return

            old_vendor_name = vendor.get('name')
            new_vendor_name = message.text.strip()

            # Try to delete the ForceReply message to clean up the chat
            try:
                if "reply_message_id" in ctx:
                    await message._client.delete_messages(message.chat.id, ctx["reply_message_id"])
            except Exception:
                pass  # Ignore if we can't delete it

            if new_vendor_name and len(new_vendor_name) <= 255 and '\n' not in new_vendor_name and '\r' not in new_vendor_name and not await asyncio.to_thread(db.exists, new_vendor_name):
                # Update the name in Firefly
                firefly_id = vendor.get("firefly_account_id")
                status_message = None

                if firefly_id:
                    try:
                        await asyncio.to_thread(
                            FireflyApi().update_account_name,
                            firefly_id,
                            new_vendor_name,
                        )
                        await asyncio.to_thread(db.update_vendor_name, ObjectId(ctx["vendor_id"]), new_vendor_name)
                        status_message = await message.reply(
                            f"✅ Vendor name updated in the database and Firefly from '<code>{_html(old_vendor_name)}</code>' "
                            f"to '<code>{_html(new_vendor_name)}</code>'."
                        )
                    except Exception as e:
                        status_message = await message.reply(
                            f"⚠️ Failed to update the vendor name in Firefly: {e}"
                        )
                else:
                    await asyncio.to_thread(db.update_vendor_name, ObjectId(ctx["vendor_id"]), new_vendor_name)
                    status_message = await message.reply(
                    f"✅ Vendor name updated in the database from '<code>{_html(old_vendor_name)}</code>' "
                    f"to '<code>{_html(new_vendor_name)}</code>'. Firefly ID not found, so Firefly was not updated."
                    )
            else:
                await message.reply("❌ The new name is empty or already exists.")
                VENDOR_CONTEXTS["edit_name"].pop(message.from_user.id, None)
                await message.stop_propagation()
                return

            # Refresh the vendor in the original message
            try:
                # Get updated vendor data
                updated_vendor = await asyncio.to_thread(db.vendors.find_one, {"_id": ObjectId(ctx["vendor_id"])})
                if updated_vendor:
                    # Get the original message
                    original_message = await message._client.get_messages(message.chat.id, ctx["message_id"])

                    # Update the vendor details in the original message
                    name = _html(updated_vendor.get("name", "Unnamed"))
                    firefly_id = updated_vendor.get("firefly_account_id", "N/A")
                    aliases = updated_vendor.get("aliases", [])
                    aliases_text = "\n".join(f"- {_html(alias)}" for alias in aliases) if aliases else "(none)"

                    # Generate the Firefly edit URL if we have a valid firefly_account_id
                    firefly_edit_url = None
                    if firefly_id and firefly_id != "N/A":
                        firefly_edit_url = get_firefly_account_edit_url(firefly_id)

                    text = (
                        f"Vendor Details:\n"
                        f"Name: <b>{name}</b>\n"
                        f"Firefly ID: <code>{_html(firefly_id)}</code>\n"
                        f"Aliases:\n{aliases_text}\n\n"
                    )

                    buttons = [
                        [
                            InlineKeyboardButton("✏️ Edit Name", callback_data=f"edit_vendor_name:{ctx['vendor_id']}"),
                        ],
                        [
                            InlineKeyboardButton("🔗 Manage Aliases", callback_data=f"manage_aliases:{ctx['vendor_id']}")
                        ]
                    ]

                    # Add a button to edit the vendor in Firefly III if we have a valid URL
                    if firefly_edit_url:
                        buttons.append([
                            InlineKeyboardButton("🔧 Edit in Firefly", url=firefly_edit_url)
                        ])

                    buttons.append([
                        InlineKeyboardButton("🔙 Back to Vendors", callback_data="back_to_vendors")
                    ])

                    markup = InlineKeyboardMarkup(buttons)
                    await original_message.edit_text(text, reply_markup=markup)

                    # Delete the status message after a short delay to clean up the chat
                    if status_message:
                        await asyncio.sleep(2)
                        await status_message.delete()
            except Exception as e:
                LOGS.error(f"Error updating vendor view: {e}")

            VENDOR_CONTEXTS["edit_name"].pop(message.from_user.id, None)
            await message.stop_propagation()

    # If this is not a reply to our ForceReply, clear contexts and continue
    elif not message.reply_to_message_id:
        await clear_vendor_contexts(message)
        await message.continue_propagation()
    # If this message is a reply but not to our ForceReply, let it propagate to other handlers
    else:
        await message.continue_propagation()


async def update_aliases_view(callback_query_or_message, vendor):
    """
    Updates the message with the aliases view for the given vendor.

    Args:
        callback_query_or_message: The CallbackQuery or Message object.
        vendor: The vendor document from the database.
    """
    name = _html(vendor.get("name", "Unnamed"))
    vendor_id = str(vendor["_id"])
    aliases = vendor.get("aliases", [])
    aliases_text = "\n".join(f"- {_html(alias)}" for alias in aliases) if aliases else "(none)"

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


@FireflyParserBot.on_callback_query(filters.regex(r"^back_to_vendors$") & filters.user(TELEGRAM_ADMINS))
async def back_to_vendors_callback(_, callback_query: CallbackQuery):
    # Clear any existing reply contexts when returning to main vendors list
    await clear_vendor_contexts(callback_query.message, callback_query.from_user.id)

    # Just show the vendors list with page 1 and no query
    # This is intentional to reset any search filtering when returning to the vendors list
    await send_vendors_list(callback_query, 1, "")
    await callback_query.answer()


def get_firefly_account_edit_url(account_id):
    """
    Generates a URL for editing an account in Firefly III

    Args:
        account_id: The Firefly III account ID

    Returns:
        A URL string to edit the account in Firefly III
    """
    from app import FIREFLY_BASE_URL

    if not account_id:
        return None

    return f"{FIREFLY_BASE_URL.rstrip('/')}/accounts/edit/{account_id}"
