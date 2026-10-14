import time

from discord.ext import commands

from database import db


def persistent_cooldown(seconds: int):
    """Per-user cooldown stored in the database, so it survives bot restarts.

    Raises CommandOnCooldown like commands.cooldown, so existing error handlers keep working.
    """
    async def check(ctx):
        row = db.record("SELECT last_used FROM cooldowns WHERE user_id=? AND command=?",
                        ctx.author.id, ctx.command.qualified_name)
        remaining = row[0] + seconds - time.time() if row else 0
        if remaining > 0:
            raise commands.CommandOnCooldown(commands.Cooldown(1, seconds), remaining, commands.BucketType.user)
        return True

    # Recorded in a before-invoke hook rather than the check, because !help also runs checks
    async def record(*args):  # called as (cog, ctx) inside a cog
        ctx = args[-1]
        db.execute("INSERT OR REPLACE INTO cooldowns (user_id, command, last_used) VALUES (?, ?, ?)",
                   ctx.author.id, ctx.command.qualified_name, time.time())
        db.commit()

    def decorator(func):
        return commands.before_invoke(record)(commands.check(check)(func))
    return decorator
