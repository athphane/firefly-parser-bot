from pyrogram import filters
from pyrogram.types import Message
import calendar
import csv
import os
from datetime import datetime, timezone
from app import FireflyParserBot, TELEGRAM_ADMINS, LOGS
from app.firefly.firefly import FireflyApi

@FireflyParserBot.on_message(filters.private & filters.user(TELEGRAM_ADMINS) & filters.command(["foreignsum"]), group=1)
async def foreign_sum(_, message: Message):
    command_parts = message.text.split()
    now = datetime.now(timezone.utc)
    year = now.year
    month = now.month
    month_name = calendar.month_name[month]
    filter_currency = None
    is_date_range = False
    display_period = None
    export_csv = False
    if len(command_parts) > 1:
        try:
            for part in command_parts:
                if part.lower() == 'csv':
                    export_csv = True
                    command_parts.remove(part)
                    break
            if len(command_parts) > 1 and command_parts[1].lower() == 'range' and len(command_parts) >= 4:
                is_date_range = True
                start_date = command_parts[2]
                end_date = command_parts[3]
                try:
                    start_dt = datetime.strptime(start_date, '%Y-%m-%d')
                    end_dt = datetime.strptime(end_date, '%Y-%m-%d')
                    if end_dt < start_dt:
                        await message.reply("End date cannot be before start date.")
                        return
                    display_period = f"{start_date} to {end_date}"
                except ValueError:
                    await message.reply("Invalid date format. Please use YYYY-MM-DD format (e.g., 2025-06-01).")
                    return
                if len(command_parts) >= 5:
                    filter_currency = command_parts[4].upper()
            elif len(command_parts) >= 3:
                month_arg = command_parts[1]
                year_arg = command_parts[2]
                month_found = False
                for i, month_abbr in enumerate(calendar.month_abbr):
                    if month_abbr.lower() == month_arg.lower()[:3] and i > 0:
                        month = i
                        month_name = calendar.month_name[month]
                        month_found = True
                        break
                if not month_found:
                    await message.reply(f"Invalid month '{month_arg}'. Please use a valid month name like 'Jan', 'Feb', etc.")
                    return
                try:
                    year = int(year_arg)
                    if year < 2000 or year > 2100:
                        await message.reply(f"Year '{year_arg}' is out of reasonable range (2000-2100).")
                        return
                except ValueError:
                    await message.reply(f"Invalid year '{year_arg}'. Please provide a valid year like 2025.")
                    return
                if len(command_parts) >= 4:
                    filter_currency = command_parts[3].upper()
            elif len(command_parts) == 2:
                month_arg = command_parts[1]
                month_found = False
                for i, month_abbr in enumerate(calendar.month_abbr):
                    if month_abbr.lower() == month_arg.lower()[:3] and i > 0:
                        month = i
                        month_name = calendar.month_name[month]
                        month_found = True
                        break
                if not month_found:
                    await message.reply(f"Invalid month '{month_arg}'. Please use a valid month name like 'Jan', 'Feb', etc.")
                    return
        except Exception as e:
            LOGS.error(f"Error in foreignsum command: {str(e)}")
            await message.reply(f"Error parsing date: {str(e)}\nUse format: `/foreignsum Jun 2025` or `/foreignsum Jun`")
            return
    if not is_date_range:
        start_date = f"{year}-{month:02d}-01"
        _, last_day = calendar.monthrange(year, month)
        end_date = f"{year}-{month:02d}-{last_day:02d}"
        display_period = f"{month_name} {year}"
    if filter_currency:
        await message.reply(f"Calculating {filter_currency} transaction totals for {display_period}...")
    else:
        await message.reply(f"Calculating foreign transaction totals for {display_period}...")
    try:
        api = FireflyApi()
        params = {
            'start': start_date,
            'end': end_date
        }
        transactions_response = api.get_json('transactions', params)
        usd_total = 0.0
        foreign_transactions = []
        MVR_PER_USD = 15.42
        for transaction_data in transactions_response['data']:
            transaction = transaction_data['attributes']
            for tx in transaction['transactions']:
                if 'foreign_amount' in tx and tx['foreign_amount'] and 'foreign_currency_code' in tx and tx['foreign_currency_code']:
                    foreign_currency = tx['foreign_currency_code']
                    foreign_amount = float(tx['foreign_amount'])
                    local_amount = float(tx['amount'])
                    if foreign_currency == 'USD':
                        usd_equiv = foreign_amount
                    else:
                        usd_equiv = local_amount / MVR_PER_USD
                    usd_total += usd_equiv
                    foreign_transactions.append({
                        'date': tx['date'],
                        'description': tx['description'],
                        'foreign_currency': foreign_currency,
                        'foreign_amount': foreign_amount,
                        'local_amount': local_amount,
                        'usd_equivalent': usd_equiv
                    })
        if foreign_transactions:
            foreign_transactions.sort(key=lambda x: x['date'], reverse=True)
            msg = f"**Foreign Transactions for {display_period} ({start_date} to {end_date}):**\n\n"
            msg += f"**Total in USD:** {usd_total:.2f}\n\n"
            msg += "**Recent Transactions (up to 10):**\n"
            for tx in foreign_transactions[:10]:
                if tx['foreign_currency'] != 'USD':
                    msg += f"• {tx['date'][:10]}: {tx['description']} - {tx['foreign_amount']:.2f} {tx['foreign_currency']} (MVR {tx['local_amount']:.2f}, USD {tx['usd_equivalent']:.2f})\n"
                else:
                    msg += f"• {tx['date'][:10]}: {tx['description']} - {tx['foreign_amount']:.2f} USD\n"
            if len(foreign_transactions) > 10:
                msg += f"\n...and {len(foreign_transactions) - 10} more transactions"
            if export_csv and foreign_transactions:
                csv_filename = f"foreign_transactions_{start_date}_to_{end_date}.csv"
                csv_path = os.path.join("downloads", csv_filename)
                os.makedirs(os.path.dirname(csv_path), exist_ok=True)
                with open(csv_path, 'w', newline='') as csvfile:
                    fieldnames = ['date', 'description', 'foreign_currency', 'foreign_amount', 'local_amount', 'usd_equivalent']
                    writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                    writer.writeheader()
                    for tx in foreign_transactions:
                        writer.writerow(tx)
                await message.reply_document(csv_path, caption=f"Full transaction data exported to CSV")
                await message.reply(msg)
            else:
                await message.reply(msg)
        else:
            await message.reply("No foreign transactions found for the specified period.")
    except Exception as e:
        await message.reply(f"Error calculating foreign transactions: {str(e)}")
    await message.stop_propagation()
