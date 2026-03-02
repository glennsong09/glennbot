import discord
import random
import aiohttp
import asyncio
import io
import hashlib
import time
from pathlib import Path
from PIL import Image

from discord.ext import commands
from discord import app_commands
from typing import Optional
from database import db


# ---------------------------------------------------------------------------
# Cache configuration
# ---------------------------------------------------------------------------

RESIZE_FACTOR = 0.5  # Scale down for faster generation (0.5 = half size)
CACHE_DIR = Path(__file__).parent.parent / "cache" / "card_images"
REFRESH_INTERVAL = 6 * 3600  # 6 hours

_card_cache: Optional[list] = None
_card_cache_time: float = 0


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------

async def _fetch_all_cards_from_api() -> list:
    """Fetch all cards from the API (no cache)."""
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


async def get_all_cards() -> list:
    """Fetch all cards from the API. Results are cached for 6 hours."""
    global _card_cache, _card_cache_time
    now = time.time()
    if _card_cache is not None and (now - _card_cache_time) < REFRESH_INTERVAL:
        return _card_cache
    _card_cache = await _fetch_all_cards_from_api()
    _card_cache_time = now
    return _card_cache


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
    alt_arts = [c for c in showcases if ((c["metadata"]["alternate_art"] == True) 
                    and (c["classification"]["type"] != "Rune"))]
    overnumbered = [
        c for c in showcases
        if c["metadata"]["overnumbered"] == True and c["metadata"]["signature"] == False
    ]

    runes = [c for c in all_cards if c["classification"]["type"] == "Rune" 
                and c["classification"]["rarity"] == "Common"]
    tokens = [c for c in all_cards if (c["classification"]["supertype"] == "Token")]
    alt_art_runes = [c for c in all_cards if ((c["classification"]["type"] == "Rune")
                        and (c["metadata"]["alternate_art"] == True))]

    cards = []

    # 7 commons
    while len(cards) < 7:
        cards.append(random.choice(commons))

    # 3 uncommons
    while len(cards) < 10:
        cards.append(random.choice(uncommons))

    # 1 foil of any rarity
    '''while len(cards) < 11:
        luck = random.randint(1, 2160)
        print("foil", luck)
        if luck == 1:
            curr_card = random.choice(signatures)
        elif luck <= 31:
            curr_card = random.choice(overnumbered)
        elif luck <= 71:
            curr_card = random.choice(alt_arts)
        elif luck <= 251:
            curr_card = random.choice(epics)
        else:
            curr_card = random.choice(rares + uncommons + commons)
        print(curr_card)
        cards.append(curr_card)'''
    
    # 11th card is foil slot
    luck = random.random()
    print("foil", luck)
    if luck < 73 / 144:
        curr_card = random.choice(commons)
    elif luck < (73 + 44) / 144:
        curr_card = random.choice(uncommons)
    else:
        curr_card = random.choice(rares)
    print(curr_card)
    cards.append(curr_card)

    '''# 2 rares or better
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
        cards.append(curr_card)'''
    
    # 12th card is always rare
    curr_card = random.choice(rares)
    print(curr_card)
    cards.append(curr_card)

    '''# 13th card is rare or better
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
    cards.append(curr_card)'''

    # 13th card is always rare or better foil
    luck = random.random()
    print("foil", luck)
    if luck < (91 / 144):
        curr_card = random.choice(rares)
    elif luck < (91 + 35) / 144:
        curr_card = random.choice(epics)
    elif luck < (91 + 35 + 13) / 144:
        curr_card = random.choice(alt_arts)
    elif luck < (91 + 35 + 13 + 4) / 144:
        curr_card = random.choice(overnumbered)
    else:
        curr_card = random.choice(signatures)
    print(curr_card)
    cards.append(curr_card)

    # 14th card is always token or rune
    luck = random.random()
    print("rune/tokens", luck)
    if luck < (61 / 144):
        curr_card = random.choice(runes)
    elif luck < (61 + 32) / 144:
        curr_card = random.choice(tokens)
    else:
        curr_card = random.choice(alt_art_runes)
    print(curr_card)
    cards.append(curr_card)

    print("---")
    return cards


# ---------------------------------------------------------------------------
# Image building
# ---------------------------------------------------------------------------

_BASE_CARD_W, _BASE_CARD_H = 744, 1039
CARD_W = int(_BASE_CARD_W * RESIZE_FACTOR)
CARD_H = int(_BASE_CARD_H * RESIZE_FACTOR)


def _url_to_cache_path(url: str) -> Path:
    """Get the local cache file path for an image URL."""
    key = hashlib.sha256(url.encode()).hexdigest()[:32]
    return CACHE_DIR / f"{key}.png"


def _process_image(data: bytes) -> Image.Image:
    """Load raw image bytes and process to standard card format."""
    img = Image.open(io.BytesIO(data)).convert("RGBA")
    if img.width > img.height:
        img = img.rotate(90, expand=True)
    if img.size != (CARD_W, CARD_H):
        img = img.resize((CARD_W, CARD_H), Image.LANCZOS)
    return img


def _load_from_cache(url: str) -> Optional[Image.Image]:
    """Load a processed image from local cache if it exists."""
    path = _url_to_cache_path(url)
    if path.exists():
        try:
            return Image.open(path).convert("RGBA")
        except Exception:
            return None
    return None


