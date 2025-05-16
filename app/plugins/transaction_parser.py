import json

from groq import Groq
from groq.types.chat import ChatCompletionSystemMessageParam, ChatCompletionUserMessageParam
from groq.types.chat.completion_create_params import ResponseFormat
from pyrogram import filters
from pyrogram.enums import ChatAction
from pyrogram.types import Message

from app import FireflyParserBot, TELEGRAM_ADMINS, GROQ_API_KEY


@FireflyParserBot.on_message(filters.private & filters.text & filters.user(TELEGRAM_ADMINS), group=100)
async def incoming_transaction_message(_, message: Message):
    await message.reply_chat_action(ChatAction.TYPING)

    client = Groq(api_key=GROQ_API_KEY)
    completion = client.chat.completions.create(
        model="meta-llama/llama-4-scout-17b-16e-instruct",
        messages=[
            ChatCompletionSystemMessageParam(role='system', content=get_system_message_for_text()),
            ChatCompletionUserMessageParam(role='user', content=message.text),
        ],
        temperature=1,
        max_completion_tokens=1024,
        top_p=1,
        stream=False,
        response_format=ResponseFormat(type='json_object'),
        stop=None,
    )

    ai_response = completion.choices[0].message.content

    json_decoded = json.loads(ai_response)

    # check if all the keys are not None
    if json_decoded.get('card') is None or json_decoded.get('date') is None or json_decoded.get('time') is None \
            or json_decoded.get('currency') is None or json_decoded.get('amount') is None \
            or json_decoded.get('location') is None or json_decoded.get('approval_code') is None \
            or json_decoded.get('reference_no') is None:
        await message.reply("I could not parse the transaction. Please try again.")
        return

    await message.reply(json_decoded)



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
The system that uses you will parse it into json and go on from there. Please do not do any markdown formatting.
"""
