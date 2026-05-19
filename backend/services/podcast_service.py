"""Podcast pipeline: discovery → transcript → summary.

Architecture
------------
1. **Discovery** (``discover_new_episodes``) — for each active channel,
   fetch ``https://www.youtube.com/feeds/videos.xml?channel_id=...`` (no
   API key, no quota), insert any episodes published in the configured
   backfill window we haven't seen yet.

2. **Processing** (``process_pending``) — for each episode missing a
   transcript or summary, pull YouTube's caption track via
   ``youtube-transcript-api`` (free, no key), then call Claude Sonnet
   with a strict JSON schema. Capped per run so the scheduler can keep up.

3. **Read API** (``get_*``) — straight SQL reads consumed by the router.

Cost note: Sonnet on a 200k-char Thinkerview episode is ~$0.15. The full
90-day backfill of both channels is ~$3-5 one-time, then ~$1/month ongoing.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timedelta, timezone

import feedparser
import httpx
from sqlalchemy import and_, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from models.podcast import PodcastChannel, PodcastEpisode

logger = logging.getLogger(__name__)
settings = get_settings()

RSS_FEED = "https://www.youtube.com/feeds/videos.xml?channel_id={cid}"

# Sonnet's context is 200k tokens; transcripts run ~4 chars/token. We cap
# at 600k chars (~150k tokens) which leaves comfortable headroom for the
# prompt + JSON output without ever overflowing. In practice Thinkerview's
# longest episodes are ~250k chars, so truncation is rare.
MAX_TRANSCRIPT_CHARS = 600_000

LANGUAGE_NAMES = {"fr": "French", "en": "English", "es": "Spanish", "de": "German"}

SUMMARY_SYSTEM = (
    "You are a precise podcast analyst. Given a podcast transcript (often "
    "imperfect, auto-generated), produce a structured summary in the "
    "requested language. Be specific: name the speakers when identifiable, "
    "the central claims, and the supporting evidence. Output ONLY a JSON "
    "object that matches the requested schema. No prose, no markdown fences."
)

SUMMARY_USER_TEMPLATE = """\
Summarize this {language_name} podcast episode for a geopolitics dashboard.
Write all string values of the output in {language_name}.

Schema (output strict JSON only — no markdown, no commentary):
{{
  "tldr": [string, string, string],
  "key_topics": [{{"label": string, "summary": string}}],
  "notable_quotes": [{{"speaker": string|null, "quote": string}}],
  "geopolitics_tags": [string]
}}

Rules:
- exactly 3 entries in "tldr" (each ≤ 25 words)
- 5–8 entries in "key_topics" (label ≤ 6 words, summary 1–3 sentences)
- 0–5 entries in "notable_quotes" (verbatim from transcript; if no speaker is
  clearly identified, set "speaker" to null)
- 3–8 entries in "geopolitics_tags" (short, lowercase, hyphen-separated:
  e.g. "russia-ukraine", "energy", "monetary-policy")

Channel: {channel_name}
Episode title: {title}

Transcript:
\"\"\"
{transcript}
\"\"\""""


# ---------------------------------------------------------------------------
# Timestamp helpers (mirror news_service for cross-app consistency)
# ---------------------------------------------------------------------------


def _to_naive_utc(dt: datetime) -> datetime:
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    return dt.replace(tzinfo=None)


def _iso_utc(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc).isoformat()


def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return _to_naive_utc(datetime.fromisoformat(s.replace("Z", "+00:00")))
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# RSS discovery
# ---------------------------------------------------------------------------


async def _fetch_rss(channel_id: str) -> list[dict]:
    """Fetch & parse one channel's YouTube uploads feed (last 15 entries)."""
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(RSS_FEED.format(cid=channel_id))
        r.raise_for_status()
    parsed = feedparser.parse(r.content)
    out: list[dict] = []
    for e in parsed.entries:
        vid = e.get("yt_videoid") or (e.get("id", "").split(":")[-1] or None)
        if not vid:
            continue
        thumb = None
        media = e.get("media_thumbnail") or []
        if isinstance(media, list) and media:
            thumb = media[0].get("url")
        out.append(
            {
                "youtube_video_id": vid,
                "title": (e.get("title") or "").strip(),
                "description": (e.get("summary") or e.get("description") or "")[:4000],
                "published_at": _parse_dt(e.get("published")),
                "thumbnail_url": thumb,
            }
        )
    return out


# ---------------------------------------------------------------------------
# Transcript fetch (sync library, wrap in to_thread)
# ---------------------------------------------------------------------------


