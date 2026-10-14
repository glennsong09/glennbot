import discord
import random
import re
import functools
import aiohttp
import asyncio
import io
import hashlib
import time
from collections import Counter
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

from discord.ext import commands
from discord import app_commands
from typing import Optional
from database import db


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RESIZE_FACTOR    = 0.5
CACHE_DIR        = Path(__file__).parent.parent / "cache" / "card_images"
REFRESH_INTERVAL = 6 * 3600
RETRY_INTERVAL   = 10 * 60  # after a failed refresh, retry this soon instead of waiting a full interval

# In release order; the last entry is the newest set and the default for all commands
SET_ID_MAP  = {'origins': 'OGN', 'spiritforged': 'SFD', 'unleashed': 'UNL', 'vendetta': 'VEN'}
DEFAULT_SET = list(SET_ID_MAP.values())[-1]

_BASE_CARD_W, _BASE_CARD_H = 744, 1039
CARD_W = int(_BASE_CARD_W * RESIZE_FACTOR)
CARD_H = int(_BASE_CARD_H * RESIZE_FACTOR)

# Pack slot probabilities (pre-computed thresholds)
_FOIL_T    = (73/144, (73+44)/144)
_PREMIUM_T = (91/144, (91+35)/144, (91+35+13)/144, (91+35+13+4)/144)
_RUNE_T    = (61/96, (61+32)/96)

_RE_OVERNUMBERED = re.compile(r"\s*\(Overnumbered\)", re.IGNORECASE)
_RE_ALT_ART      = re.compile(r"\s*\(Alternate Art\)", re.IGNORECASE)
_RE_CARD_ID      = re.compile(r"^[a-z]+-(\d+)([a-z*]?)-(\d+)$", re.IGNORECASE)  # e.g. ven-042a-166
_RE_SPECIAL_ID   = re.compile(r"^[a-z]+-sp\d+-", re.IGNORECASE)                # e.g. ven-sp1-006

# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------

async def _fetch_all_cards_from_api() -> list:
    url     = "https://api.riftcodex.com/cards"
    timeout = aiohttp.ClientTimeout(total=30)

    for attempt in range(3):
        try:
            params, cards = {"size": 50, "page": 1}, []
            async with aiohttp.ClientSession(timeout=timeout) as session:
                while True:
                    async with session.get(url, params=params) as resp:
                        resp.raise_for_status()
                        data = await resp.json()
                    cards.extend(data["items"])
                    if data["page"] >= data["pages"]:
                        break
                    params["page"] += 1
            return cards
        except Exception as e:
            print(f"[riftbound] API fetch attempt {attempt + 1}/3 failed: {e}")
            if attempt < 2:
                await asyncio.sleep(2 ** attempt)

    raise RuntimeError("[riftbound] Failed to fetch cards from API after 3 attempts")


# ---------------------------------------------------------------------------
# Card cache (encapsulates data, staleness, lock, and per-set pool cache)
# ---------------------------------------------------------------------------

class _CardCache:
    def __init__(self):
        self._data:  Optional[list]  = None
        self._time:  float           = 0
        self._lock:  asyncio.Lock    = asyncio.Lock()
        self._pools: dict[str, dict] = {}  # set_id -> precomputed pool lists

    async def get(self) -> list:
        now = time.time()
        if self._data is not None and now - self._time < REFRESH_INTERVAL:
            return self._data
        async with self._lock:
            now = time.time()
            if self._data is not None and now - self._time < REFRESH_INTERVAL:
                return self._data
            await self._load()
        return self._data

    async def _load(self) -> None:
        """Fetch fresh data. If the API is down, keep serving stale data (if any) and retry later."""
        try:
            self._data  = await _fetch_all_cards_from_api()
            self._time  = time.time()
            self._pools = {}
        except RuntimeError:
            if self._data is None:
                raise
            print("[riftbound] Card refresh failed; keeping previously cached card data")
            self._time = time.time() - REFRESH_INTERVAL + RETRY_INTERVAL

    async def get_pools(self, set_id: str) -> dict:
        data = await self.get()
        if set_id not in self._pools:
            self._pools[set_id] = _compute_pools(data, set_id)
        return self._pools[set_id]

    async def refresh(self) -> list:
        async with self._lock:
            await self._load()
        return self._data


_card_cache = _CardCache()


async def get_all_cards() -> list:
    return await _card_cache.get()


