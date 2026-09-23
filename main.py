import asyncio
import logging

import discord
from discord.ext import commands

from config import TOKEN, PREFIXES
from database import init_db

logging.basicConfig(level=logging.INFO)

intents = discord.Intents.all()


class HashiraBot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix=commands.when_mentioned_or(*PREFIXES),
            intents=intents,
            help_command=None,  # disabilitiamo quello di default, lo sostituisce cogs.help
        )

    async def setup_hook(self):
        await init_db()
        for ext in (
            "cogs.moderation",
            "cogs.logs",
            "cogs.invites",
            "cogs.leveling",
            "cogs.giveaway",
            "cogs.embeds_welcome",
            "cogs.automod",
            "cogs.info",
            "cogs.economy",
            "cogs.fun",
            "cogs.staff",
            "cogs.help",
        ):
            await self.load_extension(ext)
            logging.info(f"Caricato: {ext}")
        await self.tree.sync()
        logging.info("Slash command sincronizzati.")

    async def on_ready(self):
        logging.info(f"Bot connesso come {self.user} ({self.user.id})")
        await self.change_presence(activity=discord.Game(name="/help | .help"))


async def main():
    bot = HashiraBot()
    async with bot:
        await bot.start(TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
