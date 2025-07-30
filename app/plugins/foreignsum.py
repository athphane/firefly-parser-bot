from pyrogram import filters
from pyrogram.types import Message
import calendar
import csv
import os
from datetime import datetime, timezone
from app import FireflyParserBot, TELEGRAM_ADMINS, LOGS
from app.firefly.firefly import FireflyApi
from dataclasses import dataclass, asdict
from typing import List, Optional

MVR_PER_USD = 15.42


@dataclass
class CommandArgs:
    """Holds parsed arguments for the foreignsum command."""
    start_date: datetime
    end_date: datetime
    display_period: str
    export_csv: bool
    filter_currency: Optional[str] = None
    error_message: Optional[str] = None


@dataclass
class ForeignTransaction:
    """Represents a single foreign transaction."""
    date: str
    description: str
    foreign_currency: str
    foreign_amount: float
    local_amount: float
    usd_equivalent: float


def parse_month(month_arg: str) -> Optional[int]:
    """Parses a month string (e.g., 'Jan', 'Feb') and returns the month number."""
    for i, month_abbr in enumerate(calendar.month_abbr):
        if i > 0 and month_abbr.lower() == month_arg.lower()[:3]:
            return i
    return None


def parse_arguments(command: List[str]) -> CommandArgs:
    """Parses command arguments for the /foreignsum command."""
    parts = [p for p in command]  # Make a copy
    now = datetime.now(timezone.utc)

    export_csv = 'csv' in [p.lower() for p in parts]
    if export_csv:
        # Find and remove 'csv' case-insensitively
        for i, part in enumerate(parts):
            if part.lower() == 'csv':
                parts.pop(i)
                break

    try:
        if len(parts) > 1 and parts[1].lower() == 'range':
            if len(parts) < 4:
                return CommandArgs(
                    error_message='''For a date range, please provide start and end dates.
E.g., `/foreignsum range 2025-01-01 2025-01-31`''',
                    start_date=now, end_date=now, display_period="", export_csv=export_csv)

            start_date_str, end_date_str = parts[2], parts[3]
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d')

            if end_date < start_date:
                return CommandArgs(error_message="End date cannot be before start date.",
                                   start_date=now, end_date=now, display_period="", export_csv=export_csv)

            display_period = f"{start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}"
            filter_currency = parts[4].upper() if len(parts) >= 5 else None

        else:  # Not a range, so it's month/year based
            year, month = now.year, now.month
            filter_currency = None

            if len(parts) >= 2:  # Month is specified
                parsed_month = parse_month(parts[1])
                if not parsed_month:
                    return CommandArgs(
                        error_message=f"Invalid month '{parts[1]}'. Please use a valid month name like 'Jan', 'Feb', etc.",
                        start_date=now, end_date=now, display_period="", export_csv=export_csv)
                month = parsed_month

            if len(parts) >= 3:  # Year is specified
                try:
                    year = int(parts[2])
                    if not (2000 <= year <= 2100):
                        return CommandArgs(error_message=f"Year '{parts[2]}' is out of reasonable range (2000-2100).",
                                           start_date=now, end_date=now, display_period="", export_csv=export_csv)
                except ValueError:
                    # If the third argument is not a year, it could be a currency
                    if len(parts) == 3:
                        filter_currency = parts[2].upper()
                    else:
                        return CommandArgs(error_message=f"Invalid year '{parts[2]}'. Please provide a valid year like 2025.",
                                           start_date=now, end_date=now, display_period="", export_csv=export_csv)

            if len(parts) >= 4:  # Currency is specified
                filter_currency = parts[3].upper()

            month_name = calendar.month_name[month]
            start_date = datetime(year, month, 1)
            _, last_day = calendar.monthrange(year, month)
            end_date = datetime(year, month, last_day)
            display_period = f"{month_name} {year}"

        return CommandArgs(
            start_date=start_date,
            end_date=end_date,
            display_period=display_period,
            export_csv=export_csv,
            filter_currency=filter_currency
        )

    except ValueError:
        return CommandArgs(error_message="Invalid date format. Please use YYYY-MM-DD for ranges.",
                           start_date=now, end_date=now, display_period="", export_csv=export_csv)
    except Exception as e:
        LOGS.error(f"Error parsing foreignsum arguments: {e}")
        return CommandArgs(error_message=f"An unexpected error occurred during argument parsing: {e}",
                           start_date=now, end_date=now, display_period="", export_csv=export_csv)


