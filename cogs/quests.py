import discord
import random
import math
import aiohttp
import asyncio
import io
from aiocache import cached
from aiocache.serializers import PickleSerializer
from PIL import Image

from ast import alias
from dataclasses import replace
from discord import Member, Embed, Color
from discord.ext import commands
from discord.ext.commands import BucketType, cooldown
from typing import Optional, final
from database import db
from datetime import datetime, timedelta

# TODO: random synchronized encounters, several people have to do it in order to get the xp + completion
# QUEST STUFF
# QUEST STUFF
# QUEST STUFF

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
easy_quests = sitdown_quests
normal_quests = sitdown_quests + standup_quests
hard_quests = standup_quests

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

# Assigns a quest a random value for how many the user has to do.
def give_int(quest):
    num = random.randint(3,7)
    with_val = quest.replace("[x]", str(num))
    return (with_val, num)

# Compiles a list of quests into a string for the user.
def make_quest_statement(quests, xp_gained): 
    quest_statement = ""
    for i in range(len(quests)):
        if (i == 0):
            quest_statement = "Here are your quests for today! " + quests[i]
        elif (i == (len(quests) - 1)): 
            quest_statement = quest_statement + ", and " + quests[i].lower() + "."
        else: 
            quest_statement = quest_statement + ", " + quests[i].lower()
    quest_statement = quest_statement + " Rewards: " + str(xp_gained) + "XP."
    return quest_statement

# Compiles a list of quests into a string for the db.
def make_quest_db_entry(quests): 
    quest_statement = ""
    for i in range(len(quests)):
        if (i == 0):
            quest_statement = quests[i]
        elif (i == (len(quests) - 1)): 
            quest_statement = quest_statement + ", and " + quests[i].lower() + "."
        else: 
            quest_statement = quest_statement + ", " + quests[i].lower()
    return quest_statement

# Assembles a tuple of (quest, xp) for normal quests.
# Type: 0 = easy, 1 = normal, 2 = hard
def make_quests(type):
    num_quests_picked = 0
    quests = []
    quest_picker = []
    quest_choice_1 = []
    quest_choice_2 = random.sample(announcements, 1)

    if (type == 0): 
        num_quests_picked = random.randint(1,2)
        quest_choice_1 = random.sample(easy_quests, num_quests_picked)        
    elif (type == 1): 
        num_quests_picked = random.randint(2,4)
        quest_choice_1 = random.sample(normal_quests, num_quests_picked)        
    else: 
        num_quests_picked = random.randint(3,5)
        quest_choice_1 = random.sample(hard_quests, num_quests_picked)

    quest_picker = quest_choice_1 + quest_choice_2

    counter = 0
    for quest in quest_picker: 
        randomize_quest = give_int(quest)
        quests.append(randomize_quest[0])
        counter += randomize_quest[1]
    xp_generated = 50 + (50 * num_quests_picked) + (8 * counter)
    return (quests, xp_generated)

# PACK STUFF
# PACK STUFF
# PACK STUFF

@cached(ttl=3600, serializer=PickleSerializer())
async def get_all_cards() -> list:
    """Fetch all cards from the API. Results are cached for 1 hour."""
    url = "https://api.riftcodex.com/cards"
    params = {"size": 50, "page": 1}
    all_cards = []

    async with aiohttp.ClientSession() as session:
        while True:
            async with session.get(url, params=params) as resp:
                data = await resp.json()

            all_cards.extend(data["items"])

            if data["page"] >= data["pages"]:
                break
            params["page"] += 1

    return all_cards

def code_to_cards(all_cards: list, code: str) -> list:
    """Convert a card code string to a list of card dictionaries."""
    card_codes = code.split(" ")
    cards = [code_to_card(all_cards, code) for code in card_codes]
    missing = [card_codes[i] for i, c in enumerate(cards) if c is None]
    if missing:
        print(f"[code_to_cards] Could not find cards for codes: {missing}")
    return [c for c in cards if c is not None]

def clean_card_code(code: str) -> str:
    """Clean a card code string."""
    if "/" in code:
        return code.split("/")[0].strip()
    if code.endswith("-1"): # SFD-123-1 -> SFD-123
        return code[:-2].strip()
    return code.strip()