def _fetch_transcript_sync(
    video_id: str, preferred_langs: list[str]
) -> tuple[str, str] | None:
    """Return ``(text, lang_code)`` for the best available caption track."""
    from youtube_transcript_api import YouTubeTranscriptApi

    api = YouTubeTranscriptApi()
    try:
        listed = api.list(video_id)
    except Exception as e:
        logger.info("Cannot list transcripts for %s: %s", video_id, e)
        return None

    for lang in preferred_langs:
        try:
            tr = listed.find_transcript([lang])
            data = tr.fetch()
            return " ".join(seg.text for seg in data), tr.language_code
        except Exception:
            continue
    # Fallback: first available track of any language. Better to have an
    # imperfect summary than no row at all.
    try:
        tr = next(iter(listed))
        data = tr.fetch()
        return " ".join(seg.text for seg in data), tr.language_code
    except Exception:
        return None


async def _fetch_transcript(
    video_id: str, preferred_langs: list[str]
) -> tuple[str, str] | None:
    return await asyncio.to_thread(
        _fetch_transcript_sync, video_id, preferred_langs
    )


# ---------------------------------------------------------------------------
# LLM summarization (Claude Sonnet by default)
# ---------------------------------------------------------------------------


def _strip_code_fence(s: str) -> str:
    """Claude usually returns bare JSON when told to, but defensively strip
    a leading ```json ... ``` fence if it slips through."""
    s = s.strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s)
        s = re.sub(r"\s*```$", "", s)
    return s


