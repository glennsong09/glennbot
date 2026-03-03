import discord
import random
from discord.ext import commands
from discord.ext.commands import BucketType, cooldown
from database import db

good_morning_roulette = ['Have a great day!',
                         'Rise and shine!',
                         'Hope your day goes well!',
                         'Enjoy your day!']
good_night_roulette = ['Sleep well!',
                       'Don\'t let the bed bugs bite!',
                       'Sweet dreams!',
                       'Sleep tight!',
                       'See you tomorrow!']
gm_cd_roulette = ['Good morning again!',
                  'We\'ve already said good morning!']
gn_cd_roulette = ['Good night again!',
                  'We\'ve already said good night!',
                  'Do you miss me or something? Dummy... go to bed!']


async def setup(bot):
    await bot.add_cog(General(bot))


class General(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        print('Bot is online.')

    @commands.Cog.listener()
    async def on_connect(self):
        print('Bot is connected.')

    @commands.hybrid_command(name='hello', aliases=['hi', 'heya', 'hihi', 'hai'], description="Say hello!")
    async def hello(self, ctx):
        await self._register_profile(ctx.author)
        await ctx.send(f"Hello, {ctx.author.mention}!")

    @commands.hybrid_command(name='dm', aliases=['DM'], description="DM me!")
    async def dm(self, ctx):
        await self._register_profile(ctx.author)
        await ctx.author.send("Hello from the bot!")

    @commands.hybrid_command(name='bye', aliases=['byebye', 'bai', 'baibai'], description="Say goodbye!")
    async def bye(self, ctx):
        await self._register_profile(ctx.author)
        await ctx.send(f'Bye, {ctx.author.mention}!')

    @commands.hybrid_command(name='thanks', aliases=['ty'], description="Say thanks!")
    async def thanks(self, ctx):
        await self._register_profile(ctx.author)
        await ctx.send(f'You\'re welcome, {ctx.author.mention}! ^^')

    @commands.hybrid_command(name='goodmorning', aliases=['gm'], description="Say good morning!")
    @cooldown(1, 57600, BucketType.user)
    async def goodmorning(self, ctx):
        await self._register_profile(ctx.author)
        target = ctx.author
        curr_xp = db.record("SELECT exp FROM profiles WHERE user_id=?", target.id)[0]
        db.execute("UPDATE profiles SET exp = ? WHERE user_id=?", (curr_xp + 10), target.id)
        gm_statement = random.choice(good_morning_roulette)
        await ctx.send(f'{ctx.author.mention} ' + gm_statement)

    @commands.hybrid_command(name='goodnight', aliases=['gn'], description="Say good night!")
    @cooldown(1, 57600, BucketType.user)
    async def goodnight(self, ctx):
        await self._register_profile(ctx.author)
        target = ctx.author
        curr_xp = db.record("SELECT exp FROM profiles WHERE user_id=?", target.id)[0]
        db.execute("UPDATE profiles SET exp = ? WHERE user_id=?", (curr_xp + 10), target.id)
        gn_statement = random.choice(good_night_roulette)
        await ctx.send(f'{ctx.author.mention} ' + gn_statement)

    async def _register_profile(self, user):
        if db.record("SELECT * FROM profiles WHERE user_id = ?", user.id) is None:
            db.execute("INSERT INTO profiles (user_id, display_name) VALUES (?, ?)", user.id, user.display_name)
            db.commit()

    @goodmorning.error
    async def on_goodmorning_error(self, ctx, error):
        if isinstance(error, commands.CommandOnCooldown):
            gm_cd_statement = random.choice(gm_cd_roulette)
            await ctx.send(f'{ctx.author.mention} ' + gm_cd_statement)

    @goodnight.error
    async def on_goodnight_error(self, ctx, error):
        if isinstance(error, commands.CommandOnCooldown):
            gn_cd_statement = random.choice(gn_cd_roulette)
            await ctx.send(f'{ctx.author.mention} ' + gn_cd_statement)