def fetch_and_process_transactions(api: FireflyApi, start_date: datetime, end_date: datetime) -> List[
    ForeignTransaction]:
    """Fetches and processes foreign transactions from Firefly III."""
    params = {
        'start': start_date.strftime('%Y-%m-%d'),
        'end': end_date.strftime('%Y-%m-%d')
    }
    transactions_response = api.get_json('transactions', params)

    foreign_transactions = []
    for transaction_data in transactions_response['data']:
        transaction = transaction_data['attributes']
        for tx in transaction['transactions']:
            if tx.get('foreign_amount') and tx.get('foreign_currency_code'):
                foreign_currency = tx['foreign_currency_code']
                foreign_amount = float(tx['foreign_amount'])
                local_amount = float(tx['amount'])

                usd_equiv = foreign_amount if foreign_currency == 'USD' else local_amount / MVR_PER_USD

                foreign_transactions.append(ForeignTransaction(
                    date=tx['date'],
                    description=tx['description'],
                    foreign_currency=foreign_currency,
                    foreign_amount=foreign_amount,
                    local_amount=local_amount,
                    usd_equivalent=usd_equiv
                ))

    foreign_transactions.sort(key=lambda x: x.date, reverse=True)
    return foreign_transactions


def filter_transactions_by_currency(transactions: List[ForeignTransaction], currency: Optional[str]) -> List[
    ForeignTransaction]:
    """Filters a list of transactions by a given currency."""
    if not currency:
        return transactions
    return [t for t in transactions if t.foreign_currency == currency]


def calculate_total_usd(transactions: List[ForeignTransaction]) -> float:
    """Calculates the total USD equivalent for a list of transactions."""
    return sum(t.usd_equivalent for t in transactions)


def format_summary_message(
        transactions: List[ForeignTransaction],
        display_period: str,
        total_usd: float
) -> str:
    """Formats the summary message with transaction details."""
    msg = f"**Foreign Transactions for {display_period}**\n\n"
    msg += f"**Total in USD:** {total_usd:.2f}\n\n"

    if not transactions:
        return msg + "No transactions found."

    msg += "**Recent Transactions (up to 10):**\n"
    for tx in transactions[:10]:
        if tx.foreign_currency != 'USD':
            msg += (f"• {tx.date[:10]}: {tx.description} - "
                    f"{tx.foreign_amount:.2f} {tx.foreign_currency} "
                    f"(MVR {tx.local_amount:.2f}, USD {tx.usd_equivalent:.2f})\n")
        else:
            msg += f"• {tx.date[:10]}: {tx.description} - {tx.foreign_amount:.2f} USD\n"

    if len(transactions) > 10:
        msg += f"\n...and {len(transactions) - 10} more transactions"

    return msg


async def generate_and_send_csv(message: Message, transactions: List[ForeignTransaction], start_date: datetime,
                                end_date: datetime):
    """Generates a CSV file and sends it as a document."""
    csv_filename = f"foreign_transactions_{start_date.strftime('%Y-%m-%d')}_to_{end_date.strftime('%Y-%m-%d')}.csv"
    csv_path = os.path.join("downloads", csv_filename)
    os.makedirs(os.path.dirname(csv_path), exist_ok=True)

    with open(csv_path, 'w', newline='') as csvfile:
        fieldnames = ['date', 'description', 'foreign_currency', 'foreign_amount', 'local_amount', 'usd_equivalent']
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        for tx in transactions:
            writer.writerow(asdict(tx))

    await message.reply_document(csv_path, caption="Full transaction data exported to CSV")


@FireflyParserBot.on_message(filters.private & filters.user(TELEGRAM_ADMINS) & filters.command(["foreignsum"]), group=1)
async def foreign_sum(_, message: Message):
    """
    Calculates the sum of foreign currency transactions for a given period.
    Usage:
    /foreignsum [month] [year] [currency] [csv]
    /foreignsum range <start_date> <end_date> [currency] [csv]
    - month/year are optional, defaults to current month/year.
    - currency is optional (e.g., USD, EUR).
    - 'csv' keyword exports full data.
    - Dates for range should be in YYYY-MM-DD format.
    """
    args = parse_arguments(message.text.split())

    if args.error_message:
        await message.reply(args.error_message)
        return

    pre_message = f"Calculating foreign transaction totals for {args.display_period}..."
    if args.filter_currency:
        pre_message = f"Calculating {args.filter_currency} transaction totals for {args.display_period}..."

    status_message = await message.reply(pre_message)

    try:
        api = FireflyApi()
        all_foreign_transactions = fetch_and_process_transactions(api, args.start_date, args.end_date)
        filtered_transactions = filter_transactions_by_currency(all_foreign_transactions, args.filter_currency)
        total_usd = calculate_total_usd(filtered_transactions)

        if not filtered_transactions:
            await status_message.edit_text(
                f"No foreign transactions found for {args.display_period}" +
                (f" with currency {args.filter_currency}" if args.filter_currency else "."))
            return

        summary_message = format_summary_message(filtered_transactions, args.display_period, total_usd)

        # We need to check if the message is too long for Telegram
        if len(summary_message) > 4096:
            summary_message = summary_message[:4090] + "\n..."

        await status_message.edit_text(summary_message)

        if args.export_csv:
            await generate_and_send_csv(message, filtered_transactions, args.start_date, args.end_date)

    except Exception as e:
        LOGS.error(f"Error in foreignsum command: {e}")
        await status_message.edit_text(f"An error occurred while calculating foreign transactions: {e}")

    await message.stop_propagation()