from pyrogram import filters, StopPropagation
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, Message, ForceReply
from app import FireflyParserBot, TELEGRAM_ADMINS
from app.firefly.firefly import FireflyApi
import asyncio
import logging
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

LOGS = logging.getLogger(__name__)


def parse_positive_amount(value) -> Decimal:
    """Parse a finite, positive monetary value without binary float errors."""
    try:
        amount = Decimal(str(value).strip().replace(',', ''))
    except (InvalidOperation, TypeError, ValueError) as error:
        raise ValueError("Amount must be a number") from error
    if not amount.is_finite() or amount <= 0:
        raise ValueError("Amount must be positive")
    return amount


def money(value: Decimal, decimal_places: int = 2) -> Decimal:
    rounded = value.quantize(Decimal(1).scaleb(-decimal_places), rounding=ROUND_HALF_UP)
    if rounded <= 0:
        raise ValueError("The resulting amount must be greater than zero.")
    return rounded


def get_inner_transaction(response: dict) -> dict:
    """Return the first transaction split or reject a malformed API response."""
    try:
        transactions = response['data']['attributes']['transactions']
        transaction = transactions[0]
    except (KeyError, IndexError, TypeError) as error:
        raise ValueError("Firefly returned no transaction details.") from error
    if not isinstance(transaction, dict):
        raise ValueError("Firefly returned invalid transaction details.")
    if len(transactions) != 1:
        raise ValueError("Customize transactions with multiple splits directly in Firefly III.")
    return transaction


def currency_decimal_places(transaction: dict, foreign: bool = False) -> int:
    field = 'foreign_currency_decimal_places' if foreign else 'currency_decimal_places'
    places = transaction.get(field)
    return 2 if places is None else int(places)


def transaction_update_payload(transaction: dict, fields: dict) -> dict:
    """Target the existing journal and retain the foreign currency when editing amounts."""
    update = dict(fields)
    if transaction.get('transaction_journal_id'):
        update['transaction_journal_id'] = str(transaction['transaction_journal_id'])
    if 'foreign_amount' in update:
        update['foreign_currency_id'] = transaction.get('foreign_currency_id')
        update['foreign_currency_code'] = transaction.get('foreign_currency_code')
    return {'transactions': [update]}

# Callback data prefixes
BUDGET_CALLBACK_PREFIX = "set_budget_"
CATEGORY_CALLBACK_PREFIX = "set_category_"
SOURCE_ACCOUNT_CALLBACK_PREFIX = "set_source_"
TAGS_CALLBACK_PREFIX = "manage_tags_"
BILL_CALLBACK_PREFIX = "set_bill_"
TRANSACTION_ID_PREFIX = "trans_id_"
BACK_BUTTON_PREFIX = "back_to_main_"
CANCEL_BUTTON_PREFIX = "cancel_customization_"
SPLIT_AMOUNT_CALLBACK_PREFIX = "split_amount_"
UPDATE_AMOUNT_CALLBACK_PREFIX = "update_amount_"
DEDUCT_AMOUNT_CALLBACK_PREFIX = "deduct_amount_"
REPLY_CONTEXTS: dict[str, dict[int, dict]] = {
    "tag": {},
    "update_amount": {},
    "deduct_amount": {},
}


def get_reply_context(kind: str, user_id: int) -> dict | None:
    return REPLY_CONTEXTS[kind].get(user_id)


def set_reply_context(kind: str, user_id: int, context: dict) -> None:
    REPLY_CONTEXTS[kind][user_id] = context


def discard_reply_context(kind: str, user_id: int) -> None:
    REPLY_CONTEXTS[kind].pop(user_id, None)


def discard_user_contexts(user_id: int) -> None:
    for contexts in REPLY_CONTEXTS.values():
        contexts.pop(user_id, None)


def get_main_menu_markup(transaction_id: str, link: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔗 View in Firefly", url=link)],
        [InlineKeyboardButton("💰 Set Budget", callback_data=f"{BUDGET_CALLBACK_PREFIX}{transaction_id}")],
        [InlineKeyboardButton("📁 Set Category", callback_data=f"{CATEGORY_CALLBACK_PREFIX}{transaction_id}")],
        [InlineKeyboardButton("🏦 Set Source Account", callback_data=f"{SOURCE_ACCOUNT_CALLBACK_PREFIX}{transaction_id}")],
        [InlineKeyboardButton("📄 Link to Bill", callback_data=f"{BILL_CALLBACK_PREFIX}{transaction_id}")],
        [InlineKeyboardButton("🏷️ Manage Tags", callback_data=f"{TAGS_CALLBACK_PREFIX}{transaction_id}")],
        [InlineKeyboardButton("✂️ Split in Half", callback_data=f"{SPLIT_AMOUNT_CALLBACK_PREFIX}{transaction_id}")],
        [InlineKeyboardButton("✏️ Update Amount", callback_data=f"{UPDATE_AMOUNT_CALLBACK_PREFIX}{transaction_id}")],
        [InlineKeyboardButton("➖ Deduct Amount", callback_data=f"{DEDUCT_AMOUNT_CALLBACK_PREFIX}{transaction_id}")],
        [InlineKeyboardButton("❌ Cancel", callback_data=f"{CANCEL_BUTTON_PREFIX}{transaction_id}")]
    ])


async def clear_amount_contexts(client, message: Message, user_id: int):
    for kind in ("update_amount", "deduct_amount"):
        ctx = get_reply_context(kind, user_id)
        if ctx and "reply_message_id" in ctx:
            try:
                await client.delete_messages(message.chat.id, ctx["reply_message_id"])
            except Exception:
                pass
        discard_reply_context(kind, user_id)


