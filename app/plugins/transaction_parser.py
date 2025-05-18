import json
from groq import Groq
from groq.types.chat import ChatCompletionSystemMessageParam, ChatCompletionUserMessageParam
from groq.types.chat.completion_create_params import ResponseFormat
from pyrogram import filters
from app.firefly.firefly import FireflyApi

from pyrogram.enums import ChatAction
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from app import FireflyParserBot, TELEGRAM_ADMINS, GROQ_API_KEY
from app.models.parsed_transaction_message import ParsedTransactionMessage


def extract_transaction_details_from_text(text: str) -> dict:
    """
    Uses Groq AI to extract transaction details from the given text.
    Returns a dict with keys: card, date, time, currency, amount, location, approval_code, reference_no.
    Returns None if parsing fails or required fields are missing.
    """
    client = Groq(api_key=GROQ_API_KEY)
    completion = client.chat.completions.create(
        model="meta-llama/llama-4-scout-17b-16e-instruct",
        messages=[
            ChatCompletionSystemMessageParam(role='system', content=get_system_message_for_text()),
            ChatCompletionUserMessageParam(role='user', content=text),
        ],
        temperature=1,
        max_completion_tokens=1024,
        top_p=1,
        stream=False,
        response_format=ResponseFormat(type='json_object'),
        stop=None,
    )

    ai_response = completion.choices[0].message.content
    
    try:
        json_decoded = json.loads(ai_response)
    except Exception:
        return None
    
    required_keys = [
        'card', 'date', 'time', 'currency', 'amount',
        'location', 'approval_code', 'reference_no'
    ]
    
    if any(json_decoded.get(k) is None for k in required_keys):
        return None
    
    return json_decoded


@FireflyParserBot.on_message(filters.private & filters.text & filters.user(TELEGRAM_ADMINS), group=100)
async def incoming_transaction_message(_, message: Message):
    await message.reply_chat_action(ChatAction.TYPING)

    json_decoded = extract_transaction_details_from_text(message.text)

    if json_decoded is None:
        await message.reply("I could not parse the transaction. Please try again.")
        return

    await message.reply(json_decoded)

    parsed_transaction_message = ParsedTransactionMessage(
        card=json_decoded['card'],
        date=json_decoded['date'],
        time=json_decoded['time'],
        currency=json_decoded['currency'],
        amount=json_decoded['amount'],
        location=json_decoded['location'],
        approval_code=json_decoded['approval_code'],
        reference_no=json_decoded['reference_no'],
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