def code_to_card(all_cards: list, code: str) -> dict:
    """Convert a card code to a card dictionary."""
    return next((c for c in all_cards if clean_card_code(c["public_code"]) == clean_card_code(code)), None)


def filter_by_set(cards: list, set_id: str) -> list:
    """Filter cards by set ID."""
    return [c for c in cards if c["set"]["set_id"] == set_id]


def filter_by_rarity(cards: list, rarity: str) -> list:
    """Filter cards by rarity."""
    return [c for c in cards if c["classification"]["rarity"] == rarity]


# Assembles a pack
# Type: OGN = origins, SFD = spiritforged
async def make_pack(type):
    all_cards = await get_all_cards()
    set_cards = filter_by_set(all_cards, type)

    commons = filter_by_rarity(set_cards, "Common")
    # Remove tokens and runes from commons
    commons = [c for c in commons if not ((c["classification"]["supertype"] == "Token")
                                               or (c["classification"]["type"] == "Rune"))]
    uncommons = filter_by_rarity(set_cards, "Uncommon")
    rares = filter_by_rarity(set_cards, "Rare")
    epics = filter_by_rarity(set_cards, "Epic")
    showcases = filter_by_rarity(set_cards, "Showcase")

    signatures = [c for c in showcases if c["metadata"]["signature"] == True]
    alt_arts = [c for c in showcases if c["metadata"]["alternate_art"] == True]
    overnumbered = [
        c for c in showcases
        if c["metadata"]["overnumbered"] == True and c["metadata"]["signature"] == False
    ]

    cards = []

    # 7 commons
    while len(cards) < 7:
        curr_card = random.choice(commons)
        cards.append(curr_card)

    # 3 uncommons
    while len(cards) < 10:
        curr_card = random.choice(uncommons)
        cards.append(curr_card)

    # 1 foil of any rarity
    while len(cards) < 11:
        luck = random.randint(1, 720)
        print("foil", luck)
        if luck == 1:
            curr_card = random.choice(signatures)
            cards.append(curr_card)
            print(curr_card)
            continue
        if luck <= 11:
            curr_card = random.choice(overnumbered)
            cards.append(curr_card)
            print(curr_card)
            continue
        if luck <= 71:
            curr_card = random.choice(alt_arts)
            cards.append(curr_card)
            print(curr_card)
            continue
        if luck <= 251:
            curr_card = random.choice(epics)
            cards.append(curr_card)
            print(curr_card)
            continue
        curr_card = random.choice(rares + uncommons + commons)
        cards.append(curr_card)
        print(curr_card)

    # 2 rares or better
    while len(cards) < 13:
        luck = random.randint(1, 720)
        print("rare", luck)
        if luck == 1:
            curr_card = random.choice(signatures)
            cards.append(curr_card)
            print(curr_card)
            continue
        if luck <= 11:
            curr_card = random.choice(overnumbered)
            cards.append(curr_card)
            print(curr_card)
            continue
        if luck <= 71:
            curr_card = random.choice(alt_arts)
            cards.append(curr_card)
            print(curr_card)
            continue
        if luck <= 251:
            curr_card = random.choice(epics)
            cards.append(curr_card)
            print(curr_card)
            continue
        curr_card = random.choice(rares)
        cards.append(curr_card)
        print(curr_card)
    print("---")

    return cards

CARD_W, CARD_H = 744, 1039

async def fetch_image(session: aiohttp.ClientSession, url: str) -> Image.Image:
    async with session.get(url) as resp:
        data = await resp.read()
    img = Image.open(io.BytesIO(data)).convert("RGBA")
    if img.width > img.height:
        img = img.rotate(90, expand=True)
    if img.size != (CARD_W, CARD_H):
        img = img.resize((CARD_W, CARD_H), Image.LANCZOS)
    return img