async def get_transaction_details_text(firefly_api, transaction_id: str) -> str:
    """
    Fetches and formats transaction details from Firefly API.

    Args:
        firefly_api: FireflyApi instance
        transaction_id: The transaction ID

    Returns:
        Formatted transaction details text
    """
    try:
        transaction_data = await asyncio.to_thread(firefly_api.get_json, f"transactions/{transaction_id}")
        inner_transaction = get_inner_transaction(transaction_data)

        # Get budget, category, bill, and tag names
        budget_name = inner_transaction.get('budget_name', 'None')
        category_name = inner_transaction.get('category_name', 'None')
        bill_name = inner_transaction.get('bill_name', 'None')
        tags = inner_transaction.get('tags', [])
        tags_text = ', '.join(tags) if tags else 'None'

        details = (
            f"**Transaction Details**\n"
            f"**Description:** {inner_transaction.get('description', 'N/A')}\n"
            f"**Amount:** {parse_positive_amount(inner_transaction.get('amount')):.2f} {inner_transaction.get('currency_code', 'N/A')}\n"
            f"**Date & Time:** {inner_transaction.get('date', 'N/A')}\n"
            f"**Destination:** {inner_transaction.get('destination_name', 'N/A')}\n"
            f"**Budget:** {budget_name}\n"
            f"**Category:** {category_name}\n"
            f"**Bill:** {bill_name}\n"
            f"**Tags:** {tags_text}\n"
        )
        return details
    except Exception as e:
        LOGS.error(f"Error fetching transaction details: {e}")
        return "Error fetching transaction details."


async def clear_tag_contexts(client, message: Message, user_id: int):
    """
    Clear any existing tag-related reply contexts and attempt to delete the ForceReply messages.
    """
    ctx = get_reply_context("tag", user_id)
    if ctx and "reply_message_id" in ctx:
        try:
            await client.delete_messages(message.chat.id, ctx["reply_message_id"])
        except Exception:
            pass
    discard_reply_context("tag", user_id)


@FireflyParserBot.on_callback_query(filters.regex(r"^trans_id_\d+$") & filters.user(TELEGRAM_ADMINS))
async def handle_transaction_customization_callback(client: FireflyParserBot, callback_query: CallbackQuery):
    await callback_query.answer()
    transaction_id = callback_query.data.removeprefix(TRANSACTION_ID_PREFIX)

    firefly_api = FireflyApi()

    # Get transaction details
    transaction_details = await get_transaction_details_text(firefly_api, transaction_id)

    # Add Firefly link button
    link = firefly_api.transaction_show_url(transaction_id)

    markup = get_main_menu_markup(transaction_id, link)

    text = f"{transaction_details}\n\n**What would you like to customize?**"

    await callback_query.message.edit_text(text, reply_markup=markup)


@FireflyParserBot.on_callback_query(filters.regex(r"^set_budget_\d+$") & filters.user(TELEGRAM_ADMINS))
async def handle_set_budget_callback(client: FireflyParserBot, callback_query: CallbackQuery):
    await callback_query.answer()
    transaction_id = callback_query.data.removeprefix(BUDGET_CALLBACK_PREFIX)
    firefly_api = FireflyApi()

    try:
        budgets = await asyncio.to_thread(firefly_api.get_budgets)
        if not budgets:
            await callback_query.edit_message_text("No budgets found in Firefly III.")
            return

        # Get transaction details to prepend
        transaction_details = await get_transaction_details_text(firefly_api, transaction_id)

        buttons = []
        for budget in budgets:
            buttons.append([InlineKeyboardButton(
                budget.name,
                callback_data=f"update_trans_budget_{transaction_id}_{budget.id}",
            )])
        buttons.append([InlineKeyboardButton("⬅️ Back", callback_data=f"{BACK_BUTTON_PREFIX}{transaction_id}")])

        markup = InlineKeyboardMarkup(buttons)
        text = f"{transaction_details}\n\n**Select a budget:**"
        await callback_query.message.edit_text(text, reply_markup=markup)

    except Exception as e:
        LOGS.error(f"Error fetching budgets: {e}")
        await callback_query.edit_message_text("Failed to fetch budgets. Please try again later.")


@FireflyParserBot.on_callback_query(filters.regex(r"^set_category_\d+$") & filters.user(TELEGRAM_ADMINS))
async def handle_set_category_callback(client: FireflyParserBot, callback_query: CallbackQuery):
    await callback_query.answer()
    transaction_id = callback_query.data.removeprefix(CATEGORY_CALLBACK_PREFIX)
    firefly_api = FireflyApi()

    try:
        categories = await asyncio.to_thread(firefly_api.get_categories)
        if not categories:
            await callback_query.edit_message_text("No categories found in Firefly III.")
            return

        # Get transaction details to prepend
        transaction_details = await get_transaction_details_text(firefly_api, transaction_id)

        buttons = []
        for category in categories:
            buttons.append([InlineKeyboardButton(
                category.name,
                callback_data=f"update_trans_category_{transaction_id}_{category.id}",
            )])
        buttons.append([InlineKeyboardButton("⬅️ Back", callback_data=f"{BACK_BUTTON_PREFIX}{transaction_id}")])

        markup = InlineKeyboardMarkup(buttons)
        text = f"{transaction_details}\n\n**Select a category:**"
        await callback_query.message.edit_text(text, reply_markup=markup)

    except Exception as e:
        LOGS.error(f"Error fetching categories: {e}")
        await callback_query.edit_message_text("Failed to fetch categories. Please try again later.")


