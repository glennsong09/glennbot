import discord
import os
from discord.ext import commands
from discord import Intents
from database import db
from dotenv import load_dotenv

db.build()
load_dotenv()

intents = discord.Intents.all()

bot = commands.Bot(command_prefix="!", intents=intents)
token = os.getenv("TOKEN")

GUILD_ID = 938505162593542155


async def setup_hook():
    for filename in os.listdir('./cogs'):
        if filename.endswith('.py'):
            await bot.load_extension(f'cogs.{filename[:-3]}')
    # Sync slash commands to guild only (instant updates, no global propagation delay)
    guild = discord.Object(id=GUILD_ID)
    bot.tree.copy_global_to(guild=guild)
    synced = await bot.tree.sync(guild=guild)
    # Clear any old global commands (fixes duplicates from previous global sync)
    bot.tree.clear_commands(guild=None)
    await bot.tree.sync()
    print(f"Synced {len(synced)} slash command(s) to guild {GUILD_ID}")


bot.setup_hook = setup_hook
bot.run(token)