# ---------------------------------------------------------------------------
# Card lookup
# ---------------------------------------------------------------------------

def clean_card_code(code: str) -> str:
    if "/" in code:
        code = code.split("/")[0]
    parts = code.strip().split("-")
    if len(parts) >= 3 and parts[-1].isdigit():
        parts = parts[:-1]
    return "-".join(parts)


def code_to_cards(all_cards: list, code: str) -> list:
    lookup = {clean_card_code(c["riftbound_id"]).lower(): c for c in all_cards}
    result, missing = [], []
    for raw in code.split():
        card = lookup.get(clean_card_code(raw).lower())
        if card:
            result.append(card)
        else:
            missing.append(raw)
    if missing:
        print(f"[code_to_cards] Missing: {missing}")
    return result


def _by_set(cards: list, set_id: str) -> list:
    return [c for c in cards if c["set"]["set_id"] == set_id]


def _by_rarity(cards: list, rarity: str) -> list:
    return [c for c in cards if c["classification"]["rarity"] == rarity]


# ---------------------------------------------------------------------------
# Pack assembly
# ---------------------------------------------------------------------------

def _variant_flags(card: dict) -> tuple[bool, bool, bool]:
    """(signature, alternate_art, overnumbered). Newer sets (e.g. VEN) are missing some metadata
    flags, so also derive them from the ID: "042a" = alt art, "229*" = signature, number > set size = overnumbered."""
    m = card["metadata"]
    sig, alt, over = m["signature"], m["alternate_art"], m["overnumbered"]
    match = _RE_CARD_ID.match(card["riftbound_id"])
    if match:
        num, suffix, set_size = int(match[1]), match[2], int(match[3])
        sig  = sig  or suffix == "*"
        alt  = alt  or suffix == "a"
        over = over or (num > set_size and not sig)
    return sig, alt, over


def _is_showcase(card: dict) -> bool:
    # Newer sets (e.g. UNL) tag showcase variants with their base rarity, so check the variant flags too
    return card["classification"]["rarity"] == "Showcase" or any(_variant_flags(card))


def _dedupe(cards: list) -> list:
    """Drop duplicate API entries (same riftbound_id), preferring the one with metadata flags set."""
    def flagged(c):
        return any(c["metadata"][k] for k in ("signature", "alternate_art", "overnumbered"))

    by_id = {}
    for c in cards:
        prev = by_id.get(c["riftbound_id"])
        if prev is None or (flagged(c) and not flagged(prev)):
            by_id[c["riftbound_id"]] = c
    return list(by_id.values())


def _compute_pools(all_cards: list, set_id: str) -> dict:
    """Build and validate all card pools for a set. Called once per set per cache refresh."""
    # Special subsets like "ven-sp1-006" are pulled at alt-art rarity
    deduped       = _dedupe(_by_set(all_cards, set_id))
    specials      = [c for c in deduped if _RE_SPECIAL_ID.search(c["riftbound_id"])]
    all_set_cards = [c for c in deduped if not _RE_SPECIAL_ID.search(c["riftbound_id"])]
    showcases     = [c for c in all_set_cards if _is_showcase(c)]
    set_cards     = [c for c in all_set_cards if not _is_showcase(c)]

    commons    = [c for c in set_cards
                  if c["classification"]["rarity"] == "Common"
                  and c["classification"]["supertype"] != "Token"
                  and c["classification"]["type"] != "Rune"]
    uncommons    = _by_rarity(set_cards, "Uncommon")
    rares        = _by_rarity(set_cards, "Rare")
    epics        = _by_rarity(set_cards, "Epic")
    signatures   = [c for c in showcases if _variant_flags(c)[0]]
    alt_arts     = [c for c in showcases if _variant_flags(c)[1] and c["classification"]["type"] != "Rune"] + specials
    overnumbered = [c for c in showcases if _variant_flags(c)[2] and not _variant_flags(c)[0]]

    def _from_set_or_all(pred):
        result = [c for c in all_set_cards if pred(c)]
        return result or [c for c in all_cards if pred(c)]

    runes         = _from_set_or_all(lambda c: c["classification"]["type"] == "Rune" and c["classification"]["rarity"] == "Common")
    tokens        = _from_set_or_all(lambda c: c["classification"]["supertype"] == "Token")
    alt_art_runes = _from_set_or_all(lambda c: c["classification"]["type"] == "Rune" and c["metadata"]["alternate_art"])

    for pool, name in [(commons, "commons"), (uncommons, "uncommons"), (rares, "rares"),
                       (runes, "runes"), (tokens, "tokens")]:
        if not pool:
            raise ValueError(f"Empty card pool '{name}' for set '{set_id}'")

    return {
        'commons':      commons,
        'uncommons':    uncommons,
        'rares':        rares,
        'epics':        epics        or rares,
        'signatures':   signatures   or rares,
        'alt_arts':     alt_arts     or rares,
        'overnumbered': overnumbered or rares,
        'runes':        runes,
        'tokens':       tokens,
        'alt_art_runes': alt_art_runes or runes,
    }


