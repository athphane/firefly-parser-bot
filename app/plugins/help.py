from pyrogram import filters
from pyrogram.types import Message
from app import EXCHANGE_RATES, FireflyParserBot, LOCAL_CURRENCY, TELEGRAM_ADMINS
from app.plugins.vendors import clear_vendor_contexts

@FireflyParserBot.on_message(filters.private & filters.user(TELEGRAM_ADMINS) & filters.command(["help"]), group=1)
async def help_command(_, message: Message):
    # Clear any existing reply contexts
    await clear_vendor_contexts(message)

    help_text = (
        "**Firefly Parser Bot Help**\n\n"
        "Type `/start` to see a welcome message.\n\n"
        "**Available Commands:**\n"
        "• `/income` - Record an incoming money transaction.\n"
        "• `/foreignsum` - Show foreign transaction summary.\n"
        "• `/foreignsum_help` - Show usage instructions for `/foreignsum`.\n"
        "\n**Vendor Commands:**\n"
        "• `/vendors [search]` — List all vendors. Optionally, add a search term to filter vendors by name or alias. Results are paginated.\n"
        "• `/syncvendors` — Synchronize vendors with Firefly III. Adds new vendors, updates aliases, and removes vendors no longer present in Firefly.\n"
        "• `/help` - Show this help message.\n"
        f"\nForeign totals use the configured exchange rate "
        f"({EXCHANGE_RATES.get('USD', 'not configured')} {LOCAL_CURRENCY} per USD)."
    )
    await message.reply(help_text)
    await message.stop_propagation()

@FireflyParserBot.on_message(filters.private & filters.user(TELEGRAM_ADMINS) & filters.command(["foreignsum_help"]), group=1)
async def foreignsum_help_command(_, message: Message):
    # Clear any existing reply contexts
    await clear_vendor_contexts(message)

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
        f"Foreign totals use the configured exchange rate "
        f"({EXCHANGE_RATES.get('USD', 'not configured')} {LOCAL_CURRENCY} per USD)."
    )
    await message.reply(help_text)
    await message.stop_propagation()
