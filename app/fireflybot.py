from pyrogram import Client
from pyrogram.raw.all import layer
from pyrogram.types import BotCommand, BotCommandScopeChat

import app


class FireflyParserBot(Client):
    def __init__(self, version='0.0.0', **kwargs):
        self.version = version

        super().__init__(
            'firefly_parser_bot',
            api_id=kwargs['api_id'],
            api_hash=kwargs['api_hash'],
            bot_token=kwargs['bot_token'],
            workers=16,
            plugins=dict(root="app/plugins"),
            workdir="./workdir"
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
                    BotCommand('start', 'Start the bot'),
                    BotCommand('help', 'Show help message'),
                ],
                scope=BotCommandScopeChat(chat_id=chat)
            )

        me = await self.get_me()
        print(f"{self.__class__.__name__} v{self.version} (Layer {layer}) started on @{me.username}.\n"
              f"Firefly Parser Bot is ready to serve.")

    async def stop(self, *args):
        """
        Stop function
        :param args:
        """
        await super().stop()
        print(f"{self.__class__.__name__} stopped. Bye.")