async def make_pack(set_id: str) -> list:
    p = await _card_cache.get_pools(set_id)

    cards = random.choices(p['commons'], k=7) + random.choices(p['uncommons'], k=3)

    r = random.random()
    if r < _FOIL_T[0]:   cards.append(random.choice(p['commons']))
    elif r < _FOIL_T[1]: cards.append(random.choice(p['uncommons']))
    else:                 cards.append(random.choice(p['rares']))

    cards.append(random.choice(p['rares']))

    r = random.random()
    if r < _PREMIUM_T[0]:   cards.append(random.choice(p['rares']))
    elif r < _PREMIUM_T[1]: cards.append(random.choice(p['epics']))
    elif r < _PREMIUM_T[2]: cards.append(random.choice(p['alt_arts']))
    elif r < _PREMIUM_T[3]: cards.append(random.choice(p['overnumbered']))
    else:                    cards.append(random.choice(p['signatures']))

    r = random.random()
    if r < _RUNE_T[0]:   cards.append(random.choice(p['runes']))
    elif r < _RUNE_T[1]: cards.append(random.choice(p['tokens']))
    else:                 cards.append(random.choice(p['alt_art_runes']))

    return cards


# ---------------------------------------------------------------------------
# Image building
# ---------------------------------------------------------------------------

def _url_to_cache_path(url: str) -> Path:
    return CACHE_DIR / f"{hashlib.sha256(url.encode()).hexdigest()[:32]}.png"


def _process_image(data: bytes) -> Image.Image:
    img = Image.open(io.BytesIO(data)).convert("RGBA")
    if img.width > img.height:
        img = img.rotate(90, expand=True)
    if img.size != (CARD_W, CARD_H):
        img = img.resize((CARD_W, CARD_H), Image.LANCZOS)
    return img


def _blank_card() -> Image.Image:
    return Image.new("RGBA", (CARD_W, CARD_H), (40, 40, 40, 255))


async def fetch_image(session: aiohttp.ClientSession, url: str) -> Image.Image:
    loop = asyncio.get_running_loop()
    path = _url_to_cache_path(url)
    if path.exists():
        try:
            return await loop.run_in_executor(None, lambda: Image.open(path).convert("RGBA"))
        except Exception:
            path.unlink(missing_ok=True)
    async with session.get(url) as resp:
        data = await resp.read()
    img = await loop.run_in_executor(None, _process_image, data)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    await loop.run_in_executor(None, functools.partial(img.save, path, format="PNG"))
    return img


async def _fetch_images(urls: list) -> list:
    async with aiohttp.ClientSession() as session:
        results = await asyncio.gather(*[fetch_image(session, u) for u in urls], return_exceptions=True)
    images = []
    for i, r in enumerate(results):
        if isinstance(r, Exception):
            print(f"[riftbound] Image fetch failed (index {i}): {r}")
            images.append(_blank_card())
        else:
            images.append(r)
    return images


