"""The market-outlook brief: renderers, the CIO row, and the per-channel delivery plan.

FABLE-OUTLOOK-METHODOLOGY-LQ-946, WU-3 (§4.3 content order, §4.6 CIO record, §4.7 delivery).

Three channels, one record:

  email     the full report as HTML (single column, 600 px, tables of at most four columns)
  telegram  the same report compacted to plain text (the raw Telegram sender takes no parse mode, so
            emitting HTML tags would show them to the operator)
  text      one advisory sentence of at most ``max_chars`` (class ``market_outlook`` in
            ``config/critical_text_classes.json``; D1 raised it to 300 chars), sent through the
            existing Fi email-to-text primitive

Rules this module owns and must not get wrong twice:

  * an UNKNOWN category renders as UNKNOWN with its reason - it is never shown as a zero sub-score,
    because a missing input and a neutral reading are opposite facts (2026-11-08 ruling);
  * nothing here sizes, orders, stops or weights anything: the brief renders the record's stance and
    the CIO's template, and it is the operator's decision what to do with it;
  * the dedupe key is ``record_id:channel``; a channel whose row is already ``sent`` is skipped and
    its receipt is never overwritten, while a channel that failed may be retried (a failed attempt is
    not a delivery, and blocking it forever would lose the channel silently);
  * no address, phone number, account id or holding is stored here or in the policy - the text
    channel resolves the operator's lines in ``critical_texts``, the email target in
    ``critical_delivery``.

Pure functions: rendering, validation, the CIO row, the plan. ``deliver_channels`` takes its senders
and its log reader/writer as arguments so tests exercise the dedupe without a network or a database.
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[2]
POLICY_REL = "config/market_outlook_brief_policy.json"

RECORD_SCHEMA = "MarketOutlookRecord@v1"
CHANNELS = ("email", "telegram", "text")
MODES = ("sunday", "monday", "daily", "event")
BANDS = ("RISK-ON", "NEUTRAL", "DEFENSIVE", "RISK-OFF")
CATEGORY_STATES = ("COLLECTED", "PARTIAL", "UNKNOWN")
CATEGORY_COUNT = 11
RECORD_ID_RE = re.compile(r"^outlook:(\d{4}-\d{2}-\d{2}):(sunday|monday|daily|event):(\d+)$")

#: The primitive's cap when the class row names none. The config is authoritative (D1: 300 for this class).
DEFAULT_MAX_CHARS = 160
#: ``notification_log.dedupe_key`` is varchar(100); a key that cannot fit is refused, never truncated.
MAX_DEDUPE_KEY = 100
#: A text channel with less room than this cannot carry the stance, an action and the record id.
MIN_TEXT_CHARS = 120

EMAIL_SUBJECT_PREFIX = "Trade AI Outlook"
EMAIL_TARGET_REL_CONTACT = "critical_email_to"

#: Statuses that mean "this channel already delivered". Anything else may be attempted again.
DELIVERED_STATUSES = frozenset({"sent"})

CATEGORY_TITLES = {
    "us_cash_indices": "US cash indices",
    "futures_overnight": "Futures / overnight",
    "volatility": "Volatility",
    "breadth": "Breadth",
    "sector_rotation": "Sectors / rotation",
    "global": "Global",
    "rates_dollar": "Rates / dollar",
    "credit": "Credit",
    "commodities_crypto": "Commodities / crypto",
    "macro_events": "Macro / events",
    "positioning": "Positioning",
}


class BriefError(ValueError):
    """A brief was asked for something it must not render or send."""


# --------------------------------------------------------------------------------------------------
# policy / record loading
# --------------------------------------------------------------------------------------------------
def _read_json(path: Path) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        raise BriefError(f"unreadable: {Path(path).name} ({type(exc).__name__})") from exc


def load_policy(path: Optional[Path] = None) -> dict[str, Any]:
    """The rendering constants. A missing or broken file refuses: defaults here would be silent drift."""
    target = Path(path) if path else PROJECT_ROOT / POLICY_REL
    doc = _read_json(target)
    if not isinstance(doc, dict):
        raise BriefError(f"market outlook brief policy missing or not an object: {target.name}")
    if doc.get("schema") != "MarketOutlookBriefPolicy@v1":
        raise BriefError(f"market outlook brief policy has the wrong schema: {doc.get('schema')!r}")
    for key in ("html_width_px", "telegram_max_chars", "channels_default", "action_short_by_band"):
        if key not in doc:
            raise BriefError(f"market outlook brief policy is missing {key!r}")
    return doc


def load_record_file(path: Path) -> dict[str, Any]:
    """Read one record from disk, adapt the engine's shape, then validate. Every defect is named.

    Adaptation is the documented ``normalize_record`` mapping, not a repair: ranges become absolute
    from the record's own ATR band and anchor, thin level sides are padded so they render ``n/a``,
    and a bare digest gains its algorithm prefix. No value is invented and no reading is guessed.
    """
    doc = _read_json(Path(path))
    if not isinstance(doc, dict):
        raise BriefError(f"record is missing or not an object: {Path(path).name}")
    doc = normalize_record(doc)
    errors = validate_record(doc)
    if errors:
        raise BriefError("record refused: " + "; ".join(errors))
    return doc


def _stamp(value: Any) -> Optional[datetime]:
    try:
        at = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return at if at.tzinfo is not None else None


#: ``scenarios.<name>.<index>_range`` names the index whose key levels anchor the absolute band.
RANGE_INDEXES = {"spx_range": "SPX", "ndx_range": "NDX", "rut_range": "RUT"}
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
LEVEL_SIDES = ("support", "resistance")
MAX_LEVELS_PER_SIDE = 3
UNRENDERABLE = "n/a"


def _anchor(record: Mapping[str, Any], index_key: str) -> Optional[float]:
    """The close the engine measured levels against, recovered from any level's ``distance_pct``.

    The engine states each level as ``{level, distance_pct, source}``, so ``level / (1 +
    distance_pct/100)`` is the anchor for both sides. The first usable level wins; with no levels
    there is no anchor and a band that needs one renders ``n/a``.
    """
    levels = record.get("key_levels")
    row = levels.get(index_key) if isinstance(levels, Mapping) else None
    if not isinstance(row, Mapping):
        return None
    for side in LEVEL_SIDES:
        for item in row.get(side) or []:
            if not isinstance(item, Mapping):
                continue
            level, distance = item.get("level"), item.get("distance_pct")
            if not isinstance(level, (int, float)) or isinstance(level, bool):
                continue
            if not isinstance(distance, (int, float)) or isinstance(distance, bool):
                continue
            divisor = 1.0 + float(distance) / 100.0
            if divisor > 0:
                return float(level) / divisor
    return None


def _absolute_pair(value: Any, anchor: Optional[float]) -> Any:
    """A scenario band as absolute ``[low, high]`` index levels.

    The engine emits percent multiples of the anchor close - ``{low_1atr, high_1atr, low_2atr,
    high_2atr}``, where 1 ATR is one weekly ATR in percent. The brief states absolute levels, so the
    1-ATR band is applied to the anchor: ``anchor * (1 + multiple/100)``, rounded to 0.1. An already
    absolute pair passes through untouched; a band with no derivable anchor is ``[None, None]`` and
    the brief prints ``n/a`` rather than refusing the whole record.
    """
    if isinstance(value, (list, tuple)) and len(value) == 2:
        return list(value)
    if isinstance(value, Mapping):
        low, high = value.get("low_1atr"), value.get("high_1atr")
        if isinstance(low, (int, float)) and isinstance(high, (int, float)):
            if anchor is None:
                return [None, None]
            return [round(anchor * (1.0 + float(low) / 100.0), 1),
                    round(anchor * (1.0 + float(high) / 100.0), 1)]
    return value


def _level_numbers(values: Any) -> list[Any]:
    """A levels side as numbers in the record's order, at most three, padded with ``None`` to render ``n/a``.

    ``None`` is "this side has fewer than three levels", which the brief states; it is not a level.
    """
    out: list[Any] = []
    for item in values if isinstance(values, (list, tuple)) else []:
        if isinstance(item, Mapping):
            item = item.get("level")
        out.append(item if isinstance(item, (int, float)) and not isinstance(item, bool) else None)
    if len(out) >= MAX_LEVELS_PER_SIDE:
        return out  # an over-full side stays over-full so validation names it instead of truncating
    return (out + [None] * MAX_LEVELS_PER_SIDE)[:MAX_LEVELS_PER_SIDE]


def normalize_record(record: Any) -> Any:
    """The engine's ``MarketOutlookRecord@v1`` adapted to the brief's rendering contract.

    Idempotent, copy-on-write, and values are only ever transformed:

    * ``scenarios.<name>.<index>_range``: the engine's ATR-multiple dict becomes the absolute
      ``[low, high]`` of its 1-ATR band, anchored on the index's own key levels (see ``_anchor``);
    * ``key_levels.<INDEX>.<side>``: ``{level, source, ...}`` rows become the levels; a side with
      fewer than three is padded with ``None`` so it renders what exists plus ``n/a``;
    * ``inputs_snapshot_hash``: a bare 64-hex digest gains the ``sha256:`` prefix it names.

    Anything already in the brief's own shape is returned as it was.
    """
    if not isinstance(record, Mapping):
        return record
    out = dict(record)

    levels = record.get("key_levels")
    if isinstance(levels, Mapping):
        adapted_levels: dict[str, Any] = {}
        for name, row in levels.items():
            if isinstance(row, Mapping):
                adapted = dict(row)
                for side in LEVEL_SIDES:
                    if side in adapted:
                        adapted[side] = _level_numbers(adapted[side])
                adapted_levels[name] = adapted
            else:
                adapted_levels[name] = row
        out["key_levels"] = adapted_levels

    scenarios = record.get("scenarios")
    if isinstance(scenarios, Mapping):
        adapted_scenarios: dict[str, Any] = {}
        for name, row in scenarios.items():
            if isinstance(row, Mapping):
                adapted = dict(row)
                for band_key, index_key in RANGE_INDEXES.items():
                    if band_key in adapted:
                        adapted[band_key] = _absolute_pair(adapted[band_key], _anchor(record, index_key))
                adapted_scenarios[name] = adapted
            else:
                adapted_scenarios[name] = row
        out["scenarios"] = adapted_scenarios

    digest = out.get("inputs_snapshot_hash")
    if isinstance(digest, str) and HEX64_RE.match(digest):
        out["inputs_snapshot_hash"] = "sha256:" + digest
    return out


def validate_record(record: Mapping[str, Any]) -> list[str]:
    """Every reason the record cannot be briefed. Empty means it can. The engine's shape is accepted."""
    e: list[str] = []
    if not isinstance(record, Mapping):
        return ["record is not an object"]
    record = normalize_record(record)
    if record.get("schema") != RECORD_SCHEMA:
        e.append(f"schema is {record.get('schema')!r}, expected {RECORD_SCHEMA!r}")

    record_id = str(record.get("record_id") or "")
    if not RECORD_ID_RE.match(record_id):
        e.append("record_id is not outlook:<YYYY-MM-DD>:<sunday|monday|daily|event>:<seq>")
    if record.get("mode") not in MODES:
        e.append(f"mode is {record.get('mode')!r}, expected one of {MODES}")
    if _stamp(record.get("as_of")) is None:
        e.append("as_of is not a timezone-aware ISO timestamp")

    score = record.get("score")
    if not isinstance(score, (int, float)) or isinstance(score, bool) or not -100.0 <= float(score) <= 100.0:
        e.append("score is not a number in [-100, +100]")
    if record.get("band") not in BANDS:
        e.append(f"band is {record.get('band')!r}, expected one of {BANDS}")

    confidence = record.get("confidence")
    if not isinstance(confidence, Mapping) or not isinstance(confidence.get("value"), (int, float)):
        e.append("confidence.value is missing or not a number")
    elif not isinstance(confidence.get("band"), str) or not confidence.get("band"):
        e.append("confidence.band is missing (a confidence with no grade is not a confidence)")

    categories = record.get("categories")
    if not isinstance(categories, list) or len(categories) != CATEGORY_COUNT:
        e.append(f"categories is not a list of {CATEGORY_COUNT}")
    else:
        seen: set[str] = set()
        for index, cat in enumerate(categories):
            where = f"categories[{index}]"
            if not isinstance(cat, Mapping):
                e.append(f"{where} is not an object")
                continue
            key = str(cat.get("key") or "")
            if not key:
                e.append(f"{where}.key is empty")
            elif key in seen:
                e.append(f"{where}.key {key!r} is duplicated")
            seen.add(key)
            state = cat.get("state")
            if state not in CATEGORY_STATES:
                e.append(f"{where}.state is {state!r}, expected one of {CATEGORY_STATES}")
            sub = cat.get("subscore")
            if state == "UNKNOWN" and sub is not None:
                # The honesty rule: an UNKNOWN category has no reading. A 0 here would be a claim.
                e.append(f"{where} is UNKNOWN but carries a subscore ({sub!r}); an unmeasured category is null")
            if state in ("COLLECTED", "PARTIAL") and not isinstance(sub, (int, float)):
                e.append(f"{where} is {state} but its subscore is {sub!r}")

    scenarios = record.get("scenarios")
    if not isinstance(scenarios, Mapping):
        e.append("scenarios is missing")
    else:
        for name in ("base", "bull", "bear"):
            row = scenarios.get(name)
            if not isinstance(row, Mapping):
                e.append(f"scenarios.{name} is missing")
                continue
            if not isinstance(row.get("prob"), (int, float)):
                e.append(f"scenarios.{name}.prob is not a number")
            for band_key in RANGE_INDEXES:
                pair = row.get(band_key)
                if pair is None:
                    # The engine writes null for an index whose ATR it could not measure; the brief
                    # states the absence ("-") instead of refusing the whole record over one index.
                    continue
                # Normalization turned the engine's ATR dict into a pair; an unrenderable half is
                # None (printed "n/a") and is not a defect, but a malformed pair still is.
                if not (isinstance(pair, (list, tuple)) and len(pair) == 2
                        and all(v is None or (isinstance(v, (int, float)) and not isinstance(v, bool))
                                for v in pair)):
                    e.append(f"scenarios.{name}.{band_key} is not a [low, high] pair")

    levels = record.get("key_levels")
    if not isinstance(levels, Mapping):
        e.append("key_levels is missing")
    else:
        for index_key in ("SPX", "NDX", "RUT"):
            row = levels.get(index_key)
            if not isinstance(row, Mapping):
                e.append(f"key_levels.{index_key} is missing")
                continue
            for side in LEVEL_SIDES:
                values = row.get(side)
                # A thin side is stated (it renders what exists plus "n/a"), never a refusal. A
                # side the record does not carry at all, or one with more than three levels, is
                # still a defect: the brief must not pick which levels to show.
                if not isinstance(values, list) or not 1 <= len(values) <= MAX_LEVELS_PER_SIDE:
                    e.append(f"key_levels.{index_key}.{side} is not one to {MAX_LEVELS_PER_SIDE} levels")

    if not isinstance(record.get("catalysts"), list):
        e.append("catalysts is not a list")
    if not isinstance(record.get("what_would_change_view"), list):
        e.append("what_would_change_view is not a list")

    actions = record.get("actions_template")
    if not isinstance(actions, Mapping):
        e.append("actions_template is missing")
    elif actions.get("band") != record.get("band"):
        e.append(f"actions_template.band {actions.get('band')!r} does not match the record band {record.get('band')!r}")

    # The engine writes the bare 64-hex digest; the brief states the algorithm with it. Both are
    # the same fact, so either is accepted (normalize_record prefixes the bare form).
    digest = str(record.get("inputs_snapshot_hash") or "")
    if not (digest.startswith("sha256:") or HEX64_RE.match(digest)):
        e.append("inputs_snapshot_hash is missing or not a sha256 digest")
    return e


