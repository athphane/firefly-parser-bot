import json
import base64
import logging
import mimetypes
from decimal import Decimal, InvalidOperation
from dataclasses import dataclass
from typing import Optional

from groq import APIError, Groq
from groq.types.chat.chat_completion_content_part_image_param import ChatCompletionContentPartImageParam, ImageURL
from groq.types.chat import ChatCompletionSystemMessageParam, ChatCompletionUserMessageParam, ChatCompletionContentPartTextParam
from groq.types.chat.completion_create_params import ResponseFormatResponseFormatJsonObject
from app import (
    GROQ_API_KEY, GROQ_MODEL, GROQ_REQUESTS_PER_MINUTE,
    GROQ_TOKENS_PER_MINUTE, GROQ_TOKENS_PER_DAY, GROQ_IMAGE_TOKENS, WORKDIR,
)
from app.groq_rate_limit import GroqRateLimiter

LOGS = logging.getLogger(__name__)
GROQ_MAX_COMPLETION_TOKENS = 2048
GROQ_RATE_LIMITER = GroqRateLimiter(
    GROQ_REQUESTS_PER_MINUTE, GROQ_TOKENS_PER_MINUTE, GROQ_TOKENS_PER_DAY,
    WORKDIR / "groq-rate-limit.json",
)


def create_completion(messages):
    # UTF-8 byte length is a conservative text token estimate. Include chat
    # framing, image tokens and the maximum output before admitting a request.
    prompt_tokens = 32
    for message in messages:
        prompt_tokens += 32
        content = message['content']
        if isinstance(content, str):
            prompt_tokens += len(content.encode('utf-8'))
        else:
            for part in content:
                if part['type'] == 'text':
                    prompt_tokens += len(part['text'].encode('utf-8'))
                elif part['type'] == 'image_url':
                    prompt_tokens += GROQ_IMAGE_TOKENS

    # Disable SDK retries so every attempt passes through the limiter.
    with Groq(api_key=GROQ_API_KEY, max_retries=0) as client:
        return GROQ_RATE_LIMITER.run(
            lambda: client.chat.completions.create(
                model=GROQ_MODEL,
                messages=messages,
                temperature=0.6,
                max_completion_tokens=GROQ_MAX_COMPLETION_TOKENS,
                top_p=0.95,
                stream=False,
                reasoning_effort="none",
                response_format=ResponseFormatResponseFormatJsonObject(type='json_object'),
                stop=None,
            ),
            prompt_tokens + GROQ_MAX_COMPLETION_TOKENS,
        )


@dataclass
class TransactionExtractionResult:
    details: Optional[dict]
    completion_data: Optional[str]
    error: Optional[str] = None


def serialize_completion(completion) -> str:
    try:
        return completion.model_dump_json(indent=2)
    except Exception:
        return repr(completion)


def encode_image(image_path: str) -> str:
    """
    Encodes an image to base64 format.
    :param image_path: Path to the image file.
    :return: Base64 encoded string of the image.
    """
    with open(image_path, 'rb') as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')


def parse_completion(completion, required_keys: tuple[str, ...]) -> TransactionExtractionResult:
    """Validate and decode the structured content returned by Groq."""
    completion_data = serialize_completion(completion)

    try:
        content = completion.choices[0].message.content
        decoded = json.loads(content, parse_float=Decimal)
    except (AttributeError, IndexError, TypeError, json.JSONDecodeError) as error:
        return TransactionExtractionResult(
            details=None,
            completion_data=completion_data,
            error=f"Could not decode the completion content as JSON: {error}",
            )

    if not isinstance(decoded, dict):
        return TransactionExtractionResult(
            details=None,
            completion_data=completion_data,
            error=f"Expected a JSON object, received {type(decoded).__name__}.",
        )

    missing_keys = [key for key in required_keys if decoded.get(key) is None]
    if missing_keys:
        return TransactionExtractionResult(
            details=None,
            completion_data=completion_data,
            error=f"Missing required values: {', '.join(missing_keys)}",
        )

    string_keys = set(required_keys) - {'amount'}
    invalid_strings = [
        key for key in string_keys
        if isinstance(decoded[key], bool) or not isinstance(decoded[key], (str, int)) or not str(decoded[key]).strip()
    ]
    if invalid_strings:
        return TransactionExtractionResult(
            details=None,
            completion_data=completion_data,
            error=f"Invalid required values: {', '.join(sorted(invalid_strings))}",
        )
    for key in string_keys:
        decoded[key] = str(decoded[key]).strip()
    decoded['currency'] = decoded['currency'].upper()

    try:
        decoded['amount'] = Decimal(str(decoded['amount']).replace(',', ''))
    except (InvalidOperation, TypeError, ValueError):
        return TransactionExtractionResult(
            details=None,
            completion_data=completion_data,
            error="The extracted amount is not a valid number.",
        )

    if not decoded['amount'].is_finite() or decoded['amount'] <= 0:
        return TransactionExtractionResult(
            details=None,
            completion_data=completion_data,
            error="The extracted amount must be greater than zero.",
        )

    return TransactionExtractionResult(details=decoded, completion_data=completion_data)


