import json
import base64
import logging
from dataclasses import dataclass
from typing import Optional

from groq import APIError, Groq
from groq.types.chat.chat_completion_content_part_image_param import ChatCompletionContentPartImageParam, ImageURL
from groq.types.chat import ChatCompletionSystemMessageParam, ChatCompletionUserMessageParam, ChatCompletionContentPartTextParam
from groq.types.chat.completion_create_params import ResponseFormatResponseFormatJsonObject
from app import GROQ_API_KEY

LOGS = logging.getLogger(__name__)


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

def extract_transaction_details_from_image(path) -> TransactionExtractionResult:
    base_64_image = encode_image(path)
    
    image_for_ai = f"data:image/jpeg;base64,{base_64_image}"
        
    client = Groq(api_key=GROQ_API_KEY)
    try:
        completion = client.chat.completions.create(
            model="qwen/qwen3.6-27b",
            messages=[
                ChatCompletionUserMessageParam(role='user', content=[
                    ChatCompletionContentPartTextParam(type='text', text=get_system_message_for_image()),
                    ChatCompletionContentPartImageParam(type='image_url', image_url=ImageURL(detail='high', url=image_for_ai))
                    ]),
            ],
            temperature=0.6,
            max_completion_tokens=2048,
            top_p=0.95,
            stream=False,
            reasoning_effort="none",
            response_format=ResponseFormatResponseFormatJsonObject(type='json_object'),
            stop=None,
        )
    except APIError as error:
        LOGS.warning("Groq could not generate valid JSON for receipt extraction: %s", error)
        return TransactionExtractionResult(
            details=None,
            completion_data=None,
            error=f"Groq API error: {error}"
        )

    completion_data = serialize_completion(completion)

    try:
        ai_response = completion.choices[0].message.content
    except Exception as error:
        return TransactionExtractionResult(
            details=None,
            completion_data=completion_data,
            error=f"Could not read the completion content: {error}"
        )

    try:
        json_decoded = json.loads(ai_response)
    except Exception as error:
        return TransactionExtractionResult(
            details=None,
            completion_data=completion_data,
            error=f"Could not decode the completion content as JSON: {error}"
        )

    # If the response is `null` or not a dict, return early
    if not isinstance(json_decoded, dict):
        return TransactionExtractionResult(
            details=None,
            completion_data=completion_data,
            error=f"Expected a JSON object, received {type(json_decoded).__name__}."
        )

    required_keys = [
        'date', 'time', 'currency', 'amount',
        'location', 'reference_no'
    ]

    missing_keys = [key for key in required_keys if json_decoded.get(key) is None]
    if missing_keys:
        return TransactionExtractionResult(
            details=None,
            completion_data=completion_data,
            error=f"Missing required values: {', '.join(missing_keys)}"
        )

    return TransactionExtractionResult(
        details=json_decoded,
        completion_data=completion_data
    )


def extract_transaction_details_from_text(text: str) -> TransactionExtractionResult:
    """
    Uses Groq AI to extract transaction details from the given text.
    Returns parsed details together with the serialized Groq completion and any
    extraction error.
    """
    client = Groq(api_key=GROQ_API_KEY)
    try:
        completion = client.chat.completions.create(
            model="qwen/qwen3.6-27b",
            messages=[
                ChatCompletionSystemMessageParam(role='system', content=get_system_message_for_text()),
                ChatCompletionUserMessageParam(role='user', content=text),
            ],
            temperature=0.6,
            max_completion_tokens=2048,
            top_p=0.95,
            reasoning_effort="none",
            stream=False,
            response_format=ResponseFormatResponseFormatJsonObject(type='json_object'),
            stop=None,
        )
    except APIError as error:
        LOGS.warning("Groq could not generate valid JSON for transaction extraction: %s", error)
        return TransactionExtractionResult(
            details=None,
            completion_data=None,
            error=f"Groq API error: {error}"
        )

    completion_data = serialize_completion(completion)

    try:
        ai_response = completion.choices[0].message.content
    except Exception as error:
        return TransactionExtractionResult(
            details=None,
            completion_data=completion_data,
            error=f"Could not read the completion content: {error}"
        )

    try:
        json_decoded = json.loads(ai_response)
    except Exception as error:
        return TransactionExtractionResult(
            details=None,
            completion_data=completion_data,
            error=f"Could not decode the completion content as JSON: {error}"
        )

    # Ensure a valid dictionary was returned before accessing keys
    if not isinstance(json_decoded, dict):
        return TransactionExtractionResult(
            details=None,
            completion_data=completion_data,
            error=f"Expected a JSON object, received {type(json_decoded).__name__}."
        )

    required_keys = [
        'card', 'date', 'time', 'currency', 'amount',
        'location', 'approval_code', 'reference_no'
    ]

    missing_keys = [key for key in required_keys if json_decoded.get(key) is None]
    if missing_keys:
        return TransactionExtractionResult(
            details=None,
            completion_data=completion_data,
            error=f"Missing required values: {', '.join(missing_keys)}"
        )

    return TransactionExtractionResult(
        details=json_decoded,
        completion_data=completion_data
    )

def get_system_message_for_text():
    return """
You are a companion piece of a larger system that helps me to categorize my day to day transactions.
I will give you a sample set of Transaction Alert Messages that I receive from my bank.
Each of the transaction messages will contain what card the transaction was on,
the date and time of the transaction, the currency and amount of the transaction,
where the transaction was taken place, and other information such as approval codes and reference number.
Your task is it to extract out the important details of each transaction.
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

**Important Instructions for the `amount` Field:**
- The `amount` should always be a number, not a string.
- If the receipt contains the amount in a format like "MVR 1,234.56", extract only the numerical part and remove any commas. For example, "1,234.56" should be converted to `1234.56`.
- If the amount is not present or cannot be extracted, set the `amount` to `null`.

If any other details are missing, the corresponding key should have a value of `null`.
Ensure that all string values are properly quoted.

Do not include any additional text or explanations in your response. The output should exclusively be the JSON object.
"""
