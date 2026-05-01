from datetime import datetime
from decimal import Decimal, InvalidOperation
import logging

from pyrogram import filters
from pyrogram.enums import ButtonStyle, ChatAction
from pyrogram.types import CallbackQuery, ForceReply, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app import FireflyParserBot, TELEGRAM_ADMINS
from app.firefly.firefly import FireflyApi
from app.models.transaction_models import Account

LOGS = logging.getLogger(__name__)

INCOME_REVENUE_PREFIX = "income_revenue:"
INCOME_ASSET_PREFIX = "income_asset:"
INCOME_CREATE_CALLBACK = "income_create"
INCOME_RESTART_CALLBACK = "income_restart"
INCOME_CANCEL_CALLBACK = "income_cancel"


def _incoming_money_contexts() -> dict[int, dict]:
    if not hasattr(FireflyParserBot, '_incoming_money_contexts'):
        FireflyParserBot._incoming_money_contexts = {}

    contexts = getattr(FireflyParserBot, '_incoming_money_contexts')
    if contexts is None:
        FireflyParserBot._incoming_money_contexts = {}
        contexts = FireflyParserBot._incoming_money_contexts

    return contexts


def _get_context(user_id: int) -> dict | None:
    return _incoming_money_contexts().get(user_id)


def _set_context(user_id: int, context: dict) -> None:
    _incoming_money_contexts()[user_id] = context


def _clear_context(user_id: int) -> None:
    _incoming_money_contexts().pop(user_id, None)


async def _clear_other_reply_contexts(message: Message) -> None:
    for attr in ['_add_alias_context', '_edit_vendor_name_context', '_add_tag_context']:
        ctx = getattr(FireflyParserBot, attr, None)
        if ctx and ctx.get('reply_message_id'):
            try:
                await message.chat.delete_messages(ctx['reply_message_id'])
            except Exception:
                pass

        if hasattr(FireflyParserBot, attr):
            setattr(FireflyParserBot, attr, None)


async def _delete_reply_prompt(message: Message, context: dict | None) -> None:
    if not context or not context.get('reply_message_id'):
        return

    try:
        await message.chat.delete_messages(context['reply_message_id'])
    except Exception:
        pass


def _trim_button_label(label: str) -> str:
    if len(label) <= 60:
        return label

    return f"{label[:57]}..."


def _account_buttons(accounts: list[Account], callback_prefix: str) -> list[list[InlineKeyboardButton]]:
    buttons = []
    for account in accounts:
        buttons.append([InlineKeyboardButton(
            _trim_button_label(account.name),
            callback_data=f"{callback_prefix}{account.id}",
            style=ButtonStyle.SUCCESS
        )])

    buttons.append([InlineKeyboardButton("Cancel", callback_data=INCOME_CANCEL_CALLBACK, style=ButtonStyle.DANGER)])
    return buttons


def _cancel_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Cancel", callback_data=INCOME_CANCEL_CALLBACK, style=ButtonStyle.DANGER)]
    ])


def _confirm_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Create Transaction", callback_data=INCOME_CREATE_CALLBACK, style=ButtonStyle.SUCCESS)],
        [InlineKeyboardButton("Start Over", callback_data=INCOME_RESTART_CALLBACK, style=ButtonStyle.DEFAULT)],
        [InlineKeyboardButton("Cancel", callback_data=INCOME_CANCEL_CALLBACK, style=ButtonStyle.DANGER)]
    ])


def _find_account(accounts: list[Account], account_id: str) -> Account | None:
    for account in accounts:
        if str(account.id) == str(account_id):
            return account

    return None


def _parse_amount(amount_text: str) -> str | None:
    normalized_amount = amount_text.strip().replace(',', '')

    try:
        amount = Decimal(normalized_amount)
    except (InvalidOperation, ValueError):
        return None

    if not amount.is_finite() or amount <= 0:
        return None

    return format(amount, 'f')


def _selection_text(context: dict) -> str:
    text = "**Record Incoming Money**\n\n"

    revenue_account_name = context.get('revenue_account_name')
    asset_account_name = context.get('asset_account_name')
    amount = context.get('amount')

    if revenue_account_name:
        text += f"**Revenue account:** {revenue_account_name}\n"
    if asset_account_name:
        text += f"**Asset account:** {asset_account_name}\n"
    if amount:
        text += f"**Amount:** {amount}\n"

    return text


def _summary_text(context: dict) -> str:
    return (
        "**Incoming Money Summary**\n\n"
        f"**Revenue account:** {context['revenue_account_name']}\n"
        f"**Asset account:** {context['asset_account_name']}\n"
        f"**Amount:** {context['amount']}\n"
        f"**Description:** {context['description']}\n\n"
        "Create this transaction in Firefly III?"
    )