async def build_pack_image(pack: list, extra_card: Optional[dict] = None) -> discord.File:
    """
    Layout (13 cards):
      Row 1: cards 0-6  (7 commons, left-to-right)
      Row 2: cards 7-9  (3 uncommons, left-aligned)
             extra_card  (center, position 3, optional)
             cards 10-12 (foil + 2 rares, right-aligned)
    """
    urls = [c["media"]["image_url"] for c in pack]

    async with aiohttp.ClientSession() as session:
        fetch_tasks = [fetch_image(session, u) for u in urls]
        if extra_card:
            fetch_tasks.append(fetch_image(session, extra_card["media"]["image_url"]))
        fetched = await asyncio.gather(*fetch_tasks)

    images = list(fetched[:13])
    extra_img = fetched[13] if extra_card else None

    canvas_w = CARD_W * 7
    canvas_h = CARD_H * 2
    canvas = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 255))

    # Row 1 — 7 commons
    for i, img in enumerate(images[:7]):
        canvas.paste(img, (i * CARD_W, 0))

    # Row 2 left — 3 uncommons
    for i, img in enumerate(images[7:10]):
        canvas.paste(img, (i * CARD_W, CARD_H))

    # Row 2 center — extra card
    if extra_img:
        canvas.paste(extra_img, (3 * CARD_W, CARD_H))

    # Row 2 right — foil + 2 rares (right-aligned in the 7-card-wide row)
    for i, img in enumerate(images[10:13]):
        x = (4 + i) * CARD_W
        canvas.paste(img, (x, CARD_H))

    buf = io.BytesIO()
    canvas.save(buf, format="PNG")
    buf.seek(0)
    return discord.File(buf, filename="pack.png")

async def build_precon_pack_image(pack: list) -> discord.File:
    """
    Layout (28 cards):
      Row 1: cards 0-6   (7 cards)
      Row 2: cards 7-13  (7 cards)
      Row 3: cards 14-20 (7 cards)
      Row 4: cards 21-27 (7 cards)
    """
    urls = [c["media"]["image_url"] for c in pack]

    async with aiohttp.ClientSession() as session:
        fetched = await asyncio.gather(*[fetch_image(session, u) for u in urls])

    images = list(fetched[:28])

    canvas_w = CARD_W * 7
    canvas_h = CARD_H * 4
    canvas = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 255))

    for row in range(4):
        for col in range(7):
            idx = row * 7 + col
            if idx < len(images):
                canvas.paste(images[idx], (col * CARD_W, row * CARD_H))

    buf = io.BytesIO()
    canvas.save(buf, format="PNG")
    buf.seek(0)
    return discord.File(buf, filename="precon.png")


async def get_cards_by_set_and_type(session, set_id: str, card_type: str) -> list:
    url = "https://api.riftcodex.com/cards"
    params = {"size": 50, "page": 1}
    all_cards = []

    while True:
        async with session.get(url, params=params) as resp:
            data = await resp.json()

        for card in data["items"]:
            if (card["set"]["set_id"] == set_id and
                    card["classification"]["type"] == card_type):
                all_cards.append(card)

        if data["page"] >= data["pages"]:
            break
        params["page"] += 1

    return all_cards

async def get_cards_by_set_and_rarity(session, set_id: str, rarity: str) -> list:
    url = "https://api.riftcodex.com/cards"
    params = {"size": 50, "page": 1}
    all_cards = []

    while True:
        async with session.get(url, params=params) as resp:
            data = await resp.json()

        for card in data["items"]:
            if (card["set"]["set_id"] == set_id and
                    card["classification"]["rarity"] == rarity):
                all_cards.append(card)

        if data["page"] >= data["pages"]:
            break
        params["page"] += 1

    return all_cards

async def setup(bot):
        await bot.add_cog(Quests(bot)) 

