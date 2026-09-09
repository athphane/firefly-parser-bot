from pyrogram import filters
from app.firefly.firefly import FireflyApi
from io import BytesIO
import logging
import os

from pyrogram.enums import ChatAction
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from app import FireflyParserBot, TELEGRAM_ADMINS
from app.models.parsed_transaction_message import ParsedTransactionMessage

from app.plugins.transaction_customization import TRANSACTION_ID_PREFIX
from app.plugins.transaction_utils import (
    TransactionExtractionResult,
    extract_transaction_details_from_image,
    extract_transaction_details_from_text,
)

LOGS = logging.getLogger(__name__)


async def reply_with_error_file(message: Message, error_message: str):
    with BytesIO(error_message.encode("utf-8")) as error_file:
        error_file.name = f"transaction-error-{message.id}.txt"
        await message.reply_document(
            error_file,
            caption="Transaction processing error",
            reply_to_message_id=message.id
        )


def build_error_report(
    error_message: str,
    extraction_result: TransactionExtractionResult
) -> str:
    completion_data = extraction_result.completion_data or "No completion was returned by Groq."
    sections = [error_message]
    if extraction_result.error:
        sections.append(f"Extraction error:\n{extraction_result.error}")
    sections.append(f"Groq completion data:\n{completion_data}")
    return "\n\n".join(sections)


def clear_reply_contexts():
    """Clear any existing reply contexts to prevent conflicts."""
    if hasattr(FireflyParserBot, '_add_alias_context'):
        FireflyParserBot._add_alias_context = None
    if hasattr(FireflyParserBot, '_edit_vendor_name_context'):
        FireflyParserBot._edit_vendor_name_context = None
    if hasattr(FireflyParserBot, '_add_tag_context'):
        FireflyParserBot._add_tag_context = None
    if hasattr(FireflyParserBot, '_incoming_money_contexts'):
        FireflyParserBot._incoming_money_contexts = {}


@FireflyParserBot.on_message(filters.private & filters.text & filters.user(TELEGRAM_ADMINS), group=100)
async def incoming_transaction_message(_, message: Message):
    # Clear any vendor management reply contexts
    clear_reply_contexts()
    
    await message.reply_chat_action(ChatAction.TYPING)

    extraction_result = extract_transaction_details_from_text(message.text)
    json_decoded = extraction_result.details
    LOGS.info("json_decoded for text message %s: %s", message.id, json_decoded)

    if json_decoded is None:
        await reply_with_error_file(
            message,
            build_error_report(
                "I could not parse the transaction. Please try again.",
                extraction_result
            )
        )
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
            [InlineKeyboardButton("🔗 View in Firefly", url=link)],
            [InlineKeyboardButton("⚙️ Customize Transaction", callback_data=f"{TRANSACTION_ID_PREFIX}{transaction_id}")]
        ])
        
        await message.reply(
            details,
            reply_markup=markup,
            reply_to_message_id=message.id
        )
        return
    except Exception as e:
        details = f"Transaction created, but could not parse details. Error: {e}"
        LOGS.exception("Could not parse the created text transaction response")
        await reply_with_error_file(
            message,
            build_error_report(details, extraction_result)
        )
        return


@FireflyParserBot.on_message(filters.private & filters.photo & filters.user(TELEGRAM_ADMINS), group=100)
async def incoming_transfer_receipt(_, message: Message):
    # Clear any vendor management reply contexts
    clear_reply_contexts()
    
    await message.reply_chat_action(ChatAction.TYPING)
    
    path = await message.download()

    try:
        extraction_result = extract_transaction_details_from_image(path)
        json_decoded = extraction_result.details
        LOGS.info("json_decoded for photo message %s: %s", message.id, json_decoded)

        if json_decoded is None:
            await reply_with_error_file(
                message,
                build_error_report(
                    "I could not parse the transaction. Please try again.",
                    extraction_result
                )
            )
            return

        parsed_transaction_message = ParsedTransactionMessage(
            date=json_decoded['date'],
            time=json_decoded['time'],
            currency=json_decoded['currency'],
            amount=json_decoded['amount'],
            location=json_decoded['location'],
            reference_no=json_decoded['reference_no']
        )

        response = parsed_transaction_message.create_transaction_on_firefly(is_receipt=True, image_path=path)

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
                [InlineKeyboardButton("🔗 View in Firefly", url=link)],
                [InlineKeyboardButton("⚙️ Customize Transaction", callback_data=f"{TRANSACTION_ID_PREFIX}{transaction_id}")]
            ])

            await message.reply(
                details,
                reply_markup=markup,
                reply_to_message_id=message.id
            )
        except Exception as e:
            details = f"Transaction created, but could not parse details. Error: {e}"
            LOGS.exception("Could not parse the created photo transaction response")
            await reply_with_error_file(
                message,
                build_error_report(details, extraction_result)
            )
    finally:
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
