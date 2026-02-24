import discord
import random
import aiohttp
import asyncio
import io
from aiocache import cached
from aiocache.serializers import PickleSerializer
from PIL import Image

from discord.ext import commands
from typing import Optional
from database import db


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Card lookup utilities
# ---------------------------------------------------------------------------

def clean_card_code(code: str) -> str:
    """Clean a card code string."""
    if "/" in code:
        return code.split("/")[0].strip()
    if code.endswith("-1"):  # SFD-123-1 -> SFD-123
        return code[:-2].strip()
    return code.strip()


def code_to_card(all_cards: list, code: str) -> dict:
    """Convert a card code to a card dictionary."""
    return next((c for c in all_cards if clean_card_code(c["public_code"]) == clean_card_code(code)), None)


def code_to_cards(all_cards: list, code: str) -> list:
    """Convert a card code string to a list of card dictionaries."""
    card_codes = code.split(" ")
    cards = [code_to_card(all_cards, c) for c in card_codes]
    missing = [card_codes[i] for i, c in enumerate(cards) if c is None]
    if missing:
        print(f"[code_to_cards] Could not find cards for codes: {missing}")
    return [c for c in cards if c is not None]


def filter_by_set(cards: list, set_id: str) -> list:
    """Filter cards by set ID."""
    return [c for c in cards if c["set"]["set_id"] == set_id]


def filter_by_rarity(cards: list, rarity: str) -> list:
    """Filter cards by rarity."""
    return [c for c in cards if c["classification"]["rarity"] == rarity]


# ---------------------------------------------------------------------------
# Pack assembly  (type: OGN = origins, SFD = spiritforged)
# ---------------------------------------------------------------------------

async def make_pack(type):
    all_cards = await get_all_cards()
    set_cards = filter_by_set(all_cards, type)

    commons = filter_by_rarity(set_cards, "Common")
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
        cards.append(random.choice(commons))

    # 3 uncommons
    while len(cards) < 10:
        cards.append(random.choice(uncommons))

    # 1 foil of any rarity
    while len(cards) < 11:
        luck = random.randint(1, 720)
        print("foil", luck)
        if luck == 1:
            curr_card = random.choice(signatures)
        elif luck <= 11:
            curr_card = random.choice(overnumbered)
        elif luck <= 71:
            curr_card = random.choice(alt_arts)
        elif luck <= 251:
            curr_card = random.choice(epics)
        else:
            curr_card = random.choice(rares + uncommons + commons)
        print(curr_card)
        cards.append(curr_card)

    # 2 rares or better
    while len(cards) < 13:
        luck = random.randint(1, 720)
        print("rare", luck)
        if luck == 1:
            curr_card = random.choice(signatures)
        elif luck <= 11:
            curr_card = random.choice(overnumbered)
        elif luck <= 71:
            curr_card = random.choice(alt_arts)
        elif luck <= 251:
            curr_card = random.choice(epics)
        else:
            curr_card = random.choice(rares)
        print(curr_card)
        cards.append(curr_card)

    print("---")
    return cards


# ---------------------------------------------------------------------------
# Image building
# ---------------------------------------------------------------------------

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

    for i, img in enumerate(images[:7]):
        canvas.paste(img, (i * CARD_W, 0))

    for i, img in enumerate(images[7:10]):
        canvas.paste(img, (i * CARD_W, CARD_H))

    if extra_img:
        canvas.paste(extra_img, (3 * CARD_W, CARD_H))

    for i, img in enumerate(images[10:13]):
        canvas.paste(img, ((4 + i) * CARD_W, CARD_H))

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


# ---------------------------------------------------------------------------
# Riftbound cog
# ---------------------------------------------------------------------------

class Riftbound(commands.Cog):
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

    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        await get_all_cards()  # Warm the card cache on startup

    @commands.command(name='generateriftboundpack', aliases=['riftpack', 'riftboundpack'])
    async def gen_riftbound(self, ctx, type: Optional[str]):
        await self._register_profile(ctx.author)
        set_id = 'OGN' if type == 'origins' else 'SFD'
        pack = await make_pack(set_id)
        pack_image = await build_pack_image(pack)
        await ctx.send(file=pack_image)

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

    async def _register_profile(self, user):
        if db.record("SELECT * FROM profiles WHERE user_id = ?", user.id) == None:
            db.execute("INSERT INTO profiles (user_id, display_name) VALUES (?, ?)", user.id, user.display_name)
            db.commit()


async def setup(bot):
    await bot.add_cog(Riftbound(bot))