source_account_filter = filters.regex(r"^set_source_\d+$") & filters.user(TELEGRAM_ADMINS)
bill_filter = filters.regex(r"^set_bill_\d+$") & filters.user(TELEGRAM_ADMINS)


@FireflyParserBot.on_callback_query(source_account_filter)
async def handle_set_source_account_callback(client: FireflyParserBot, callback_query: CallbackQuery):
    await callback_query.answer()
    transaction_id = callback_query.data.removeprefix(SOURCE_ACCOUNT_CALLBACK_PREFIX)
    firefly_api = FireflyApi()

    try:
        accounts = await asyncio.to_thread(firefly_api.get_asset_accounts)
        if not accounts:
            await callback_query.edit_message_text("No asset accounts found in Firefly III.")
            return

        # Get transaction details to prepend
        transaction_details = await get_transaction_details_text(firefly_api, transaction_id)

        buttons = []
        for account in accounts:
            buttons.append([InlineKeyboardButton(
                account.name,
                callback_data=f"update_trans_source_{transaction_id}_{account.id}",
            )])
        buttons.append([InlineKeyboardButton("⬅️ Back", callback_data=f"{BACK_BUTTON_PREFIX}{transaction_id}")])

        markup = InlineKeyboardMarkup(buttons)
        text = f"{transaction_details}\n\n**Select a source account:**"
        await callback_query.message.edit_text(text, reply_markup=markup)

    except Exception as e:
        LOGS.error(f"Error fetching asset accounts: {e}")
        await callback_query.edit_message_text("Failed to fetch accounts. Please try again later.")


@FireflyParserBot.on_callback_query(bill_filter)
async def handle_set_bill_callback(client: FireflyParserBot, callback_query: CallbackQuery):
    await callback_query.answer()
    transaction_id = callback_query.data.removeprefix(BILL_CALLBACK_PREFIX)
    firefly_api = FireflyApi()

    try:
        bills = await asyncio.to_thread(firefly_api.get_bills)

        # Get transaction details to check current bill
        transaction_data = await asyncio.to_thread(firefly_api.get_json, f"transactions/{transaction_id}")
        if not transaction_data or 'data' not in transaction_data:
            await callback_query.edit_message_text("Failed to fetch transaction details.")
            return

        inner_transaction = get_inner_transaction(transaction_data)
        current_bill_id = inner_transaction.get('bill_id')
        current_bill_name = inner_transaction.get('bill_name', 'None')

        # Get transaction details to prepend
        transaction_details = await get_transaction_details_text(firefly_api, transaction_id)

        buttons = []
        for bill in bills:
            buttons.append([InlineKeyboardButton(
                bill.name,
                callback_data=f"update_trans_bill_{transaction_id}_{bill.id}",
            )])

        # Add unlink button if there's a bill linked
        if current_bill_id:
            buttons.append([InlineKeyboardButton(
                f"🗑️ Unlink '{current_bill_name}'",
                callback_data=f"unlink_trans_bill_{transaction_id}",
            )])

        buttons.append([InlineKeyboardButton("⬅️ Back", callback_data=f"{BACK_BUTTON_PREFIX}{transaction_id}")])

        markup = InlineKeyboardMarkup(buttons)
        text = f"{transaction_details}\n\n**Select a bill:**"
        await callback_query.message.edit_text(text, reply_markup=markup)

    except Exception as e:
        LOGS.error(f"Error fetching bills: {e}")
        await callback_query.edit_message_text("Failed to fetch bills. Please try again later.")


def parse_update_callback(data: str, prefix: str) -> tuple[str, str]:
    if not data.startswith(prefix):
        raise ValueError("Unexpected callback prefix.")
    transaction_id, separator, value = data.removeprefix(prefix).partition('_')
    if not separator or not transaction_id.isdigit() or not value.isdigit():
        raise ValueError("Invalid callback identifiers.")
    return transaction_id, value


async def apply_transaction_field_update(
    callback_query: CallbackQuery,
    transaction_id: str,
    field: str,
    value,
    success_message: str,
    failure_action: str,
) -> None:
    firefly_api = FireflyApi()
    try:
        response = await asyncio.to_thread(firefly_api.get_json, f"transactions/{transaction_id}")
        inner_transaction = get_inner_transaction(response)
        payload = {"transactions": [{field: value}]}
        await asyncio.to_thread(
            firefly_api.update_transaction, transaction_id,
            transaction_update_payload(inner_transaction, payload["transactions"][0]),
        )
        transaction_details = await get_transaction_details_text(firefly_api, transaction_id)
        link = firefly_api.transaction_show_url(transaction_id)
        markup = get_main_menu_markup(transaction_id, link)
        text = (
            f"{transaction_details}\n\n✅ **{success_message}**"
            "\n\n**What would you like to customize?**"
        )
        await callback_query.message.edit_text(text, reply_markup=markup)
    except Exception as e:
        LOGS.error("Error updating %s for transaction %s: %s", field, transaction_id, e)
        await callback_query.edit_message_text(f"Failed to {failure_action}. Please try again.")


@FireflyParserBot.on_callback_query(filters.regex(r"^update_trans_budget_\d+_\d+$") & filters.user(TELEGRAM_ADMINS))
async def update_transaction_budget(_, callback_query: CallbackQuery):
    await callback_query.answer("Updating budget...")
    transaction_id, budget_id = parse_update_callback(callback_query.data, "update_trans_budget_")
    await apply_transaction_field_update(
        callback_query, transaction_id, "budget_id", budget_id,
        "Budget updated successfully!", "update budget",
    )