def _build_grid(images: list, cols: int = 7, numbered: bool = False, bg=(0, 0, 0, 0)) -> io.BytesIO:
    n         = len(images)
    grid_cols = min(n, cols)
    rows      = (n + cols - 1) // cols
    label_h   = int(CARD_H * 0.14) if numbered else 0
    cell_h    = CARD_H + label_h
    canvas    = Image.new("RGBA", (CARD_W * grid_cols, cell_h * rows), bg)

    draw, font = None, None
    if numbered:
        draw = ImageDraw.Draw(canvas)
        try:
            font = ImageFont.truetype("arial.ttf", size=int(label_h * 0.65))
        except Exception:
            font = ImageFont.load_default()

    for i, img in enumerate(images):
        col, row = i % cols, i // cols
        x, y = col * CARD_W, row * cell_h
        canvas.paste(img, (x, y))
        if numbered:
            lx, ly = x, y + CARD_H
            draw.rectangle([lx, ly, lx + CARD_W, ly + label_h], fill=(20, 20, 20, 230))
            text = str(i + 1)
            bbox = draw.textbbox((0, 0), text, font=font)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            draw.text((lx + (CARD_W - tw) // 2, ly + (label_h - th) // 2), text, fill=(220, 200, 140, 255), font=font)

    buf = io.BytesIO()
    canvas.save(buf, format="WEBP", quality=90)
    buf.seek(0)
    return buf


async def build_pack_image(pack: list) -> discord.File:
    loop = asyncio.get_running_loop()
    imgs = await _fetch_images([c["media"]["image_url"] for c in pack])
    buf  = await loop.run_in_executor(None, _build_grid, imgs)
    return discord.File(buf, filename="pack.webp")


async def build_draft_pack_image(pack: list) -> discord.File:
    loop = asyncio.get_running_loop()
    imgs = await _fetch_images([c["media"]["image_url"] for c in pack])
    buf  = await loop.run_in_executor(None, functools.partial(_build_grid, imgs, numbered=True))
    return discord.File(buf, filename="draft_pack.webp")


async def build_precon_pack_image(pack: list) -> discord.File:
    loop = asyncio.get_running_loop()
    imgs = await _fetch_images([c["media"]["image_url"] for c in pack[:28]])
    buf  = await loop.run_in_executor(None, functools.partial(_build_grid, imgs, bg=(0, 0, 0, 255)))
    return discord.File(buf, filename="precon.webp")


async def refresh_all_images(cards: list) -> int:
    """Download any card images not already in the cache. Returns how many were downloaded."""
    urls = list({c["media"]["image_url"] for c in cards if c.get("media", {}).get("image_url")})
    urls = [u for u in urls if not _url_to_cache_path(u).exists()]
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    sem = asyncio.Semaphore(20)

    async def download_one(session: aiohttp.ClientSession, url: str) -> bool:
        async with sem:
            try:
                async with session.get(url) as resp:
                    if resp.status != 200:
                        return False
                    data = await resp.read()
                loop = asyncio.get_running_loop()
                img  = await loop.run_in_executor(None, _process_image, data)
                await loop.run_in_executor(None, functools.partial(img.save, _url_to_cache_path(url), format="PNG"))
                return True
            except Exception as e:
                print(f"[riftbound] Failed to cache {url[:60]}: {e}")
                return False

    async with aiohttp.ClientSession() as session:
        results = await asyncio.gather(*[download_one(session, u) for u in urls])
    return sum(results)


async def refresh_card_data_and_images() -> None:
    print("[riftbound] Refreshing card data and images...")
    cards = await _card_cache.refresh()
    count = await refresh_all_images(cards)
    print(f"[riftbound] Downloaded {count} new card images")


# ---------------------------------------------------------------------------
# Sealed pool formatting
# ---------------------------------------------------------------------------

def _format_sealed_pool(cards: list) -> list[str]:
    groups: dict[str, list] = {
        "Legend": [], "Champion": [], "MainDeck": [],
        "Battlefields": [], "Gear": [], "Runes": [],
    }

    for card in cards:
        classification = card.get("classification") or {}
        card_type = classification.get("type") or ""
        supertype = classification.get("supertype") or ""
        raw_name  = card.get("name") or "Unknown"

        if supertype == "Token" or "// Buff" in raw_name:
            continue

        name = _RE_OVERNUMBERED.sub("", _RE_ALT_ART.sub("", raw_name.replace(" - ", ", ")))

        if card_type == "Rune":
            groups["Runes"].append(name)
        elif card_type == "Battlefield":
            groups["Battlefields"].append(name)
        elif card_type == "Gear":
            groups["Gear"].append(name)
        elif supertype == "Legend" or card_type == "Legend":
            groups["Legend"].append(name)
        elif "Champion" in card_type or "Champion" in supertype:
            groups["Champion"].append(name)
        else:
            groups["MainDeck"].append(name)

    lines = []
    for label, names in groups.items():
        if not names:
            continue
        lines.append(f"{label}:")
        for name, count in sorted(Counter(names).items(), key=lambda x: (-x[1], x[0])):
            lines.append(f"{count} {name}")
        lines.append("")

    chunks, current = [], ""
    for line in lines:
        addition = line + "\n"
        if len(current) + len(addition) > 1900:
            chunks.append(current.strip())
            current = addition
        else:
            current += addition
    if current.strip():
        chunks.append(current.strip())
    return chunks


# ---------------------------------------------------------------------------
# Draft helpers
# ---------------------------------------------------------------------------

class DeckTypeConverter(commands.Converter):
    async def convert(self, _ctx, argument):
        if argument.lower() in SET_ID_MAP:
            return argument.lower()
        raise commands.BadArgument()


class DraftBarrier:
    def __init__(self, player_ids: list):
        self._ids   = set(player_ids)
        self._ready: set = set()
        self._event = asyncio.Event()

    async def player_ready(self, user_id: int):
        self._ready.add(user_id)
        if self._ready >= self._ids:
            self._event.set()

    async def wait(self):
        await self._event.wait()


async def _wait_for_barrier(barrier: DraftBarrier, cancel: asyncio.Event) -> bool:
    """Wait for barrier or cancellation. Returns True if the draft was cancelled."""
    barrier_task = asyncio.create_task(barrier.wait())
    cancel_task  = asyncio.create_task(cancel.wait())
    _, pending = await asyncio.wait([barrier_task, cancel_task], return_when=asyncio.FIRST_COMPLETED)
    for t in pending:
        t.cancel()
        try:
            await t
        except asyncio.CancelledError:
            pass
    return cancel.is_set()


class DraftPickView(discord.ui.View):
    def __init__(self, barrier: DraftBarrier, user_id: int, cards: list, round_picks: dict):
        super().__init__(timeout=300)  # 5 minutes
        self.barrier     = barrier
        self.user_id     = user_id
        self.cards       = cards
        self.round_picks = round_picks  # {user_id: (idx, card)}
        self.message: Optional[discord.Message] = None

        for i, card in enumerate(cards):
            label = f"{i + 1} - {card.get('name', f'Card {i+1}')}"[:80]
            btn = discord.ui.Button(label=label, style=discord.ButtonStyle.secondary, row=i // 5)
            btn.callback = self._make_callback(i)
            self.add_item(btn)

    def _make_callback(self, idx: int):
        async def callback(interaction: discord.Interaction):
            if interaction.user.id != self.user_id:
                await interaction.response.send_message("This isn't your pick!", ephemeral=True)
                return
            if self.user_id in self.round_picks:  # ignore double-clicks
                await interaction.response.defer()
                return
            self.stop()
            card = self.cards[idx]
            await interaction.response.defer()
            await interaction.message.delete()
            await interaction.followup.send(f"Picked **{card.get('name', f'Card {idx+1}')}**. Waiting for other players...")
            self.round_picks[self.user_id] = (idx, card)
            await self.barrier.player_ready(self.user_id)
        return callback

    async def on_timeout(self):
        if self.user_id in self.round_picks:
            return
        card = self.cards[0]
        self.round_picks[self.user_id] = (0, card)
        if self.message:
            try:
                await self.message.edit(
                    content=f"Time's up! Auto-picked **{card.get('name', 'Card 1')}**.",
                    attachments=[],
                    view=None,
                )
            except Exception:
                pass
        await self.barrier.player_ready(self.user_id)


# ---------------------------------------------------------------------------
# Riftbound cog
# ---------------------------------------------------------------------------

class Riftbound(commands.Cog):
    PRECONS = {
        'SFD': {
            'companion': "SFD-116-1",  # Yone
            'decks': [
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
            ],
        },
        'UNL': {
            'companion': None,
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
        self._refresh_task:   Optional[asyncio.Task] = None
        self._active_drafts:  dict[int, dict]        = {}  # channel_id -> {initiator_id, cancel}

    async def _refresh_loop(self) -> None:
        while True:
            try:
                await refresh_card_data_and_images()
            except Exception as e:
                print(f"[riftbound] Refresh failed: {e}")
            await asyncio.sleep(REFRESH_INTERVAL)

    # Started once when the cog loads (on_ready fires again on every reconnect)
    async def cog_load(self):
        self._refresh_task = asyncio.create_task(self._refresh_loop())

    async def cog_unload(self):
        if self._refresh_task:
            self._refresh_task.cancel()

    @commands.hybrid_group(name="riftbound", description="Riftbound card game commands")
    async def riftbound(self, ctx: commands.Context):
        await ctx.send_help(ctx.command)

    @riftbound.command(name="pack", description="Open a Riftbound pack")
    @app_commands.describe(deck_type="Pack type (default: newest set)")
    @app_commands.choices(deck_type=[
        app_commands.Choice(name="Origins",      value="origins"),
        app_commands.Choice(name="Spiritforged", value="spiritforged"),
        app_commands.Choice(name="Unleashed",    value="unleashed"),
        app_commands.Choice(name="Vendetta",     value="vendetta"),
    ])
    async def riftbound_open(self, ctx: commands.Context, deck_type: Optional[str] = None):
        await ctx.defer()
        await self._register_profile(ctx.author)
        pack = await make_pack(SET_ID_MAP.get(deck_type, DEFAULT_SET))
        await ctx.send(file=await build_pack_image(pack))

    @riftbound.command(name="sealed", description="Generate a sealed pool")
    @app_commands.describe(deck_type="Pack type (default: newest set)")
    @app_commands.choices(deck_type=[
        app_commands.Choice(name="Origins",      value="origins"),
        app_commands.Choice(name="Spiritforged", value="spiritforged"),
        app_commands.Choice(name="Unleashed",    value="unleashed"),
        app_commands.Choice(name="Vendetta",     value="vendetta"),
    ])
    async def riftbound_sealed(self, ctx: commands.Context, deck_type: Optional[str] = None):
        await ctx.defer()
        await self._register_profile(ctx.author)
        set_id = SET_ID_MAP.get(deck_type, DEFAULT_SET)
        packs  = await asyncio.gather(*[make_pack(set_id) for _ in range(5)])

        precon_set  = self.PRECONS.get(set_id, self.PRECONS['SFD'])
        precon_code = random.choice(precon_set['decks'])
        if precon_set.get('companion'):
            precon_code += " " + precon_set['companion']

        all_cards   = await get_all_cards()
        precon_pack = code_to_cards(all_cards, precon_code)

        images = await asyncio.gather(
            build_precon_pack_image(precon_pack),
            *[build_pack_image(pack) for pack in packs],
        )

        all_cards_flat = [card for pack in (*packs, precon_pack) for card in pack]
        export_code    = " ".join(clean_card_code(c["riftbound_id"]).upper() + "-1" for c in all_cards_flat)

        await ctx.send(f"{ctx.author.mention} Here's your sealed pool!", files=list(images))
        for chunk in _format_sealed_pool(all_cards_flat):
            await ctx.send(chunk)
        await ctx.send(f"Code: `{export_code}`")

    @riftbound.group(name="draft", with_app_command=False, invoke_without_command=True)
    async def riftbound_draft(self, ctx: commands.Context, deck_type: Optional[DeckTypeConverter] = None, *users: discord.Member):
        """Use !riftbound draft [origins|spiritforged|unleashed|vendetta] @player1 @player2 ... (default: newest set)"""
        if ctx.invoked_subcommand is not None:
            return

        await self._register_profile(ctx.author)
        set_id  = SET_ID_MAP.get(deck_type, DEFAULT_SET)
        players = list(users)

        if len(players) < 2:
            await ctx.send("Draft requires at least 2 players!")
            return

        if ctx.channel.id in self._active_drafts:
            await ctx.send("A draft is already running in this channel!")
            return

        for player in players:
            if player.bot:
                await ctx.send(f"Cannot include bot {player.mention} in draft.")
                return

        for player in players:
            try:
                await player.send(f"We are about to begin Riftbound draft, {player.mention}.")
            except discord.Forbidden:
                await ctx.send(f"Could not DM {player.mention} (DMs disabled)")
                return

        await ctx.send(f"Draft started! Generating packs for {', '.join(p.mention for p in players)}...")

        cancel_event = asyncio.Event()
        self._active_drafts[ctx.channel.id] = {
            'initiator_id': ctx.author.id,
            'cancel':       cancel_event,
        }

        try:
            all_player_packs = await asyncio.gather(*[
                asyncio.gather(*[make_pack(set_id) for _ in range(3)])
                for _ in players
            ])
            player_packs = {p.id: list(packs) for p, packs in zip(players, all_player_packs)}

            n         = len(players)
            all_picks = {p.id: [] for p in players}
            cancelled = False

            for pack_round in range(3):
                if cancelled:
                    break
                await ctx.send(f"Pack {pack_round + 1} starting!")

                current_packs = {p.id: list(player_packs[p.id][pack_round])[:13] for p in players}
                pack_picks    = {p.id: [] for p in players}
                pick_num      = 0

                while any(len(current_packs[p.id]) > 1 for p in players):
                    if cancelled:
                        break
                    pick_num += 1
                    round_picks = {}
                    barrier     = DraftBarrier([p.id for p in players])

                    pack_images = await asyncio.gather(*[
                        build_draft_pack_image(current_packs[p.id]) for p in players
                    ])
                    views = [DraftPickView(barrier, p.id, current_packs[p.id], round_picks) for p in players]
                    messages = await asyncio.gather(*[
                        player.send(
                            f"Pack {pack_round + 1}, Pick {pick_num} — {len(current_packs[player.id])} cards remain:",
                            file=img,
                            view=view,
                        )
                        for player, img, view in zip(players, pack_images, views)
                    ])
                    for view, msg in zip(views, messages):
                        view.message = msg

                    cancelled = await _wait_for_barrier(barrier, cancel_event)
                    if cancelled:
                        for view in views:
                            view.stop()
                        break

                    # Odd rounds (1, 3) pass left; even rounds (2) pass right
                    direction = -1 if pack_round % 2 == 0 else 1
                    new_packs = {}
                    for i, player in enumerate(players):
                        picked_idx, picked_card = round_picks[player.id]
                        pack_picks[player.id].append(picked_card)
                        all_picks[player.id].append(picked_card)
                        remaining = [c for j, c in enumerate(current_packs[player.id]) if j != picked_idx]
                        new_packs[players[(i + direction) % n].id] = remaining
                    current_packs = new_packs

                if cancelled:
                    break

                for player in players:
                    last = current_packs[player.id]
                    if last:
                        card = last[0]
                        pack_picks[player.id].append(card)
                        all_picks[player.id].append(card)
                        await player.send(f"Last card in the pack: **{card.get('name', 'Unknown')}** has been added to your pool.")

                await ctx.send(f"Pack {pack_round + 1} complete!")
                await asyncio.gather(*[
                    self._send_pack_summary(player, pack_picks[player.id], pack_round)
                    for player in players if pack_picks[player.id]
                ])

            if cancelled:
                await ctx.send(f"Draft ended early by {ctx.author.mention}. Sending current pools...")
                await asyncio.gather(*[
                    self._send_final_pool(player, all_picks[player.id])
                    for player in players if all_picks[player.id]
                ])
            else:
                await ctx.send(f"Draft complete! {', '.join(p.mention for p in players)} — check your DMs for your full pool.")
                await asyncio.gather(*[
                    self._send_final_pool(player, all_picks[player.id])
                    for player in players if all_picks[player.id]
                ])

        finally:
            self._active_drafts.pop(ctx.channel.id, None)

    @riftbound_draft.command(name="end", with_app_command=False)
    async def riftbound_draft_end(self, ctx: commands.Context):
        """Use !riftbound draft end to forcibly stop the current draft."""
        draft = self._active_drafts.get(ctx.channel.id)
        if not draft:
            await ctx.send("There is no active draft in this channel.")
            return
        if ctx.author.id != draft['initiator_id']:
            await ctx.send("Only the person who started the draft can end it.")
            return
        draft['cancel'].set()
        await ctx.send("Ending the draft...")

    async def _send_pack_summary(self, player: discord.Member, picks: list, pack_round: int):
        img = await build_pack_image(picks)
        await player.send(f"Your Pack {pack_round + 1} picks ({len(picks)} cards):", file=img)

    async def _send_final_pool(self, player: discord.Member, picks: list):
        img = await build_pack_image(picks)
        await player.send(f"Your full draft pool ({len(picks)} cards):", file=img)
        for chunk in _format_sealed_pool(picks):
            await player.send(chunk)

    async def _register_profile(self, user):
        if db.record("SELECT * FROM profiles WHERE user_id = ?", user.id) is None:
            db.execute("INSERT INTO profiles (user_id, display_name) VALUES (?, ?)", user.id, user.display_name)
            db.commit()


async def setup(bot):
    await bot.add_cog(Riftbound(bot))
