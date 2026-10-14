import discord
import os
import sys
import traceback
from datetime import timedelta
from discord.ext import commands
from database import db
from dotenv import load_dotenv

db.build()
load_dotenv()

intents = discord.Intents.default()
intents.message_content = True  # needed for ! prefix commands
intents.members = True          # needed to look up @mentioned members (!notify, !riftbound draft)

bot = commands.Bot(command_prefix="!", intents=intents)
token = os.getenv("TOKEN")
if not token:
    sys.exit("TOKEN is not set. Add it to your .env file.")

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


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    # Commands with their own error handler (goodmorning, goodnight, quest) already reply to cooldowns
    if isinstance(error, commands.CommandOnCooldown) and ctx.command.has_error_handler():
        return

    if isinstance(error, commands.CommandOnCooldown):
        msg = f"That command is on cooldown. Try again in {timedelta(seconds=int(error.retry_after))}."
    elif isinstance(error, commands.UserInputError):
        msg = f"{error}\nUsage: `{ctx.clean_prefix}{ctx.command.qualified_name} {ctx.command.signature}`"
    elif isinstance(error, commands.CheckFailure):
        msg = "You can't use that command here."
    else:
        original = error
        while hasattr(original, "original"):  # slash command errors can be wrapped twice
            original = original.original
        if isinstance(original, discord.Forbidden):
            msg = "I don't have permission to do that here. Check my channel permissions (e.g. Send Messages, Attach Files)."
        else:
            msg = "Something went wrong running that command. Please try again in a bit."
        print(f"Error in command '{ctx.command}':", file=sys.stderr)
        traceback.print_exception(type(error), error, error.__traceback__)

    try:
        await ctx.send(msg, ephemeral=True)
    except discord.HTTPException:
        pass


bot.setup_hook = setup_hook
bot.run(token)