@FireflyParserBot.on_callback_query(filters.regex(r"^update_trans_category_\d+_\d+$") & filters.user(TELEGRAM_ADMINS))
async def update_transaction_category(_, callback_query: CallbackQuery):
    await callback_query.answer("Updating category...")
    transaction_id, category_id = parse_update_callback(callback_query.data, "update_trans_category_")
    await apply_transaction_field_update(
        callback_query, transaction_id, "category_id", category_id,
        "Category updated successfully!", "update category",
    )


@FireflyParserBot.on_callback_query(filters.regex(r"^update_trans_source_\d+_\d+$") & filters.user(TELEGRAM_ADMINS))
async def update_transaction_source_account(_, callback_query: CallbackQuery):
    await callback_query.answer("Updating source account...")
    transaction_id, account_id = parse_update_callback(callback_query.data, "update_trans_source_")
    await apply_transaction_field_update(
        callback_query, transaction_id, "source_id", account_id,
        "Source account updated successfully!", "update source account",
    )


@FireflyParserBot.on_callback_query(filters.regex(r"^update_trans_bill_\d+_\d+$") & filters.user(TELEGRAM_ADMINS))
async def update_transaction_bill(_, callback_query: CallbackQuery):
    await callback_query.answer("Updating bill...")
    transaction_id, bill_id = parse_update_callback(callback_query.data, "update_trans_bill_")
    await apply_transaction_field_update(
        callback_query, transaction_id, "bill_id", bill_id,
        "Bill updated successfully!", "update bill",
    )


@FireflyParserBot.on_callback_query(filters.regex(r"^unlink_trans_bill_\d+$") & filters.user(TELEGRAM_ADMINS))
async def unlink_transaction_bill(_, callback_query: CallbackQuery):
    await callback_query.answer("Unlinking bill...")
    transaction_id = callback_query.data.removeprefix("unlink_trans_bill_")
    await apply_transaction_field_update(
        callback_query, transaction_id, "bill_id", None,
        "Bill unlinked successfully!", "unlink bill",
    )


@FireflyParserBot.on_callback_query(filters.regex(r"^back_to_main_\d+$") & filters.user(TELEGRAM_ADMINS))
async def back_to_main_menu(client: FireflyParserBot, callback_query: CallbackQuery):
    await callback_query.answer()
    transaction_id = callback_query.data.removeprefix(BACK_BUTTON_PREFIX)

    firefly_api = FireflyApi()

    transaction_details = await get_transaction_details_text(firefly_api, transaction_id)
    link = firefly_api.transaction_show_url(transaction_id)

    markup = get_main_menu_markup(transaction_id, link)

    text = f"{transaction_details}\n\n**What would you like to customize?**"

    await callback_query.message.edit_text(text, reply_markup=markup)


@FireflyParserBot.on_callback_query(filters.regex(r"^cancel_customization_\d+$") & filters.user(TELEGRAM_ADMINS))
async def cancel_customization(client: FireflyParserBot, callback_query: CallbackQuery):
    await callback_query.answer()
    await clear_tag_contexts(client, callback_query.message, callback_query.from_user.id)
    await clear_amount_contexts(client, callback_query.message, callback_query.from_user.id)

    # Edit back to original transaction state with just View in Firefly and Customize buttons
    transaction_id = callback_query.data.removeprefix(CANCEL_BUTTON_PREFIX)
    firefly_api = FireflyApi()

    transaction_details = await get_transaction_details_text(firefly_api, transaction_id)
    link = firefly_api.transaction_show_url(transaction_id)

    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔗 View in Firefly", url=link)],
        [InlineKeyboardButton("⚙️ Customize Transaction", callback_data=f"{TRANSACTION_ID_PREFIX}{transaction_id}")]
    ])

    text = f"{transaction_details}\n\n**Transaction customization cancelled.**"
    await callback_query.message.edit_text(text, reply_markup=markup)


@FireflyParserBot.on_callback_query(filters.regex(r"^manage_tags_\d+$") & filters.user(TELEGRAM_ADMINS))
async def handle_manage_tags_callback(client: FireflyParserBot, callback_query: CallbackQuery):
    await callback_query.answer()
    transaction_id = callback_query.data.removeprefix(TAGS_CALLBACK_PREFIX)
    firefly_api = FireflyApi()

    try:
        # Get the transaction details to show current tags
        transaction_data = await asyncio.to_thread(firefly_api.get_json, f"transactions/{transaction_id}")
        if not transaction_data or 'data' not in transaction_data:
            await callback_query.edit_message_text("Failed to fetch transaction details.")
            return

        inner_transaction = get_inner_transaction(transaction_data)
        current_tags = list(inner_transaction.get('tags') or [])

        # Get transaction details to prepend
        transaction_details = await get_transaction_details_text(firefly_api, transaction_id)

        # Format current tags display with remove buttons
        if current_tags:
            tags_display = "\n".join([f"• {tag}" for tag in current_tags])
        else:
            tags_display = "No tags yet"

        # Quick tags for common Ramadan-related tags
        quick_tags = ["ramadan", "iftar", "suhur", "eid"]
        quick_buttons = []
        for tag in quick_tags:
            # Only show quick-add button if tag doesn't already exist
            if tag not in current_tags:
                quick_buttons.append([InlineKeyboardButton(
                    f"+ {tag.title()}",
                    callback_data=f"quick_add_tag_{transaction_id}_{tag}"
                )])

        # Create markup with quick add buttons, custom add option, and remove tag buttons
        all_buttons = quick_buttons.copy()
        all_buttons.append([InlineKeyboardButton("✏️ Add Custom Tag", callback_data=f"add_custom_tag_{transaction_id}")])

        # Add remove buttons for each existing tag
        for tag_index, tag in enumerate(current_tags):
            all_buttons.append([InlineKeyboardButton(
                f"🗑️ {tag}",
                callback_data=f"remove_tag_{transaction_id}_{tag_index}",
            )])

        all_buttons.append([InlineKeyboardButton("⬅️ Back", callback_data=f"{BACK_BUTTON_PREFIX}{transaction_id}")])

        markup = InlineKeyboardMarkup(all_buttons)

        text = (
            f"{transaction_details}\n\n"
            f"**Current Tags:**\n{tags_display}\n\n"
            f"**Quick Add Ramadan Tags:**"
        )
        await callback_query.message.edit_text(text, reply_markup=markup)

    except Exception as e:
        LOGS.error(f"Error fetching transaction tags: {e}")
        await callback_query.edit_message_text("Failed to fetch transaction details. Please try again.")


