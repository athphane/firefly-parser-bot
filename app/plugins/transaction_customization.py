from pyrogram import filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, Message, ForceReply
from pyrogram.enums import ButtonStyle
from app import FireflyParserBot, TELEGRAM_ADMINS
from app.firefly.firefly import FireflyApi
import logging

from app.models.transaction_models import Account, Budget, Category

LOGS = logging.getLogger(__name__)

# Callback data prefixes
BUDGET_CALLBACK_PREFIX = "set_budget_"
CATEGORY_CALLBACK_PREFIX = "set_category_"
SOURCE_ACCOUNT_CALLBACK_PREFIX = "set_source_"
TAGS_CALLBACK_PREFIX = "manage_tags_"
TRANSACTION_ID_PREFIX = "trans_id_"
BACK_BUTTON_PREFIX = "back_to_main_"
CANCEL_BUTTON_PREFIX = "cancel_customization_"


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
        transaction_data = firefly_api.get_json(f"transactions/{transaction_id}")
        if not transaction_data or 'data' not in transaction_data:
            return "Transaction not found."
            
        transaction = transaction_data['data']
        attributes = transaction['attributes']
        transactions_list = attributes['transactions']
        if not transactions_list:
            return "Transaction details not found."
            
        inner_transaction = transactions_list[0]
        
        # Get budget, category, and tag names
        budget_name = inner_transaction.get('budget_name', 'None')
        category_name = inner_transaction.get('category_name', 'None')
        tags = inner_transaction.get('tags', [])
        tags_text = ', '.join(tags) if tags else 'None'
        
        details = (
            f"**Transaction Details**\n"
            f"**Description:** {inner_transaction.get('description', 'N/A')}\n"
            f"**Amount:** {float(inner_transaction.get('amount', 0)):.2f} {inner_transaction.get('currency_code', 'N/A')}\n"
            f"**Date & Time:** {inner_transaction.get('date', 'N/A')}\n"
            f"**Destination:** {inner_transaction.get('destination_name', 'N/A')}\n"
            f"**Budget:** {budget_name}\n"
            f"**Category:** {category_name}\n"
            f"**Tags:** {tags_text}\n"
        )
        return details
    except Exception as e:
        LOGS.error(f"Error fetching transaction details: {e}")
        return "Error fetching transaction details."


async def clear_tag_contexts(message: Message):
    """
    Clear any existing tag-related reply contexts and attempt to delete the ForceReply messages.
    """
    if hasattr(FireflyParserBot, '_add_tag_context'):
        ctx = getattr(FireflyParserBot, '_add_tag_context')
        if ctx and "reply_message_id" in ctx:
            try:
                await message.chat.delete_messages(ctx["reply_message_id"])
            except Exception:
                pass
        FireflyParserBot._add_tag_context = None


@FireflyParserBot.on_callback_query(filters.regex(f"^{TRANSACTION_ID_PREFIX}.*") & filters.user(TELEGRAM_ADMINS))
async def handle_transaction_customization_callback(client: FireflyParserBot, callback_query: CallbackQuery):
    await callback_query.answer()
    data = callback_query.data
    parts = data.split("_")
    transaction_id = str(parts[2])  # Expects "trans_id_XXX"

    firefly_api = FireflyApi()
    
    # Get transaction details
    transaction_details = await get_transaction_details_text(firefly_api, transaction_id)
    
    # Add Firefly link button
    link = firefly_api.transaction_show_url(transaction_id)
    
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("View in Firefly", url=link, style=ButtonStyle.PRIMARY)],
        [InlineKeyboardButton("Set Budget", callback_data=f"{BUDGET_CALLBACK_PREFIX}{transaction_id}", style=ButtonStyle.PRIMARY)],
        [InlineKeyboardButton("Set Category", callback_data=f"{CATEGORY_CALLBACK_PREFIX}{transaction_id}", style=ButtonStyle.PRIMARY)],
        [InlineKeyboardButton("Set Source Account", callback_data=f"{SOURCE_ACCOUNT_CALLBACK_PREFIX}{transaction_id}", style=ButtonStyle.PRIMARY)],
        [InlineKeyboardButton("Manage Tags", callback_data=f"{TAGS_CALLBACK_PREFIX}{transaction_id}", style=ButtonStyle.PRIMARY)],
        [InlineKeyboardButton("❌ Cancel", callback_data=f"{CANCEL_BUTTON_PREFIX}{transaction_id}", style=ButtonStyle.DANGER)]
    ])
    
    text = f"{transaction_details}\n\n**What would you like to customize?**"
    
    await callback_query.message.edit_text(text, reply_markup=markup)