async def fetch_image(session: aiohttp.ClientSession, url: str) -> Image.Image:
    """Fetch card image, using local cache when available."""
    cached = _load_from_cache(url)
    if cached is not None:
        return cached

    async with session.get(url) as resp:
        data = await resp.read()
    img = _process_image(data)

    # Save to cache for next time
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = _url_to_cache_path(url)
    img.save(path, format="PNG")

    return img


async def refresh_all_images() -> int:
    """Fetch all card images and cache them locally. Returns count of images cached."""
    all_cards = await _fetch_all_cards_from_api()
    urls = list({c["media"]["image_url"] for c in all_cards if c.get("media", {}).get("image_url")})

    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    async def download_one(session: aiohttp.ClientSession, url: str) -> bool:
        path = _url_to_cache_path(url)
        try:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return False
                data = await resp.read()
            img = _process_image(data)
            img.save(path, format="PNG")
            return True
        except Exception as e:
            print(f"[riftbound] Failed to cache image {url[:60]}...: {e}")
            return False

    sem = asyncio.Semaphore(20)  # Limit concurrent downloads

    async def limited_download(session: aiohttp.ClientSession, url: str) -> bool:
        async with sem:
            return await download_one(session, url)

    async with aiohttp.ClientSession() as session:
        results = await asyncio.gather(*[limited_download(session, u) for u in urls])

    return sum(1 for r in results if r)


async def refresh_card_data_and_images() -> None:
    """Refresh card data and all card images. Called every 6 hours."""
    global _card_cache, _card_cache_time
    print("[riftbound] Refreshing card data and images...")
    _card_cache = await _fetch_all_cards_from_api()
    _card_cache_time = time.time()
    count = await refresh_all_images()
    print(f"[riftbound] Cached {count} card images")


async def build_pack_image(pack: list) -> discord.File:
    """
    Layout (14 cards):
      Row 1: cards 0-6   (7 commons, left-to-right)
      Row 2: cards 7-9   (3 uncommons, columns 0-2)
             card 10     (foil, column 3)
             cards 11-12 (2 rares, columns 4-5)
             card 13     (token/rune, column 6)
    """
    urls = [c["media"]["image_url"] for c in pack]

    async with aiohttp.ClientSession() as session:
        fetched = await asyncio.gather(*[fetch_image(session, u) for u in urls])

    images = list(fetched)

    canvas_w = CARD_W * 7
    canvas_h = CARD_H * 2
    canvas = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 255))

    for i, img in enumerate(images[:7]):
        canvas.paste(img, (i * CARD_W, 0))

    for i, img in enumerate(images[7:10]):
        canvas.paste(img, (i * CARD_W, CARD_H))

    canvas.paste(images[10], (3 * CARD_W, CARD_H))

    for i, img in enumerate(images[11:13]):
        canvas.paste(img, ((4 + i) * CARD_W, CARD_H))

    canvas.paste(images[13], (6 * CARD_W, CARD_H))

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
        self._refresh_task: Optional[asyncio.Task] = None

    async def _refresh_loop(self) -> None:
        """Background task: refresh card data and images every 6 hours."""
        while True:
            await asyncio.sleep(REFRESH_INTERVAL)  # Sleep first; on_ready does initial refresh
            try:
                await refresh_card_data_and_images()
            except Exception as e:
                print(f"[riftbound] Refresh failed: {e}")

    @commands.Cog.listener()
    async def on_ready(self):
        # Initial refresh: card data + pre-fetch all images
        await refresh_card_data_and_images()
        # Start background refresh every 6 hours
        if self._refresh_task is None or self._refresh_task.done():
            self._refresh_task = asyncio.create_task(self._refresh_loop())

    @commands.hybrid_group(name="riftbound", description="Riftbound card game commands")
    async def riftbound(self, ctx: commands.Context):
        """Riftbound card game commands. Use `open` or `sealed` subcommands."""
        await ctx.send_help(ctx.command)

    @riftbound.command(name="pack", description="Open a Riftbound pack")
    @app_commands.describe(deck_type="Pack type: origins or spiritforged (default)")
    @app_commands.choices(deck_type=[
        app_commands.Choice(name="Origins", value="origins"),
        app_commands.Choice(name="Spiritforged", value="spiritforged"),
    ])
    async def riftbound_open(self, ctx: commands.Context, deck_type: Optional[str] = None):
        """Open a single Riftbound pack. Use !riftbound open or /riftbound open."""
        async with ctx.typing():
            await self._register_profile(ctx.author)
            set_id = 'OGN' if deck_type == 'origins' else 'SFD'
            pack = await make_pack(set_id)
            pack_image = await build_pack_image(pack)
        await ctx.send(file=pack_image)

    @riftbound.command(name="sealed", description="Generate a sealed pool")
    @app_commands.describe(deck_type="Pack type: origins or spiritforged (default)")
    @app_commands.choices(deck_type=[
        app_commands.Choice(name="Origins", value="origins"),
        app_commands.Choice(name="Spiritforged", value="spiritforged"),
    ])
    async def riftbound_sealed(self, ctx: commands.Context, deck_type: Optional[str] = None):
        """Generate a sealed pool. Use !riftbound sealed or /riftbound sealed."""
        async with ctx.typing():
            await self._register_profile(ctx.author)
            set_id = 'OGN' if deck_type == 'origins' else 'SFD'
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