# --------------------------------------------------------------------------------------------------
# small formatters
# --------------------------------------------------------------------------------------------------
def _clean(value: Any) -> str:
    return " ".join(str(value if value is not None else "").split())


def _day(iso: Any) -> str:
    try:
        return date.fromisoformat(str(iso)[:10]).strftime("%a")
    except ValueError:
        return str(iso or "")


def _month_day(iso: Any) -> str:
    try:
        stamp = date.fromisoformat(str(iso)[:10])
    except ValueError:
        return str(iso or "")
    return f"{stamp.month}/{stamp.day}"


def _clock(value: Any) -> str:
    """``08:30`` -> ``8:30``; anything else is returned unchanged rather than guessed."""
    raw = _clean(value)
    match = re.match(r"^0?(\d{1,2}):(\d{2})", raw)
    return f"{match.group(1)}:{match.group(2)}" if match else raw


def _price(value: Any) -> str:
    """A level as the operator reads it: integers stay integers, halves keep one place, absence is n/a."""
    if value is None:
        return UNRENDERABLE
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        text = f"{float(value):.4f}".rstrip("0").rstrip(".")
        return text or "0"
    return str(value)


def _pair(pair: Any) -> str:
    if isinstance(pair, (list, tuple)) and len(pair) == 2:
        return f"{_price(pair[0])}-{_price(pair[1])}"
    return "-"