@FireflyParserBot.on_callback_query(filters.regex(f"^{BUDGET_CALLBACK_PREFIX}.*") & filters.user(TELEGRAM_ADMINS))
async def handle_set_budget_callback(client: FireflyParserBot, callback_query: CallbackQuery):
    await callback_query.answer()
    transaction_id = str(callback_query.data.replace(BUDGET_CALLBACK_PREFIX, ""))
    firefly_api = FireflyApi()

    try:
        budgets = firefly_api.get_budgets()
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
                style=ButtonStyle.SUCCESS
            )])
        buttons.append([InlineKeyboardButton("<< Back", callback_data=f"{BACK_BUTTON_PREFIX}{transaction_id}", style=ButtonStyle.DEFAULT)])

        markup = InlineKeyboardMarkup(buttons)
        text = f"{transaction_details}\n\n**Select a budget:**"
        await callback_query.message.edit_text(text, reply_markup=markup)

    except Exception as e:
        LOGS.error(f"Error fetching budgets: {e}")
        await callback_query.edit_message_text("Failed to fetch budgets. Please try again later.")


@FireflyParserBot.on_callback_query(filters.regex(f"^{CATEGORY_CALLBACK_PREFIX}.*") & filters.user(TELEGRAM_ADMINS))
async def handle_set_category_callback(client: FireflyParserBot, callback_query: CallbackQuery):
    await callback_query.answer()
    transaction_id = str(callback_query.data.replace(CATEGORY_CALLBACK_PREFIX, ""))
    firefly_api = FireflyApi()

    try:
        categories = firefly_api.get_categories()
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
                style=ButtonStyle.SUCCESS
            )])
        buttons.append([InlineKeyboardButton("<< Back", callback_data=f"{BACK_BUTTON_PREFIX}{transaction_id}", style=ButtonStyle.DEFAULT)])

        markup = InlineKeyboardMarkup(buttons)
        text = f"{transaction_details}\n\n**Select a category:**"
        await callback_query.message.edit_text(text, reply_markup=markup)

    except Exception as e:
        LOGS.error(f"Error fetching categories: {e}")
        await callback_query.edit_message_text("Failed to fetch categories. Please try again later.")


source_account_filter = filters.regex(f"^{SOURCE_ACCOUNT_CALLBACK_PREFIX}.*") & filters.user(TELEGRAM_ADMINS)


@FireflyParserBot.on_callback_query(source_account_filter)
async def handle_set_source_account_callback(client: FireflyParserBot, callback_query: CallbackQuery):
    await callback_query.answer()
    transaction_id = str(callback_query.data.replace(SOURCE_ACCOUNT_CALLBACK_PREFIX, ""))
    firefly_api = FireflyApi()

    try:
        accounts = firefly_api.get_asset_accounts()
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
                style=ButtonStyle.SUCCESS
            )])
        buttons.append([InlineKeyboardButton("<< Back", callback_data=f"{BACK_BUTTON_PREFIX}{transaction_id}", style=ButtonStyle.DEFAULT)])

        markup = InlineKeyboardMarkup(buttons)
        text = f"{transaction_details}\n\n**Select a source account:**"
        await callback_query.message.edit_text(text, reply_markup=markup)

    except Exception as e:
        LOGS.error(f"Error fetching asset accounts: {e}")
        await callback_query.edit_message_text("Failed to fetch accounts. Please try again later.")