class Quests(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        print('Bot is online.')
        await get_all_cards()  # Warm the card cache on startup

    @commands.Cog.listener()
    async def on_connect(self):
        print('Bot is connected.')

    # Hello command.
    @commands.command(name='hello', aliases = ['hi', 'heya', 'hihi', 'Hello', 'HELLO', 'hai'])
    async def hello(self, ctx):
        await self._register_profile(ctx.author)
        await ctx.send(f"Hello, {ctx.author.mention}!")

    ''' # Hello command.
    @commands.command()
    async def hello(self, ctx):
        await self._register_profile(ctx.author)
        await ctx.send(f"Hello, {ctx.author.mention}!") '''

    # Goodbye command.
    @commands.command(name='bye', aliases = ['Bye', 'byebye', 'BYE', 'bai', 'baibai'])
    async def bye(self, ctx):
        await self._register_profile(ctx.author)
        await ctx.send(f'Bye, {ctx.author.mention}!')

    # Thanks command.
    @commands.command(name='thanks', aliases = ['ty', 'Thanks', 'TY'])
    async def thanks(self, ctx):
        await self._register_profile(ctx.author)
        await ctx.send(f'You\'re welcome, {ctx.author.mention}! ^^')

    # Good morning command 
    # TODO: Need to check if time is before 12 pm in the person's timezone
    @commands.command(name='goodmorning', aliases = ['gm', 'GM'])
    @cooldown(1, 57600, BucketType.user)
    async def goodmorning(self, ctx):
        await self._register_profile(ctx.author)
        #curr_time = datetime.now()
        #curr_time_str = curr_time.strftime("%H:%M:%S")
        #print("Current Time =", curr_time_str)
        target = ctx.author
        curr_xp = db.record("SELECT exp FROM profiles WHERE user_id=?", target.id)[0]
        db.execute("UPDATE profiles SET exp = ? WHERE user_id=?", (curr_xp + 10), target.id)
        gm_statement = random.choice(good_morning_roulette)
        await ctx.send(f'{ctx.author.mention} ' + gm_statement)

    # Good night command
    # TODO:  Need to check if time is before 12 am in the person's timezone
    @commands.command(name='goodnight', aliases = ['gn', 'GN'])
    @cooldown(1, 57600, BucketType.user)
    async def goodnight(self, ctx):
        await self._register_profile(ctx.author)
        #print(ctx.message.created_at)
        target = ctx.author
        curr_xp = db.record("SELECT exp FROM profiles WHERE user_id=?", target.id)[0]
        db.execute("UPDATE profiles SET exp = ? WHERE user_id=?", (curr_xp + 10), target.id)
        gn_statement = random.choice(good_night_roulette)
        await ctx.send(f'{ctx.author.mention} ' + gn_statement)

    # Focused work start command.
    # TODO: bank for 2 hours of focused work, can ping start
    #@commands.command(name='focusedworkstart', aliases = ['fwstart', 'Focusedworkstart'])
    #async def quest(self, ctx): 
        #return

    # Focused work stop command.
    # TODO: bank for 2 hours of focused work, can ping stop
    #@commands.command(name='focusedwork', aliases = ['fwstop', 'Focusedworkstop'])
    #async def quest(self, ctx): 
        #return

    # Quest command.
    # TODO: make cd reset at a common time (user's time)
    @commands.command(name='quest')
    @cooldown(1, 86400, BucketType.user)
    async def quest(self, ctx, type: Optional[str]): 
        await self._register_profile(ctx.author)
        target = ctx.author
        final_quests = []

        if (type == 'easy'):
            final_quests = make_quests(0)
        elif (type == 'hard'):
            final_quests = make_quests(2)
        else: 
            final_quests = make_quests(1)

        quest_statement = make_quest_statement(final_quests[0], final_quests[1])
        quest_db_statement = make_quest_db_entry(final_quests[0])
        db.execute("UPDATE profiles SET current_quest_exp = ? WHERE user_id=?", final_quests[1], target.id)
        #db.execute("UPDATE profiles SET has_taken_quest = ? WHERE user_id=?", 1, target.id)
        db.execute("UPDATE profiles SET current_quest = ? WHERE user_id=?", quest_db_statement, target.id)
        db.commit()
        await ctx.send(f'{ctx.author.mention}\n' + quest_statement)

    # Updates the db if the user has completed their quest. 
    # TODO: different message if hasnt taken a quest yet that day vs has + trying to complete again
    @commands.command(name='complete')
    async def complete(self, ctx): 
        await self._register_profile(ctx.author)
        target = ctx.author
        curr_xp = db.record("SELECT exp FROM profiles WHERE user_id=?", target.id)[0]
        curr_quest_xp = db.record("SELECT current_quest_exp FROM profiles WHERE user_id=?", target.id)[0]       
        if (curr_quest_xp == None):
            await ctx.send("Can't do that. You've submitted this quest already!")
            return
        db.execute("UPDATE profiles SET exp = ? WHERE user_id=?", (curr_quest_xp + curr_xp), target.id)
        db.execute("UPDATE profiles SET current_quest = ? WHERE user_id=?", None, target.id)
        db.execute("UPDATE profiles SET current_quest_exp = ? WHERE user_id=?", None, target.id)
        db.commit()
        await self._check_level(ctx)
        await ctx.send("Okay! Here are your rewards: " + str(curr_quest_xp) + "XP.")

    # Command to generate a riftbound pack.
    @commands.command(name='generateriftboundpack', aliases = ['riftpack', 'riftboundpack'])
    async def gen_riftbound(self, ctx, type: Optional[str]): 
        await self._register_profile(ctx.author)
        set_id = 'OGN' if type == 'origins' else 'SFD'
        pack = await make_pack(set_id)
        pack_image = await build_pack_image(pack)
        await ctx.send(file=pack_image)


    PRECONS = [
        # Irelia
        "SFD-195-1 SFD-220-1 SFD-124-1 SFD-034-1 SFD-036-1 SFD-045-1 SFD-130-1 SFD-038-1 SFD-039-1 SFD-133-1 SFD-048-1 SFD-125-1 SFD-137-1 SFD-141-1 SFD-127-1 OGN-042-1 OGN-042-1 OGN-042-1 OGN-042-1 OGN-042-1 OGN-042-1 OGN-166-1 OGN-166-1 OGN-166-1 OGN-166-1 OGN-166-1 OGN-166-1",
        # Jax
        "SFD-193-1 SFD-213-1 SFD-033-1 SFD-040-1 SFD-041-1 SFD-042-1 SFD-095-1 SFD-098-1 SFD-102-1 SFD-107-1 SFD-037-1 SFD-093-1 SFD-054-1 SFD-092-1 SFD-035-1 OGN-042-1 OGN-042-1 OGN-042-1 OGN-042-1 OGN-042-1 OGN-042-1 OGN-126-1 OGN-126-1 OGN-126-1 OGN-126-1 OGN-126-1 OGN-126-1",
        # Rek'Sai
        "SFD-187-1 SFD-217-1 SFD-003-1 SFD-004-1 SFD-018-1 SFD-151-1 SFD-159-1 SFD-006-1 SFD-010-1 SFD-015-1 SFD-156-1 SFD-157-1 SFD-161-1 SFD-164-1 SFD-170-1 OGN-007-1 OGN-007-1 OGN-007-1 OGN-007-1 OGN-007-1 OGN-007-1 OGN-214-1 OGN-214-1 OGN-214-1 OGN-214-1 OGN-214-1 OGN-214-1",
        # Lucian
        "SFD-183-1 SFD-218-1 SFD-009-1 SFD-097-1 SFD-108-1 SFD-001-1 SFD-007-1 SFD-011-1 SFD-016-1 SFD-095-1 SFD-099-1 SFD-096-1 SFD-107-1 SFD-113-1 SFD-002-1 OGN-007-1 OGN-007-1 OGN-007-1 OGN-007-1 OGN-007-1 OGN-007-1 OGN-126-1 OGN-126-1 OGN-126-1 OGN-126-1 OGN-126-1 OGN-126-1",
        # Renata
        "SFD-201-1 SFD-214-1 SFD-063-1 SFD-064-1 SFD-069-1 SFD-155-1 SFD-162-1 SFD-070-1 SFD-074-1 SFD-154-1 SFD-072-1 SFD-171-1 SFD-158-1 SFD-165-1 SFD-152-1 OGN-089-1 OGN-089-1 OGN-089-1 OGN-089-1 OGN-089-1 OGN-089-1 OGN-214-1 OGN-214-1 OGN-214-1 OGN-214-1 OGN-214-1 OGN-214-1",
        # Ezreal
        "SFD-199-1 SFD-215-1 SFD-122-1 SFD-124-1 SFD-066-1 SFD-069-1 SFD-129-1 SFD-138-1 SFD-067-1 SFD-070-1 SFD-078-1 SFD-126-1 SFD-077-1 SFD-082-1 SFD-132-1 OGN-089-1 OGN-089-1 OGN-089-1 OGN-089-1 OGN-089-1 OGN-089-1 OGN-166-1 OGN-166-1 OGN-166-1 OGN-166-1 OGN-166-1 OGN-166-1",
    ]
    YONE = "SFD-116-1"

    # Command to generate a sealed pool (1 precon + 5 packs).
    @commands.command(name='sealed')
    async def gen_sealed(self, ctx, type: Optional[str]):
        await self._register_profile(ctx.author)
        set_id = 'OGN' if type == 'origins' else 'SFD'
        packs = await asyncio.gather(*[make_pack(set_id) for _ in range(5)])

        precon_code = random.choice(self.PRECONS) + " " + self.YONE
        all_cards = await get_all_cards()
        precon_pack = code_to_cards(all_cards, precon_code)

        precon_image = build_precon_pack_image(precon_pack)
        other_images = [build_pack_image(pack) for pack in packs]
        images = await asyncio.gather(precon_image, *other_images)

        card_codes = []
        for pack in (packs + [precon_pack]):
            for card in pack:
                card_codes.append(clean_card_code(card["public_code"]))
        export_code = " ".join(card_codes)
        await ctx.send(f"{ctx.author.mention} Here's your sealed pool!\nCode: {export_code}", files=list(images))

    # Registers the user if they don't have a profile. Otherwise, does nothing.
    async def _register_profile(self, user):
        if db.record("SELECT * FROM profiles WHERE user_id = ?", user.id) == None:
            db.execute("INSERT INTO profiles (user_id, display_name) VALUES (?, ?)", user.id, user.display_name)
            db.commit()

    # Checks level for levelups.
    async def _check_level(self, ctx):
        print("Checking level")
        curr_level = db.record("SELECT level FROM profiles WHERE user_id = ?", ctx.author.id)[0]
        curr_xp = db.record("SELECT exp FROM profiles WHERE user_id = ?", ctx.author.id)[0]
        needed_xp = 1000 * math.log(curr_level + 1, 2)
        #print(f"curr_xp: {curr_xp}")
        #print(f"needed_xp: {needed_xp}")
        xp_left = curr_xp - needed_xp
        #print(f"xp_left: {xp_left}")
        if xp_left > 0:
            db.execute("UPDATE profiles SET level = level + 1 WHERE user_id = ?", ctx.author.id)
            db.execute("UPDATE profiles SET exp = ? WHERE user_id = ?", xp_left, ctx.author.id)
            db.commit()
            new_level = db.record("SELECT level FROM profiles WHERE user_id = ?", ctx.author.id)[0]
            message = "Congratulations! You are now level " + str(new_level) + "!"
            await ctx.send(message)
    
    # CD error message if user attempts to ping for multiple quests in a day.
    @quest.error
    async def on_quest_error(self, ctx, error):
        if isinstance(error, commands.CommandOnCooldown):
            remaining_time = str(timedelta(seconds=int(error.retry_after)))
            await ctx.send(f'{ctx.author.mention} Try again in ' + str(remaining_time + '.'))
            #embed = discord.Embed(title="Cooldown Alert!", description=f'{ctx.author.mention}, you can use this command again in ' + str(remaining_time), color=0xE74C3C)
            #await ctx.send(embed=embed)

    # CD error message if user attempts to ping for multiple quests in a day.
    @goodmorning.error
    async def on_quest_error(self, ctx, error):
        if isinstance(error, commands.CommandOnCooldown):
            gm_cd_statement = random.choice(gm_cd_roulette)
            await ctx.send(f'{ctx.author.mention} ' + gm_cd_statement)

    # CD error message if user attempts to ping for multiple quests in a day.
    @goodnight.error
    async def on_quest_error(self, ctx, error):
        if isinstance(error, commands.CommandOnCooldown):
            gn_cd_statement = random.choice(gn_cd_roulette)
            await ctx.send(f'{ctx.author.mention} ' + gn_cd_statement)