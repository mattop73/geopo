"""Curated keyword/entity extractor for news articles.

We deliberately do **not** call an LLM here — tagging every article (potentially
hundreds per refresh) with a paid API would be slow and expensive, and a free
heuristic is plenty good for "small chips under a headline".

Strategy: a vocabulary of geopolitically-relevant entities (countries, leaders,
organisations, commodities, conflict/event terms). For each article we scan
``title + description`` once and keep the entities that appear, deduplicated
and preserving vocabulary order.

Each entry can be either:
    "Ukraine"                      # surface form == display label
    ("Israel-Gaza", ["israel", "gaza", "hamas"])  # display label, alias list

Aliases are matched with word boundaries so "iran" doesn't match "iranian"
(we'd add "iranian" explicitly). Multi-word aliases match as substrings.
"""

from __future__ import annotations

import re
from typing import Iterable

# (label, [aliases])  — aliases are matched case-insensitively
_RAW_VOCAB: list[tuple[str, list[str]]] = [
    # --- Countries / regions ---
    ("Ukraine",        ["ukraine", "ukrainian"]),
    ("Russia",         ["russia", "russian", "kremlin"]),
    ("China",          ["china", "chinese", "beijing"]),
    ("Taiwan",         ["taiwan", "taiwanese"]),
    ("USA",            ["united states", "u.s.", "us economy", "u.s. economy", "washington"]),
    ("Iran",           ["iran", "iranian", "tehran"]),
    ("Israel",         ["israel", "israeli", "tel aviv"]),
    ("Gaza",           ["gaza", "rafah"]),
    ("Lebanon",        ["lebanon", "lebanese", "beirut"]),
    ("Syria",          ["syria", "syrian", "damascus"]),
    ("Yemen",          ["yemen", "yemeni", "sana'a"]),
    ("North Korea",    ["north korea", "pyongyang", "dprk"]),
    ("South Korea",    ["south korea", "seoul"]),
    ("Japan",          ["japan", "japanese", "tokyo"]),
    ("India",          ["india", "indian", "new delhi"]),
    ("Pakistan",       ["pakistan", "pakistani", "islamabad"]),
    ("EU",             ["european union", " eu ", "brussels"]),
    ("UK",             ["united kingdom", "britain", "british", "london"]),
    ("France",         ["france", "french", "paris"]),
    ("Germany",        ["germany", "german", "berlin"]),
    ("Italy",          ["italy", "italian", "rome"]),
    ("Turkey",         ["turkey", "turkish", "ankara", "erdogan"]),
    ("Saudi Arabia",   ["saudi arabia", "saudi", "riyadh"]),
    ("Venezuela",      ["venezuela", "venezuelan", "caracas", "maduro"]),
    ("Argentina",      ["argentina", "argentine", "milei"]),
    ("Brazil",         ["brazil", "brazilian", "lula"]),
    ("Mexico",         ["mexico", "mexican"]),
    ("Africa",         ["africa", "african", "sahel"]),

    # --- People ---
    ("Trump",      ["trump"]),
    ("Biden",      ["biden"]),
    ("Harris",     ["kamala harris", " harris"]),
    ("Putin",      ["putin"]),
    ("Zelensky",   ["zelensky", "zelenskyy"]),
    ("Xi Jinping", ["xi jinping", " xi "]),
    ("Netanyahu",  ["netanyahu"]),
    ("Macron",     ["macron"]),
    ("Merz",       ["merz"]),
    ("Meloni",     ["meloni"]),
    ("Starmer",    ["starmer"]),
    ("Powell",     ["jerome powell", " powell"]),

    # --- Organisations ---
    ("NATO",     ["nato"]),
    ("UN",       ["united nations", " un "]),
    ("OPEC",     ["opec"]),
    ("Fed",      ["federal reserve", " fed "]),
    ("ECB",      ["ecb", "european central bank"]),
    ("IMF",      ["imf", "international monetary fund"]),
    ("Hamas",    ["hamas"]),
    ("Hezbollah",["hezbollah"]),
    ("Houthi",   ["houthi", "houthis"]),
    ("Wagner",   ["wagner group", "wagner "]),
    ("IRGC",     ["irgc", "revolutionary guard"]),

    # --- Commodities / markets ---
    ("Oil",          ["crude oil", " oil ", "brent", "wti"]),
    ("Natural gas",  ["natural gas", " lng "]),
    ("Gold",         [" gold "]),
    ("Silver",       [" silver "]),
    ("Copper",       [" copper "]),
    ("Wheat",        ["wheat"]),
    ("Corn",         [" corn "]),
    ("Soybeans",     ["soybean", "soybeans"]),
    ("Cocoa",        ["cocoa"]),
    ("Coffee",       ["coffee"]),
    ("Sugar",        [" sugar "]),
    ("Cotton",       ["cotton"]),
    ("Stocks",       ["s&p 500", "nasdaq", "dow jones"]),
    ("Bitcoin",      ["bitcoin", " btc "]),

    # --- Events / themes ---
    ("War",          [" war ", "warfare"]),
    ("Ceasefire",    ["ceasefire", "cease-fire"]),
    ("Sanctions",    ["sanction", "sanctions"]),
    ("Tariffs",      ["tariff", "tariffs"]),
    ("Election",     ["election", "elections", "ballot", "primary"]),
    ("Coup",         ["coup", "putsch"]),
    ("Summit",       ["summit"]),
    ("Treaty",       ["treaty"]),
    ("Inflation",    ["inflation", " cpi ", " ppi "]),
    ("Recession",    ["recession"]),
    ("Rate cut",     ["rate cut", "rate cuts"]),
    ("Rate hike",    ["rate hike", "rate hikes"]),
    ("Drought",      ["drought"]),
    ("Famine",       ["famine"]),
    ("Cyberattack",  ["cyberattack", "cyber attack", "ransomware"]),
    ("AI",           [" ai ", "artificial intelligence"]),
    ("Drone",        ["drone", "drones", "uav"]),
    ("Nuclear",      ["nuclear"]),
    ("Missile",      ["missile", "icbm"]),
    ("Pipeline",     ["pipeline"]),
    ("Refugee",      ["refugee", "refugees", "asylum"]),
    ("Trade war",    ["trade war"]),
    ("Strike",       ["strike", "strikes"]),
    ("Protest",      ["protest", "protests", "demonstration"]),
]