@FireflyParserBot.on_callback_query(filters.regex("^update_trans_budget_.*") & filters.user(TELEGRAM_ADMINS))
async def update_transaction_budget(client: FireflyParserBot, callback_query: CallbackQuery):
    await callback_query.answer("Updating budget...")
    parts = callback_query.data.split("_")
    transaction_id = str(parts[3])
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
        
        # Edit the message back to show updated transaction details
        transaction_details = await get_transaction_details_text(firefly_api, transaction_id)
        link = firefly_api.transaction_show_url(transaction_id)
        
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("View in Firefly", url=link, style=ButtonStyle.PRIMARY)],
            [InlineKeyboardButton("Set Budget", callback_data=f"{BUDGET_CALLBACK_PREFIX}{transaction_id}", style=ButtonStyle.PRIMARY)],
            [InlineKeyboardButton("Set Category", callback_data=f"{CATEGORY_CALLBACK_PREFIX}{transaction_id}", style=ButtonStyle.PRIMARY)],
            [InlineKeyboardButton("Set Source Account", callback_data=f"{SOURCE_ACCOUNT_CALLBACK_PREFIX}{transaction_id}", style=ButtonStyle.PRIMARY)],
            [InlineKeyboardButton("Manage Tags", callback_data=f"{TAGS_CALLBACK_PREFIX}{transaction_id}", style=ButtonStyle.PRIMARY)],
            [InlineKeyboardButton("Cancel", callback_data=f"{CANCEL_BUTTON_PREFIX}{transaction_id}", style=ButtonStyle.DANGER)]
        ])
        
        text = f"{transaction_details}\n\n✅ **Budget updated successfully!**\n\n**What would you like to customize?**"
        await callback_query.message.edit_text(text, reply_markup=markup)
    except Exception as e:
        LOGS.error(f"Error updating budget for transaction {transaction_id}: {e}")
        await callback_query.edit_message_text("Failed to update budget. Please try again.")


@FireflyParserBot.on_callback_query(filters.regex("^update_trans_category_.*") & filters.user(TELEGRAM_ADMINS))
async def update_transaction_category(client: FireflyParserBot, callback_query: CallbackQuery):
    await callback_query.answer("Updating category...")
    parts = callback_query.data.split("_")
    transaction_id = str(parts[3])
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
        
        # Edit the message back to show updated transaction details
        transaction_details = await get_transaction_details_text(firefly_api, transaction_id)
        link = firefly_api.transaction_show_url(transaction_id)
        
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("View in Firefly", url=link, style=ButtonStyle.PRIMARY)],
            [InlineKeyboardButton("Set Budget", callback_data=f"{BUDGET_CALLBACK_PREFIX}{transaction_id}", style=ButtonStyle.PRIMARY)],
            [InlineKeyboardButton("Set Category", callback_data=f"{CATEGORY_CALLBACK_PREFIX}{transaction_id}", style=ButtonStyle.PRIMARY)],
            [InlineKeyboardButton("Set Source Account", callback_data=f"{SOURCE_ACCOUNT_CALLBACK_PREFIX}{transaction_id}", style=ButtonStyle.PRIMARY)],
            [InlineKeyboardButton("Manage Tags", callback_data=f"{TAGS_CALLBACK_PREFIX}{transaction_id}", style=ButtonStyle.PRIMARY)],
            [InlineKeyboardButton("Cancel", callback_data=f"{CANCEL_BUTTON_PREFIX}{transaction_id}", style=ButtonStyle.DANGER)]
        ])
        
        text = f"{transaction_details}\n\n✅ **Category updated successfully!**\n\n**What would you like to customize?**"
        await callback_query.message.edit_text(text, reply_markup=markup)
    except Exception as e:
        LOGS.error(f"Error updating category for transaction {transaction_id}: {e}")
        await callback_query.edit_message_text("Failed to update category. Please try again.")


