from pyrogram import Client
from pyrogram.raw.all import layer
from pyrogram.types import BotCommand, BotCommandScopeChat
import logging
import app

LOGS = logging.getLogger(__name__)


class FireflyParserBot(Client):
    def __init__(self, version='0.0.0', **kwargs):
        self.version = version
        app.WORKDIR.mkdir(parents=True, exist_ok=True)

        super().__init__(
            'firefly_parser_bot',
            api_id=kwargs['api_id'],
            api_hash=kwargs['api_hash'],
            bot_token=kwargs['bot_token'],
            # Pyrogram's update queue is FIFO. One worker finishes all handlers
            # for an update before starting the next message or callback.
            workers=1,
            plugins=dict(root="app/plugins"),
            workdir=str(app.WORKDIR),
        )

    def __str__(self):
        """
        String representation of the class object
        """
        return self.__class__.__name__

    async def start(self):
        await super().start()

        for chat in app.TELEGRAM_ADMINS:
            await self.set_bot_commands(
                [
                    BotCommand('income', 'Record incoming money'),
                    BotCommand('vendors', 'List all vendors'),
                    BotCommand('start', 'Start the bot'),
                    BotCommand('help', 'Show help message'),
                    BotCommand('syncvendors', 'Fetch all vendors from Firefly'),
                    BotCommand('foreignsum', 'Show foreign transaction summary'),
                    BotCommand('foreignsum_help', 'Show usage instructions for /foreignsum'),
                ],
                scope=BotCommandScopeChat(chat_id=chat)
            )

        me = await self.get_me()
        LOGS.info(f"{self.__class__.__name__} v{self.version} (Layer {layer}) started on @{me.username}.\n"
                  f"Firefly Parser Bot is ready to serve.")

    async def stop(self, *args):
        """
        Stop function
        :param args:
        """
        await super().stop()
        LOGS.info(f"{self.__class__.__name__} stopped. Bye.")
