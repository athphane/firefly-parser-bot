from pyrogram import filters
from pyrogram.enums import ChatAction
from pyrogram.types import Message

from app import FireflyParserBot, TELEGRAM_ADMINS
from app.database.vendorsdb import VendorsDB
from app.firefly.firefly import FireflyApi


@FireflyParserBot.on_message(filters.user(TELEGRAM_ADMINS) & filters.command(["syncvendors"]), group=1)
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