async def _start_income_flow(message: Message, user_id: int, edit_existing: bool = False) -> None:
    firefly_api = FireflyApi()

    try:
        revenue_accounts = firefly_api.get_revenue_accounts()
    except Exception as e:
        LOGS.error(f"Error fetching revenue accounts: {e}")
        error_text = "Failed to fetch revenue accounts from Firefly III. Please try again later."
        if edit_existing:
            await message.edit_text(error_text)
        else:
            await message.reply(error_text)
        return

    if not revenue_accounts:
        text = "No revenue accounts found in Firefly III."
        if edit_existing:
            await message.edit_text(text)
        else:
            await message.reply(text)
        return

    text = "**Record Incoming Money**\n\nSelect the revenue account this money came from."
    markup = InlineKeyboardMarkup(_account_buttons(revenue_accounts, INCOME_REVENUE_PREFIX))

    if edit_existing:
        await message.edit_text(text, reply_markup=markup)
        context_message_id = message.id
    else:
        sent_message = await message.reply(text, reply_markup=markup)
        context_message_id = sent_message.id

    _set_context(user_id, {
        'state': 'select_revenue',
        'message_id': context_message_id
    })


async def _get_callback_context(callback_query: CallbackQuery, expected_states: set[str] | None = None) -> dict | None:
    context = _get_context(callback_query.from_user.id)
    if not context or context.get('message_id') != callback_query.message.id:
        await callback_query.answer("This income flow has expired. Send /income again.")
        return None

    if expected_states and context.get('state') not in expected_states:
        await callback_query.answer("This income flow has expired. Send /income again.")
        return None

    await callback_query.answer()
    return context


async def _prompt_for_amount(message: Message, user_id: int, context: dict) -> None:
    context['state'] = 'awaiting_amount'
    reply_message = await message.reply(
        "Enter the amount you are receiving.",
        reply_markup=ForceReply(selective=True)
    )

    context['reply_message_id'] = reply_message.id
    _set_context(user_id, context)


async def _prompt_for_description(message: Message, user_id: int, context: dict) -> None:
    context['state'] = 'awaiting_description'
    reply_message = await message.reply(
        "Enter a short transaction description.",
        reply_markup=ForceReply(selective=True)
    )

    context['reply_message_id'] = reply_message.id
    _set_context(user_id, context)


async def _send_review_message(message: Message, user_id: int, context: dict) -> None:
    review_message = await message.reply(_summary_text(context), reply_markup=_confirm_markup())

    context['message_id'] = review_message.id
    _set_context(user_id, context)


@FireflyParserBot.on_message(filters.private & filters.user(TELEGRAM_ADMINS) & filters.command(["income", "incoming"]), group=1)
async def income_command(_, message: Message) -> None:
    await message.reply_chat_action(ChatAction.TYPING)
    await _clear_other_reply_contexts(message)

    user_id = message.from_user.id
    existing_context = _get_context(user_id)
    await _delete_reply_prompt(message, existing_context)
    _clear_context(user_id)

    await _start_income_flow(message, user_id)
    await message.stop_propagation()


@FireflyParserBot.on_callback_query(filters.regex(f"^{INCOME_REVENUE_PREFIX}.*") & filters.user(TELEGRAM_ADMINS))
async def select_revenue_account(_, callback_query: CallbackQuery) -> None:
    context = await _get_callback_context(callback_query, {'select_revenue'})
    if not context:
        return

    revenue_account_id = callback_query.data.replace(INCOME_REVENUE_PREFIX, '', 1)
    firefly_api = FireflyApi()

    try:
        revenue_accounts = firefly_api.get_revenue_accounts()
        asset_accounts = firefly_api.get_asset_accounts()
    except Exception as e:
        LOGS.error(f"Error fetching accounts for incoming transaction: {e}")
        await callback_query.message.edit_text("Failed to fetch accounts from Firefly III. Please try again later.")
        return

    revenue_account = _find_account(revenue_accounts, revenue_account_id)
    if not revenue_account:
        await callback_query.message.edit_text("Selected revenue account was not found. Send /income to start again.")
        _clear_context(callback_query.from_user.id)
        return

    if not asset_accounts:
        await callback_query.message.edit_text("No asset accounts found in Firefly III.")
        _clear_context(callback_query.from_user.id)
        return

    context.update({
        'state': 'select_asset',
        'revenue_account_id': revenue_account.id,
        'revenue_account_name': revenue_account.name
    })
    _set_context(callback_query.from_user.id, context)

    text = f"{_selection_text(context)}\nSelect the asset account where this money belongs."
    markup = InlineKeyboardMarkup(_account_buttons(asset_accounts, INCOME_ASSET_PREFIX))
    await callback_query.message.edit_text(text, reply_markup=markup)


@FireflyParserBot.on_callback_query(filters.regex(f"^{INCOME_ASSET_PREFIX}.*") & filters.user(TELEGRAM_ADMINS))
async def select_asset_account(_, callback_query: CallbackQuery) -> None:
    context = await _get_callback_context(callback_query, {'select_asset'})
    if not context:
        return

    asset_account_id = callback_query.data.replace(INCOME_ASSET_PREFIX, '', 1)
    firefly_api = FireflyApi()

    try:
        asset_accounts = firefly_api.get_asset_accounts()
    except Exception as e:
        LOGS.error(f"Error fetching asset accounts for incoming transaction: {e}")
        await callback_query.message.edit_text("Failed to fetch asset accounts from Firefly III. Please try again later.")
        return

    asset_account = _find_account(asset_accounts, asset_account_id)
    if not asset_account:
        await callback_query.message.edit_text("Selected asset account was not found. Send /income to start again.")
        _clear_context(callback_query.from_user.id)
        return

    context.update({
        'asset_account_id': asset_account.id,
        'asset_account_name': asset_account.name
    })

    await _prompt_for_amount(callback_query.message, callback_query.from_user.id, context)


