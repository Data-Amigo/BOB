from __future__ import annotations

import html
import logging
import os
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI
from psycopg.rows import dict_row
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
)
from telegram.error import InvalidToken, NetworkError, TelegramError, TimedOut
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from ganji_mtaani_agent.db import (
    fetch_bot_user_profile,
    get_postgres_connection,
    insert_bot_conversation,
    insert_bot_slip,
    insert_bot_slip_legs,
    upsert_bot_user,
    upsert_bot_user_consents,
    upsert_bot_user_preferences,
)
from ganji_mtaani_agent.etl.canonical_fixtures import _candidate_from_row, normalize_team_name

PROJECT_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(PROJECT_ROOT / ".env", override=False)

CHANNEL_TELEGRAM = "telegram"
PROBABILITY_BUCKETS = ("70-80%", "80-90%", "90-100%")
BUCKET_TIER_LABELS = {
    "70-80%": "Bronze",
    "80-90%": "Silver",
    "90-100%": "Gold",
}
_OUTCOME_LABELS: dict[str, str] = {"1": "Home Win", "2": "Away Win", "X": "Draw"}
_TIER_EMOJIS: dict[str, str] = {"Gold": "🥇", "Silver": "🥈", "Bronze": "🥉"}
_SPORT_EMOJIS: dict[str, str] = {"football": "⚽", "basketball": "🏀"}
logger = logging.getLogger(__name__)

(
    STATE_TERMS,
    STATE_DATA_CONSENT,
    STATE_MARKETING_CONSENT,
    STATE_PHONE,
    STATE_PREFERRED_NAME,
    STATE_SPORT,
    STATE_FREQUENCY,
    STATE_SERVICE_MODE,
    STATE_SLIP_SIZE,
    STATE_RISK,
) = range(10)


@dataclass(frozen=True, slots=True)
class TelegramBotConfig:
    token: str
    openai_api_key: str | None = None
    openai_model: str = "gpt-5-mini"
    default_slip_size: int = 3
    slip_min_probability: float = 70.0
    default_stake_kes: float = 100.0

    @classmethod
    def from_env(cls) -> "TelegramBotConfig":
        token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        if not token:
            raise RuntimeError("TELEGRAM_BOT_TOKEN is missing. Set it in the project root .env file.")
        return cls(
            token=token,
            openai_api_key=os.getenv("OPENAI_API_KEY"),
            openai_model=os.getenv("OPENAI_MODEL", "gpt-5-mini"),
        )


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _he(value: Any) -> str:
    """Escape a value for Telegram HTML parse mode."""
    return html.escape(str(value or ""))


def _bucket_label(probability: float | None) -> str | None:
    if probability is None:
        return None
    if probability < 40:
        return "<40%"
    if probability < 50:
        return "40-50%"
    if probability < 60:
        return "50-60%"
    if probability < 70:
        return "60-70%"
    if probability < 80:
        return "70-80%"
    if probability < 90:
        return "80-90%"
    return "90-100%"


def _safe_probability(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_forebet_event_date(value: str | None) -> date | None:
    if not value:
        return None
    text = str(value).strip()
    try:
        return datetime.strptime(text, "%d/%m/%Y %H:%M").date()
    except ValueError:
        try:
            return datetime.strptime(text, "%d/%m/%Y").date()
        except ValueError:
            return None


def _parse_forebet_event_time(value: str | None) -> str | None:
    """Extract the HH:MM time string from a forebet event_datetime_text."""
    if not value:
        return None
    match = re.search(r"\b(\d{1,2}:\d{2})\b", str(value).strip())
    return match.group(1) if match else None


def _get_openai_client() -> tuple[OpenAI | None, str]:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    model = os.getenv("OPENAI_MODEL", "gpt-5-mini").strip() or "gpt-5-mini"
    if not api_key:
        return None, model
    return OpenAI(api_key=api_key), model


def _llm_text(*, system_prompt: str, user_prompt: str, fallback_text: str) -> str:
    client, model = _get_openai_client()
    if client is None:
        return fallback_text
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        content = response.choices[0].message.content if response.choices else None
        if content:
            return str(content).strip()
    except Exception as exc:  # pragma: no cover - graceful fallback in live bot mode
        logger.warning("OpenAI response generation failed, using fallback text: %s", exc)
    return fallback_text


def _normalize_sport_choice(value: str | None) -> list[str]:
    if not value:
        return ["football"]
    normalized = str(value).strip().lower()
    if any(tok in normalized for tok in ("both", "and", "&")):
        return ["football", "basketball"]
    if "basketball" in normalized:
        return ["basketball"]
    return ["football"]


def _tier_label_from_bucket(bucket: str | None) -> str | None:
    if not bucket:
        return None
    return BUCKET_TIER_LABELS.get(bucket)


def _profile_stage(profile: dict[str, Any] | None) -> str:
    if not profile or not profile.get("terms_accepted"):
        return "terms"
    if not str(profile.get("preferred_name") or "").strip():
        return "preferred_name"
    if not list(profile.get("preferred_sports_json") or []):
        return "preferred_sports"
    if not str(profile.get("risk_profile") or "").strip():
        return "risk_profile"
    return "ready"


def _detect_sport_from_text(text: str, fallback_sports: list[str] | None = None) -> str:
    lowered = text.lower()
    if "basketball" in lowered:
        return "basketball"
    if "football" in lowered or "soccer" in lowered:
        return "football"
    if fallback_sports:
        return fallback_sports[0]
    return "football"


def _is_affirmative(text: str) -> bool:
    lowered = str(text or "").strip().lower()
    return lowered in {"yes", "y", "agree", "agreed", "accept", "accepted", "continue", "ok", "okay"}


def _is_negative(text: str) -> bool:
    lowered = str(text or "").strip().lower()
    return lowered in {"no", "n", "decline", "stop", "cancel"}


def _detect_slip_size_from_text(text: str, default_value: int = 3) -> int:
    lowered = text.lower()
    if "4-leg" in lowered or "4 leg" in lowered or "4-fold" in lowered or "4 fold" in lowered:
        return 4
    if "3-leg" in lowered or "3 leg" in lowered or "3-fold" in lowered or "3 fold" in lowered:
        return 3
    return default_value


def _detect_slip_count_from_text(text: str, default_value: int = 3) -> int:
    lowered = text.lower()
    match = re.search(r"(\d+)\s*(?:slips|slip)", lowered)
    if match:
        try:
            return max(1, min(int(match.group(1)), 12))
        except ValueError:
            return default_value
    if "multiple" in lowered or "many" in lowered or "several" in lowered:
        return 3
    return default_value


def _message_intent(text: str) -> str:
    lowered = text.lower().strip()
    if "tomorrow" in lowered:
        return "games_tomorrow"
    if any(token in lowered for token in ("today", "games", "fixtures")):
        return "games_today"
    if "performance" in lowered or "yesterday" in lowered or "result" in lowered:
        return "performance_summary"
    if "slip" in lowered or "pick" in lowered or "bet" in lowered:
        return "generate_slips"
    if lowered in {"hi", "hello", "hey", "yo"}:
        return "greeting"
    return "general"


def _names_compatible(left: str, right: str) -> bool:
    if left == right:
        return True
    left_tokens = {token for token in left.split() if token}
    right_tokens = {token for token in right.split() if token}
    if not left_tokens or not right_tokens:
        return False
    overlap = left_tokens & right_tokens
    return len(overlap) >= min(2, len(left_tokens), len(right_tokens))


def _ensure_bot_user(update: Update) -> int:
    telegram_user = update.effective_user
    chat = update.effective_chat
    if telegram_user is None or chat is None:
        raise RuntimeError("Telegram update is missing user or chat context.")

    with get_postgres_connection(autocommit=True) as connection:
        return upsert_bot_user(
            connection,
            channel=CHANNEL_TELEGRAM,
            channel_user_id=str(telegram_user.id),
            chat_id=str(chat.id),
            username=telegram_user.username,
            first_name=telegram_user.first_name,
            last_name=telegram_user.last_name,
            status="active",
            last_seen_at=_now_utc(),
        )


def _log_conversation(
    *,
    user_id: int | None,
    update: Update | None,
    direction: str,
    text: str | None,
    intent: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    chat_id = str(update.effective_chat.id) if update and update.effective_chat else None
    with get_postgres_connection(autocommit=True) as connection:
        insert_bot_conversation(
            connection,
            user_id=user_id,
            channel=CHANNEL_TELEGRAM,
            chat_id=chat_id,
            message_direction=direction,
            message_text=text,
            intent=intent,
            metadata_json=metadata or {},
        )


async def _reply_logged(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    *,
    user_id: int | None,
    intent: str | None = None,
    reply_markup: Any | None = None,
    parse_mode: str | None = None,
) -> None:
    if update.effective_message is None:
        return
    try:
        await update.effective_message.reply_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
    except TimedOut:
        logger.warning("Telegram reply timed out once; retrying without changing the response body.")
        await update.effective_message.reply_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
    _log_conversation(user_id=user_id, update=update, direction="outbound", text=text, intent=intent)


def _log_update_received(update: Update) -> None:
    """Log incoming updates so the prototype is easier to debug live."""

    if update.effective_user is None or update.effective_chat is None:
        logger.info("Received Telegram update without user/chat context: %s", update)
        return
    message_text = ""
    if update.effective_message is not None:
        message_text = update.effective_message.text or "[non-text message]"
    logger.info(
        "Received update from user_id=%s chat_id=%s username=%s text=%s",
        update.effective_user.id,
        update.effective_chat.id,
        update.effective_user.username,
        message_text,
    )


def _build_consent_keyboard(prefix: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Yes", callback_data=f"{prefix}:yes"),
                InlineKeyboardButton("No", callback_data=f"{prefix}:no"),
            ]
        ]
    )