@FireflyParserBot.on_callback_query(filters.regex(r"^quick_add_tag_\d+_[a-z]+$") & filters.user(TELEGRAM_ADMINS))
async def quick_add_tag(client: FireflyParserBot, callback_query: CallbackQuery):
    await callback_query.answer("Adding tag...")
    parts = callback_query.data.split("_")
    transaction_id = str(parts[3])
    tag = "_".join(parts[4:])  # Handle multi-word tags

    firefly_api = FireflyApi()

    try:
        # Get current transaction to fetch existing tags
        transaction_data = await asyncio.to_thread(firefly_api.get_json, f"transactions/{transaction_id}")
        if not transaction_data or 'data' not in transaction_data:
            await callback_query.edit_message_text("Failed to fetch transaction details.")
            return

        inner_transaction = get_inner_transaction(transaction_data)
        current_tags = list(inner_transaction.get('tags') or [])

        # Add the new tag if it doesn't already exist
        if tag not in current_tags:
            current_tags.append(tag)

        # Update transaction with new tags
        payload = {
            "transactions": [
                {
                    "tags": current_tags
                }
            ]
        }
        await asyncio.to_thread(
            firefly_api.update_transaction, transaction_id,
            transaction_update_payload(inner_transaction, payload["transactions"][0]),
        )

        # Refresh the tags view by updating callback data
        callback_query.data = f"{TAGS_CALLBACK_PREFIX}{transaction_id}"
        await handle_manage_tags_callback(client, callback_query)

    except StopPropagation:
        raise
    except Exception as e:
        LOGS.error(f"Error adding tag to transaction {transaction_id}: {e}")
        await callback_query.edit_message_text("Failed to add tag. Please try again.")


@FireflyParserBot.on_callback_query(filters.regex(r"^remove_tag_\d+_\d+$") & filters.user(TELEGRAM_ADMINS))
async def remove_tag(client: FireflyParserBot, callback_query: CallbackQuery):
    await callback_query.answer("Removing tag...")
    parts = callback_query.data.split("_")
    transaction_id = str(parts[2])
    try:
        tag_index = int(parts[3])
    except (IndexError, ValueError):
        await callback_query.edit_message_text("Invalid tag selection.")
        return

    firefly_api = FireflyApi()

    try:
        # Get current transaction to fetch existing tags
        transaction_data = await asyncio.to_thread(firefly_api.get_json, f"transactions/{transaction_id}")
        if not transaction_data or 'data' not in transaction_data:
            await callback_query.edit_message_text("Failed to fetch transaction details.")
            return

        inner_transaction = get_inner_transaction(transaction_data)
        current_tags = list(inner_transaction.get('tags') or [])

        if not 0 <= tag_index < len(current_tags):
            await callback_query.edit_message_text("That tag no longer exists.")
            return
        current_tags.pop(tag_index)

        # Update transaction with new tags
        payload = {
            "transactions": [
                {
                    "tags": current_tags
                }
            ]
        }
        await asyncio.to_thread(
            firefly_api.update_transaction, transaction_id,
            transaction_update_payload(inner_transaction, payload["transactions"][0]),
        )

        # Refresh tags view by updating callback data
        callback_query.data = f"{TAGS_CALLBACK_PREFIX}{transaction_id}"
        await handle_manage_tags_callback(client, callback_query)

    except Exception as e:
        LOGS.error(f"Error removing tag from transaction {transaction_id}: {e}")
        await callback_query.edit_message_text("Failed to remove tag. Please try again.")


@FireflyParserBot.on_callback_query(filters.regex(r"^add_custom_tag_\d+$") & filters.user(TELEGRAM_ADMINS))
async def add_custom_tag_callback(client: FireflyParserBot, callback_query: CallbackQuery):
    await callback_query.answer()
    transaction_id = callback_query.data.removeprefix("add_custom_tag_")

    # Clear any existing stale tag context and its ForceReply message
    await clear_tag_contexts(client, callback_query.message, callback_query.from_user.id)

    text = "Reply with the tag you want to add:"
    reply_msg = await callback_query.message.reply(
        text,
        reply_markup=ForceReply(selective=True)
    )
    set_reply_context("tag", callback_query.from_user.id, {
        "user_id": callback_query.from_user.id,
        "transaction_id": transaction_id,
        "message_id": callback_query.message.id,
        "reply_message_id": reply_msg.id
    })