def extract_transaction_details_from_image(path: str) -> TransactionExtractionResult:
    try:
        base_64_image = encode_image(path)
        media_type = mimetypes.guess_type(path)[0] or "image/jpeg"
        if not media_type.startswith("image/"):
            media_type = "image/jpeg"
        image_for_ai = f"data:{media_type};base64,{base_64_image}"
        completion = create_completion([
            ChatCompletionUserMessageParam(role='user', content=[
                ChatCompletionContentPartTextParam(type='text', text=get_system_message_for_image()),
                ChatCompletionContentPartImageParam(type='image_url', image_url=ImageURL(detail='high', url=image_for_ai))
            ]),
        ])
    except (APIError, ValueError, OSError) as error:
        LOGS.warning("Groq could not generate valid JSON for receipt extraction: %s", error)
        return TransactionExtractionResult(
            details=None,
            completion_data=None,
            error=f"Groq API error: {error}"
        )

    required_keys = (
        'date', 'time', 'currency', 'amount',
        'location', 'reference_no'
    )
    return parse_completion(completion, required_keys)


def extract_transaction_details_from_text(text: str) -> TransactionExtractionResult:
    """
    Uses Groq AI to extract transaction details from the given text.
    Returns parsed details together with the serialized Groq completion and any
    extraction error.
    """
    try:
        completion = create_completion([
            ChatCompletionSystemMessageParam(role='system', content=get_system_message_for_text()),
            ChatCompletionUserMessageParam(role='user', content=text),
        ])
    except (APIError, ValueError, OSError) as error:
        LOGS.warning("Groq could not generate valid JSON for transaction extraction: %s", error)
        return TransactionExtractionResult(
            details=None,
            completion_data=None,
            error=f"Groq API error: {error}"
        )

    # Card and approval code are genuinely optional; many alerts omit them.
    required_keys = (
        'date', 'time', 'currency', 'amount', 'location', 'reference_no'
    )
    return parse_completion(completion, required_keys)

def get_system_message_for_text():
    return """
You are a companion piece of a larger system that helps me to categorize my day to day transactions.
I will give you a sample set of Transaction Alert Messages that I receive from my bank.
Each of the transaction messages will contain what card the transaction was on,
the date and time of the transaction, the currency and amount of the transaction,
where the transaction was taken place, and other information such as approval codes and reference number.
Your task is it to extract out the important details of each transaction.
Return `date` as DD/MM/YY and `time` as HH:MM:SS using a 24-hour clock.
You must output exactly one valid JSON object, never a JSON string or top-level null. The JSON object MUST have the following keys: card,date,time,currency,amount,location,approval_code,reference_no.
If you cannot find any value, set that key to null. Keep every required key in the object.
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
Return `date` as DD/MM/YYYY and `time` as HH:MM using a 24-hour clock. Include seconds as HH:MM:SS when they are printed.

**Important Instructions for the `amount` Field:**
- The `amount` should always be a number, not a string.
- If the receipt contains the amount in a format like "MVR 1,234.56", extract only the numerical part and remove any commas. For example, "1,234.56" should be converted to `1234.56`.
- If the amount is not present or cannot be extracted, set the `amount` to `null`.

If any other details are missing, the corresponding key should have a value of `null`.
Ensure that all string values are properly quoted.

Do not include any additional text or explanations in your response. The output should exclusively be the JSON object.
"""
