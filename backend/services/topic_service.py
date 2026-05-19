"""Thematic classification shared by news, polymarket, and commodity layers.

Why keyword matching (not LLM)?
- Deterministic & free. We need this on every news article and every market on
  every refresh — paying an LLM per item would be both slow and expensive.
- Transparent. A user looking at "why was this article tagged Russia-Ukraine?"
  can read the keyword list.
- The optional LLM call sits on top of this layer (see /api/themes/analyze)
  and reasons over already-grouped items.

Topic order matters: more specific topics first, broader ones last.
A short list of `commodity_tickers` for each topic captures the standard
market "linkage" used by analysts (e.g. oil + wheat for Russia–Ukraine).
"""

from __future__ import annotations

from typing import TypedDict


class Topic(TypedDict):
    id: str
    label: str
    icon: str
    color: str
    keywords: list[str]
    commodity_tickers: list[str]


TOPICS: list[Topic] = [
    {
        "id": "russia_ukraine",
        "label": "Russia–Ukraine",
        "icon": "🇺🇦",
        "color": "#3b82f6",
        "keywords": [
            "ukraine", "russia", "russian", "putin", "zelensky", "kyiv", "kiev",
            "moscow", "kremlin", "donbas", "donetsk", "luhansk", "crimea",
            "kharkiv", "mariupol", "nato", "wagner", "shoigu", "lavrov",
        ],
        "commodity_tickers": ["CL=F", "BZ=F", "NG=F", "ZW=F", "GC=F"],
    },
    {
        "id": "middle_east",
        "label": "Middle East",
        "icon": "🕊️",
        "color": "#f97316",
        "keywords": [
            "israel", "israeli", "gaza", "hamas", "hezbollah", "lebanon",
            "iran", "iranian", "tehran", "houthi", "yemen", "syria", "assad",
            "west bank", "netanyahu", "ayatollah", "red sea", "saudi",
        ],
        "commodity_tickers": ["CL=F", "BZ=F", "GC=F"],
    },
    {
        "id": "china_taiwan",
        "label": "China–Taiwan",
        "icon": "🇨🇳",
        "color": "#ef4444",
        "keywords": [
            "china", "chinese", "xi jinping", "taiwan", "beijing", "ccp",
            "tsai", "lai ching-te", "south china sea", "hong kong", "pla",
        ],
        "commodity_tickers": ["HG=F", "SI=F", "ZS=F", "CT=F"],
    },
    {
        "id": "energy",
        "label": "Energy & Oil",
        "icon": "⛽",
        "color": "#fbbf24",
        "keywords": [
            "opec", "oil", "crude", "brent", "wti", "lng", "natural gas",
            "pipeline", "refinery", "aramco", "gasoline", "barrel",
        ],
        "commodity_tickers": ["CL=F", "BZ=F", "NG=F", "RB=F", "HO=F"],
    },
    {
        "id": "macro",
        "label": "Macro & Monetary",
        "icon": "💸",
        "color": "#a855f7",
        "keywords": [
            "fed", "federal reserve", "powell", "rate hike", "rate cut",
            "rates", "inflation", "cpi", "ppi", "recession", "ecb", "boe",
            "boj", "treasury yield", "currency", "dollar index",
        ],
        "commodity_tickers": ["GC=F", "SI=F", "DX-Y.NYB", "EURUSD=X", "USDJPY=X", "GBPUSD=X"],
    },
    {
        "id": "trade",
        "label": "Trade & Tariffs",
        "icon": "📦",
        "color": "#06b6d4",
        "keywords": [
            "tariff", "tariffs", "trade war", "wto", "import", "export",
            "supply chain", "embargo", "sanction", "sanctions",
        ],
        "commodity_tickers": ["HG=F", "PA=F", "PL=F"],
    },
    {
        "id": "agriculture",
        "label": "Agriculture & Food",
        "icon": "🌾",
        "color": "#84cc16",
        "keywords": [
            "wheat", "corn", "soybean", "cocoa", "coffee", "sugar", "cotton",
            "harvest", "drought", "famine", "fertilizer", "ammonia",
            "food security", "agriculture", "crop",
        ],
        "commodity_tickers": ["ZW=F", "ZC=F", "ZS=F", "CC=F", "KC=F", "SB=F", "CT=F"],
    },
    {
        "id": "elections",
        "label": "Elections & Politics",
        "icon": "🗳️",
        "color": "#22c55e",
        "keywords": [
            "election", "ballot", "voter", "primary", "caucus", "president",
            "presidential", "trump", "biden", "harris", "macron", "merz",
            "meloni", "starmer", "coup", "regime", "impeachment",
        ],
        "commodity_tickers": [],
    },
]

OTHER_TOPIC: Topic = {
    "id": "other",
    "label": "Other",
    "icon": "📰",
    "color": "#94a3b8",
    "keywords": [],
    "commodity_tickers": [],
}


def classify_text(text: str | None) -> str:
    """Return the topic id matching the first keyword found, or 'other'."""
    if not text:
        return OTHER_TOPIC["id"]
    t = text.lower()
    for topic in TOPICS:
        for kw in topic["keywords"]:
            if kw in t:
                return topic["id"]
    return OTHER_TOPIC["id"]


def topic_meta(topic_id: str) -> Topic:
    """Look up a topic definition by id; falls back to the OTHER bucket."""
    for t in TOPICS:
        if t["id"] == topic_id:
            return t
    return OTHER_TOPIC


def all_topics() -> list[Topic]:
    """All topic definitions in display order (specific → other last)."""
    return [*TOPICS, OTHER_TOPIC]