@FireflyParserBot.on_message(filters.private & filters.user(TELEGRAM_ADMINS), group=10)
async def handle_add_tag_reply(client, message: Message):
    # Check if this is a reply to our ForceReply for adding tags
    ctx = get_reply_context("tag", message.from_user.id)
    if not ctx:
        await message.continue_propagation()
        return

    # Check if this message is a reply to our ForceReply message
    if not message.reply_to_message_id:
        await message.continue_propagation()
        return

    if ctx.get("reply_message_id") != message.reply_to_message_id:
        await message.continue_propagation()
        return

    # Check if the user is the one who initiated the action
    if ctx.get("user_id") != message.from_user.id:
        await message.continue_propagation()
        return

    if not message.text:
        await message.reply("Please reply with text to this prompt.")
        await message.stop_propagation()
        return

    # Process the tag addition
    tag = message.text.strip()
    chat_id = message.chat.id
    reply_msg_id = ctx["reply_message_id"]
    original_msg_id = ctx["message_id"]
    transaction_id = ctx["transaction_id"]

    if not tag or len(tag) > 100 or '\n' in tag or '\r' in tag:
        # Delete the user's empty reply, keep the prompt for retry
        try:
            await message.delete()
        except Exception:
            pass
        await message.stop_propagation()
        return

    firefly_api = FireflyApi()

    try:
        # Get current transaction to fetch existing tags
        transaction_data = await asyncio.to_thread(firefly_api.get_json, f"transactions/{transaction_id}")
        if not transaction_data or 'data' not in transaction_data:
            try:
                await client.delete_messages(chat_id, reply_msg_id)
            except Exception:
                pass
            try:
                await message.delete()
            except Exception:
                pass
            try:
                original_message = await client.get_messages(chat_id, original_msg_id)
                await original_message.edit_text("❌ Failed to fetch transaction details.")
            except Exception:
                pass
            discard_reply_context("tag", message.from_user.id)
            await message.stop_propagation()
            return

        inner_transaction = get_inner_transaction(transaction_data)
        current_tags = list(inner_transaction.get('tags') or [])

        # Add the new tag if it doesn't already exist
        if tag not in current_tags:
            current_tags.append(tag)

        # Update transaction with new tags
        payload = {
            "transactions": [
                {
                    "tags": current_tags
                }
            ]
        }
        await asyncio.to_thread(
            firefly_api.update_transaction, transaction_id,
            transaction_update_payload(inner_transaction, payload["transactions"][0]),
        )

        # Delete the ForceReply prompt and user's reply to clean up the chat
        try:
            await client.delete_messages(chat_id, reply_msg_id)
        except Exception:
            pass
        try:
            await message.delete()
        except Exception:
            pass

        # Refresh the tags view in the original message
        original_message = await client.get_messages(chat_id, original_msg_id)

        # Create a mock callback query object
        class MockCallbackQuery:
            def __init__(self, message):
                self.message = message
                self.data = f"{TAGS_CALLBACK_PREFIX}{transaction_id}"
                self.from_user = message.from_user

            async def answer(self, text=None):
                pass

        mock_callback = MockCallbackQuery(original_message)
        await handle_manage_tags_callback(FireflyParserBot, mock_callback)

    except StopPropagation:
        raise
    except Exception as e:
        LOGS.error(f"Error adding tag to transaction {transaction_id}: {e}")
        try:
            await client.delete_messages(chat_id, reply_msg_id)
        except Exception:
            pass
        try:
            await message.delete()
        except Exception:
            pass
        try:
            original_message = await client.get_messages(chat_id, original_msg_id)
            await original_message.edit_text("❌ Failed to add tag. Please try again.")
        except Exception:
            pass

    discard_reply_context("tag", message.from_user.id)
    await message.stop_propagation()


@FireflyParserBot.on_callback_query(filters.regex(r"^split_amount_\d+$") & filters.user(TELEGRAM_ADMINS))
async def handle_split_amount_callback(client: FireflyParserBot, callback_query: CallbackQuery):
    await callback_query.answer("Splitting amount in half...")
    transaction_id = callback_query.data.removeprefix(SPLIT_AMOUNT_CALLBACK_PREFIX)
    firefly_api = FireflyApi()

    try:
        transaction_data = await asyncio.to_thread(firefly_api.get_json, f"transactions/{transaction_id}")
        if not transaction_data or 'data' not in transaction_data:
            await callback_query.edit_message_text("Failed to fetch transaction details.")
            return

        inner_transaction = get_inner_transaction(transaction_data)
        current_amount = parse_positive_amount(inner_transaction.get('amount'))
        new_amount = money(current_amount / 2, currency_decimal_places(inner_transaction))

        update_payload = {"transactions": [{"amount": str(new_amount)}]}

        foreign_amount = inner_transaction.get('foreign_amount')
        if foreign_amount:
            new_foreign = money(
                parse_positive_amount(foreign_amount) / 2,
                currency_decimal_places(inner_transaction, foreign=True),
            )
            update_payload["transactions"][0]["foreign_amount"] = str(new_foreign)

        await asyncio.to_thread(
            firefly_api.update_transaction, transaction_id,
            transaction_update_payload(inner_transaction, update_payload["transactions"][0]),
        )

        transaction_details = await get_transaction_details_text(firefly_api, transaction_id)
        link = firefly_api.transaction_show_url(transaction_id)
        markup = get_main_menu_markup(transaction_id, link)

        text = f"{transaction_details}\n\n✅ **Amount split in half: {current_amount:.2f} → {new_amount:.2f}**\n\n**What would you like to customize?**"
        await callback_query.message.edit_text(text, reply_markup=markup)

    except Exception as e:
        LOGS.error(f"Error splitting amount for transaction {transaction_id}: {e}")
        await callback_query.edit_message_text("Failed to split amount. Please try again.")