async def _summarize(
    transcript: str, title: str, channel_name: str, language: str
) -> dict | None:
    if not settings.anthropic_api_key:
        logger.warning(
            "ANTHROPIC_API_KEY missing — cannot summarize podcast episode"
        )
        return None

    truncated = transcript
    if len(truncated) > MAX_TRANSCRIPT_CHARS:
        logger.info(
            "Truncating transcript from %d to %d chars before summarizing",
            len(truncated),
            MAX_TRANSCRIPT_CHARS,
        )
        truncated = truncated[:MAX_TRANSCRIPT_CHARS]

    lang_name = LANGUAGE_NAMES.get(language, "English")
    prompt = SUMMARY_USER_TEMPLATE.format(
        language_name=lang_name,
        title=title,
        channel_name=channel_name,
        transcript=truncated,
    )

    import anthropic

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    raw = ""
    try:
        resp = await client.messages.create(
            model=settings.podcast_summary_model,
            max_tokens=2048,
            system=SUMMARY_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = resp.content[0].text if resp.content else ""
        return json.loads(_strip_code_fence(raw))
    except json.JSONDecodeError as e:
        logger.error(
            "Podcast summary JSON parse failed: %s; head=%r", e, raw[:300]
        )
        return None
    except Exception as e:
        logger.error("Anthropic summarize failed for %r: %s", title, e)
        return None


# ---------------------------------------------------------------------------
# Public pipeline
# ---------------------------------------------------------------------------


async def discover_new_episodes(db: AsyncSession) -> int:
    """Insert new episodes from RSS, capped to ``podcast_backfill_days``.

    Returns the number of newly inserted rows. Does **not** transcribe or
    summarize — that is the ``process_pending`` job's responsibility.
    """
    cutoff = datetime.utcnow() - timedelta(days=settings.podcast_backfill_days)

    channels = (
        await db.execute(
            select(PodcastChannel).where(PodcastChannel.active == True)  # noqa: E712
        )
    ).scalars().all()

    inserted = 0
    for ch in channels:
        if not ch.youtube_channel_id:
            logger.debug("Channel %s has no youtube_channel_id, skipping", ch.slug)
            continue
        try:
            entries = await _fetch_rss(ch.youtube_channel_id)
        except Exception as e:
            logger.error("RSS fetch failed for %s: %s", ch.slug, e)
            continue
        for ent in entries:
            pub = ent["published_at"]
            if not pub or pub < cutoff:
                continue
            existing = await db.execute(
                select(PodcastEpisode.id).where(
                    PodcastEpisode.youtube_video_id == ent["youtube_video_id"]
                )
            )
            if existing.scalar_one_or_none():
                continue
            db.add(PodcastEpisode(channel_id=ch.id, **ent))
            inserted += 1
    await db.commit()
    if inserted:
        logger.info(
            "Discovered %d new podcast episodes (window=%d days)",
            inserted,
            settings.podcast_backfill_days,
        )
    return inserted


async def process_pending(db: AsyncSession, max_episodes: int = 3) -> int:
    """Transcribe + summarize the next ``max_episodes`` pending rows.

    Cap is intentionally small (default 3 per tick) so a 50-episode backfill
    spreads naturally over ~10 scheduler ticks instead of blocking the event
    loop. The summary call itself is async and yields between awaits.
    """
    rows = (
        await db.execute(
            select(PodcastEpisode, PodcastChannel)
            .join(
                PodcastChannel,
                PodcastEpisode.channel_id == PodcastChannel.id,
            )
            .where(
                and_(
                    PodcastEpisode.summary_json.is_(None),
                    PodcastEpisode.error.is_(None),
                )
            )
            .order_by(desc(PodcastEpisode.published_at))
            .limit(max_episodes)
        )
    ).all()

    processed = 0
    for ep, ch in rows:
        preferred = [ch.language]
        if ch.language != "en":
            preferred.append("en")
        try:
            if not ep.transcript:
                got = await _fetch_transcript(ep.youtube_video_id, preferred)
                if not got:
                    ep.error = "No transcript available on YouTube"
                    await db.commit()
                    continue
                ep.transcript, ep.transcript_lang = got
                # Commit transcript before LLM call so we don't re-fetch if
                # the summary step crashes.
                await db.commit()

            summary = await _summarize(
                ep.transcript, ep.title, ch.name, ch.language
            )
            if summary is None:
                ep.error = "Summarization failed (see backend logs)"
            else:
                ep.summary_json = summary
                ep.summary_model = settings.podcast_summary_model
                ep.summary_at = datetime.utcnow()
                ep.error = None
            await db.commit()
            processed += 1
        except Exception as e:
            logger.exception(
                "Episode %s processing failed: %s", ep.youtube_video_id, e
            )
            ep.error = str(e)[:500]
            await db.commit()
    if processed:
        logger.info("Processed %d podcast episode(s) this tick", processed)
    return processed


# ---------------------------------------------------------------------------
# Read API
# ---------------------------------------------------------------------------


async def get_channels(db: AsyncSession) -> list[dict]:
    chans = (
        await db.execute(
            select(PodcastChannel).order_by(PodcastChannel.id)
        )
    ).scalars().all()

    counts_rows = (
        await db.execute(
            select(PodcastEpisode.channel_id, func.count(PodcastEpisode.id))
            .group_by(PodcastEpisode.channel_id)
        )
    ).all()
    counts = {cid: n for cid, n in counts_rows}

    pending_rows = (
        await db.execute(
            select(PodcastEpisode.channel_id, func.count(PodcastEpisode.id))
            .where(
                and_(
                    PodcastEpisode.summary_json.is_(None),
                    PodcastEpisode.error.is_(None),
                )
            )
            .group_by(PodcastEpisode.channel_id)
        )
    ).all()
    pending = {cid: n for cid, n in pending_rows}

    return [
        {
            "id": c.id,
            "slug": c.slug,
            "name": c.name,
            "language": c.language,
            "youtube_channel_id": c.youtube_channel_id,
            "description": c.description,
            "active": c.active,
            "episode_count": counts.get(c.id, 0),
            "pending_count": pending.get(c.id, 0),
        }
        for c in chans
    ]


def _episode_row_to_dict(
    ep: PodcastEpisode, ch: PodcastChannel, *, include_transcript: bool = False
) -> dict:
    out = {
        "id": ep.id,
        "youtube_video_id": ep.youtube_video_id,
        "youtube_url": f"https://www.youtube.com/watch?v={ep.youtube_video_id}",
        "title": ep.title,
        "description": ep.description,
        "published_at": _iso_utc(ep.published_at),
        "duration_sec": ep.duration_sec,
        "thumbnail_url": ep.thumbnail_url,
        "channel": {
            "slug": ch.slug,
            "name": ch.name,
            "language": ch.language,
        },
        "has_transcript": bool(ep.transcript),
        "transcript_lang": ep.transcript_lang,
        "summary": ep.summary_json,
        "summary_model": ep.summary_model,
        "summary_at": _iso_utc(ep.summary_at),
        "error": ep.error,
    }
    if include_transcript:
        out["transcript"] = ep.transcript
    return out


async def get_episodes(
    db: AsyncSession,
    channel_slug: str | None = None,
    limit: int = 60,
) -> list[dict]:
    q = (
        select(PodcastEpisode, PodcastChannel)
        .join(
            PodcastChannel, PodcastEpisode.channel_id == PodcastChannel.id
        )
        .order_by(desc(PodcastEpisode.published_at))
        .limit(limit)
    )
    if channel_slug:
        q = q.where(PodcastChannel.slug == channel_slug)
    rows = (await db.execute(q)).all()
    return [_episode_row_to_dict(ep, ch) for ep, ch in rows]


async def get_episode(db: AsyncSession, episode_id: int) -> dict | None:
    row = (
        await db.execute(
            select(PodcastEpisode, PodcastChannel)
            .join(
                PodcastChannel,
                PodcastEpisode.channel_id == PodcastChannel.id,
            )
            .where(PodcastEpisode.id == episode_id)
        )
    ).one_or_none()
    if not row:
        return None
    ep, ch = row
    return _episode_row_to_dict(ep, ch, include_transcript=True)


async def reset_episode(db: AsyncSession, episode_id: int) -> bool:
    """Clear transcript+summary so the next scheduler tick redoes them."""
    ep = (
        await db.execute(
            select(PodcastEpisode).where(PodcastEpisode.id == episode_id)
        )
    ).scalar_one_or_none()
    if not ep:
        return False
    ep.transcript = None
    ep.transcript_lang = None
    ep.summary_json = None
    ep.summary_model = None
    ep.summary_at = None
    ep.error = None
    await db.commit()
    return True
