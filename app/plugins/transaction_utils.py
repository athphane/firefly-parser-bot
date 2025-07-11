import json
import base64
from groq import Groq
from groq.types.chat.chat_completion_content_part_image_param import ChatCompletionContentPartImageParam, ImageURL
from groq.types.chat import ChatCompletionSystemMessageParam, ChatCompletionUserMessageParam, ChatCompletionContentPartTextParam
from groq.types.chat.completion_create_params import ResponseFormatResponseFormatJsonObject
from app import GROQ_API_KEY

def encode_image(image_path: str) -> str:
    """
    Encodes an image to base64 format.
    :param image_path: Path to the image file.
    :return: Base64 encoded string of the image.
    """
    with open(image_path, 'rb') as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')

def extract_transaction_details_from_image(path) -> dict:
    base_64_image = encode_image(path)
    
    image_for_ai = f"data:image/jpeg;base64,{base_64_image}"
        
    client = Groq(api_key=GROQ_API_KEY)
    completion = client.chat.completions.create(
        model="meta-llama/llama-4-scout-17b-16e-instruct",
        messages=[
            ChatCompletionUserMessageParam(role='user', content=[
                ChatCompletionContentPartTextParam(type='text', text=get_system_message_for_image()),
                ChatCompletionContentPartImageParam(type='image_url', image_url=ImageURL(detail='high', url=image_for_ai))
                ]),
        ],
        temperature=1,
        max_completion_tokens=1024,
        top_p=1,
        stream=False,
        response_format=ResponseFormatResponseFormatJsonObject(type='json_object'),
        stop=None,
    )

    ai_response = completion.choices[0].message.content

    try:
        json_decoded = json.loads(ai_response)
    except Exception:
        return None

    # If the response is `null` or not a dict, return early
    if not isinstance(json_decoded, dict):
        return None

    required_keys = [
        'date', 'time', 'currency', 'amount',
        'location', 'reference_no'
    ]

    if any(json_decoded.get(k) is None for k in required_keys):
        return None

    return json_decoded

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
        response_format=ResponseFormatResponseFormatJsonObject(type='json_object'),
        stop=None,
    )

    ai_response = completion.choices[0].message.content

    try:
        json_decoded = json.loads(ai_response)
    except Exception:
        return None

    # Ensure a valid dictionary was returned before accessing keys
    if not isinstance(json_decoded, dict):
        return None

    required_keys = [
        'card', 'date', 'time', 'currency', 'amount',
        'location', 'approval_code', 'reference_no'
    ]

    if any(json_decoded.get(k) is None for k in required_keys):
        return None

    return json_decoded

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