@FireflyParserBot.on_callback_query(filters.regex(r"^update_amount_\d+$") & filters.user(TELEGRAM_ADMINS))
async def handle_update_amount_callback(client: FireflyParserBot, callback_query: CallbackQuery):
    await callback_query.answer()
    transaction_id = callback_query.data.removeprefix(UPDATE_AMOUNT_CALLBACK_PREFIX)

    firefly_api = FireflyApi()
    try:
        transaction_data = await asyncio.to_thread(firefly_api.get_json, f"transactions/{transaction_id}")
        if not transaction_data or 'data' not in transaction_data:
            await callback_query.edit_message_text("Failed to fetch transaction details.")
            return

        inner_transaction = get_inner_transaction(transaction_data)
        current_amount = parse_positive_amount(inner_transaction.get('amount'))
        currency = inner_transaction.get('currency_code', '')
    except Exception:
        await callback_query.edit_message_text("Failed to fetch transaction details.")
        return

    # Clear any existing stale amount context and its ForceReply message
    await clear_amount_contexts(client, callback_query.message, callback_query.from_user.id)

    text = f"Current amount: **{current_amount:.2f} {currency}**\n\nReply with the new amount:"
    reply_msg = await callback_query.message.reply(
        text,
        reply_markup=ForceReply(selective=True)
    )
    set_reply_context("update_amount", callback_query.from_user.id, {
        "user_id": callback_query.from_user.id,
        "transaction_id": transaction_id,
        "message_id": callback_query.message.id,
        "reply_message_id": reply_msg.id,
        "currency": currency,
        "current_amount": current_amount
    })


@FireflyParserBot.on_callback_query(filters.regex(r"^deduct_amount_\d+$") & filters.user(TELEGRAM_ADMINS))
async def handle_deduct_amount_callback(client: FireflyParserBot, callback_query: CallbackQuery):
    await callback_query.answer()
    transaction_id = callback_query.data.removeprefix(DEDUCT_AMOUNT_CALLBACK_PREFIX)

    firefly_api = FireflyApi()
    try:
        transaction_data = await asyncio.to_thread(firefly_api.get_json, f"transactions/{transaction_id}")
        if not transaction_data or 'data' not in transaction_data:
            await callback_query.edit_message_text("Failed to fetch transaction details.")
            return

        inner_transaction = get_inner_transaction(transaction_data)
        current_amount = parse_positive_amount(inner_transaction.get('amount'))
        currency = inner_transaction.get('currency_code', '')
    except Exception:
        await callback_query.edit_message_text("Failed to fetch transaction details.")
        return

    await clear_amount_contexts(client, callback_query.message, callback_query.from_user.id)

    text = f"Current amount: **{current_amount:.2f} {currency}**\n\nReply with the amount to deduct:"
    reply_msg = await callback_query.message.reply(
        text,
        reply_markup=ForceReply(selective=True)
    )
    set_reply_context("deduct_amount", callback_query.from_user.id, {
        "user_id": callback_query.from_user.id,
        "transaction_id": transaction_id,
        "message_id": callback_query.message.id,
        "reply_message_id": reply_msg.id,
        "currency": currency,
        "current_amount": current_amount
    })


@FireflyParserBot.on_message(filters.private & filters.user(TELEGRAM_ADMINS), group=10)
async def handle_update_amount_reply(client, message: Message):
    ctx = get_reply_context("update_amount", message.from_user.id)
    if not ctx:
        await message.continue_propagation()
        return

    if not message.reply_to_message_id:
        await message.continue_propagation()
        return

    if ctx.get("reply_message_id") != message.reply_to_message_id:
        await message.continue_propagation()
        return

    if ctx.get("user_id") != message.from_user.id:
        await message.continue_propagation()
        return

    if not message.text:
        await message.reply("Please reply with text to this prompt.")
        await message.stop_propagation()
        return

    raw_amount = message.text.strip()
    chat_id = message.chat.id
    reply_msg_id = ctx["reply_message_id"]
    original_msg_id = ctx["message_id"]
    transaction_id = ctx["transaction_id"]

    # Validate amount first
    try:
        new_amount = parse_positive_amount(raw_amount)
    except ValueError:
        # Delete the user's invalid reply, keep the prompt for retry
        try:
            await message.delete()
        except Exception:
            pass
        await message.stop_propagation()
        return

    firefly_api = FireflyApi()

    try:
        transaction_data = await asyncio.to_thread(firefly_api.get_json, f"transactions/{transaction_id}")
        if not transaction_data or 'data' not in transaction_data:
            # Clean up on fetch failure
            try:
                await client.delete_messages(chat_id, reply_msg_id)
            except Exception:
                pass
            try:
                await message.delete()
            except Exception:
                pass
            try:
                original_message = await client.get_messages(chat_id, original_msg_id)
                await original_message.edit_text("❌ Failed to fetch transaction details.")
            except Exception:
                pass
            discard_reply_context("update_amount", message.from_user.id)
            await message.stop_propagation()
            return

        inner_transaction = get_inner_transaction(transaction_data)
        old_amount = parse_positive_amount(inner_transaction.get('amount'))

        new_amount = money(new_amount, currency_decimal_places(inner_transaction))
        update_payload = {"transactions": [{"amount": str(new_amount)}]}

        foreign_amount = inner_transaction.get('foreign_amount')
        if foreign_amount:
            ratio = new_amount / old_amount
            new_foreign = money(
                parse_positive_amount(foreign_amount) * ratio,
                currency_decimal_places(inner_transaction, foreign=True),
            )
            update_payload["transactions"][0]["foreign_amount"] = str(new_foreign)

        await asyncio.to_thread(
            firefly_api.update_transaction, transaction_id,
            transaction_update_payload(inner_transaction, update_payload["transactions"][0]),
        )

        # Delete the ForceReply prompt and user's reply to clean up the chat
        try:
            await client.delete_messages(chat_id, reply_msg_id)
        except Exception:
            pass
        try:
            await message.delete()
        except Exception:
            pass

        # Edit the original transaction details message
        transaction_details = await get_transaction_details_text(firefly_api, transaction_id)
        link = firefly_api.transaction_show_url(transaction_id)
        markup = get_main_menu_markup(transaction_id, link)
        text = f"{transaction_details}\n\n✅ **Amount updated: {old_amount:.2f} → {new_amount:.2f}**\n\n**What would you like to customize?**"

        try:
            original_message = await client.get_messages(chat_id, original_msg_id)
            await original_message.edit_text(text, reply_markup=markup)
        except Exception:
            pass

    except StopPropagation:
        raise
    except Exception as e:
        LOGS.error(f"Error updating amount for transaction {transaction_id}: {e}")
        try:
            await client.delete_messages(chat_id, reply_msg_id)
        except Exception:
            pass
        try:
            await message.delete()
        except Exception:
            pass
        try:
            original_message = await client.get_messages(chat_id, original_msg_id)
            await original_message.edit_text("❌ Failed to update amount. Please try again.")
        except Exception:
            pass

    discard_reply_context("update_amount", message.from_user.id)
    await message.stop_propagation()


