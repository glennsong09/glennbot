import discord
import random
import aiohttp
import asyncio
import io
import hashlib
import time
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

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
    """Normalize a card code to set-number form (e.g. SFD-195-1 or unl-189-219 -> SFD-195 / unl-189)."""
    if "/" in code:
        code = code.split("/")[0]
    parts = code.strip().split("-")
    # Strip trailing numeric-only segment (copy count or set size)
    if len(parts) >= 3 and parts[-1].isdigit():
        parts = parts[:-1]
    return "-".join(parts)


def code_to_card(all_cards: list, code: str) -> dict:
    """Convert a card code to a card dictionary."""
    target = clean_card_code(code).lower()
    return next((c for c in all_cards if clean_card_code(c["riftbound_id"]).lower() == target), None)


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
# Pack assembly  (type: OGN = origins, SFD = spiritforged, UNL = unleashed)
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

    runes = ([c for c in set_cards if c["classification"]["type"] == "Rune"
                and c["classification"]["rarity"] == "Common"]
             or [c for c in all_cards if c["classification"]["type"] == "Rune"
                and c["classification"]["rarity"] == "Common"])
    tokens = ([c for c in set_cards if c["classification"]["supertype"] == "Token"]
              or [c for c in all_cards if c["classification"]["supertype"] == "Token"])
    alt_art_runes = ([c for c in set_cards if (c["classification"]["type"] == "Rune"
                        and c["metadata"]["alternate_art"] == True)]
                     or [c for c in all_cards if (c["classification"]["type"] == "Rune"
                        and c["metadata"]["alternate_art"] == True)])

    cards = []

    # 7 commons
    while len(cards) < 7:
        cards.append(random.choice(commons))

    # 3 uncommons
    while len(cards) < 10:
        cards.append(random.choice(uncommons))
    
    # 11th card is foil slot
    luck = random.random()
    print("foil", luck)
    if luck < 73 / 144:
        curr_card = random.choice(commons)
    elif luck < (73 + 44) / 144:
        curr_card = random.choice(uncommons)
    else:
        curr_card = random.choice(rares)
    #(curr_card)
    cards.append(curr_card)
    
    # 12th card is always rare
    curr_card = random.choice(rares)
    #print(curr_card)
    cards.append(curr_card)

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
    #print(curr_card)
    cards.append(curr_card)

    # 14th card is always token or rune
    luck = random.random()
    print("rune/tokens", luck)
    if luck < (61 / 96):
        curr_card = random.choice(runes)
    elif luck < (61 + 32) / 96:
        curr_card = random.choice(tokens)
    else:
        curr_card = random.choice(alt_art_runes)
    #print(curr_card)
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
    """Build a compact grid image for any number of cards (7 per row)."""
    urls = [c["media"]["image_url"] for c in pack]

    async with aiohttp.ClientSession() as session:
        fetched = await asyncio.gather(*[fetch_image(session, u) for u in urls])

    images = list(fetched)
    n = len(images)
    cols = min(n, 7)
    rows = (n + 6) // 7

    canvas = Image.new("RGBA", (CARD_W * cols, CARD_H * rows), (0, 0, 0, 0))
    for i, img in enumerate(images):
        canvas.paste(img, ((i % 7) * CARD_W, (i // 7) * CARD_H))

    buf = io.BytesIO()
    canvas.save(buf, format="PNG")
    buf.seek(0)
    return discord.File(buf, filename="pack.png")


async def build_draft_pack_image(pack: list) -> discord.File:
    """Like build_pack_image but draws a numbered label below each card for draft pick selection."""
    urls = [c["media"]["image_url"] for c in pack]

    async with aiohttp.ClientSession() as session:
        fetched = await asyncio.gather(*[fetch_image(session, u) for u in urls])

    images = list(fetched)
    n = len(images)
    cols = min(n, 7)
    rows = (n + 6) // 7
    label_h = int(CARD_H * 0.14)
    cell_h = CARD_H + label_h

    canvas = Image.new("RGBA", (CARD_W * cols, cell_h * rows), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    try:
        font = ImageFont.truetype("arial.ttf", size=int(label_h * 0.65))
    except Exception:
        font = ImageFont.load_default()

    for i, img in enumerate(images):
        col = i % 7
        row = i // 7
        x = col * CARD_W
        y = row * cell_h
        canvas.paste(img, (x, y))

        label = str(i + 1)
        lx, ly = x, y + CARD_H
        draw.rectangle([lx, ly, lx + CARD_W, ly + label_h], fill=(20, 20, 20, 230))
        bbox = draw.textbbox((0, 0), label, font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        draw.text((lx + (CARD_W - text_w) // 2, ly + (label_h - text_h) // 2), label, fill=(220, 200, 140, 255), font=font)

    buf = io.BytesIO()
    canvas.save(buf, format="PNG")
    buf.seek(0)
    return discord.File(buf, filename="draft_pack.png")


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
# Converters
# ---------------------------------------------------------------------------

class DeckTypeConverter(commands.Converter):
    async def convert(self, _ctx, argument):
        if argument.lower() in ('origins', 'spiritforged', 'unleashed'):
            return argument.lower()
        raise commands.BadArgument()


# ---------------------------------------------------------------------------
# Draft helpers
# ---------------------------------------------------------------------------

class DraftBarrier:
    """Blocks until all expected players have signalled ready."""
    def __init__(self, player_ids: list):
        self._ids = set(player_ids)
        self._ready: set = set()
        self._event = asyncio.Event()

    def reset(self):
        self._ready.clear()
        self._event.clear()

    async def player_ready(self, user_id: int):
        self._ready.add(user_id)
        if self._ready >= self._ids:
            self._event.set()

    async def wait(self):
        await self._event.wait()


PACK_ASSET = Path(__file__).parent.parent / "assets" / "sfd_pack.jpg"


class PackSelectView(discord.ui.View):
    def __init__(self, barrier: DraftBarrier, user_id: int, packs: dict, choices: dict):
        super().__init__(timeout=600)
        self.barrier = barrier
        self.user_id = user_id
        self.packs = packs      # {1: pack1, 2: pack2, 3: pack3}
        self.choices = choices  # {user_id: pack_num}, shared across all views

    async def _pick(self, interaction: discord.Interaction, pack_num: int):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This isn't your choice to make!", ephemeral=True)
            return
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(content=f"You chose Pack {pack_num}!", view=self)
        pack_image = await build_draft_pack_image(self.packs[pack_num][:13])
        await interaction.followup.send(file=pack_image)
        self.choices[self.user_id] = pack_num
        await self.barrier.player_ready(self.user_id)

    @discord.ui.button(label="Pack 1", style=discord.ButtonStyle.primary)
    async def pack1(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await self._pick(interaction, 1)

    @discord.ui.button(label="Pack 2", style=discord.ButtonStyle.primary)
    async def pack2(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await self._pick(interaction, 2)

    @discord.ui.button(label="Pack 3", style=discord.ButtonStyle.primary)
    async def pack3(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await self._pick(interaction, 3)


class CardPickView(discord.ui.View):
    def __init__(self, barrier: DraftBarrier, user_id: int, cards: list, player_picks: dict):
        super().__init__(timeout=600)
        self.barrier = barrier
        self.user_id = user_id
        self.cards = cards
        self.player_picks = player_picks  # {user_id: [card, ...]}, shared across all views

        for i, card in enumerate(cards):
            name = card.get('name', f'Card {i + 1}')
            label = f"{i + 1} - {name}"[:80]  # Discord button label max is 80 chars
            btn = discord.ui.Button(label=label, style=discord.ButtonStyle.secondary, row=i // 5)
            btn.callback = self._make_pick_callback(i)
            self.add_item(btn)

    def _make_pick_callback(self, idx: int):
        async def callback(interaction: discord.Interaction):
            if interaction.user.id != self.user_id:
                await interaction.response.send_message("This isn't your pick!", ephemeral=True)
                return
            for child in self.children:
                child.disabled = True
            card = self.cards[idx]
            card_name = card.get('name', f'Card {idx + 1}')
            await interaction.response.edit_message(
                content=f"You picked **{card_name}**! Waiting for other players...", view=self
            )
            self.player_picks[self.user_id].append(card)
            await self.barrier.player_ready(self.user_id)
        return callback


class ReadyView(discord.ui.View):
    def __init__(self, barrier: DraftBarrier, user_id: int):
        super().__init__(timeout=600)
        self.barrier = barrier
        self.user_id = user_id

    @discord.ui.button(label="Ready", style=discord.ButtonStyle.green)
    async def ready(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This isn't your button!", ephemeral=True)
            return
        button.disabled = True
        await interaction.response.edit_message(content="You're ready! Waiting for other players...", view=self)
        await self.barrier.player_ready(self.user_id)


# ---------------------------------------------------------------------------
# Riftbound cog
# ---------------------------------------------------------------------------

class Riftbound(commands.Cog):
    # Each set entry has a list of precon deck codes and the companion card appended to each.
    # To add a new set: add a new key matching its set_id, fill in precons and companion.
    PRECONS = {
        'SFD': {
            'companion': "SFD-116-1",  # Yone
            'decks': [
                # Irelia
                "SFD-195-1 SFD-220-1 SFD-124-1 SFD-034-1 SFD-036-1 SFD-045-1 SFD-130-1 SFD-038-1 SFD-039-1 SFD-133-1 SFD-048-1 SFD-125-1 SFD-137-1 SFD-141-1 SFD-127-1 OGN-042-1 OGN-042-1 OGN-042-1 OGN-042-1 OGN-042-1 OGN-042-1 OGN-166-1 OGN-166-1 OGN-166-1 OGN-166-1 OGN-166-1 OGN-166-1",
                # Jax
                "SFD-193-1 SFD-213-1 SFD-033-1 SFD-040-1 SFD-041-1 SFD-042-1 SFD-095-1 SFD-098-1 SFD-102-1 SFD-107-1 SFD-037-1 SFD-093-1 SFD-054-1 SFD-092-1 SFD-035-1 OGN-042-1 OGN-042-1 OGN-042-1 OGN-042-1 OGN-042-1 OGN-042-1 OGN-126-1 OGN-126-1 OGN-126-1 OGN-126-1 OGN-126-1 OGN-126-1",
                # Rek'Sai
                "SFD-187-1 SFD-217-1 SFD-003-1 SFD-004-1 SFD-018-1 SFD-151-1 SFD-159-1 SFD-006-1 SFD-010-1 SFD-015-1 SFD-156-1 SFD-157-1 SFD-161-1 SFD-164-1 SFD-170-1 OGN-007-1 OGN-007-1 OGN-007-1 OGN-007-1 OGN-007-1 OGN-007-1 OGN-214-1 OGN-214-114-1 OGN-214-1 OGN-214- OGN-214-1 OGN-21",
                # Lucian
                "SFD-183-1 SFD-218-1 SFD-009-1 SFD-097-1 SFD-108-1 SFD-001-1 SFD-007-1 SFD-011-1 SFD-016-1 SFD-095-1 SFD-099-1 SFD-096-1 SFD-107-1 SFD-113-1 SFD-002-1 OGN-007-1 OGN-007-1 OGN-007-1 OGN-007-1 OGN-007-1 OGN-007-1 OGN-126-1 OGN-126-1 OGN-126-1 OGN-126-1 OGN-126-1 OGN-126-1",
                # Renata
                "SFD-201-1 SFD-214-1 SFD-063-1 SFD-064-1 SFD-069-1 SFD-155-1 SFD-162-1 SFD-070-1 SFD-074-1 SFD-154-1 SFD-072-1 SFD-171-1 SFD-158-1 SFD-165-1 SFD-152-1 OGN-089-1 OGN-089-1 OGN-089-1 OGN-089-1 OGN-089-1 OGN-089-1 OGN-214-1 OGN-214-1 OGN-214-1 OGN-214-1 OGN-214-1 OGN-214-1",
                # Ezreal
                "SFD-199-1 SFD-215-1 SFD-122-1 SFD-124-1 SFD-066-1 SFD-069-1 SFD-129-1 SFD-138-1 SFD-067-1 SFD-070-1 SFD-078-1 SFD-126-1 SFD-077-1 SFD-082-1 SFD-132-1 OGN-089-1 OGN-089-1 OGN-089-1 OGN-089-1 OGN-089-1 OGN-089-1 OGN-166-1 OGN-166-1 OGN-166-1 OGN-166-1 OGN-166-1 OGN-166-1",
            ],
        },
        'UNL': {
            'companion': "UNL-169-1",  # Ashe
            'decks': [
                # Khazix
                "UNL-201-1 UNL-143-1 UNL-136-1 UNL-092-1 UNL-095-1 UNL-124-1 UNL-127-1 UNL-101-1 UNL-102-1 UNL-096-1 UNL-135-1 UNL-097-1 UNL-129-1 UNL-126-1 UNL-124-1 OGN-166-1 OGN-166-1 OGN-166-1 OGN-166-1 OGN-166-1 OGN-166-1 OGN-126-1 OGN-126-1 OGN-126-1 OGN-126-1 OGN-126-1 OGN-126-1",
                # Yi
                "UNL-191-1 UNL-113-1 UNL-031-1 UNL-039-1 UNL-094-1 UNL-107-1 UNL-040-1 UNL-038-1 UNL-043-1 UNL-047-1 UNL-108-1 UNL-034-1 UNL-091-1 UNL-100-1 UNL-213-1 OGN-042-1 OGN-042-1 OGN-042-1 OGN-042-1 OGN-042-1 OGN-042-1 OGN-126-1 OGN-126-1 OGN-126-1 OGN-126-1 OGN-126-1 OGN-126-1",
                # Jhin
                "UNL-181-1 UNL-022-1 UNL-061-1 UNL-074-1 UNL-065-1 UNL-013-1 UNL-009-1 UNL-004-1 UNL-073-1 UNL-062-1 UNL-017-1 UNL-064-1 UNL-069-1 UNL-005-1 UNL-211-1 OGN-007-1 OGN-007-1 OGN-007-1 OGN-007-1 OGN-007-1 OGN-007-1 OGN-089-1 OGN-089-1 OGN-089-1 OGN-089-1 OGN-089-1 OGN-089-1",
                # Diana
                "UNL-197-1 UNL-079-1 UNL-134-1 UNL-131-1 UNL-065-1 UNL-121-1 UNL-071-1 UNL-063-1 UNL-125-1 UNL-072-1 UNL-128-1 UNL-122-1 UNL-130-1 UNL-066-1 UNL-205-1 OGN-089-1 OGN-089-1 OGN-089-1 OGN-089-1 OGN-089-1 OGN-089-1 OGN-166-1 OGN-166-1 OGN-166-1 OGN-166-1 OGN-166-1 OGN-166-1",
                # Vi
                "UNL-187-1 UNL-176-1 UNL-153-1 UNL-002-1 UNL-007-1 UNL-152-1 UNL-155-1 UNL-006-1 UNL-163-1 UNL-017-1 UNL-001-1 UNL-160-1 UNL-012-1 UNL-018-1 UNL-218-1 OGN-007-1 OGN-007-1 OGN-007-1 OGN-007-1 OGN-007-1 OGN-007-1 OGN-214-1 OGN-214-1 OGN-214-1 OGN-214-1 OGN-214-1 OGN-214-1",
                # Ivern
                "UNL-195-1 UNL-051-1 UNL-046-1 UNL-032-1 UNL-036-1 UNL-159-1 UNL-154-1 UNL-155-1 UNL-156-1 UNL-033-1 UNL-166-1 UNL-044-1 UNL-160-1 UNL-167-1 UNL-217-1 OGN-042-1 OGN-042-1 OGN-042-1 OGN-042-1 OGN-042-1 OGN-042-1 OGN-214-1 OGN-214-1 OGN-214-1 OGN-214-1 OGN-214-1 OGN-214-1",
            ],
        },
    }

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
    @app_commands.describe(deck_type="Pack type: origins, spiritforged, or unleashed (default)")
    @app_commands.choices(deck_type=[
        app_commands.Choice(name="Origins", value="origins"),
        app_commands.Choice(name="Spiritforged", value="spiritforged"),
        app_commands.Choice(name="Unleashed", value="unleashed"),
    ])
    async def riftbound_open(self, ctx: commands.Context, deck_type: Optional[str] = None):
        """Open a single Riftbound pack. Use !riftbound open or /riftbound open."""
        await ctx.defer()
        await self._register_profile(ctx.author)
        set_id = {'origins': 'OGN', 'spiritforged': 'SFD', 'unleashed': 'UNL'}.get(deck_type, 'UNL')
        pack = await make_pack(set_id)
        pack_image = await build_pack_image(pack)
        await ctx.send(file=pack_image)

    @riftbound.command(name="sealed", description="Generate a sealed pool")
    @app_commands.describe(deck_type="Pack type: origins, spiritforged, or unleashed (default)")
    @app_commands.choices(deck_type=[
        app_commands.Choice(name="Origins", value="origins"),
        app_commands.Choice(name="Spiritforged", value="spiritforged"),
        app_commands.Choice(name="Unleashed", value="unleashed"),
    ])
    async def riftbound_sealed(self, ctx: commands.Context, deck_type: Optional[str] = None):
        """Generate a sealed pool. Use !riftbound sealed or /riftbound sealed."""
        await ctx.defer()
        await self._register_profile(ctx.author)
        set_id = {'origins': 'OGN', 'spiritforged': 'SFD', 'unleashed': 'UNL'}.get(deck_type, 'UNL')
        packs = await asyncio.gather(*[make_pack(set_id) for _ in range(5)])

        precon_set = self.PRECONS.get(set_id, self.PRECONS['SFD'])
        precon_code = random.choice(precon_set['decks']) + " " + precon_set['companion']
        all_cards = await get_all_cards()
        precon_pack = code_to_cards(all_cards, precon_code)

        precon_image = build_precon_pack_image(precon_pack)
        other_images = [build_pack_image(pack) for pack in packs]
        images = await asyncio.gather(precon_image, *other_images)

        card_codes = []
        for pack in (packs + [precon_pack]):
            for card in pack:
                card_codes.append(clean_card_code(card["riftbound_id"]).upper() + "-1")
        export_code = " ".join(card_codes)
        await ctx.send(f"{ctx.author.mention} Here's your sealed pool!\nCode: {export_code}", files=list(images))

    @riftbound.command(name="draft", description="Start a draft game", with_app_command=False)
    async def riftbound_draft(self, ctx: commands.Context, deck_type: Optional[DeckTypeConverter] = None, *users: discord.Member):
        """Start a draft. Use !riftbound draft [origins|spiritforged] @player1 @player2 ..."""
        await self._register_profile(ctx.author)
        set_id = {'origins': 'OGN', 'spiritforged': 'SFD', 'unleashed': 'UNL'}.get(deck_type, 'UNL')
        players = list(users)

        # Ensure there are players mentioned
        if not players:
            await ctx.send("Please mention at least one player!")
            return
        
        # Ensure none of the players are bots, so we don't try to DM them and fail the draft start
        for player in players:
            if player.bot:
                await ctx.send(f"Cannot include bot {player.mention} in draft.")
                return
        
        # Ensure all players have DMs open
        for player in players:
            try:
                msg = await player.send(f"We are about to begin Riftbound draft, {player.mention}.")
            except discord.Forbidden:
                await ctx.send(f"Could not DM {player.mention} (DMs disabled)") 
                return

        # If we got here, all players are valid and have DMs open
        await ctx.send(f"Draft started! Generating packs for {', '.join(p.mention for p in players)}...")

        # Generate 3 packs per player
        player_packs = {}
        for player in players:
            packs = await asyncio.gather(*[make_pack(set_id) for _ in range(3)])
            player_packs[player.id] = {i + 1: pack for i, pack in enumerate(packs)}


        # Round 1: players choose which pack to open
        pack_choices = {}
        barrier = DraftBarrier([p.id for p in players])
        for player in players:
            pack_files = [discord.File(PACK_ASSET, filename=f"pack{i+1}.jpg") for i in range(3)]
            view = PackSelectView(barrier, player.id, player_packs[player.id], pack_choices)
            await player.send("Which pack do you want to open first?", files=pack_files, view=view)

        await ctx.send("Packs sent! Waiting for all players to choose a pack...")
        await barrier.wait()

        await ctx.send("All players chose a pack! Waiting for card picks...")

        # Round 1: players pick a card from their chosen pack
        player_picks = {p.id: [] for p in players}
        barrier.reset()
        for player in players:
            pack = list(player_packs[player.id][pack_choices[player.id]])[:13]
            view = CardPickView(barrier, player.id, pack, player_picks)
            await player.send("Pick a card! The numbers match card positions in the image above.", view=view)
        await barrier.wait()
        await ctx.send("All players have made their picks!")

        

        



    async def _register_profile(self, user):
        if db.record("SELECT * FROM profiles WHERE user_id = ?", user.id) == None:
            db.execute("INSERT INTO profiles (user_id, display_name) VALUES (?, ?)", user.id, user.display_name)
            db.commit()


async def setup(bot):
    await bot.add_cog(Riftbound(bot))
