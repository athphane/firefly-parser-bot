from pyrogram import filters
from app.firefly.firefly import FireflyApi


from pyrogram.enums import ChatAction
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from app import FireflyParserBot, TELEGRAM_ADMINS
from app.models.parsed_transaction_message import ParsedTransactionMessage

from app.plugins.transaction_utils import extract_transaction_details_from_image, extract_transaction_details_from_text


@FireflyParserBot.on_message(filters.private & filters.text & filters.user(TELEGRAM_ADMINS), group=100)
async def incoming_transaction_message(_, message: Message):
    await message.reply_chat_action(ChatAction.TYPING)

    json_decoded = extract_transaction_details_from_text(message.text)

    if json_decoded is None:
        await message.reply("I could not parse the transaction. Please try again.")
        return

    parsed_transaction_message = ParsedTransactionMessage(
        date=json_decoded['date'],
        time=json_decoded['time'],
        currency=json_decoded['currency'],
        amount=json_decoded['amount'],
        location=json_decoded['location'],
        reference_no=json_decoded['reference_no'],
        card=json_decoded['card'],
        approval_code=json_decoded['approval_code'],
        raw_transaction_message=message.text
    )

    response = parsed_transaction_message.create_transaction_on_firefly()

    # Prepare a concise reply with transaction details and a button link using Pyrogram's InlineKeyboardMarkup
    try:
        transaction = response.json()['data']['attributes']['transactions'][0]
        transaction_id = response.json()['data']['id']
        
        link = FireflyApi().transaction_show_url(transaction_id)
        
        details = (
            f"**Transaction created!**\n"
            f"**Description:** {transaction.get('description')}\n"
            f"**Amount:** {float(transaction.get('amount')):.2f} {transaction.get('currency_code')}\n"
            f"**Date & Time:** {transaction.get('date')}\n"
            f"**Destination:** {transaction.get('destination_name')}"
        )
        
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("View in Firefly", url=link)]
        ])
        
        await message.reply(details, reply_markup=markup)
        return
    except Exception as e:
        details = f"Transaction created, but could not parse details. Error: {e}"
        await message.reply(details)
        print(e)
        return


@FireflyParserBot.on_message(filters.private & filters.photo & filters.user(TELEGRAM_ADMINS), group=100)
async def incoming_transfer_receipt(_, message: Message):
    await message.reply_chat_action(ChatAction.TYPING)
    
    path = await message.download()

    json_decoded = extract_transaction_details_from_image(path)

    if json_decoded is None:
        await message.reply("I could not parse the transaction. Please try again.")
        return

    parsed_transaction_message = ParsedTransactionMessage(
        date=json_decoded['date'],
        time=json_decoded['time'],
        currency=json_decoded['currency'],
        amount=json_decoded['amount'],
        location=json_decoded['location'],
        reference_no=json_decoded['reference_no'],
    )

    response = parsed_transaction_message.create_transaction_on_firefly(is_receipt=True)


    # Prepare a concise reply with transaction details and a button link using Pyrogram's InlineKeyboardMarkup
    try:
        transaction = response.json()['data']['attributes']['transactions'][0]
        transaction_id = response.json()['data']['id']
        
        link = FireflyApi().transaction_show_url(transaction_id)
        
        details = (
            f"**Transaction created!**\n"
            f"**Description:** {transaction.get('description')}\n"
            f"**Amount:** {float(transaction.get('amount')):.2f} {transaction.get('currency_code')}\n"
            f"**Date & Time:** {transaction.get('date')}\n"
            f"**Destination:** {transaction.get('destination_name')}"
        )
        
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("View in Firefly", url=link)]
        ])
        
        await message.reply(details, reply_markup=markup)
        return
    except Exception as e:
        details = f"Transaction created, but could not parse details. Error: {e}"
        await message.reply(details)
        return


def get_system_message_for_text():
    return """
You are a companion piece of a larger system that helps me to categorize my day to day transactions.
I will give you a sample set of Transaction Alert Messages that I receive from my bank.
Each of the transaction messages will contain what card the transaction was on,
the date and time of the transaction, the currency and amount of the transaction,
where the transaction was taken place, and other information such as approval codes and reference number.
Your task is it to extract out the important details of each transaction.
You should output each transaction as a json object. Give the json object as as string. The json object you return MUST have the following keys: card,date,time,currency,amount,location,approval_code,reference_no.
If you cannot find any of the above keys, please return null.
When stripping whitespace from the values, please make sure to ONLY strip the whitespace from the start and end of the string. Any whitespace other than that is important.
The system that uses you will parse it into json and go on from there. Please do not do any markdown formatting.
"""


def get_system_message_for_image():
    return """
You are part of a system designed to extract specific details from transaction receipts.
When given an image of a receipt, your task is to extract the following information:
- Date of the transaction
- Time of the transaction
- Currency used
- Amount of the transaction
- Location (referred to as the "to" field on the receipt)
- Reference number of the transaction

You must output the extracted data as a JSON object with the keys: `date`, `time`, `currency`, `amount`, `location`, and `reference_no`.

**Important Instructions for the `amount` Field:**
- The `amount` should always be a number, not a string.
- If the receipt contains the amount in a format like "MVR 1,234.56", extract only the numerical part and remove any commas. For example, "1,234.56" should be converted to `1234.56`.
- If the amount is not present or cannot be extracted, set the `amount` to `null`.

If any other details are missing, the corresponding key should have a value of `null`.
Ensure that all string values are properly quoted.

Do not include any additional text or explanations in your response. The output should exclusively be the JSON object.
"""