@FireflyParserBot.on_callback_query(filters.regex("^update_trans_source_.*") & filters.user(TELEGRAM_ADMINS))
async def update_transaction_source_account(client: FireflyParserBot, callback_query: CallbackQuery):
    await callback_query.answer("Updating source account...")
    parts = callback_query.data.split("_")
    transaction_id = str(parts[3])
    account_id = parts[4]

    firefly_api = FireflyApi()
    payload = {
        "transactions": [
            {
                "source_id": account_id
            }
        ]
    }
    try:
        firefly_api.update_transaction(transaction_id, payload)
        
        # Edit the message back to show updated transaction details
        transaction_details = await get_transaction_details_text(firefly_api, transaction_id)
        link = firefly_api.transaction_show_url(transaction_id)
        
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("View in Firefly", url=link, style=ButtonStyle.PRIMARY)],
            [InlineKeyboardButton("Set Budget", callback_data=f"{BUDGET_CALLBACK_PREFIX}{transaction_id}", style=ButtonStyle.PRIMARY)],
            [InlineKeyboardButton("Set Category", callback_data=f"{CATEGORY_CALLBACK_PREFIX}{transaction_id}", style=ButtonStyle.PRIMARY)],
            [InlineKeyboardButton("Set Source Account", callback_data=f"{SOURCE_ACCOUNT_CALLBACK_PREFIX}{transaction_id}", style=ButtonStyle.PRIMARY)],
            [InlineKeyboardButton("Manage Tags", callback_data=f"{TAGS_CALLBACK_PREFIX}{transaction_id}", style=ButtonStyle.PRIMARY)],
            [InlineKeyboardButton("Cancel", callback_data=f"{CANCEL_BUTTON_PREFIX}{transaction_id}", style=ButtonStyle.DANGER)]
        ])
        
        text = f"{transaction_details}\n\n✅ **Source account updated successfully!**\n\n**What would you like to customize?**"
        await callback_query.message.edit_text(text, reply_markup=markup)
    except Exception as e:
        LOGS.error(f"Error updating source account for transaction {transaction_id}: {e}")
        await callback_query.edit_message_text("Failed to update source account. Please try again.")


@FireflyParserBot.on_callback_query(filters.regex(f"^{BACK_BUTTON_PREFIX}.*") & filters.user(TELEGRAM_ADMINS))
async def back_to_main_menu(client: FireflyParserBot, callback_query: CallbackQuery):
    await callback_query.answer()
    transaction_id = str(callback_query.data.replace(BACK_BUTTON_PREFIX, ""))
    
    firefly_api = FireflyApi()
    
    # Get transaction details and Firefly link
    transaction_details = await get_transaction_details_text(firefly_api, transaction_id)
    link = firefly_api.transaction_show_url(transaction_id)
    
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("View in Firefly", url=link, style=ButtonStyle.PRIMARY)],
        [InlineKeyboardButton("Set Budget", callback_data=f"{BUDGET_CALLBACK_PREFIX}{transaction_id}", style=ButtonStyle.PRIMARY)],
        [InlineKeyboardButton("Set Category", callback_data=f"{CATEGORY_CALLBACK_PREFIX}{transaction_id}", style=ButtonStyle.PRIMARY)],
        [InlineKeyboardButton("Set Source Account", callback_data=f"{SOURCE_ACCOUNT_CALLBACK_PREFIX}{transaction_id}", style=ButtonStyle.PRIMARY)],
        [InlineKeyboardButton("Manage Tags", callback_data=f"{TAGS_CALLBACK_PREFIX}{transaction_id}", style=ButtonStyle.PRIMARY)],
        [InlineKeyboardButton("Cancel", callback_data=f"{CANCEL_BUTTON_PREFIX}{transaction_id}", style=ButtonStyle.DANGER)]
    ])
    
    text = f"{transaction_details}\n\n**What would you like to customize?**"
    
    await callback_query.message.edit_text(text, reply_markup=markup)


@FireflyParserBot.on_callback_query(filters.regex(f"^{CANCEL_BUTTON_PREFIX}.*") & filters.user(TELEGRAM_ADMINS))
async def cancel_customization(client: FireflyParserBot, callback_query: CallbackQuery):
    await callback_query.answer()
    await clear_tag_contexts(callback_query.message)
    
    # Edit back to original transaction state with just View in Firefly and Customize buttons
    transaction_id = str(callback_query.data.replace(CANCEL_BUTTON_PREFIX, ""))
    firefly_api = FireflyApi()
    
    transaction_details = await get_transaction_details_text(firefly_api, transaction_id)
    link = firefly_api.transaction_show_url(transaction_id)
    
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("View in Firefly", url=link, style=ButtonStyle.PRIMARY)],
        [InlineKeyboardButton("Customize Transaction", callback_data=f"{TRANSACTION_ID_PREFIX}{transaction_id}", style=ButtonStyle.SUCCESS)]
    ])
    
    text = f"{transaction_details}\n\n**Transaction customization cancelled.**"
    await callback_query.message.edit_text(text, reply_markup=markup)