def _build_phone_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("Share Phone Number", request_contact=True)],
            [KeyboardButton("Skip")],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def _build_simple_keyboard(options: list[str]) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup([[option] for option in options], resize_keyboard=True, one_time_keyboard=True)


def _fetch_upcoming_forebet_candidates(*, sport: str, min_probability: float, limit: int = 500) -> list[dict[str, Any]]:
    sport_values = ["football", "soccer"] if sport == "football" else [sport]

    with get_postgres_connection() as connection, connection.cursor(row_factory=dict_row) as cursor:
        # Filter by date and probability in SQL so the LIMIT applies after filtering,
        # not before. The old approach (ORDER BY created_at LIMIT 120) missed football
        # games scraped earlier in the same run.
        cursor.execute(
            """
            SELECT
                id,
                source_name,
                sport,
                league,
                home_team,
                away_team,
                match_url,
                event_datetime_text,
                pred_outcome,
                CASE
                    WHEN pred_outcome = '1' THEN prob_1
                    WHEN pred_outcome = '2' THEN prob_2
                    WHEN pred_outcome = 'X' THEN prob_x
                    ELSE NULL
                END AS pred_probability,
                confidence,
                created_at
            FROM forebet_predictions
            WHERE LOWER(sport) = ANY(%s)
              AND match_url IS NOT NULL
              AND pred_outcome IS NOT NULL
              AND event_datetime_text ~ E'^\\\\d{2}/\\\\d{2}/\\\\d{4}'
              AND TO_DATE(SUBSTRING(event_datetime_text, 1, 10), 'DD/MM/YYYY')
                  BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL '7 days'
              AND CASE
                    WHEN pred_outcome = '1' THEN prob_1
                    WHEN pred_outcome = '2' THEN prob_2
                    WHEN pred_outcome = 'X' THEN prob_x
                    ELSE NULL
                  END >= %s
            ORDER BY
                TO_DATE(SUBSTRING(event_datetime_text, 1, 10), 'DD/MM/YYYY') ASC,
                CASE
                    WHEN pred_outcome = '1' THEN prob_1
                    WHEN pred_outcome = '2' THEN prob_2
                    WHEN pred_outcome = 'X' THEN prob_x
                    ELSE NULL
                END DESC NULLS LAST
            LIMIT %s
            """,
            (sport_values, min_probability, limit),
        )
        rows = [dict(row) for row in cursor.fetchall()]

    # Deduplicate by match_url (same match from multiple scrape runs)
    deduped: dict[str, dict[str, Any]] = {}
    for row in rows:
        event_date = _parse_forebet_event_date(row.get("event_datetime_text"))
        if event_date is None:
            continue
        row["event_date"] = event_date
        row["event_time"] = _parse_forebet_event_time(row.get("event_datetime_text"))
        row["probability_bucket"] = _bucket_label(float(row.get("pred_probability") or 0.0))
        dedupe_key = str(row.get("match_url") or f"{row.get('home_team')}::{row.get('away_team')}::{event_date.isoformat()}")
        if dedupe_key not in deduped:
            deduped[dedupe_key] = row

    # Second pass: deduplicate same match stored under both 'football' and 'soccer' labels
    name_deduped: dict[str, dict[str, Any]] = {}
    for row in deduped.values():
        name_key = (
            f"{(row.get('home_team') or '').lower()}::"
            f"{(row.get('away_team') or '').lower()}::"
            f"{row['event_date'].isoformat()}"
        )
        existing = name_deduped.get(name_key)
        if existing is None or (row.get("pred_probability") or 0.0) > (existing.get("pred_probability") or 0.0):
            name_deduped[name_key] = row

    candidates = list(name_deduped.values())
    candidates.sort(key=lambda item: (
        item["event_date"],
        item.get("event_time") or "99:99",
        -(item.get("pred_probability") or 0.0),
    ))
    return candidates


