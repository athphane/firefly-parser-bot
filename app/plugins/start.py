from pyrogram import filters
from pyrogram.types import Message

from app import FireflyParserBot, TELEGRAM_ADMINS


@FireflyParserBot.on_message(filters.private & filters.user(TELEGRAM_ADMINS) & filters.command(["start"]), group=1)
async def start_command(_, message: Message):
    await message.reply("Send transaction SMS and I will put it into your firefly automatically.")
    await message.stop_propagation()