def score_int(record: Mapping[str, Any]) -> str:
    """``-21`` / ``+7``: the score as the operator reads it. ASCII minus keeps the SMS in one segment."""
    return f"{round(float(record['score'])):+d}"


def band_label(record: Mapping[str, Any], policy: Mapping[str, Any]) -> str:
    labels = policy.get("band_labels") or {}
    return str(labels.get(record["band"], record["band"]))


def action_short(record: Mapping[str, Any], policy: Mapping[str, Any]) -> str:
    """The stance's template action. Numbers only from the record; the policy supplies the wording."""
    by_band = policy.get("action_short_by_band") or {}
    return str(by_band.get(record["band"], "follow the CIO stance"))


def dedupe_key(record_id: str, channel: str) -> str:
    key = f"{_clean(record_id)}:{_clean(channel).lower()}"
    if len(key) > MAX_DEDUPE_KEY:
        raise BriefError(f"dedupe key longer than {MAX_DEDUPE_KEY} characters: {key!r}")
    return key


def subject(record: Mapping[str, Any], policy: Mapping[str, Any]) -> str:
    """``Trade AI Outlook — Sun 2026-11-08 — DEFENSIVE (S -21, conf LOW)``"""
    return (f"{EMAIL_SUBJECT_PREFIX} - {_day(record['as_of'])} {str(record['as_of'])[:10]} - "
            f"{record['band']} (S {score_int(record)}, conf {_clean(record['confidence'].get('band')).upper()})")


def _category_title(key: str) -> str:
    return CATEGORY_TITLES.get(key, key.replace("_", " "))


def _sub_text(cat: Mapping[str, Any]) -> str:
    if cat.get("state") == "UNKNOWN" or cat.get("subscore") is None:
        return "UNKNOWN"
    return f"{float(cat['subscore']):+.2f}"


def _coverage_text(cat: Mapping[str, Any]) -> str:
    try:
        return f"{round(float(cat.get('coverage')) * 100):d}%"
    except (TypeError, ValueError):
        return "-"


def _conf_why(conf: Mapping[str, Any]) -> str:
    """The confidence detractors, as §4.3 item 1 requires them in the header of every rendering.

    One builder so the HTML, the plain-text MIME alternative and the Telegram message cannot disagree about why the
    confidence is what it is. A missing component prints 0%, which the schema forbids for a real record — a record
    without them fails ``validate_record`` before any renderer is reached.
    """
    return (f"coverage {round(float(conf.get('coverage') or 0) * 100)}%, "
            f"freshness {round(float(conf.get('freshness') or 0) * 100)}%, "
            f"agreement {round(float(conf.get('agreement') or 0) * 100)}%, "
            f"event-risk factor {round(float(conf.get('u_event') or 0) * 100)}%")


def _not_measured(record: Mapping[str, Any]) -> list[str]:
    """UNKNOWN categories with the first named reason, then the partial categories' refused indicators."""
    lines: list[str] = []
    for cat in record.get("categories") or []:
        if not isinstance(cat, Mapping):
            continue
        if cat.get("state") != "UNKNOWN":
            continue
        reason = ""
        for indicator in cat.get("indicators") or []:
            if isinstance(indicator, Mapping) and _clean(indicator.get("refused_reason")):
                reason = _clean(indicator["refused_reason"])
                break
        lines.append(f"{_category_title(str(cat.get('key') or ''))}: UNKNOWN" + (f" - {reason}" if reason else ""))
    for cat in record.get("categories") or []:
        if not isinstance(cat, Mapping) or cat.get("state") != "PARTIAL":
            continue
        missing = [_clean(ind.get("key")) for ind in cat.get("indicators") or []
                   if isinstance(ind, Mapping) and ind.get("raw") is None]
        if missing:
            lines.append(f"{_category_title(str(cat.get('key') or ''))}: partly measured, no reading for "
                         + ", ".join(missing))
    return lines


