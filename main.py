import discord
import os
from discord.ext import commands
from discord import Intents
from database import db
from dotenv import load_dotenv

db.build()
load_dotenv()

intents = discord.Intents.all()

bot = commands.Bot(command_prefix="!", intents = intents)
token = os.getenv("TOKEN")

''' @bot.command()
async def load(ctx, extension):
    await bot.load_extension(f'cogs.{extension}')

@bot.command()
async def unload(ctx, extension):
    await bot.unload_extension(f'cogs.{extension}') ''' 

async def setup_hook():
    for filename in os.listdir('./cogs'):
        if filename.endswith('.py'):
            await bot.load_extension(f'cogs.{filename[:-3]}')

bot.setup_hook = setup_hook
bot.run(token)