def _fetch_best_bookmaker_odds_by_key(*, sport: str, event_date: date) -> list[dict[str, Any]]:
    with get_postgres_connection() as connection, connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT
                bo.id,
                bo.source_name,
                bo.sport,
                bo.home_team,
                bo.away_team,
                bo.event_datetime_text,
                bo.home_odds,
                bo.draw_odds,
                bo.away_odds,
                COALESCE(sr.started_at, bo.created_at) AS source_run_started_at
            FROM bookmaker_odds AS bo
            LEFT JOIN source_runs AS sr
                ON sr.id = bo.run_id
            WHERE LOWER(bo.sport) = ANY(%s)
            ORDER BY bo.id DESC
            """,
            ((["football", "soccer"] if sport == "football" else [sport]),),
        )
        bookmaker_rows = [dict(row) for row in cursor.fetchall()]

    matched_rows: list[dict[str, Any]] = []
    for bookmaker_row in bookmaker_rows:
        started_at = bookmaker_row.get("source_run_started_at")
        reference_date = started_at.date() if isinstance(started_at, datetime) else event_date
        candidate = _candidate_from_row(
            {
                "source_name": bookmaker_row.get("source_name"),
                "source_row_id": bookmaker_row.get("id"),
                "sport": bookmaker_row.get("sport"),
                "home_team": bookmaker_row.get("home_team"),
                "away_team": bookmaker_row.get("away_team"),
                "event_datetime_text": bookmaker_row.get("event_datetime_text"),
            },
            source_table="bookmaker_odds",
            reference_date=reference_date,
        )
        if candidate is None or candidate.source_event_date != event_date:
            continue
        matched_rows.append(bookmaker_row)
    return matched_rows


def _attach_best_odds(candidates: list[dict[str, Any]], *, sport: str) -> list[dict[str, Any]]:
    candidates_by_date: dict[date, list[dict[str, Any]]] = {}
    for row in candidates:
        candidates_by_date.setdefault(row["event_date"], []).append(row)

    enriched_rows: list[dict[str, Any]] = []
    for event_date, date_rows in candidates_by_date.items():
        bookmaker_rows = _fetch_best_bookmaker_odds_by_key(sport=sport, event_date=event_date)
        for row in date_rows:
            normalized_home = normalize_team_name(row.get("home_team"))
            normalized_away = normalize_team_name(row.get("away_team"))
            best_odds: float | None = None
            best_source: str | None = None
            for bookmaker_row in bookmaker_rows:
                bookmaker_home = normalize_team_name(bookmaker_row.get("home_team"))
                bookmaker_away = normalize_team_name(bookmaker_row.get("away_team"))
                if not (
                    bookmaker_home == normalized_home or _names_compatible(bookmaker_home, normalized_home)
                ):
                    continue
                if not (
                    bookmaker_away == normalized_away or _names_compatible(bookmaker_away, normalized_away)
                ):
                    continue
                pred_outcome = str(row.get("pred_outcome") or "")
                selected_odds = None
                if pred_outcome == "1":
                    selected_odds = bookmaker_row.get("home_odds")
                elif pred_outcome == "2":
                    selected_odds = bookmaker_row.get("away_odds")
                elif pred_outcome == "X":
                    selected_odds = bookmaker_row.get("draw_odds")
                try:
                    selected_odds = float(selected_odds)
                except (TypeError, ValueError):
                    continue
                if best_odds is None or selected_odds > best_odds:
                    best_odds = selected_odds
                    best_source = str(bookmaker_row.get("source_name") or "")

            enriched = dict(row)
            enriched["selected_odds"] = best_odds
            enriched["bookmaker_source"] = best_source
            enriched_rows.append(enriched)
    return enriched_rows


def _choose_slip_rows(*, sport: str, slip_size: int, min_probability: float) -> list[dict[str, Any]]:
    candidates = _fetch_upcoming_forebet_candidates(sport=sport, min_probability=min_probability)
    if not candidates:
        return []

    grouped: dict[date, list[dict[str, Any]]] = {}
    for row in candidates:
        grouped.setdefault(row["event_date"], []).append(row)

    selected_date = None
    for event_date in sorted(grouped):
        if len(grouped[event_date]) >= slip_size:
            selected_date = event_date
            break
    if selected_date is None:
        selected_date = sorted(grouped)[0]

    day_rows = grouped[selected_date]
    day_rows.sort(key=lambda row: (-(row.get("pred_probability") or 0.0), row.get("home_team") or ""))
    chosen = day_rows[:slip_size]
    return _attach_best_odds(chosen, sport=sport)


def _generate_slips(*, sport: str, slip_size: int, slip_count: int, min_probability: float) -> list[list[dict[str, Any]]]:
    candidates = _fetch_upcoming_forebet_candidates(sport=sport, min_probability=min_probability)
    if not candidates:
        return []

    grouped: dict[date, list[dict[str, Any]]] = {}
    for row in candidates:
        grouped.setdefault(row["event_date"], []).append(row)

    slips: list[list[dict[str, Any]]] = []
    for event_date in sorted(grouped):
        date_rows = grouped[event_date]
        date_rows.sort(key=lambda row: (-(row.get("pred_probability") or 0.0), row.get("home_team") or ""))
        chunk_index = 0
        while chunk_index + slip_size <= len(date_rows) and len(slips) < slip_count:
            chosen = date_rows[chunk_index : chunk_index + slip_size]
            slips.append(_attach_best_odds(chosen, sport=sport))
            chunk_index += slip_size
        if len(slips) >= slip_count:
            break
    return slips


def _format_multi_slip_message(
    *,
    sport: str,
    slips: list[list[dict[str, Any]]],
    slip_size: int,
    requested_count: int,
) -> str:
    if not slips:
        return (
            f"😕 Not enough {sport} games to build {requested_count} × {slip_size}-leg slips right now.\n"
            "Try again after the next data refresh."
        )

    sport_emoji = _SPORT_EMOJIS.get(sport, "🎯")
    leg_nums = ["1️⃣", "2️⃣", "3️⃣", "4️⃣"]

    intro = _llm_text(
        system_prompt="You are BOB, a sharp betting research assistant. Be brief, confident, and honest about risk.",
        user_prompt=(
            f"You built {len(slips)} {slip_size}-leg {sport} slips from {sum(len(s) for s in slips)} "
            "high-probability games (Bronze 70-80%, Silver 80-90%, Gold 90-100%+). "
            "Write one short punchy sentence introducing these slips and reminding the user that no win is guaranteed."
        ),
        fallback_text=(
            f"Here are your {len(slips)} {sport} slips — high-probability picks, but no win is ever guaranteed."
        ),
    )

    lines = [f"{sport_emoji} <b>{_he(intro)}</b>", ""]

    for slip_index, slip_rows in enumerate(slips, start=1):
        first_date = slip_rows[0].get("event_date")
        date_str = (
            f"{first_date.day} {first_date.strftime('%b %Y')}"
            if isinstance(first_date, date)
            else "TBD"
        )
        combined_odds = 1.0
        _FALLBACK_ODDS = 1.5

        lines.append(f"━━━━━━━━━━━━━━━━━━━━━━")
        lines.append(f"📋 <b>Slip {slip_index}/{len(slips)}</b>  ·  {_he(sport.title())} {slip_size}-leg  ·  📅 {date_str}")
        lines.append("")

        for row_index, row in enumerate(slip_rows, start=1):
            num = leg_nums[row_index - 1] if row_index <= len(leg_nums) else f"{row_index}."
            probability = float(row.get("pred_probability") or 0.0)
            odds_value = row.get("selected_odds")
            bucket = str(row.get("probability_bucket") or "")
            tier = _tier_label_from_bucket(bucket) or ""
            tier_emoji = _TIER_EMOJIS.get(tier, "")
            outcome = str(row.get("pred_outcome") or "")
            outcome_label = _OUTCOME_LABELS.get(outcome, outcome)

            if isinstance(odds_value, float):
                display_odds = odds_value
                bookmaker = _he(row.get("bookmaker_source") or "")
                odds_part = f"<b>{display_odds:.2f}</b>" + (f" via {bookmaker}" if bookmaker else "")
            else:
                display_odds = _FALLBACK_ODDS
                odds_part = f"<b>~{display_odds:.2f}</b> <i>(estimated)</i>"

            combined_odds *= display_odds

            lines.append(f"  {num} <b>{_he(row.get('home_team'))} vs {_he(row.get('away_team'))}</b>")
            lines.append(f"      ✅ <b>{_he(outcome)}</b> ({_he(outcome_label)})  ·  📊 <b>{probability:.1f}%</b> {tier_emoji}")
            lines.append(f"      💰 {odds_part}")
            lines.append("")

        lines.append(
            f"  💎 <b>Combined: {combined_odds:.2f}x</b>  ·  "
            f"KES 500 → ~KES {combined_odds * 500:,.0f}  ·  KES 1,000 → ~KES {combined_odds * 1000:,.0f}"
        )
        lines.append("")

    lines.append("━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("💬 Ask: <i>more slips · football only · basketball only</i>")
    return "\n".join(lines).strip()


def _format_slip_message(*, sport: str, slip_rows: list[dict[str, Any]], slip_size: int) -> str:
    if not slip_rows:
        return (
            f"😕 No {slip_size}-leg {sport} slip available right now.\n"
            "Try again after the next data refresh."
        )

    sport_emoji = _SPORT_EMOJIS.get(sport, "🎯")
    event_date = slip_rows[0].get("event_date")
    date_str = (
        f"{event_date.day} {event_date.strftime('%b %Y')}"
        if isinstance(event_date, date)
        else "TBD"
    )

    first_time = slip_rows[0].get("event_time") or ""
    time_part = f"  ·  🕐 KO from {first_time}" if first_time else ""
    lines = [
        f"{sport_emoji} <b>BOB {slip_size}-Leg {_he(sport.title())} Slip</b>",
        f"📅 <b>Date:</b> {date_str}{time_part}",
        "",
    ]

    _FALLBACK_ODDS = 1.5
    combined_odds = 1.0

    leg_nums = ["1️⃣", "2️⃣", "3️⃣", "4️⃣"]
    for idx, row in enumerate(slip_rows, start=1):
        num = leg_nums[idx - 1] if idx <= len(leg_nums) else f"{idx}."
        probability = float(row.get("pred_probability") or 0.0)
        odds_value = row.get("selected_odds")
        bucket = str(row.get("probability_bucket") or "")
        tier = _tier_label_from_bucket(bucket) or ""
        tier_emoji = _TIER_EMOJIS.get(tier, "")
        outcome = str(row.get("pred_outcome") or "")
        outcome_label = _OUTCOME_LABELS.get(outcome, outcome)
        league = _he(row.get("league") or "")

        if isinstance(odds_value, float):
            display_odds = odds_value
            bookmaker = _he(row.get("bookmaker_source") or "")
            odds_line = f"   💰 Odds: <b>{display_odds:.2f}</b>" + (f" via {bookmaker}" if bookmaker else "")
        else:
            display_odds = _FALLBACK_ODDS
            odds_line = f"   💰 Odds: <b>~{display_odds:.2f}</b> <i>(estimated)</i>"

        combined_odds *= display_odds

        lines.append(f"{num} <b>{_he(row.get('home_team'))} vs {_he(row.get('away_team'))}</b>")
        if league:
            lines.append(f"   🏟 {league}")
        lines.append(f"   ✅ Pick: <b>{_he(outcome)} ({_he(outcome_label)})</b>")
        lines.append(f"   📊 <b>{probability:.1f}%</b>  {tier_emoji} {_he(tier)} ({_he(bucket)})")
        lines.append(odds_line)
        lines.append("")

    lines.append(f"💎 <b>Combined odds: {combined_odds:.2f}x</b>")
    lines.append(f"💵 KES 500 → ~KES {combined_odds * 500:,.0f}  ·  KES 1,000 → ~KES {combined_odds * 1000:,.0f}")

    return "\n".join(lines).strip()


def _store_bot_slip(*, user_id: int | None, update: Update, sport: str, slip_size: int, slip_rows: list[dict[str, Any]]) -> None:
    if update.effective_chat is None or not slip_rows:
        return
    event_date = slip_rows[0].get("event_date")
    combined_odds = 1.0
    odds_found = False
    for row in slip_rows:
        selected_odds = row.get("selected_odds")
        if isinstance(selected_odds, float):
            combined_odds *= selected_odds
            odds_found = True
    if not odds_found:
        combined_odds = None

    with get_postgres_connection(autocommit=True) as connection:
        slip_id = insert_bot_slip(
            connection,
            user_id=user_id,
            channel=CHANNEL_TELEGRAM,
            chat_id=str(update.effective_chat.id),
            sport=sport,
            slip_size=slip_size,
            stake_kes=None,
            bucket_labels=sorted(
                {
                    f"{_tier_label_from_bucket(str(row.get('probability_bucket') or '')) or str(row.get('probability_bucket') or '')}"
                    f" ({str(row.get('probability_bucket') or '')})"
                    for row in slip_rows
                    if row.get("probability_bucket")
                }
            ),
            source_logic="telegram_prototype_high_probability",
            status="pending",
            event_date=event_date if isinstance(event_date, date) else None,
            total_combined_odds=combined_odds,
            predicted_payout_kes=None,
            metadata_json={"bucket_pool": list(PROBABILITY_BUCKETS)},
        )
        insert_bot_slip_legs(
            connection,
            slip_id=slip_id,
            rows=[
                {
                    "leg_no": index,
                    "sport": sport,
                    "event_date": row.get("event_date"),
                    "event_datetime_text": row.get("event_datetime_text"),
                    "source_name": row.get("source_name"),
                    "competition": row.get("league"),
                    "home_team": row.get("home_team"),
                    "away_team": row.get("away_team"),
                    "match_url": row.get("match_url"),
                    "pred_outcome": row.get("pred_outcome"),
                    "pred_probability": row.get("pred_probability"),
                    "probability_bucket": row.get("probability_bucket"),
                    "selected_odds": row.get("selected_odds"),
                    "bookmaker_source": row.get("bookmaker_source"),
                    "metadata_json": {"confidence": row.get("confidence")},
                }
                for index, row in enumerate(slip_rows, start=1)
            ],
        )


def _store_generated_slips(
    *,
    user_id: int | None,
    update: Update,
    sport: str,
    slip_size: int,
    slips: list[list[dict[str, Any]]],
) -> None:
    for slip_rows in slips:
        _store_bot_slip(user_id=user_id, update=update, sport=sport, slip_size=slip_size, slip_rows=slip_rows)


def _fetch_profile_for_update(update: Update) -> dict[str, Any] | None:
    with get_postgres_connection() as connection:
        return fetch_bot_user_profile(
            connection,
            channel=CHANNEL_TELEGRAM,
            channel_user_id=str(update.effective_user.id),
        )


async def _send_onboarding_prompt(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    user_id: int,
    stage: str,
) -> None:
    if stage == "terms":
        await _reply_logged(
            update,
            context,
            "👋 Welcome to BOB!\n\n"
            "I'm your betting research assistant — I analyze games and build smart slips from high-probability data.\n\n"
            "Tap I Agree to accept the Terms of Use and consent to BOB storing your profile and slip history.\n\n"
            "Bet responsibly. Wins are never guaranteed.",
            user_id=user_id,
            intent="intro",
            reply_markup=_build_consent_keyboard("terms"),
        )
        return
    if stage == "preferred_name":
        await _reply_logged(
            update,
            context,
            "What should I call you? Your first name or a nickname works great.",
            user_id=user_id,
            intent="preferred_name_prompt",
            reply_markup=ReplyKeyboardRemove(),
        )
        return
    if stage == "preferred_sports":
        await _reply_logged(
            update,
            context,
            "Which sport should I focus on? ⚽ Football, 🏀 Basketball, or both?",
            user_id=user_id,
            intent="sport_prompt",
            reply_markup=_build_simple_keyboard(["Football ⚽", "Basketball 🏀", "Both"]),
        )
        return
    if stage == "risk_profile":
        await _reply_logged(
            update,
            context,
            "Last one — what's your betting style?\n\n"
            "🛡 Cautious — safer picks, 3-leg slips\n"
            "⚖️ Balanced — mix of value and safety, 3-leg slips\n"
            "🔥 Aggressive — higher odds, 4-leg slips",
            user_id=user_id,
            intent="risk_prompt",
            reply_markup=_build_simple_keyboard(["🛡 Cautious", "⚖️ Balanced", "🔥 Aggressive"]),
        )
        return


async def _complete_onboarding_if_possible(update: Update, context: ContextTypes.DEFAULT_TYPE, *, user_id: int) -> bool:
    profile = _fetch_profile_for_update(update)
    stage = _profile_stage(profile)
    if stage != "ready":
        await _send_onboarding_prompt(update, context, user_id=user_id, stage=stage)
        return False
    return True


async def _process_onboarding_text(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    user_id: int,
    incoming_text: str,
    profile: dict[str, Any] | None,
) -> bool:
    stage = _profile_stage(profile)
    if stage == "ready":
        return True

    normalized_text = incoming_text.strip()
    normalized_lower = normalized_text.lower()

    with get_postgres_connection(autocommit=True) as connection:
        if stage == "terms":
            if _is_affirmative(normalized_text):
                upsert_bot_user_consents(
                    connection,
                    user_id=user_id,
                    terms_accepted=True,
                    terms_accepted_at=_now_utc(),
                    data_processing_consent=True,
                    data_processing_consent_at=_now_utc(),
                )
            else:
                await _reply_logged(
                    update,
                    context,
                    "To continue with BOB, please tap I Agree to accept the terms.",
                    user_id=user_id,
                    intent="terms_text_retry",
                    reply_markup=_build_consent_keyboard("terms"),
                )
                return False
        elif stage == "preferred_name":
            upsert_bot_user(
                connection,
                channel=CHANNEL_TELEGRAM,
                channel_user_id=str(update.effective_user.id),
                chat_id=str(update.effective_chat.id),
                username=update.effective_user.username,
                first_name=update.effective_user.first_name,
                last_name=update.effective_user.last_name,
                pseudo_name=normalized_text,
                last_seen_at=_now_utc(),
            )
            upsert_bot_user_preferences(
                connection,
                user_id=user_id,
                preferred_name=normalized_text,
            )
        elif stage == "preferred_sports":
            upsert_bot_user_preferences(
                connection,
                user_id=user_id,
                preferred_sports=_normalize_sport_choice(normalized_text),
            )
        elif stage == "risk_profile":
            clean_risk = re.sub(r"[^a-z]", "", normalized_lower)
            derived_slip_size = 4 if clean_risk == "aggressive" else 3
            upsert_bot_user_preferences(
                connection,
                user_id=user_id,
                risk_profile=clean_risk,
                preferred_slip_size=derived_slip_size,
                service_mode="both",
                betting_frequency="regular",
            )
        else:
            await _send_onboarding_prompt(update, context, user_id=user_id, stage=stage)
            return False

    refreshed_profile = _fetch_profile_for_update(update)
    next_stage = _profile_stage(refreshed_profile)
    if next_stage == "ready":
        completion_text = _llm_text(
            system_prompt="You are BoB, a warm betting research assistant. Congratulate the user briefly and explain what they can ask next.",
            user_prompt=(
                "The user has finished onboarding. Mention that BoB can answer natural questions about today's games, create multiple slips, "
                "and summarize performance. Mention that the current prototype focuses on Bronze 70-80, Silver 80-90, and Gold 90-100 pools."
            ),
            fallback_text=(
                "You're all set. You can now ask me natural questions like 'what games do we have today?' or 'give me 3 football slips'. "
                "I currently focus on Bronze (70-80%), Silver (80-90%), and Gold (90-100%) pools."
            ),
        )
        await _reply_logged(update, context, completion_text, user_id=user_id, intent="onboarding_complete", reply_markup=ReplyKeyboardRemove())
        return True

    await _send_onboarding_prompt(update, context, user_id=user_id, stage=next_stage)
    return False


async def _reply_with_games_today(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    user_id: int,
    profile: dict[str, Any],
    target_date: date | None = None,
) -> None:
    preferred_sports = list(profile.get("preferred_sports_json") or ["football"])
    today = date.today()
    tomorrow = today + timedelta(days=1)

    # Decide which dates to display
    if target_date is not None:
        dates_to_show = [(target_date, target_date.strftime("%A %-d %b") if hasattr(date, "strftime") else str(target_date))]
    else:
        dates_to_show = [(today, "Today"), (tomorrow, "Tomorrow")]

    games_by_sport: dict[str, list[dict[str, Any]]] = {}
    for sport in preferred_sports:
        candidates = _fetch_upcoming_forebet_candidates(sport=sport, min_probability=60.0)
        games_by_sport[sport] = candidates

    total_visible = sum(
        len([r for r in rows if r.get("event_date") in {d for d, _ in dates_to_show}])
        for rows in games_by_sport.values()
    )
    if total_visible == 0:
        label = "tomorrow" if target_date == tomorrow else "today"
        await _reply_logged(
            update,
            context,
            f"No upcoming games found for {label}. Try again after the next data refresh.",
            user_id=user_id,
            intent="games_today_empty",
        )
        return

    lines: list[str] = []
    leg_nums = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣"]

    for sport, all_rows in games_by_sport.items():
        sport_emoji = _SPORT_EMOJIS.get(sport, "🎯")
        for show_date, label in dates_to_show:
            rows = [r for r in all_rows if r.get("event_date") == show_date][:6]
            if not rows:
                continue
            date_str = (
                show_date.strftime("%A, %d %b")
                if show_date not in (today, tomorrow)
                else label
            )
            lines.append(f"{sport_emoji} <b>{_he(sport.title())} — {_he(date_str)}'s Picks</b>")
            lines.append("")
            for idx, row in enumerate(rows, start=1):
                num = leg_nums[idx - 1] if idx <= len(leg_nums) else f"{idx}."
                probability = float(row.get("pred_probability") or 0.0)
                bucket = str(row.get("probability_bucket") or "")
                tier = _tier_label_from_bucket(bucket) or ""
                tier_emoji = _TIER_EMOJIS.get(tier, "")
                outcome = str(row.get("pred_outcome") or "")
                outcome_label = _OUTCOME_LABELS.get(outcome, outcome)
                time_str = row.get("event_time") or ""
                time_part = f"  🕐 {time_str}" if time_str else ""
                lines.append(
                    f"  {num} <b>{_he(row.get('home_team'))} vs {_he(row.get('away_team'))}</b>{time_part}\n"
                    f"      ✅ {_he(outcome_label)}  ·  📊 <b>{probability:.1f}%</b>"
                    + (f" {tier_emoji} {_he(tier)}" if tier else "")
                )
            lines.append("")

    lines.append("━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("💬 Ask: <i>give me 3 football slips · give me 4-leg slip · tomorrow's games</i>")
    await _reply_logged(update, context, "\n".join(lines).strip(), user_id=user_id, intent="games_today", parse_mode="HTML")


async def _reply_with_slips(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    user_id: int,
    profile: dict[str, Any],
    request_text: str,
) -> None:
    preferred_sports = list(profile.get("preferred_sports_json") or ["football"])
    sport = _detect_sport_from_text(request_text, preferred_sports)
    default_slip_size = int(profile.get("preferred_slip_size") or 3)
    slip_size = _detect_slip_size_from_text(request_text, default_value=default_slip_size)
    slip_count = _detect_slip_count_from_text(request_text, default_value=3)
    slips = _generate_slips(sport=sport, slip_size=slip_size, slip_count=slip_count, min_probability=70.0)
    _store_generated_slips(user_id=user_id, update=update, sport=sport, slip_size=slip_size, slips=slips)
    message = _format_multi_slip_message(
        sport=sport,
        slips=slips,
        slip_size=slip_size,
        requested_count=slip_count,
    )
    await _reply_logged(update, context, message, user_id=user_id, intent="multi_slip_response", parse_mode="HTML")


async def _reply_with_general_answer(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    user_id: int,
    profile: dict[str, Any],
    request_text: str,
) -> None:
    preferred_name = profile.get("preferred_name") or profile.get("pseudo_name") or profile.get("first_name") or "there"
    response_text = _llm_text(
        system_prompt=(
            "You are BoB, a conversational betting research assistant. "
            "Reply naturally, explain what you can do, and suggest the next useful action. "
            "Do not promise guaranteed winnings."
        ),
        user_prompt=(
            f"User name: {preferred_name}. "
            f"User message: {request_text}. "
            "Available capabilities: explain today's games, generate football or basketball slips, summarize profile, and later performance. "
            "Write a short natural reply that answers and nudges the user toward asking for games or slips."
        ),
        fallback_text=(
            f"Hi {preferred_name}. I can help you with today's games, generate football or basketball slips, "
            "and explain the high-probability pools. Try asking 'what games do we have today?' or 'give me 3 football slips'."
        ),
    )
    await _reply_logged(update, context, response_text, user_id=user_id, intent="general_conversational_reply")


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    _log_update_received(update)
    user_id = _ensure_bot_user(update)
    incoming_text = update.effective_message.text if update.effective_message else "/start"
    _log_conversation(user_id=user_id, update=update, direction="inbound", text=incoming_text, intent="start")
    context.user_data.clear()
    context.user_data["bot_user_id"] = user_id
    intro_text = (
        "⚽🔥 Bonga na BOB — Cheza Smart, Si Kubahatisha.\n\n"
        "I'm BOB, your betting research assistant.\n\n"
        "I analyze games and build high-probability 3-leg and 4-leg slips from Bronze (70-80%), "
        "Silver (80-90%), and Gold (90-100%+) pools.\n\n"
        "Tap ✅ I Agree to accept the Terms of Use and consent to BOB storing your profile and slip history.\n\n"
        "Bet responsibly — wins are never guaranteed."
    )
    await _reply_logged(
        update,
        context,
        intro_text,
        user_id=user_id,
        intent="intro",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ I Agree", callback_data="terms:yes"),
            InlineKeyboardButton("❌ No Thanks", callback_data="terms:no"),
        ]]),
    )
    return STATE_TERMS


async def profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _log_update_received(update)
    user_id = _ensure_bot_user(update)
    incoming_text = update.effective_message.text if update.effective_message else "/profile"
    _log_conversation(user_id=user_id, update=update, direction="inbound", text=incoming_text, intent="profile")
    profile = _fetch_profile_for_update(update)
    if not profile:
        await _send_onboarding_prompt(update, context, user_id=user_id, stage="terms")
        return
    sports = ", ".join(profile.get("preferred_sports_json") or []) or "not set"
    message = (
        f"Profile summary\n"
        f"Name: {profile.get('preferred_name') or profile.get('pseudo_name') or profile.get('first_name') or 'n/a'}\n"
        f"Telegram: @{profile.get('username') or 'n/a'}\n"
        f"Phone: {profile.get('phone_number') or 'not shared'}\n"
        f"Sports: {sports}\n"
        f"Service mode: {profile.get('service_mode') or 'not set'}\n"
        f"Preferred slip size: {profile.get('preferred_slip_size') or 'not set'}\n"
        f"Marketing consent: {'yes' if profile.get('marketing_consent') else 'no'}"
    )
    await _reply_logged(update, context, message, user_id=user_id, intent="profile_summary")


async def _deliver_slip(update: Update, context: ContextTypes.DEFAULT_TYPE, *, slip_size: int) -> None:
    _log_update_received(update)
    user_id = _ensure_bot_user(update)
    incoming_text = update.effective_message.text if update.effective_message else f"/slip{slip_size}"
    _log_conversation(user_id=user_id, update=update, direction="inbound", text=incoming_text, intent=f"slip_{slip_size}")

    profile = _fetch_profile_for_update(update)
    stage = _profile_stage(profile)
    if stage != "ready":
        await _send_onboarding_prompt(update, context, user_id=user_id, stage=stage)
        return

    preferred_sports = list(profile.get("preferred_sports_json") or [])
    requested_sport = None
    if context.args:
        requested_sport = str(context.args[0]).strip().lower()
    if requested_sport not in {"football", "basketball"}:
        requested_sport = preferred_sports[0] if preferred_sports else "football"

    slip_rows = _choose_slip_rows(sport=requested_sport, slip_size=slip_size, min_probability=70.0)
    _store_bot_slip(user_id=user_id, update=update, sport=requested_sport, slip_size=slip_size, slip_rows=slip_rows)
    message = _format_slip_message(sport=requested_sport, slip_rows=slip_rows, slip_size=slip_size)
    await _reply_logged(update, context, message, user_id=user_id, intent=f"slip_{slip_size}_response", parse_mode="HTML")


async def slip3_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _deliver_slip(update, context, slip_size=3)


async def slip4_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _deliver_slip(update, context, slip_size=4)


async def today_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _log_update_received(update)
    user_id = _ensure_bot_user(update)
    incoming_text = update.effective_message.text if update.effective_message else "/today"
    _log_conversation(user_id=user_id, update=update, direction="inbound", text=incoming_text, intent="today")
    profile = _fetch_profile_for_update(update)
    stage = _profile_stage(profile)
    if stage != "ready":
        await _send_onboarding_prompt(update, context, user_id=user_id, stage=stage)
        return
    slip_size = int(profile.get("preferred_slip_size") or 3)
    await _deliver_slip(update, context, slip_size=slip_size)


async def terms_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    user_id = int(context.user_data.get("bot_user_id") or _ensure_bot_user(update))
    accepted = query.data.endswith(":yes")
    with get_postgres_connection(autocommit=True) as connection:
        upsert_bot_user_consents(
            connection,
            user_id=user_id,
            terms_accepted=accepted,
            terms_accepted_at=_now_utc() if accepted else None,
            data_processing_consent=accepted,
            data_processing_consent_at=_now_utc() if accepted else None,
        )
    if not accepted:
        await query.edit_message_text("No problem. Come back with /start whenever you're ready.")
        _log_conversation(user_id=user_id, update=update, direction="outbound", text="Terms declined.", intent="terms_declined")
        return ConversationHandler.END
    await query.edit_message_text("✅ Done! What should I call you? Share your first name or a nickname.")
    _log_conversation(user_id=user_id, update=update, direction="outbound", text="Asked for preferred name.", intent="preferred_name_prompt")
    return STATE_PREFERRED_NAME


async def data_consent_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    user_id = int(context.user_data.get("bot_user_id") or _ensure_bot_user(update))
    accepted = query.data.endswith(":yes")
    with get_postgres_connection(autocommit=True) as connection:
        upsert_bot_user_consents(
            connection,
            user_id=user_id,
            data_processing_consent=accepted,
            data_processing_consent_at=_now_utc() if accepted else None,
        )
    if not accepted:
        await query.edit_message_text("Understood. I cannot continue without data processing consent, so the onboarding will stop here.")
        _log_conversation(user_id=user_id, update=update, direction="outbound", text="Data processing consent declined.", intent="data_consent_declined")
        return ConversationHandler.END
    await query.edit_message_text("Great. What should I call you? You can share your preferred name or nickname.")
    _log_conversation(user_id=user_id, update=update, direction="outbound", text="Asked for preferred name after data consent.", intent="preferred_name_prompt")
    return STATE_PREFERRED_NAME


async def marketing_consent_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    user_id = int(context.user_data.get("bot_user_id") or _ensure_bot_user(update))
    accepted = query.data.endswith(":yes")
    with get_postgres_connection(autocommit=True) as connection:
        upsert_bot_user_consents(
            connection,
            user_id=user_id,
            marketing_consent=accepted,
            marketing_consent_at=_now_utc() if accepted else None,
        )
    await query.edit_message_text("Thanks. If you want, share your phone number now. This is optional for the Telegram prototype.")
    await update.effective_chat.send_message(
        "Share your phone number or tap Skip.",
        reply_markup=_build_phone_keyboard(),
    )
    _log_conversation(user_id=user_id, update=update, direction="outbound", text="Asked for optional phone number.", intent="phone_prompt")
    return STATE_PHONE


async def phone_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    _log_update_received(update)
    user_id = int(context.user_data.get("bot_user_id") or _ensure_bot_user(update))
    phone_number = None
    if update.effective_message and update.effective_message.contact:
        phone_number = update.effective_message.contact.phone_number
    elif update.effective_message and str(update.effective_message.text or "").strip().lower() == "skip":
        phone_number = None
    else:
        await _reply_logged(update, context, "Please share your phone number with the button or tap Skip.", user_id=user_id, intent="phone_retry", reply_markup=_build_phone_keyboard())
        return STATE_PHONE

    with get_postgres_connection(autocommit=True) as connection:
        upsert_bot_user(
            connection,
            channel=CHANNEL_TELEGRAM,
            channel_user_id=str(update.effective_user.id),
            chat_id=str(update.effective_chat.id),
            username=update.effective_user.username,
            first_name=update.effective_user.first_name,
            last_name=update.effective_user.last_name,
            phone_number=phone_number,
            last_seen_at=_now_utc(),
        )
    await _reply_logged(update, context, "What should I call you? You can share your preferred name or nickname.", user_id=user_id, intent="preferred_name_prompt", reply_markup=ReplyKeyboardRemove())
    return STATE_PREFERRED_NAME


async def preferred_name_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    _log_update_received(update)
    user_id = int(context.user_data.get("bot_user_id") or _ensure_bot_user(update))
    preferred_name = str(update.effective_message.text or "").strip()
    context.user_data["preferred_name"] = preferred_name
    _log_conversation(user_id=user_id, update=update, direction="inbound", text=preferred_name, intent="preferred_name")
    await _reply_logged(
        update,
        context,
        "Which sport do you want BoB to focus on first?",
        user_id=user_id,
        intent="sport_prompt",
        reply_markup=_build_simple_keyboard(["football", "basketball", "both"]),
    )
    return STATE_SPORT


async def sport_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    _log_update_received(update)
    user_id = int(context.user_data.get("bot_user_id") or _ensure_bot_user(update))
    sport_choice = str(update.effective_message.text or "").strip()
    context.user_data["preferred_sports"] = _normalize_sport_choice(sport_choice)
    _log_conversation(user_id=user_id, update=update, direction="inbound", text=sport_choice, intent="preferred_sport")
    await _reply_logged(
        update,
        context,
        "Are you a regular bettor or an occasional bettor?",
        user_id=user_id,
        intent="frequency_prompt",
        reply_markup=_build_simple_keyboard(["regular", "occasional"]),
    )
    return STATE_FREQUENCY


async def frequency_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    _log_update_received(update)
    user_id = int(context.user_data.get("bot_user_id") or _ensure_bot_user(update))
    betting_frequency = str(update.effective_message.text or "").strip().lower()
    context.user_data["betting_frequency"] = betting_frequency
    _log_conversation(user_id=user_id, update=update, direction="inbound", text=betting_frequency, intent="betting_frequency")
    await _reply_logged(
        update,
        context,
        "How do you want BoB to help you most?",
        user_id=user_id,
        intent="service_mode_prompt",
        reply_markup=_build_simple_keyboard(["ready-made slips", "research mode", "both"]),
    )
    return STATE_SERVICE_MODE


async def service_mode_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    _log_update_received(update)
    user_id = int(context.user_data.get("bot_user_id") or _ensure_bot_user(update))
    service_mode = str(update.effective_message.text or "").strip().lower()
    context.user_data["service_mode"] = service_mode
    _log_conversation(user_id=user_id, update=update, direction="inbound", text=service_mode, intent="service_mode")
    await _reply_logged(
        update,
        context,
        "Which slip size do you prefer to start with?",
        user_id=user_id,
        intent="slip_size_prompt",
        reply_markup=_build_simple_keyboard(["3", "4"]),
    )
    return STATE_SLIP_SIZE


async def slip_size_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    _log_update_received(update)
    user_id = int(context.user_data.get("bot_user_id") or _ensure_bot_user(update))
    slip_size_text = str(update.effective_message.text or "").strip()
    preferred_slip_size = 4 if slip_size_text == "4" else 3
    context.user_data["preferred_slip_size"] = preferred_slip_size
    _log_conversation(user_id=user_id, update=update, direction="inbound", text=slip_size_text, intent="preferred_slip_size")
    await _reply_logged(
        update,
        context,
        "What risk style fits you best?",
        user_id=user_id,
        intent="risk_prompt",
        reply_markup=_build_simple_keyboard(["cautious", "balanced", "aggressive"]),
    )
    return STATE_RISK


async def risk_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    _log_update_received(update)
    user_id = int(context.user_data.get("bot_user_id") or _ensure_bot_user(update))
    risk_profile = str(update.effective_message.text or "").strip().lower()
    _log_conversation(user_id=user_id, update=update, direction="inbound", text=risk_profile, intent="risk_profile")
    with get_postgres_connection(autocommit=True) as connection:
        upsert_bot_user(
            connection,
            channel=CHANNEL_TELEGRAM,
            channel_user_id=str(update.effective_user.id),
            chat_id=str(update.effective_chat.id),
            username=update.effective_user.username,
            first_name=update.effective_user.first_name,
            last_name=update.effective_user.last_name,
            pseudo_name=context.user_data.get("preferred_name"),
            last_seen_at=_now_utc(),
        )
        upsert_bot_user_preferences(
            connection,
            user_id=user_id,
            preferred_name=context.user_data.get("preferred_name"),
            preferred_sports=context.user_data.get("preferred_sports"),
            betting_frequency=context.user_data.get("betting_frequency"),
            service_mode=context.user_data.get("service_mode"),
            preferred_slip_size=context.user_data.get("preferred_slip_size"),
            risk_profile=risk_profile,
        )
    await _reply_logged(
        update,
        context,
        "You are all set.\n\n"
        "Use:\n"
        "/profile - see your saved profile\n"
        "/today - get your default high-probability slip\n"
        "/slip3 - get a 3-leg high-probability slip\n"
        "/slip4 - get a 4-leg high-probability slip\n\n"
        "For this prototype, BoB uses only Bronze (70-80%), Silver (80-90%), and Gold (90-100%).",
        user_id=user_id,
        intent="onboarding_complete",
        reply_markup=ReplyKeyboardRemove(),
    )
    return ConversationHandler.END


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    _log_update_received(update)
    user_id = context.user_data.get("bot_user_id")
    _log_conversation(user_id=int(user_id) if user_id else None, update=update, direction="inbound", text="/cancel", intent="cancel")
    await _reply_logged(update, context, "The current onboarding flow has been cancelled. Send /start whenever you want to continue.", user_id=int(user_id) if user_id else None, intent="cancelled", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


async def telegram_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log bot exceptions in a cleaner way during prototype runs."""

    logger.exception("Telegram bot error while handling update: %s", update, exc_info=context.error)