@FireflyParserBot.on_message(filters.private & filters.user(TELEGRAM_ADMINS), group=10)
async def handle_deduct_amount_reply(client, message: Message):
    ctx = get_reply_context("deduct_amount", message.from_user.id)
    if not ctx:
        await message.continue_propagation()
        return

    if not message.reply_to_message_id:
        await message.continue_propagation()
        return

    if ctx.get("reply_message_id") != message.reply_to_message_id:
        await message.continue_propagation()
        return

    if ctx.get("user_id") != message.from_user.id:
        await message.continue_propagation()
        return

    if not message.text:
        await message.reply("Please reply with text to this prompt.")
        await message.stop_propagation()
        return

    raw_amount = message.text.strip()
    chat_id = message.chat.id
    reply_msg_id = ctx["reply_message_id"]
    original_msg_id = ctx["message_id"]
    transaction_id = ctx["transaction_id"]
    try:
        deduct_amount = parse_positive_amount(raw_amount)
    except ValueError:
        try:
            await message.delete()
        except Exception:
            pass
        await message.stop_propagation()
        return

    firefly_api = FireflyApi()

    try:
        transaction_data = await asyncio.to_thread(firefly_api.get_json, f"transactions/{transaction_id}")
        if not transaction_data or 'data' not in transaction_data:
            try:
                await client.delete_messages(chat_id, reply_msg_id)
            except Exception:
                pass
            try:
                await message.delete()
            except Exception:
                pass
            try:
                original_message = await client.get_messages(chat_id, original_msg_id)
                await original_message.edit_text("❌ Failed to fetch transaction details.")
            except Exception:
                pass
            discard_reply_context("deduct_amount", message.from_user.id)
            await message.stop_propagation()
            return

        inner_transaction = get_inner_transaction(transaction_data)
        old_amount = parse_positive_amount(inner_transaction.get('amount'))

        if deduct_amount >= old_amount:
            try:
                await message.delete()
            except Exception:
                pass
            await message.stop_propagation()
            return

        new_amount = money(old_amount - deduct_amount, currency_decimal_places(inner_transaction))

        update_payload = {"transactions": [{"amount": str(new_amount)}]}

        foreign_amount = inner_transaction.get('foreign_amount')
        if foreign_amount:
            ratio = new_amount / old_amount
            new_foreign = money(
                parse_positive_amount(foreign_amount) * ratio,
                currency_decimal_places(inner_transaction, foreign=True),
            )
            update_payload["transactions"][0]["foreign_amount"] = str(new_foreign)

        await asyncio.to_thread(
            firefly_api.update_transaction, transaction_id,
            transaction_update_payload(inner_transaction, update_payload["transactions"][0]),
        )

        try:
            await client.delete_messages(chat_id, reply_msg_id)
        except Exception:
            pass
        try:
            await message.delete()
        except Exception:
            pass

        transaction_details = await get_transaction_details_text(firefly_api, transaction_id)
        link = firefly_api.transaction_show_url(transaction_id)
        markup = get_main_menu_markup(transaction_id, link)
        text = f"{transaction_details}\n\n✅ **Amount deducted: {old_amount:.2f} - {deduct_amount:.2f} = {new_amount:.2f}**\n\n**What would you like to customize?**"

        try:
            original_message = await client.get_messages(chat_id, original_msg_id)
            await original_message.edit_text(text, reply_markup=markup)
        except Exception:
            pass

    except StopPropagation:
        raise
    except Exception as e:
        LOGS.error(f"Error deducting amount from transaction {transaction_id}: {e}")
        try:
            await client.delete_messages(chat_id, reply_msg_id)
        except Exception:
            pass
        try:
            await message.delete()
        except Exception:
            pass
        try:
            original_message = await client.get_messages(chat_id, original_msg_id)
            await original_message.edit_text("❌ Failed to deduct amount. Please try again.")
        except Exception:
            pass

    discard_reply_context("deduct_amount", message.from_user.id)
    await message.stop_propagation()
