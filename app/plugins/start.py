from pyrogram import filters
from pyrogram.enums import ChatAction
from pyrogram.types import Message

from app import FireflyParserBot, TELEGRAM_ADMINS
from app.database.vendorsdb import VendorsDB
from app.firefly.firefly import FireflyApi


@FireflyParserBot.on_message(filters.user(TELEGRAM_ADMINS) & filters.command(["start"]), group=1)
async def start_command(_, message: Message):
    await message.reply("Send transaction SMS and I will put it into your firefly automatically.")


@FireflyParserBot.on_message(filters.user(TELEGRAM_ADMINS) & filters.command(["syncvendors"]), group=1)
async def sync_vendors(_, message: Message):
    await message.reply("I am going to start syncing vendors from your Firefly instance to myself.")

    await message.reply_chat_action(ChatAction.TYPING)

    acounts = FireflyApi().accounts('expense', True)

    for account in acounts:
        account_id = account['id']
        attributes = account['attributes']
        notes: str = attributes['notes']

        if ('***'
            'NOT A VENDOR'
            '***') in notes:
            print(f"Skipping vendor {account['attributes']['name']}")
            continue

        vendor = VendorsDB().find_vendor_by_firefly_account_id(account_id)

        if not vendor:
            vendor = VendorsDB().add_vendor(
                name=attributes['name'],
                description=attributes['description'],
                firefly_account_id=account_id
            )
            print(f"New vendor added: {attributes['name']}")

        aliases = extract_aliases(notes)

        for alias in aliases:
            VendorsDB().add_alias_to_vendor(
                vendor_name=attributes['name'],
                alias=alias
            )
            print(f"New alias added: {alias} to vendor {attributes['name']}")

    await message.reply('Yo im done')


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
    # filtering

    return aliases
