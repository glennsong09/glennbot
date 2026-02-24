from discord import Member, Embed, Color
from discord.ext import commands
from discord import app_commands
from typing import Optional
from database import db


class Profile(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_command(name="profile", description="View your or another user's profile")
    @app_commands.describe(member="The user whose profile to view (leave empty for your own)")
    async def show_profile(self, ctx, member: Optional[Member] = None):
        target = member or ctx.author

        # Check if user has a profile. If not, create profile.
        display_name = db.record("SELECT display_name FROM profiles WHERE user_id=?", target.id) or None

        if display_name is None:
            db.execute("INSERT INTO profiles (user_id, display_name) VALUES (?, ?)", target.id, target.name)
            db.commit()
            display_name = target.name
        else:
            display_name = display_name[0]

        # Get stats
        profile_pic = target.avatar.url
        level, exp, tokens = db.records("SELECT level, exp, tokens FROM profiles WHERE user_id=?", target.id)[0]
        current_quest = db.record("SELECT current_quest FROM profiles WHERE user_id=?", target.id)[0]

        # Create embed
        embed = Embed(title = display_name, color = Color.orange())
        embed.add_field(name = 'Level', value = level)
        embed.add_field(name = 'EXP', value = int(exp))
        #embed.add_field(name = 'Tokens', value = tokens)
        embed.add_field(name = 'Quest', value = current_quest)
        embed.set_thumbnail(url=profile_pic)

        await ctx.send(embed=embed)

    # Registers the user if they don't have a profile. Otherwise, does nothing.
    async def _register_profile(self, user):
        if db.record("SELECT * FROM profiles WHERE user_id = ?", user.id) == None:
            db.execute("INSERT INTO profiles (user_id, display_name) VALUES (?, ?)", user.id, user.display_name)
            db.commit()
        

async def setup(bot):
    await bot.add_cog(Profile(bot))
