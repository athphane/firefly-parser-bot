# AGENTS.md

This file contains guidelines for agentic coding agents working in this repository.

## Build, Lint, and Test Commands

### Running the Application
```bash
python -m app
```

### Dependencies
```bash
pip install -r requirements.txt
```

### Testing
No formal test framework is configured. The only test file is `vendor_test.py`, which can be run directly:
```bash
python vendor_test.py
```

### Linting/Type Checking
No linting or type checking tools are currently configured. No commands to run.

## Code Style Guidelines

### Imports
Order imports by category with blank lines between each group:
1. Standard library imports (`import logging`, `from datetime import datetime`)
2. Third-party imports (`from pyrogram import filters`, `import pymongo`)
3. Local imports (`from app import FireflyParserBot`, `from app.database.vendorsdb import VendorsDB`)

Use `Union[T, None]` or `T | None` for optional types.

### Formatting
- 4 spaces for indentation
- Blank lines between functions and methods
- No strict line length limit enforced

### Type Hints
- Always include type hints for function parameters and return values
- Use `Union` or `|` for optional types: `Union[None, str]` or `str | None`
- Use generics for collections: `list[str]`, `dict[str, int]`
- Import types from `typing` module as needed

### Naming Conventions
- Classes: PascalCase (`FireflyParserBot`, `ParsedTransactionMessage`)
- Functions and methods: snake_case (`find_vendor_by_title`, `extract_transaction_details`)
- Constants: UPPER_CASE with underscores (`TELEGRAM_API_ID`, `VENDORS_PER_PAGE`)
- Private methods: prefix with single underscore (`_generate_alias_notes`)
- Modules/packages: lowercase (`vendors.py`, `database/`)

### Error Handling
- Always log errors using the module-level logger: `LOGS.error(f"Error: {e}")`
- Use try-except blocks for API calls and JSON parsing
- Return `None` or raise exceptions appropriately
- Validate JSON responses before accessing keys: check `isinstance(json_decoded, dict)`

### Logging
- Import logging at the top of each file
- Define module-level logger: `LOGS = logging.getLogger(__name__)`
- Log important actions and errors: `LOGS.info("Action completed")`, `LOGS.error("Error occurred")`

### Docstrings
- Use triple-quoted strings for function/method documentation
- Include parameter descriptions with Args: sections
- Include return type information with Returns: sections
- Example:
  ```python
  def find_vendor_by_title(title: str):
      """Finds a vendor by title.
      
      Args:
          title: The vendor title to search for.
          
      Returns:
          The vendor document or None if not found.
      """
  ```

### Async/Await
- Use `async def` for asynchronous functions
- Always `await` coroutines
- Pyrogram handlers use decorators: `@FireflyParserBot.on_message(...)`

### Configuration
- All configuration is loaded from `config.ini` in `app/__init__.py`
- Access config values as module-level constants: `from app import TELEGRAM_API_ID`
- Use `config.get()` for string values, `config.getint()` for integers
- Use `fallback` parameter for optional config values

### Pyrogram/Telegram Bot Patterns
- Use `filters.private & filters.user(TELEGRAM_ADMINS)` for admin-only commands
- Use `group` parameter for handler priority (lower number = higher priority)
- Use `InlineKeyboardMarkup` and `InlineKeyboardButton` for interactive buttons
- Use `await message.stop_propagation()` to prevent handler chaining
- Use `await message.continue_propagation()` to allow other handlers to process

### Database (MongoDB)
- Use `VendorsDB()` class from `app.database.vendorsdb`
- Access collection via `self.vendors = database()["vendors"]`
- Use MongoDB query operators (`$or`, `$regex`, `$options`) for complex queries
- Use `ReturnDocument.AFTER` for update-and-return operations

### Models
- Use `@dataclass` for simple data models (see `transaction_models.py`)
- Use regular classes for complex models with methods (see `ParsedTransactionMessage`)
- All models are in `app/models/`

### API Integration
- Use `FireflyApi()` class from `app.firefly.firefly`
- All API methods handle their own error logging
- Use `requests` for HTTP calls with proper headers
- API endpoints use `get_json`, `post_json`, `put_json` methods