def _compile_pattern(alias: str) -> re.Pattern[str]:
    """Compile a case-insensitive regex for an alias.

    Aliases padded with spaces (e.g. ``' eu '``) become whole-word matches.
    Multi-word aliases (no leading/trailing space) match as substrings, since
    we want "european union" anywhere in the headline.
    Single-word aliases without padding get word-boundary anchors.
    """
    a = alias.strip()
    if alias.startswith(" ") or alias.endswith(" "):
        # Whole-word match (caller intent: avoid prefix collisions like
        # "iran" → "iranian"; or "ai" → "said").
        return re.compile(rf"\b{re.escape(a)}\b", re.IGNORECASE)
    if " " in a:
        # Multi-word phrase: substring match is fine.
        return re.compile(re.escape(a), re.IGNORECASE)
    return re.compile(rf"\b{re.escape(a)}\b", re.IGNORECASE)


# Pre-compile once at import time.
_VOCAB: list[tuple[str, list[re.Pattern[str]]]] = [
    (label, [_compile_pattern(a) for a in aliases])
    for label, aliases in _RAW_VOCAB
]


def extract_keywords(text: str | None, max_tags: int = 6) -> list[str]:
    """Return up to ``max_tags`` distinct entity labels matching ``text``.

    The order of the returned tags reflects vocabulary order (most specific →
    broader themes), which tends to read well in the UI.
    """
    if not text:
        return []
    haystack = f" {text} "  # padding so leading/trailing word-boundary patterns match
    found: list[str] = []
    for label, patterns in _VOCAB:
        if any(p.search(haystack) for p in patterns):
            found.append(label)
            if len(found) >= max_tags:
                break
    return found


def extract_keywords_for_article(title: str | None, description: str | None, max_tags: int = 6) -> list[str]:
    """Convenience wrapper combining title + description with title weighted first."""
    parts: Iterable[str] = (p for p in (title, description) if p)
    return extract_keywords(" ".join(parts), max_tags=max_tags)