@FireflyParserBot.on_callback_query(filters.regex(f"^{TAGS_CALLBACK_PREFIX}.*") & filters.user(TELEGRAM_ADMINS))
async def handle_manage_tags_callback(client: FireflyParserBot, callback_query: CallbackQuery):
    await callback_query.answer()
    transaction_id = str(callback_query.data.replace(TAGS_CALLBACK_PREFIX, ""))
    firefly_api = FireflyApi()

    try:
        # Get the transaction details to show current tags
        transaction_data = firefly_api.get_json(f"transactions/{transaction_id}")
        if not transaction_data or 'data' not in transaction_data:
            await callback_query.edit_message_text("Failed to fetch transaction details.")
            return

        transaction = transaction_data['data']
        attributes = transaction['attributes']
        transactions_list = attributes['transactions']
        if not transactions_list:
            await callback_query.edit_message_text("No transaction details found.")
            return

        inner_transaction = transactions_list[0]
        current_tags = inner_transaction.get('tags', [])

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
                    callback_data=f"quick_add_tag_{transaction_id}_{tag}",
                    style=ButtonStyle.SUCCESS
                )])

        # Create markup with quick add buttons, custom add option, and remove tag buttons
        all_buttons = quick_buttons.copy()
        all_buttons.append([InlineKeyboardButton("✏️ Add Custom Tag", callback_data=f"add_custom_tag_{transaction_id}", style=ButtonStyle.PRIMARY)])

        # Add remove buttons for each existing tag
        for tag in current_tags:
            all_buttons.append([InlineKeyboardButton(
                f"🗑️ {tag}",
                callback_data=f"remove_tag_{transaction_id}_{tag}",
                style=ButtonStyle.DANGER
            )])

        all_buttons.append([InlineKeyboardButton("<< Back", callback_data=f"{BACK_BUTTON_PREFIX}{transaction_id}", style=ButtonStyle.DEFAULT)])

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


@FireflyParserBot.on_callback_query(filters.regex(f"^quick_add_tag_.*") & filters.user(TELEGRAM_ADMINS))
async def quick_add_tag(client: FireflyParserBot, callback_query: CallbackQuery):
    await callback_query.answer("Adding tag...")
    parts = callback_query.data.split("_")
    transaction_id = str(parts[3])
    tag = "_".join(parts[4:])  # Handle multi-word tags

    firefly_api = FireflyApi()

    try:
        # Get current transaction to fetch existing tags
        transaction_data = firefly_api.get_json(f"transactions/{transaction_id}")
        if not transaction_data or 'data' not in transaction_data:
            await callback_query.edit_message_text("Failed to fetch transaction details.")
            return

        transaction = transaction_data['data']
        attributes = transaction['attributes']
        transactions_list = attributes['transactions']
        inner_transaction = transactions_list[0]
        current_tags = inner_transaction.get('tags', [])

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
        firefly_api.update_transaction(transaction_id, payload)

        # Refresh the tags view by updating callback data
        callback_query.data = f"{TAGS_CALLBACK_PREFIX}{transaction_id}"
        await handle_manage_tags_callback(client, callback_query)

    except Exception as e:
        LOGS.error(f"Error adding tag to transaction {transaction_id}: {e}")
        await callback_query.edit_message_text("Failed to add tag. Please try again.")


