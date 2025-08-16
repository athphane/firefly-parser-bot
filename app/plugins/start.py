from pyrogram import filters
from pyrogram.types import Message

from app import FireflyParserBot, TELEGRAM_ADMINS


@FireflyParserBot.on_message(filters.private & filters.user(TELEGRAM_ADMINS) & filters.command(["start"]), group=1)
async def start_command(_, message: Message):
    # Clear any existing reply contexts
    if hasattr(FireflyParserBot, '_add_alias_context'):
        FireflyParserBot._add_alias_context = None
    if hasattr(FireflyParserBot, '_edit_vendor_name_context'):
        FireflyParserBot._edit_vendor_name_context = None
        
    start_text = (
        "Welcome to Firefly Parser Bot!\n\n"
        "Type /help to see available commands and usage instructions."
    )
    await message.reply(start_text)
    await message.stop_propagation()