@FireflyParserBot.on_message(filters.private & filters.text & filters.user(TELEGRAM_ADMINS), group=10)
async def handle_income_reply(client: FireflyParserBot, message: Message) -> None:
    context = _get_context(message.from_user.id)
    if not context or context.get('state') not in {'awaiting_amount', 'awaiting_description'}:
        await message.continue_propagation()
        return

    if context.get('reply_message_id') != message.reply_to_message_id:
        await message.continue_propagation()
        return

    original_message = await client.get_messages(message.chat.id, context['message_id'])
    await _delete_reply_prompt(message, context)

    try:
        await message.delete()
    except Exception:
        pass

    if context['state'] == 'awaiting_amount':
        amount = _parse_amount(message.text)
        if not amount:
            reply_message = await original_message.reply(
                "Enter a positive amount, for example 1250.50.",
                reply_markup=ForceReply(selective=True)
            )
            context['reply_message_id'] = reply_message.id
            _set_context(message.from_user.id, context)
            await message.stop_propagation()
            return

        context['amount'] = amount
        await _prompt_for_description(original_message, message.from_user.id, context)
        await message.stop_propagation()
        return

    description = message.text.strip()
    if not description:
        reply_message = await original_message.reply(
            "Enter a short transaction description.",
            reply_markup=ForceReply(selective=True)
        )
        context['reply_message_id'] = reply_message.id
        _set_context(message.from_user.id, context)
        await message.stop_propagation()
        return

    context.update({
        'state': 'confirm',
        'description': description,
        'reply_message_id': None
    })
    _set_context(message.from_user.id, context)

    await _send_review_message(original_message, message.from_user.id, context)
    await message.stop_propagation()


@FireflyParserBot.on_callback_query(filters.regex(f"^{INCOME_CREATE_CALLBACK}$") & filters.user(TELEGRAM_ADMINS))
async def create_income_transaction(_, callback_query: CallbackQuery) -> None:
    context = await _get_callback_context(callback_query, {'confirm'})
    if not context:
        return

    firefly_api = FireflyApi()

    try:
        response = firefly_api.create_incoming_transaction(
            revenue_account_id=context['revenue_account_id'],
            asset_account_id=context['asset_account_id'],
            amount=context['amount'],
            description=context['description'],
            date=datetime.now().isoformat(timespec='seconds')
        )

        transaction_id = response['data']['id']
        transaction = response['data']['attributes']['transactions'][0]
        link = firefly_api.transaction_show_url(transaction_id)

        details = (
            "**Incoming transaction created!**\n"
            f"**Description:** {transaction.get('description')}\n"
            f"**Amount:** {float(transaction.get('amount')):.2f} {transaction.get('currency_code')}\n"
            f"**Date & Time:** {transaction.get('date')}\n"
            f"**Source:** {transaction.get('source_name')}\n"
            f"**Destination:** {transaction.get('destination_name')}"
        )
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("View in Firefly", url=link, style=ButtonStyle.PRIMARY)]
        ])

        await callback_query.message.edit_text(details, reply_markup=markup)
        _clear_context(callback_query.from_user.id)
    except Exception as e:
        LOGS.error(f"Error creating incoming transaction: {e}")
        await callback_query.message.edit_text(
            f"{_summary_text(context)}\n\nFailed to create the transaction. Please try again.",
            reply_markup=_confirm_markup()
        )


@FireflyParserBot.on_callback_query(filters.regex(f"^{INCOME_RESTART_CALLBACK}$") & filters.user(TELEGRAM_ADMINS))
async def restart_income_transaction(_, callback_query: CallbackQuery) -> None:
    context = await _get_callback_context(callback_query)
    if not context:
        return

    await _delete_reply_prompt(callback_query.message, context)
    _clear_context(callback_query.from_user.id)
    await _start_income_flow(callback_query.message, callback_query.from_user.id, edit_existing=True)


@FireflyParserBot.on_callback_query(filters.regex(f"^{INCOME_CANCEL_CALLBACK}$") & filters.user(TELEGRAM_ADMINS))
async def cancel_income_transaction(_, callback_query: CallbackQuery) -> None:
    context = _get_context(callback_query.from_user.id)
    if not context or context.get('message_id') != callback_query.message.id:
        await callback_query.answer("This income flow has expired. Send /income again.")
        return

    await callback_query.answer("Cancelled")
    await _delete_reply_prompt(callback_query.message, context)
    _clear_context(callback_query.from_user.id)
    await callback_query.message.edit_text("Incoming transaction cancelled.")