@FireflyParserBot.on_callback_query(filters.regex(f"^remove_tag_.*") & filters.user(TELEGRAM_ADMINS))
async def remove_tag(client: FireflyParserBot, callback_query: CallbackQuery):
    await callback_query.answer("Removing tag...")
    parts = callback_query.data.split("_")
    transaction_id = str(parts[2])
    tag = "_".join(parts[3:])  # Handle multi-word tags

    firefly_api = FireflyApi()

    try:
        # Get current transaction to fetch existing tags
        transaction_data = firefly_api.get_json(f"transactions/{transaction_id}")
        if not transaction_data or 'data' not in transaction_data:
            await callback_query.edit_message_text("Failed to fetch transaction details.")
            return

        transaction = transaction_data['data']
        attributes = transaction['attributes']
        transactions_list = attributes['transactions']
        inner_transaction = transactions_list[0]
        current_tags = inner_transaction.get('tags', [])

        # Remove the tag if it exists
        if tag in current_tags:
            current_tags.remove(tag)

        # Update transaction with new tags
        payload = {
            "transactions": [
                {
                    "tags": current_tags
                }
            ]
        }
        firefly_api.update_transaction(transaction_id, payload)

        # Refresh tags view by updating callback data
        callback_query.data = f"{TAGS_CALLBACK_PREFIX}{transaction_id}"
        await handle_manage_tags_callback(client, callback_query)

    except Exception as e:
        LOGS.error(f"Error removing tag from transaction {transaction_id}: {e}")
        await callback_query.edit_message_text("Failed to remove tag. Please try again.")


@FireflyParserBot.on_callback_query(filters.regex(f"^add_custom_tag_.*") & filters.user(TELEGRAM_ADMINS))
async def add_custom_tag_callback(client: FireflyParserBot, callback_query: CallbackQuery):
    await callback_query.answer()
    transaction_id = str(callback_query.data.replace("add_custom_tag_", ""))

    text = "Send the tag you want to add as a reply to this message."
    reply_msg = await callback_query.message.reply(
        text,
        reply_markup=ForceReply(selective=True)
    )
    FireflyParserBot._add_tag_context = {
        "user_id": callback_query.from_user.id,
        "transaction_id": transaction_id,
        "message_id": callback_query.message.id,
        "reply_message_id": reply_msg.id
    }


@FireflyParserBot.on_message(filters.private & filters.user(TELEGRAM_ADMINS), group=10)
async def handle_add_tag_reply(_, message: Message):
    # Check if this is a reply to our ForceReply for adding tags
    if not hasattr(FireflyParserBot, '_add_tag_context'):
        await message.continue_propagation()
        return

    ctx = getattr(FireflyParserBot, "_add_tag_context", None)
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

    # Process the tag addition
    tag = message.text.strip()

    # Try to delete the ForceReply message to clean up the chat
    try:
        if "reply_message_id" in ctx:
            await message.chat.delete_messages(ctx["reply_message_id"])
    except Exception:
        pass

    # Delete the user's reply message
    try:
        await message.delete()
    except Exception:
        pass

    if not tag:
        original_message = await message.chat.get_messages(ctx["message_id"])
        await original_message.edit_text("❌ Tag cannot be empty.")
        FireflyParserBot._add_tag_context = None
        await message.stop_propagation()
        return

    firefly_api = FireflyApi()
    transaction_id = ctx["transaction_id"]

    try:
        # Get current transaction to fetch existing tags
        transaction_data = firefly_api.get_json(f"transactions/{transaction_id}")
        if not transaction_data or 'data' not in transaction_data:
            original_message = await message.chat.get_messages(ctx["message_id"])
            await original_message.edit_text("❌ Failed to fetch transaction details.")
            FireflyParserBot._add_tag_context = None
            await message.stop_propagation()
            return

        transaction = transaction_data['data']
        attributes = transaction['attributes']
        transactions_list = attributes['transactions']
        inner_transaction = transactions_list[0]
        current_tags = inner_transaction.get('tags', [])

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
        firefly_api.update_transaction(transaction_id, payload)

        # Refresh the tags view in the original message
        original_message = await message.chat.get_messages(ctx["message_id"])

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

    except Exception as e:
        LOGS.error(f"Error adding tag to transaction {transaction_id}: {e}")
        try:
            original_message = await message.chat.get_messages(ctx["message_id"])
            await original_message.edit_text("❌ Failed to add tag. Please try again.")
        except Exception:
            pass

    FireflyParserBot._add_tag_context = None
    await message.stop_propagation()
