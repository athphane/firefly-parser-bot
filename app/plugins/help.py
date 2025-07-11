from pyrogram import filters
from pyrogram.types import Message
from app import FireflyParserBot, TELEGRAM_ADMINS

@FireflyParserBot.on_message(filters.private & filters.user(TELEGRAM_ADMINS) & filters.command(["help"]), group=1)
async def help_command(_, message: Message):
    help_text = (
        "**Firefly Parser Bot Help**\n\n"
        "Type `/start` to see a welcome message.\n\n"
        "**Available Commands:**\n"
        "• `/foreignsum` - Show foreign transaction summary.\n"
        "• `/foreignsum_help` - Show usage instructions for `/foreignsum`.\n"
        "\n**Vendor Commands:**\n"
        "• `/vendors [search]` — List all vendors. Optionally, add a search term to filter vendors by name or alias. Results are paginated.\n"
        "• `/syncvendors` — Synchronize vendors with Firefly III. Adds new vendors, updates aliases, and removes vendors no longer present in Firefly.\n"
        "• `/help` - Show this help message.\n"
        "\nAll results are consolidated in USD using a fixed exchange rate (15.42 MVR per USD)."
    )
    await message.reply(help_text)
    await message.stop_propagation()

@FireflyParserBot.on_message(filters.private & filters.user(TELEGRAM_ADMINS) & filters.command(["foreignsum_help"]), group=1)
async def foreignsum_help_command(_, message: Message):
    help_text = (
        "**/foreignsum Command Usage**\n\n"
        "This command summarizes your foreign transactions.\n\n"
        "**Examples:**\n"
        "• `/foreignsum` - Show foreign transactions for the current month\n"
        "• `/foreignsum Jun` - Show foreign transactions for June of the current year\n"
        "• `/foreignsum Jun 2025` - Show foreign transactions for June 2025\n"
        "• `/foreignsum Jun 2025 USD` - Show only USD transactions for June 2025\n"
        "• `/foreignsum range 2025-06-01 2025-06-15` - Show transactions for a date range\n"
        "• `/foreignsum range 2025-06-01 2025-06-15 USD` - Show USD transactions for a date range\n"
        "• Add `csv` to any command to export transactions to a CSV file, e.g., `/foreignsum Jun 2025 csv`\n\n"
        "All results are consolidated in USD using a fixed exchange rate (15.42 MVR per USD)."
    )
    await message.reply(help_text)
    await message.stop_propagation()