def _key_levels_rows(record: Mapping[str, Any]) -> list[tuple[str, str, str, str]]:
    rows = []
    levels = record.get("key_levels") or {}
    for name in ("SPX", "NDX", "RUT"):
        row = levels.get(name) or {}
        support = ", ".join(_price(v) for v in (row.get("support") or [])) or "-"
        resistance = ", ".join(_price(v) for v in (row.get("resistance") or [])) or "-"
        rows.append((name, support, resistance, _clean(row.get("basis")) or "-"))
    return rows


def _catalyst_rows(record: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    rows = [c for c in (record.get("catalysts") or []) if isinstance(c, Mapping)]
    return sorted(rows, key=lambda c: (str(c.get("date_et") or ""), str(c.get("time_et") or "")))


def _short_event(name: Any, limit: int = 22) -> str:
    words = _clean(name).split()
    out = ""
    for word in words:
        candidate = f"{out} {word}".strip()
        if len(candidate) > limit:
            break
        out = candidate
    return out or (words[0][:limit] if words else "")


def _catalyst_token(row: Mapping[str, Any]) -> str:
    parts = [_day(row.get("date_et")), _clock(row.get("time_et")), _short_event(row.get("event"))]
    token = " ".join(part for part in parts if part)
    if str(row.get("impact") or "").upper() == "HIGH":
        token += " HIGH"
    return token


# --------------------------------------------------------------------------------------------------
# the text (SMS) sentence
# --------------------------------------------------------------------------------------------------
def _text_head(record: Mapping[str, Any]) -> str:
    conf = _clean(record["confidence"].get("band")).upper() or "-"
    return (f"OUTLOOK {_day(record['as_of'])} {_month_day(record['as_of'])}: S {score_int(record)} "
            f"{record['band']} conf {conf}.")


def _text_tail(record: Mapping[str, Any], tail: str) -> str:
    return f"{tail} id {record['record_id']}".strip()


def render_text(record: Mapping[str, Any], *, policy: Mapping[str, Any], max_chars: int = DEFAULT_MAX_CHARS,
                context: Optional["BriefContext"] = None) -> str:
    """The one-sentence advisory text. Never over ``max_chars``; refuses rather than truncating blindly.

    Order of surrender when the budget is tight: "Full report emailed." goes first (the report is already
    in the operator's inbox, and a pointer costs a third catalyst), then the last catalysts, which are also
    in the email. The head, the band, the action's first clause and the record id always survive - they are
    what makes the text actionable and deduplicable.
    """
    cap = int(max_chars)
    if cap < MIN_TEXT_CHARS:
        raise BriefError(f"the text class cap is {cap} characters, below the {MIN_TEXT_CHARS} this brief needs; "
                         "raise max_chars for market_outlook in config/critical_text_classes.json")
    head = _text_head(record)
    action = action_short(record, policy)
    tail = "Full report emailed."
    tokens = [_catalyst_token(row) for row in _catalyst_rows(record)]
    tokens = [token for token in tokens if token]

    for count in range(min(3, len(tokens)), -1, -1):
        catalysts = (" Catalysts: " + "; ".join(tokens[:count]) + ".") if count else " Catalysts: none scheduled."
        for spoken_tail in (tail, ""):
            sentence = f"{head}{catalysts} Action: {action}."
            if spoken_tail:
                sentence += f" {spoken_tail}"
            text = _text_tail(record, sentence)
            if len(text) <= cap:
                return text
    # Last resort: the first clause of the action, then whatever fits of the rest - the id survives.
    first_clause = action.split(",")[0].strip() or action
    sentence = f"{head} Action: {first_clause}."
    text = _text_tail(record, sentence)
    if len(text) <= cap:
        return text
    raise BriefError(f"record {record['record_id']} cannot be texted in {cap} characters "
                     f"(the standing sentence alone needs {len(text)})")


# --------------------------------------------------------------------------------------------------
# context
# --------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class BriefContext:
    """What the brief needs beyond the record. Everything optional: absence renders as absence."""

    monday_plan: str = ""
    track_record: tuple[Mapping[str, Any], ...] = ()
    last_delivery: str = ""
    headlines: tuple[str, ...] = ()
    prior_band: str = ""
    generated_at: str = ""

    @classmethod
    def from_mapping(cls, value: Optional[Mapping[str, Any]]) -> "BriefContext":
        if not isinstance(value, Mapping):
            return cls()
        heads = value.get("headlines") or ()
        if isinstance(heads, str):
            heads = (heads,)
        track = value.get("track_record") or ()
        return cls(
            monday_plan=_clean_line_block(value.get("monday_plan")),
            track_record=tuple(row for row in track if isinstance(row, Mapping)),
            last_delivery=_clean(value.get("last_delivery")),
            headlines=tuple(_clean(h) for h in heads if _clean(h)),
            prior_band=_clean(value.get("prior_band")),
            generated_at=_clean(value.get("generated_at")),
        )


def _clean_line_block(value: Any) -> str:
    """Keep the line structure of a folded brief; strip trailing spaces and blank runs."""
    if not value:
        return ""
    lines = [line.rstrip() for line in str(value).replace("\r\n", "\n").split("\n")]
    out: list[str] = []
    for line in lines:
        if not line.strip():
            if out and out[-1] != "":
                out.append("")
            continue
        out.append(line)
    return "\n".join(out).strip()


def band_moved(record: Mapping[str, Any], context: BriefContext) -> bool:
    prior = context.prior_band or _clean(record.get("prior_band"))
    return bool(prior) and prior != record.get("band")


# --------------------------------------------------------------------------------------------------
# email: HTML and plain-text alternative
# --------------------------------------------------------------------------------------------------
_CSS_WRAP = ("max-width:{width}px;margin:0 auto;padding:16px;font-family:-apple-system,BlinkMacSystemFont,"
             "'Segoe UI',Roboto,Helvetica,Arial,sans-serif;font-size:15px;line-height:1.45;color:#111;"
             "background:#fff")
_CSS_H2 = "font-size:16px;margin:24px 0 8px;padding-bottom:4px;border-bottom:1px solid #e5e5e5;color:#111"
_CSS_TABLE = "width:100%;border-collapse:collapse;font-size:13px;margin:6px 0 2px"
_CSS_TH = "text-align:left;font-weight:600;padding:4px 6px;border-bottom:1px solid #d0d0d0;color:#444"
_CSS_TD = "padding:4px 6px;border-bottom:1px solid #efefef;vertical-align:top"
_CSS_MUTED = "color:#666;font-size:12px"
_CSS_BAND = {"RISK-ON": "#137333", "NEUTRAL": "#5f6368", "DEFENSIVE": "#b06000", "RISK-OFF": "#a50e0e"}


def _e(value: Any) -> str:
    return html.escape(_clean(value), quote=True)


def _h2(title: str) -> str:
    return f'<h2 style="{_CSS_H2}">{_e(title)}</h2>'


def _table(headers: Sequence[str], rows: Iterable[Sequence[Any]]) -> str:
    if len(headers) > 4:
        raise BriefError(f"an outlook table may carry at most four columns, got {len(headers)}")
    head = "".join(f'<th style="{_CSS_TH}">{_e(h)}</th>' for h in headers)
    body = "".join(
        "<tr>" + "".join(f'<td style="{_CSS_TD}">{_e(cell)}</td>' for cell in row) + "</tr>"
        for row in rows
    )
    return f'<table style="{_CSS_TABLE}"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>'


def render_html(record: Mapping[str, Any], *, policy: Mapping[str, Any], max_chars: int = DEFAULT_MAX_CHARS,
                context: Optional[BriefContext] = None) -> str:
    """The full report. Section order is §4.3's, one to eleven."""
    ctx = context or BriefContext()
    width = int(policy.get("html_width_px") or 600)
    conf = record["confidence"]
    conf_band = _clean(conf.get("band")).upper()
    regime = record.get("regime") or {}
    colour = _CSS_BAND.get(str(record["band"]), "#111")
    parts: list[str] = []

    # 1. header
    headline = f"{_day(record['as_of'])} {str(record['as_of'])[:10]} - {record['band']} (S {score_int(record)})"
    conf_why = _conf_why(conf)
    episode = _clean(regime.get("episode_id"))
    parts.append(
        f'<h1 style="font-size:19px;margin:0 0 6px;color:{colour}">{_e(headline)}</h1>'
        f'<div style="font-size:13px;color:#333">Confidence {_e(conf_band)} '
        f'({_e(round(float(conf.get("value") or 0) * 100))}%) - {_e(conf_why)}.</div>'
        f'<div style="font-size:13px;color:#333;margin-top:4px">Market Risk Engine: '
        f'{_e(regime.get("mre_tier") or "UNKNOWN")} ({_e(regime.get("mre_score") if regime.get("mre_score") is not None else "-")})'
        + (f' - open episode {_e(episode)}' if episode else ' - no open episode')
        + f'. Mode {_e(record.get("mode"))}.</div>'
    )
    if band_moved(record, ctx):
        prior = ctx.prior_band or _clean(record.get("prior_band"))
        parts.append(f'<div style="font-size:13px;color:{colour};font-weight:600;margin-top:4px">'
                     f'Band moved {_e(prior)} to {_e(record.get("band"))}.</div>')

    # 2. the view
    rows = []
    for name in ("base", "bull", "bear"):
        row_value = (record.get("scenarios") or {}).get(name) or {}
        rows.append((name.upper(), f"{round(float(row_value.get('prob') or 0) * 100)}%",
                     _pair(row_value.get("spx_range")), _pair(row_value.get("ndx_range"))))
    parts.append(_h2("The view"))
    parts.append(_table(("Scenario", "Prob", "SPX", "NDX"), rows))
    rut = " &middot; ".join(
        f"{name.upper()} {_pair((record.get('scenarios') or {}).get(name, {}).get('rut_range'))}"
        for name in ("base", "bull", "bear")
    )
    parts.append(f'<div style="{_CSS_MUTED}">RUT: {rut}</div>')
    for name in ("base", "bull", "bear"):
        triggers = [t for t in ((record.get("scenarios") or {}).get(name) or {}).get("triggers") or [] if _clean(t)]
        if triggers:
            parts.append(f'<div style="font-size:13px;margin-top:4px"><strong>{_e(name.upper())}</strong>: '
                         + _e("; ".join(_clean(t) for t in triggers)) + "</div>")

    # 3. cross-asset scorecard
    parts.append(_h2("Cross-asset scorecard"))
    parts.append(_table(("Category", "Sub-score", "Coverage", "State"),
                        [(_category_title(str(cat.get("key"))), _sub_text(cat), _coverage_text(cat),
                          str(cat.get("state"))) for cat in record.get("categories") or []]))

    # 4. levels
    parts.append(_h2("Levels that matter"))
    parts.append(_table(("Index", "Support", "Resistance", "Basis"), _key_levels_rows(record)))

    # 5. catalysts
    parts.append(_h2("This week's catalysts"))
    catalyst_rows = []
    for row in _catalyst_rows(record):
        prior = _clean(row.get("prior")) or "-"
        consensus = _clean(row.get("consensus")) or "-"
        held = row.get("held_flag_per_account_id") or []
        catalyst_rows.append((f"{_day(row.get('date_et'))} {_clock(row.get('time_et'))}",
                              _clean(row.get("event")), _clean(row.get("impact")),
                              f"prior {prior} / cons {consensus}" + (f" - held: {len(held)} account(s)" if held else "")))
    parts.append(_table(("When", "Event", "Impact", "Prior / consensus"), catalyst_rows)
                 if catalyst_rows else f'<div style="{_CSS_MUTED}">No scheduled releases in the window.</div>')

    # 6. overnight
    overnight = record.get("overnight") or {}
    parts.append(_h2("Overnight so far"))
    gap = overnight.get("futures_gap_pct")
    gap_text = f"{float(gap):+.2f}%" if isinstance(gap, (int, float)) else "not measured yet"
    parts.append(f'<div style="font-size:13px">Sunday futures gap: {_e(gap_text)}. Asia: '
                 f'{_e(overnight.get("asia") or "not measured")}. Crypto: '
                 f'{_e(overnight.get("crypto") or "not measured")}.</div>')
    headlines = list(ctx.headlines) or [_clean(h) for h in overnight.get("headlines") or [] if _clean(h)]
    if headlines:
        parts.append('<ul style="margin:6px 0 0 18px;padding:0;font-size:13px">'
                     + "".join(f"<li>{_e(head)}</li>" for head in headlines[:5]) + "</ul>")
    else:
        parts.append(f'<div style="{_CSS_MUTED}">No weekend headlines collected.</div>')

    # 7. positioning
    parts.append(_h2("Positioning"))
    positioning = [cat for cat in record.get("categories") or [] if cat.get("key") == "positioning"]
    if positioning:
        cat = positioning[0]
        parts.append(f'<div style="font-size:13px">Sub-score {_e(_sub_text(cat))}, coverage '
                     f'{_e(_coverage_text(cat))}, state {_e(cat.get("state"))}.</div>')
        indicator_rows = [(str(ind.get("key")), ind.get("raw") if ind.get("raw") is not None else "no reading",
                           _clean(ind.get("refused_reason")) or (str(ind.get("as_of"))[:10] if ind.get("as_of") else "-"))
                          for ind in cat.get("indicators") or [] if isinstance(ind, Mapping)]
        if indicator_rows:
            parts.append(_table(("Indicator", "Reading", "As-of / reason"), indicator_rows))
    else:
        parts.append(f'<div style="{_CSS_MUTED}">Positioning was not measured.</div>')

    # 8. what would change the view
    parts.append(_h2("What would change our view"))
    trigger_rows = [(str(t.get("trigger")), str(t.get("threshold")), str(t.get("status") or "-"))
                    for t in record.get("what_would_change_view") or [] if isinstance(t, Mapping)]
    parts.append(_table(("Trigger", "Threshold", "Status"), trigger_rows)
                 if trigger_rows else f'<div style="{_CSS_MUTED}">No standing triggers.</div>')

    # 9. what we do
    actions = record.get("actions_template") or {}
    parts.append(_h2("What we do"))
    parts.append(f'<div style="font-size:13px">Band <strong>{_e(record["band"])}</strong> - tranche release: '
                 f'{_e(actions.get("tranche_release") or "not stated")} - reserve floor: '
                 f'{_e(actions.get("reserve_floor") or "not stated")}.</div>'
                 f'<div style="font-size:13px;margin-top:4px">{_e(actions.get("exposure_note") or "")}</div>'
                 f'<div style="{_CSS_MUTED};margin-top:4px">Per-account specifics stay in the Command Center, '
                 f'where the CIO applies this template to each account.</div>')

    # 10. last week graded + track record
    parts.append(_h2("Last week's call"))
    grading = record.get("grading") or {}
    if grading:
        parts.append(f'<div style="font-size:13px">Grading {_e(grading.get("for_prior_record_id") or "-")}: '
                     f'{_e(grading.get("realized") or "-")}; scenario realized '
                     f'{_e(grading.get("scenario_hit") or "-")}; Brier {_e(grading.get("brier") if grading.get("brier") is not None else "-")}; '
                     f'levels {_e(grading.get("level_hits") or "-")}.</div>')
    else:
        parts.append(f'<div style="{_CSS_MUTED}">No grading is recorded for the prior record yet.</div>')
    if ctx.track_record:
        parts.append(_table(("Week", "Band", "Realized", "Hit"),
                            [(str(row.get("week") or "-"), str(row.get("band") or "-"),
                              str(row.get("realized") or "-"), str(row.get("hit") or "-"))
                             for row in ctx.track_record[:8]]))

    # 11. not measured + footer
    parts.append(_h2("Not measured"))
    lines = _not_measured(record)
    parts.append('<ul style="margin:6px 0 0 18px;padding:0;font-size:13px">'
                 + "".join(f"<li>{_e(line)}</li>" for line in lines) + "</ul>"
                 if lines else f'<div style="{_CSS_MUTED}">Every category was measured.</div>')

    if ctx.monday_plan:
        parts.append(_h2("Monday plan"))
        parts.append('<pre style="white-space:pre-wrap;font-size:12px;line-height:1.4;margin:6px 0 0;'
                     f'font-family:ui-monospace,Menlo,Consolas,monospace">{html.escape(ctx.monday_plan)}</pre>')

    footer = [f"record {record['record_id']}", f"policy {record.get('policy_version') or '-'}",
              f"inputs {record.get('inputs_snapshot_hash') or '-'}"]
    if record.get("engine_commit"):
        footer.append(f"engine {str(record.get('engine_commit'))[:12]}")
    if ctx.last_delivery:
        footer.append(ctx.last_delivery)
    parts.append(f'<div style="{_CSS_MUTED};margin-top:18px;border-top:1px solid #e5e5e5;padding-top:8px">'
                 f'Data as of {_e(record["as_of"])}. ' + _e(" - ".join(footer)) + "</div>")

    body = "\n".join(parts)
    return ("<!doctype html><html><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
            f"<title>{_e(subject(record, policy))}</title></head>"
            f'<body style="margin:0;background:#fff"><div style="{_CSS_WRAP.format(width=width)}">{body}</div>'
            "</body></html>")


def render_email_text(record: Mapping[str, Any], *, policy: Mapping[str, Any],
                      context: Optional[BriefContext] = None) -> str:
    """The plain-text alternative carried beside the HTML, for clients that refuse HTML."""
    ctx = context or BriefContext()
    conf = record["confidence"]
    lines = [subject(record, policy), "",
             f"Confidence {_clean(conf.get('band')).upper()} ({round(float(conf.get('value') or 0) * 100)}%) - "
             f"{_conf_why(conf)}.",
             f"Market Risk Engine: {(record.get('regime') or {}).get('mre_tier') or 'UNKNOWN'}.", "",
             "THE VIEW"]
    for name in ("base", "bull", "bear"):
        row = (record.get("scenarios") or {}).get(name) or {}
        lines.append(f"  {name.upper():5s} {round(float(row.get('prob') or 0) * 100):3d}%  "
                     f"SPX {_pair(row.get('spx_range'))}  NDX {_pair(row.get('ndx_range'))}  RUT {_pair(row.get('rut_range'))}")
    lines += ["", "SCORECARD"]
    for cat in record.get("categories") or []:
        lines.append(f"  {_category_title(str(cat.get('key'))):22s} {_sub_text(cat):>8s} "
                     f"{_coverage_text(cat):>4s} {cat.get('state')}")
    lines += ["", "LEVELS"]
    for name, support, resistance, basis in _key_levels_rows(record):
        lines.append(f"  {name}: support {support} | resistance {resistance} ({basis})")
    lines += ["", "THIS WEEK'S CATALYSTS"]
    catalysts = _catalyst_rows(record)
    for row in catalysts:
        lines.append(f"  {_day(row.get('date_et'))} {_clock(row.get('time_et'))} {_clean(row.get('event'))} "
                     f"[{_clean(row.get('impact'))}] prior {_clean(row.get('prior')) or '-'} / "
                     f"cons {_clean(row.get('consensus')) or '-'}")
    if not catalysts:
        lines.append("  none scheduled")
    overnight = record.get("overnight") or {}
    lines += ["", "OVERNIGHT",
              f"  futures gap: {overnight.get('futures_gap_pct') if overnight.get('futures_gap_pct') is not None else 'not measured'}",
              f"  asia: {_clean(overnight.get('asia')) or 'not measured'}",
              f"  crypto: {_clean(overnight.get('crypto')) or 'not measured'}"]
    for head in (ctx.headlines or tuple(overnight.get("headlines") or ()))[:5]:
        lines.append(f"  - {_clean(head)}")
    lines += ["", "WHAT WOULD CHANGE OUR VIEW"]
    for trigger in record.get("what_would_change_view") or []:
        if isinstance(trigger, Mapping):
            lines.append(f"  {_clean(trigger.get('trigger'))} {_clean(trigger.get('threshold'))} "
                         f"[{_clean(trigger.get('status')) or '-'}]")
    actions = record.get("actions_template") or {}
    lines += ["", "WHAT WE DO",
              f"  tranche release: {_clean(actions.get('tranche_release')) or 'not stated'}",
              f"  reserve floor: {_clean(actions.get('reserve_floor')) or 'not stated'}",
              f"  {_clean(actions.get('exposure_note'))}"]
    grading = record.get("grading") or {}
    if grading:
        lines += ["", "LAST WEEK'S CALL",
                  f"  {_clean(grading.get('realized'))}; scenario {_clean(grading.get('scenario_hit'))}; "
                  f"Brier {grading.get('brier')}; {_clean(grading.get('level_hits'))}"]
    lines += ["", "NOT MEASURED"] + [f"  {line}" for line in _not_measured(record)]
    if ctx.monday_plan:
        lines += ["", "MONDAY PLAN", ctx.monday_plan]
    lines += ["", f"record {record['record_id']} - policy {record.get('policy_version')} - "
                  f"data as of {record['as_of']}"]
    return "\n".join(lines)


# --------------------------------------------------------------------------------------------------
# telegram (plain text: the raw sender carries no parse mode)
# --------------------------------------------------------------------------------------------------
def render_telegram(record: Mapping[str, Any], *, policy: Mapping[str, Any],
                    context: Optional[BriefContext] = None) -> str:
    ctx = context or BriefContext()
    cap = int(policy.get("telegram_max_chars") or 4000)
    conf = record["confidence"]
    lines: list[str] = []

    lines.append(f"MARKET OUTLOOK - {_day(record['as_of'])} {str(record['as_of'])[:10]} ({(record.get('mode') or '').upper()})")
    lines.append(f"S {score_int(record)} - {record['band']} - confidence {_clean(conf.get('band')).upper()} "
                 f"({round(float(conf.get('value') or 0) * 100)}%) - {_conf_why(conf)}")
    regime = record.get("regime") or {}
    episode = _clean(regime.get("episode_id"))
    lines.append(f"MRE {_clean(regime.get('mre_tier')) or 'UNKNOWN'}"
                 + (f" - episode {episode}" if episode else " - no open episode"))
    if band_moved(record, ctx):
        lines.append(f"Band moved {ctx.prior_band or _clean(record.get('prior_band'))} to {record.get('band')}")
    lines.append("")

    lines.append("THE VIEW")
    for name in ("base", "bull", "bear"):
        row = (record.get("scenarios") or {}).get(name) or {}
        lines.append(f"  {name.upper():5s} {round(float(row.get('prob') or 0) * 100):3d}% "
                     f"SPX {_pair(row.get('spx_range'))} NDX {_pair(row.get('ndx_range'))}")
    lines.append("")

    lines.append("SCORECARD")
    for cat in record.get("categories") or []:
        lines.append(f"  {_category_title(str(cat.get('key')))[:18]:18s} {_sub_text(cat):>8s} "
                     f"cov {_coverage_text(cat):>4s} {cat.get('state')}")
    lines.append("")

    lines.append("LEVELS")
    for name, support, resistance, _basis in _key_levels_rows(record):
        lines.append(f"  {name}: sup {support} | res {resistance}")
    lines.append("")

    lines.append("CATALYSTS")
    catalysts = _catalyst_rows(record)
    for row in catalysts:
        lines.append(f"  {_day(row.get('date_et'))} {_clock(row.get('time_et'))} "
                     f"{_clean(row.get('event'))} [{_clean(row.get('impact'))}]")
    if not catalysts:
        lines.append("  none scheduled")
    lines.append("")

    overnight = record.get("overnight") or {}
    gap = overnight.get("futures_gap_pct")
    lines.append("OVERNIGHT")
    lines.append(f"  gap: {f'{float(gap):+.2f}%' if isinstance(gap, (int, float)) else 'not measured'} | "
                 f"asia: {_clean(overnight.get('asia')) or 'not measured'} | "
                 f"crypto: {_clean(overnight.get('crypto')) or 'not measured'}")
    for head in (ctx.headlines or tuple(overnight.get("headlines") or ()))[:5]:
        lines.append(f"  - {_clean(head)}")
    lines.append("")

    lines.append("WHAT WOULD CHANGE THE VIEW")
    for trigger in record.get("what_would_change_view") or []:
        if isinstance(trigger, Mapping):
            lines.append(f"  {_clean(trigger.get('trigger'))} {_clean(trigger.get('threshold'))} "
                         f"[{_clean(trigger.get('status')) or '-'}]")
    lines.append("")

    actions = record.get("actions_template") or {}
    lines.append("WHAT WE DO")
    lines.append(f"  tranche release: {_clean(actions.get('tranche_release')) or 'not stated'} | "
                 f"reserve floor: {_clean(actions.get('reserve_floor')) or 'not stated'}")
    lines.append(f"  {_clean(actions.get('exposure_note'))}")
    lines.append("  per-account specifics: Command Center")
    lines.append("")

    grading = record.get("grading") or {}
    lines.append("LAST WEEK'S CALL")
    if grading:
        lines.append(f"  {_clean(grading.get('realized'))} - scenario {_clean(grading.get('scenario_hit'))} - "
                     f"Brier {grading.get('brier') if grading.get('brier') is not None else '-'}")
    else:
        lines.append("  not graded yet")
    for row in ctx.track_record[:8]:
        lines.append(f"  {_clean(row.get('week'))}: {_clean(row.get('band'))} -> {_clean(row.get('realized'))} "
                     f"[{_clean(row.get('hit'))}]")
    lines.append("")

    lines.append("NOT MEASURED")
    not_measured = _not_measured(record)
    lines.extend(f"  {line}" for line in not_measured) if not_measured else lines.append("  nothing")
    lines.append("")

    if ctx.monday_plan:
        lines.append("MONDAY PLAN")
        lines.append(ctx.monday_plan)
        lines.append("")

    if ctx.last_delivery:
        lines.append(ctx.last_delivery)
        lines.append("")
    lines.append(f"record {record['record_id']}")
    lines.append(f"policy {record.get('policy_version')}")

    text = "\n".join(lines).strip()
    if len(text) > cap:
        # Telegram chunks long messages itself (``_smart_split``); the policy cap is a sanity bound, not a
        # silent truncation: a brief that outgrows it is refused rather than cut.
        raise BriefError(f"telegram brief is {len(text)} characters, over the {cap}-character policy cap")
    return text


# --------------------------------------------------------------------------------------------------
# CIO + Market Risk Engine
# --------------------------------------------------------------------------------------------------
def decision_id(record: Mapping[str, Any]) -> str:
    """Deterministic from the record id, so a re-run cannot mint a second CIO row for one outlook."""
    match = RECORD_ID_RE.match(str(record.get("record_id") or ""))
    if not match:
        raise BriefError("a CIO row needs a valid record id")
    day, mode, seq = match.groups()
    return f"cio-outlook-{day}-{mode}-{seq}"


def cio_decision_row(record: Mapping[str, Any], policy: Mapping[str, Any]) -> dict[str, Any]:
    """The one ``cio_decisions`` row §4.6 requires. It states a stance; it is not an order."""
    conf = record["confidence"]
    summary = [
        {"category": cat.get("key"), "subscore": cat.get("subscore"), "coverage": cat.get("coverage"),
         "state": cat.get("state")}
        for cat in record.get("categories") or [] if isinstance(cat, Mapping)
    ]
    return {
        "decision_id": decision_id(record),
        "symbol": "MARKET",
        "strategy_type": "market_outlook",
        "group_id": record["record_id"],
        "action": record["band"],
        "action_class": "outlook",
        "priority": "high" if record["band"] == "RISK-OFF" else "medium",
        "confidence_raw": float(conf.get("value") or 0.0),
        "confidence_calibrated": float(conf.get("value") or 0.0),
        "decision_safety": "safe",
        "human_review_required": True,
        "rationale": (f"{record['record_id']}: S {score_int(record)}, band {record['band']}, "
                      f"confidence {_clean(conf.get('band')).upper()}, action {action_short(record, policy)}"),
        "status": "proposed",
        "supporting_signals": summary,
        "metadata": {
            "record_id": record["record_id"],
            "policy_version": record.get("policy_version"),
            "mode": record.get("mode"),
            "inputs_snapshot_hash": record.get("inputs_snapshot_hash"),
            "broker_authority": "none: this row states a stance and places nothing",
        },
    }


# --------------------------------------------------------------------------------------------------
# delivery plan and the delivery walk
# --------------------------------------------------------------------------------------------------
@dataclass
class ChannelPlan:
    channel: str
    action: str  # send | skip
    reason: str = ""
    detail: dict[str, Any] = field(default_factory=dict)


def parse_channels(value: Any) -> list[str]:
    """``email,telegram,text`` -> an ordered, de-duplicated list. An unknown name is refused by name."""
    if value is None:
        return list(CHANNELS)
    if isinstance(value, str):
        raw = [part.strip().lower() for part in value.split(",")]
    else:
        raw = [str(part).strip().lower() for part in value]
    out: list[str] = []
    for name in raw:
        if not name:
            continue
        if name not in CHANNELS:
            raise BriefError(f"unknown channel {name!r}; expected some of {', '.join(CHANNELS)}")
        if name not in out:
            out.append(name)
    if not out:
        raise BriefError("no channels requested")
    return out


def plan_channels(record: Mapping[str, Any], *, policy: Mapping[str, Any], channels: Sequence[str],
                  existing: Optional[Mapping[str, str]] = None, mode: Optional[str] = None,
                  text_class_enabled: bool = True) -> list[ChannelPlan]:
    """What each requested channel will do, decided before anything is sent.

    ``existing`` maps channel -> the ``notification_log`` status for this record's key. A channel whose
    row is already ``sent`` is skipped; nothing else is a delivery.
    """
    status = {str(k).lower(): str(v or "").lower() for k, v in (existing or {}).items()}
    record_mode = str(mode or record.get("mode") or "")
    text_modes = set(policy.get("text_modes") or ("sunday", "monday"))
    text_bands = set(policy.get("text_on_band_change") or ())
    prior = _clean(record.get("prior_band"))
    plans: list[ChannelPlan] = []
    for channel in channels:
        if status.get(channel) in DELIVERED_STATUSES:
            plans.append(ChannelPlan(channel, "skip", f"already delivered ({dedupe_key(record['record_id'], channel)})"))
            continue
        if channel == "text":
            if not text_class_enabled:
                plans.append(ChannelPlan(channel, "skip", "class market_outlook is switched off in config/critical_text_classes.json"))
                continue
            if record_mode not in text_modes and not (prior and prior != record.get("band")
                                                      and record["band"] in text_bands):
                plans.append(ChannelPlan(channel, "skip",
                                         f"mode {record_mode or 'unknown'} is not a text mode and the band did not move into "
                                         + "/".join(sorted(text_bands))))
                continue
        plans.append(ChannelPlan(channel, "send"))
    return plans


Sender = Callable[..., Mapping[str, Any]]


def deliver_channels(
    record: Mapping[str, Any],
    *,
    policy: Mapping[str, Any],
    plans: Sequence[ChannelPlan],
    senders: Mapping[str, Sender],
    read_status: Callable[[str], Optional[str]],
    write_log: Callable[[dict[str, Any]], None],
    text_max_chars: int = DEFAULT_MAX_CHARS,
    context: Optional[BriefContext] = None,
    notification_date: Optional[str] = None,
) -> dict[str, Any]:
    """Walk the plan, hand each message to its channel, and log one row per channel per record.

    A sender returns ``{ok, provider_id, error, status}``. The log row is written after the attempt, and
    only when this walk may change it: a row already ``sent`` is left exactly as it is, so a later run
    can never overwrite the receipt that proves the first delivery.
    """
    ctx = context or BriefContext()
    day = notification_date or str(record["as_of"])[:10]
    results: list[dict[str, Any]] = []

    def record_result(channel: str, status: str, *, provider_id: Any = None, error: Any = None,
                      detail: Any = None) -> None:
        key = dedupe_key(record["record_id"], channel)
        write_log({
            "notification_date": day,
            "notification_type": "market_outlook_brief",
            "channel": channel,
            "dedupe_key": key,
            "status": status,
            "sent_at": detail.get("sent_at") if isinstance(detail, Mapping) else None,
            "error": (str(error)[:500] if error else None),
            "subject": subject(record, policy) if channel == "email" else "MARKET OUTLOOK",
            "body_summary": (detail or {}).get("summary") if isinstance(detail, Mapping) else None,
            "payload": {"record_id": record["record_id"], "provider_id": provider_id,
                        **(detail if isinstance(detail, Mapping) else {})},
        })

    for plan in plans:
        channel = plan.channel
        if plan.action == "skip":
            # Never overwrite a sent row with "deduped": the receipt is the proof, not a note.
            results.append({"channel": channel, "status": "skipped", "reason": plan.reason})
            continue
        current = read_status(dedupe_key(record["record_id"], channel))
        if str(current or "").lower() in DELIVERED_STATUSES:
            results.append({"channel": channel, "status": "deduped",
                            "reason": f"notification_log already shows sent for {dedupe_key(record['record_id'], channel)}"})
            continue
        sender = senders.get(channel)
        if sender is None:
            results.append({"channel": channel, "status": "refused", "reason": "no sender is wired for this channel"})
            continue
        try:
            outcome = sender(record, policy=policy, max_chars=text_max_chars, context=ctx)
        except BriefError as exc:
            record_result(channel, "failed", error=str(exc))
            results.append({"channel": channel, "status": "failed", "reason": str(exc)})
            continue
        except Exception as exc:  # a channel failing must not stop the other channels
            record_result(channel, "failed", error=f"{type(exc).__name__}: {exc}")
            results.append({"channel": channel, "status": "failed",
                            "reason": f"{type(exc).__name__}: {exc}"})
            continue
        ok = bool(outcome.get("ok"))
        status = str(outcome.get("status") or ("sent" if ok else "failed"))
        record_result(channel, status, provider_id=outcome.get("provider_id"),
                      error=outcome.get("error"), detail=outcome.get("detail"))
        results.append({"channel": channel, "status": status,
                        "provider_id": outcome.get("provider_id"),
                        "reason": outcome.get("error") or outcome.get("reason") or ""})
    return {"results": results,
            "sent": [r for r in results if r["status"] == "sent"],
            "attempted": [r for r in results if r["status"] in ("sent", "failed")],
            "skipped": [r for r in results if r["status"] in ("skipped", "deduped", "refused")]}