async def fallback_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle natural user text with onboarding-first conversational routing."""

    _log_update_received(update)
    user_id = _ensure_bot_user(update)
    incoming_text = update.effective_message.text if update.effective_message else ""
    _log_conversation(user_id=user_id, update=update, direction="inbound", text=incoming_text, intent="fallback_text")
    profile = _fetch_profile_for_update(update)
    stage = _profile_stage(profile)
    intent = _message_intent(incoming_text)

    if stage != "ready":
        # Let BoB still be useful before full onboarding is complete.
        if intent in ("games_today", "games_tomorrow"):
            td = date.today() + timedelta(days=1) if intent == "games_tomorrow" else None
            await _reply_with_games_today(update, context, user_id=user_id, profile=profile or {}, target_date=td)
            await _reply_logged(
                update,
                context,
                "I can already show you games, but to personalize slips properly I still need to finish your quick onboarding.",
                user_id=user_id,
                intent="onboarding_nudge_after_games",
            )
            return
        if intent == "generate_slips":
            await _reply_with_slips(update, context, user_id=user_id, profile=profile or {}, request_text=incoming_text)
            await _reply_logged(
                update,
                context,
                "I can already draft slips, but to personalize them properly I still need to finish your quick onboarding.",
                user_id=user_id,
                intent="onboarding_nudge_after_slips",
            )
            return
        progressed = await _process_onboarding_text(
            update,
            context,
            user_id=user_id,
            incoming_text=incoming_text,
            profile=profile,
        )
        if not progressed:
            return
        profile = _fetch_profile_for_update(update)

    if intent == "games_today":
        await _reply_with_games_today(update, context, user_id=user_id, profile=profile)
        return
    if intent == "games_tomorrow":
        await _reply_with_games_today(
            update, context, user_id=user_id, profile=profile,
            target_date=date.today() + timedelta(days=1),
        )
        return
    if intent == "generate_slips":
        await _reply_with_slips(update, context, user_id=user_id, profile=profile, request_text=incoming_text)
        return
    if intent == "performance_summary":
        await _reply_logged(
            update,
            context,
            "I'm almost ready for performance follow-up too. For now I can already help with today's games and generate multiple football or basketball slips from the Bronze, Silver, and Gold pools.",
            user_id=user_id,
            intent="performance_stub",
        )
        return
    await _reply_with_general_answer(update, context, user_id=user_id, profile=profile, request_text=incoming_text)


def build_application(config: TelegramBotConfig | None = None) -> Application:
    selected_config = config or TelegramBotConfig.from_env()
    application = (
        Application.builder()
        .token(selected_config.token)
        .connect_timeout(30.0)
        .read_timeout(30.0)
        .write_timeout(30.0)
        .pool_timeout(30.0)
        .build()
    )
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("cancel", cancel_command))
    application.add_handler(CallbackQueryHandler(terms_callback, pattern=r"^terms:(yes|no)$"))
    application.add_handler(CommandHandler("profile", profile_command))
    application.add_handler(CommandHandler("today", today_command))
    application.add_handler(CommandHandler("slip3", slip3_command))
    application.add_handler(CommandHandler("slip4", slip4_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, fallback_text_handler))
    application.add_error_handler(telegram_error_handler)
    return application


def run_polling_bot() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    application = build_application()
    try:
        logger.info("BoB Telegram prototype is running. Open Telegram and send /start to your bot.")
        application.run_polling(drop_pending_updates=True)
    except InvalidToken as exc:
        raise RuntimeError(
            "Telegram bot token was rejected. Recheck TELEGRAM_BOT_TOKEN in the project root .env file."
        ) from exc
    except NetworkError as exc:
        raise RuntimeError(
            "Telegram bot could not reach Telegram's API. "
            "Please confirm this machine has internet access to api.telegram.org and that no proxy/firewall is blocking it."
        ) from exc
    except TelegramError as exc:
        raise RuntimeError(f"Telegram bot startup failed: {exc}") from exc
