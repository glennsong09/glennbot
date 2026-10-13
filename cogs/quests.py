import discord
import random
import math
from discord.ext import commands
from discord.ext.commands import BucketType, cooldown
from discord import app_commands
from typing import Optional
from database import db
from datetime import timedelta

# TODO: random synchronized encounters, several people have to do it in order to get the xp + completion

# Here is the list of all quests separated by types.
# TODO: More types of quests
sitdown_quests = ['Drink [x] sips of water',
                  'Stretch your hands for [x] minutes',
                  'Rest your eyes for [x] minutes',
                  'Rest your hands for [x] minutes']
standup_quests = ['Stretch for [x] minutes',
                  'Do [x] pushups',
                  'Do [x] jumping jacks',
                  'Do [x] squats',
                  'Do [x] lunges',
                  'Do [x] situps',
                  'Do [x] crunches']
active_quests = ['Go on a walk/work out for [x] minutes']
announcements = ['Say 1 thing that made you happy today',
                 'Say 1 thing you want to do today',
                 'Say 1 thing you want to accomplish',
                 'Say 1 thing you want to get done tomorrow',
                 'Say 1 thing that makes you happy']
easy_quests   = sitdown_quests
normal_quests = sitdown_quests + standup_quests
hard_quests   = standup_quests

XP_BASE        = 50
XP_PER_QUEST   = 50
XP_PER_COUNTER = 8


def give_int(quest):
    """Assign a random value to the [x] placeholder in a quest string."""
    num = random.randint(3, 7)
    return (quest.replace("[x]", str(num)), num)


def _join_quests(quests: list) -> str:
    """Join a list of quest strings into a readable sentence."""
    if len(quests) == 1:
        return quests[0]
    head   = quests[0]
    middle = [q.lower() for q in quests[1:-1]]
    tail   = "and " + quests[-1].lower() + "."
    return ", ".join([head] + middle + [tail])


def make_quest_db_entry(quests: list) -> str:
    return _join_quests(quests)


def make_quest_statement(quests: list, xp_gained: int) -> str:
    return f"Here are your quests for today! {_join_quests(quests)} Rewards: {xp_gained}XP."


def make_quests(type):
    """Assemble a (quests, xp) tuple. Type: 0 = easy, 1 = normal, 2 = hard."""
    if type == 0:
        num_quests_picked = random.randint(1, 2)
        quest_choice_1 = random.sample(easy_quests, num_quests_picked)
    elif type == 1:
        num_quests_picked = random.randint(2, 4)
        quest_choice_1 = random.sample(normal_quests, num_quests_picked)
    else:
        num_quests_picked = random.randint(3, 5)
        quest_choice_1 = random.sample(hard_quests, num_quests_picked)

    announcement = random.sample(announcements, 1)

    quests, counter = [], 0
    for quest in quest_choice_1:
        text, num = give_int(quest)
        quests.append(text)
        counter += num

    # Announcements have no [x] — add them as-is and don't count toward XP counter
    for quest in announcement:
        quests.append(quest)

    xp_generated = XP_BASE + (XP_PER_QUEST * num_quests_picked) + (XP_PER_COUNTER * counter)
    return (quests, xp_generated)


class Quests(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # Quest command.
    # TODO: make cd reset at a common time (user's time)
    @commands.hybrid_command(name='quest', description="Get your daily quests!")
    @app_commands.describe(quest_type="Quest difficulty: easy, normal, or hard")
    @app_commands.choices(quest_type=[
        app_commands.Choice(name="Easy",   value="easy"),
        app_commands.Choice(name="Normal", value="normal"),
        app_commands.Choice(name="Hard",   value="hard"),
    ])
    @cooldown(1, 86400, BucketType.user)
    async def quest(self, ctx, quest_type: Optional[str] = None):
        await self._register_profile(ctx.author)

        if quest_type == 'easy':
            final_quests = make_quests(0)
        elif quest_type == 'hard':
            final_quests = make_quests(2)
        else:
            final_quests = make_quests(1)

        quest_statement    = make_quest_statement(final_quests[0], final_quests[1])
        quest_db_statement = make_quest_db_entry(final_quests[0])

        db.execute(
            "UPDATE profiles SET current_quest=?, current_quest_exp=? WHERE user_id=?",
            quest_db_statement, final_quests[1], ctx.author.id,
        )
        db.commit()
        await ctx.send(f'{ctx.author.mention}\n{quest_statement}')

    # Updates the db if the user has completed their quest.
    @commands.hybrid_command(name='complete', description="Complete your current quest")
    async def complete(self, ctx):
        await self._register_profile(ctx.author)

        row = db.record("SELECT exp, current_quest_exp FROM profiles WHERE user_id=?", ctx.author.id)
        curr_xp, curr_quest_xp = row[0], row[1]

        if curr_quest_xp is None:
            await ctx.send("You don't have an active quest! Use `/quest` to get one.")
            return

        db.execute(
            "UPDATE profiles SET exp=?, current_quest=?, current_quest_exp=? WHERE user_id=?",
            curr_quest_xp + curr_xp, None, None, ctx.author.id,
        )
        db.commit()
        await self._check_level(ctx)
        await ctx.send(f"Okay! Here are your rewards: {curr_quest_xp}XP.")

    async def _register_profile(self, user):
        if db.record("SELECT * FROM profiles WHERE user_id = ?", user.id) is None:
            db.execute("INSERT INTO profiles (user_id, display_name) VALUES (?, ?)", user.id, user.display_name)
            db.commit()

    async def _check_level(self, ctx):
        row = db.record("SELECT level, exp FROM profiles WHERE user_id = ?", ctx.author.id)
        curr_level, curr_xp = row[0], row[1]

        leveled_up = False
        while curr_xp > (needed := 1000 * math.log(curr_level + 1, 2)):
            curr_xp    -= needed
            curr_level += 1
            leveled_up  = True

        if leveled_up:
            db.execute(
                "UPDATE profiles SET level=?, exp=? WHERE user_id=?",
                curr_level, curr_xp, ctx.author.id,
            )
            db.commit()
            await ctx.send(f"Congratulations! You are now level {curr_level}!")

    @quest.error
    async def on_quest_error(self, ctx, error):
        if isinstance(error, commands.CommandOnCooldown):
            remaining_time = str(timedelta(seconds=int(error.retry_after)))
            await ctx.send(f'{ctx.author.mention} Try again in {remaining_time}.')


async def setup(bot):
    await bot.add_cog(Quests(bot))
