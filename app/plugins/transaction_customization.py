from pyrogram import filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from app import FireflyParserBot, TELEGRAM_ADMINS
from app.firefly.firefly import FireflyApi
import logging

from app.models.transaction_models import Budget, Category

LOGS = logging.getLogger(__name__)

# Callback data prefixes
BUDGET_CALLBACK_PREFIX = "set_budget_"
CATEGORY_CALLBACK_PREFIX = "set_category_"
TRANSACTION_ID_PREFIX = "trans_id_"
BACK_BUTTON_PREFIX = "back_to_main_"
CANCEL_BUTTON_PREFIX = "cancel_customization_"


@FireflyParserBot.on_callback_query(filters.regex(f"^{TRANSACTION_ID_PREFIX}.*") & filters.user(TELEGRAM_ADMINS))
async def handle_transaction_customization_callback(client: FireflyParserBot, callback_query: CallbackQuery):
    await callback_query.answer()
    data = callback_query.data
    parts = data.split("_")
    transaction_id = parts[2]  # Expects "trans_id_XXX"

    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("Set Budget", callback_data=f"{BUDGET_CALLBACK_PREFIX}{transaction_id}")],
        [InlineKeyboardButton("Set Category", callback_data=f"{CATEGORY_CALLBACK_PREFIX}{transaction_id}")],
        [InlineKeyboardButton("Cancel", callback_data=f"{CANCEL_BUTTON_PREFIX}{transaction_id}")]
    ])
    await client.send_message(
        chat_id=callback_query.message.chat.id,
        text="What would you like to customize for this transaction?",
        reply_markup=markup
    )


@FireflyParserBot.on_callback_query(filters.regex(f"^{BUDGET_CALLBACK_PREFIX}.*") & filters.user(TELEGRAM_ADMINS))
async def handle_set_budget_callback(client: FireflyParserBot, callback_query: CallbackQuery):
    await callback_query.answer()
    transaction_id = callback_query.data.replace(BUDGET_CALLBACK_PREFIX, "")
    firefly_api = FireflyApi()

    try:
        budgets = firefly_api.get_budgets()
        if not budgets:
            await callback_query.edit_message_text("No budgets found in Firefly III.")
            return

        buttons = []
        for budget in budgets:
            buttons.append([InlineKeyboardButton(
                budget.name,
                callback_data=f"update_trans_budget_{transaction_id}_{budget.id}"
            )])
        buttons.append([InlineKeyboardButton("<< Back", callback_data=f"{BACK_BUTTON_PREFIX}{transaction_id}")])

        markup = InlineKeyboardMarkup(buttons)
        await callback_query.edit_message_text("Select a budget:", reply_markup=markup)

    except Exception as e:
        LOGS.error(f"Error fetching budgets: {e}")
        await callback_query.edit_message_text("Failed to fetch budgets. Please try again later.")


@FireflyParserBot.on_callback_query(filters.regex(f"^{CATEGORY_CALLBACK_PREFIX}.*") & filters.user(TELEGRAM_ADMINS))
async def handle_set_category_callback(client: FireflyParserBot, callback_query: CallbackQuery):
    await callback_query.answer()
    transaction_id = callback_query.data.replace(CATEGORY_CALLBACK_PREFIX, "")
    firefly_api = FireflyApi()

    try:
        categories = firefly_api.get_categories()
        if not categories:
            await callback_query.edit_message_text("No categories found in Firefly III.")
            return

        buttons = []
        for category in categories:
            buttons.append([InlineKeyboardButton(
                category.name,
                callback_data=f"update_trans_category_{transaction_id}_{category.id}"
            )])
        buttons.append([InlineKeyboardButton("<< Back", callback_data=f"{BACK_BUTTON_PREFIX}{transaction_id}")])

        markup = InlineKeyboardMarkup(buttons)
        await callback_query.edit_message_text("Select a category:", reply_markup=markup)

    except Exception as e:
        LOGS.error(f"Error fetching categories: {e}")
        await callback_query.edit_message_text("Failed to fetch categories. Please try again later.")


@FireflyParserBot.on_callback_query(filters.regex("^update_trans_budget_.*") & filters.user(TELEGRAM_ADMINS))
async def update_transaction_budget(client: FireflyParserBot, callback_query: CallbackQuery):
    await callback_query.answer("Updating budget...")
    parts = callback_query.data.split("_")
    transaction_id = parts[3]
    budget_id = parts[4]

    firefly_api = FireflyApi()
    payload = {
        "transactions": [
            {
                "budget_id": budget_id
            }
        ]
    }
    try:
        firefly_api.update_transaction(transaction_id, payload)
        await callback_query.message.delete()
        await client.send_message(chat_id=callback_query.message.chat.id, text="Budget updated successfully!")
    except Exception as e:
        LOGS.error(f"Error updating budget for transaction {transaction_id}: {e}")
        await callback_query.edit_message_text("Failed to update budget. Please try again.")


@FireflyParserBot.on_callback_query(filters.regex("^update_trans_category_.*") & filters.user(TELEGRAM_ADMINS))
async def update_transaction_category(client: FireflyParserBot, callback_query: CallbackQuery):
    await callback_query.answer("Updating category...")
    parts = callback_query.data.split("_")
    transaction_id = parts[3]
    category_id = parts[4]

    firefly_api = FireflyApi()
    payload = {
        "transactions": [
            {
                "category_id": category_id
            }
        ]
    }
    try:
        firefly_api.update_transaction(transaction_id, payload)
        await callback_query.message.delete()
        await client.send_message(chat_id=callback_query.message.chat.id, text="Category updated successfully!")
    except Exception as e:
        LOGS.error(f"Error updating category for transaction {transaction_id}: {e}")
        await callback_query.edit_message_text("Failed to update category. Please try again.")


@FireflyParserBot.on_callback_query(filters.regex(f"^{BACK_BUTTON_PREFIX}.*") & filters.user(TELEGRAM_ADMINS))
async def back_to_main_menu(client: FireflyParserBot, callback_query: CallbackQuery):
    await callback_query.answer()
    transaction_id = callback_query.data.replace(BACK_BUTTON_PREFIX, "")
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("Set Budget", callback_data=f"{BUDGET_CALLBACK_PREFIX}{transaction_id}")],
        [InlineKeyboardButton("Set Category", callback_data=f"{CATEGORY_CALLBACK_PREFIX}{transaction_id}")],
        [InlineKeyboardButton("Cancel", callback_data=f"{CANCEL_BUTTON_PREFIX}{transaction_id}")]
    ])
    await callback_query.message.edit_text(
        "What would you like to customize for this transaction?",
        reply_markup=markup
    )


@FireflyParserBot.on_callback_query(filters.regex(f"^{CANCEL_BUTTON_PREFIX}.*") & filters.user(TELEGRAM_ADMINS))
async def cancel_customization(client: FireflyParserBot, callback_query: CallbackQuery):
    await callback_query.answer()
    await callback_query.message.delete()