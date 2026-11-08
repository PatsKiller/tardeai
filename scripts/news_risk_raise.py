#!/usr/bin/env python3
"""news_risk_raise.py — lane news-risk-raise (LQ-20261107-1239).

The Home market-risk card is built from what the operator holds, has been stopped out of, and watches. Company
news arrives all weekend into `news_articles` and is classified by `news-to-catalyst`, but nothing joined the two:
13,172 articles landed between Friday's close and Sunday 16:45 ET on 2026-11-08 and none of them could reach Risk
or Home. This lane is that join, and nothing more:

  1. take every non-duplicate article since the last completed NYSE close (Friday 16:00 ET at a weekend);
  2. tag it with the scope(s) whose symbol it names — `held`, `stopped_out`, `watchlist` — in
     `news_articles.agent_tags` (one atomic UPDATE that replaces this writer's previous tag, so re-runs do not stack);
  3. raise the material ones (the canonical `news-to-catalyst` severities `high` / `critical`) into
     `catalyst_events` when no catalyst row exists yet, and into `market_event_candidates` while a market-scope
     episode is open. A raised candidate is provenance-only: it carries `source = {news-risk-raise}` and the article
     ids in `reason_evidence`, is never ranked, and never overwrites the lane's own candidate.

The severity scale is NOT re-invented: an article's existing `catalyst_events` row decides; only an article with no
row is classified with `news_to_catalyst`'s own keyword map and `_severity_from_weight`, so both writers agree.

Advisory only. MBI_BEHAVIOR = 0: this lane has no price, size, order, stop or broker path; it writes tags and
provenance rows. `--dry-run` is the default and makes the session READ ONLY at the server; `--apply` writes and
leaves a LaneRunReceipt v2.

  python3 scripts/news_risk_raise.py [--dry-run|--apply] [--now ISO] [--hours N] [--json]
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
for _p in (str(ROOT), str(SCRIPTS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

LANE = "news-risk-raise"
POLICY_REL = "config/news_risk_raise.json"
TAG_KIND = "risk_scope"
#: A ticker-shaped symbol. CUSIP placeholders ("543354104") and spaces never scope-match a news article.
TICKER = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")
_LOG = logging.getLogger(__name__)


def _rollback_quietly(conn: Any) -> None:
    """Roll back before re-raising. A rollback that itself fails cannot change the failure being reported, so it
    is recorded and never raised over the original error."""
    try:
        conn.rollback()
    except Exception as exc:  # noqa: BLE001 -- the run's own exception is the one that must reach the caller
        _LOG.debug("rollback did not complete: %s", type(exc).__name__)


def _close_quietly(*handles: Any) -> None:
    """Close what this run opened. A close failure is recorded; the transaction's outcome is already settled."""
    for h in handles:
        try:
            h.close()
        except Exception as exc:  # noqa: BLE001 -- nothing left to report; the outcome is already decided
            _LOG.debug("close failed for %r: %s", h, type(exc).__name__)


# ── pure logic (unit-tested without a database) ──────────────────────────────────────────────────────────────
def load_policy(path: Path | None = None) -> dict[str, Any]:
    p = path or (ROOT / POLICY_REL)
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SystemExit(f"ABORT: {POLICY_REL} unreadable ({type(exc).__name__}: {exc})")
    if not isinstance(doc, dict) or doc.get("schema") != "NewsRiskRaisePolicy@v1":
        raise SystemExit(f"ABORT: {POLICY_REL} is not a NewsRiskRaisePolicy@v1 document")
    return doc


def last_close(now: datetime) -> datetime:
    """The instant of the most recent completed NYSE close (16:00 ET, 13:00 on early closes, and Friday's close at a
    weekend). Uses the shared session calendar, never a hardcoded weekday rule."""
    from lib.market_risk import sessions

    day = sessions.last_closed_session(now)
    return datetime.combine(day, sessions.close_time(day), sessions.ET)


def ticker(symbol: Any) -> str | None:
    s = str(symbol or "").strip().upper()
    return s if TICKER.match(s) else None


def build_scope(held: Iterable[Any], stopped_out: Iterable[Any], watchlist: Iterable[Any]) -> dict[str, list[str]]:
    """symbol -> scopes, in the configured order. A held symbol is never also 'stopped_out' (the loss sale it may
    have earlier is history, not the operator's current exposure)."""
    scope: dict[str, list[str]] = {}
    held_syms = {t for t in (ticker(s) for s in held) if t}
    for s in sorted(held_syms):
        scope.setdefault(s, []).append("held")
    for s in sorted({t for t in (ticker(s) for s in stopped_out) if t} - held_syms):
        scope.setdefault(s, []).append("stopped_out")
    for s in sorted({t for t in (ticker(s) for s in watchlist) if t} - held_syms):
        scope.setdefault(s, []).append("watchlist")
    return scope


def classify_untagged(title: str, summary: str | None) -> tuple[str, str]:
    """(catalyst_type, severity) for an article the canonical lane has not classified, using THAT lane's keyword map
    and weight thresholds. Imported lazily so a broken import degrades to 'other' rather than killing a run."""
    try:
        import news_to_catalyst as ntc

        ctype = ntc._classify(title or "", summary or "")
        weights = {"earnings_beat": 0.8, "earnings_miss": 0.8, "guidance_raise": 0.75, "guidance_lower": 0.8,
                   "contract_win": 0.7, "fda_approval": 0.85, "merger_acquisition": 0.75, "insider_buy": 0.55,
                   "analyst_upgrade": 0.5, "short_squeeze": 0.6, "geopolitical": 0.6, "dividend_increase": 0.55,
                   "dividend_cut": 0.75, "stock_split": 0.55, "buyback": 0.5, "ceo_change": 0.65,
                   "sector_rotation": 0.4}
        return ctype, ntc._severity_from_weight(float(weights.get(ctype, 0.3)))
    except Exception:  # noqa: BLE001 — classification is best-effort; the tag is still written
        return "other", "low"


def is_material(severity: Any, policy: Mapping[str, Any]) -> bool:
    return str(severity or "").lower() in {str(s).lower() for s in policy.get("material_severities") or ["high", "critical"]}


def plan_raises(articles: Iterable[Mapping[str, Any]], catalyst: Mapping[str, Mapping[str, Any]],
                scope: Mapping[str, list[str]], policy: Mapping[str, Any]) -> tuple[list[dict], list[dict]]:
    """Split the scoped articles into (tagged, raised). ``catalyst`` is keyed by the stringified news id and carries
    the canonical row when one exists. Every scoped article is tagged; only a material one is raised."""
    tagged: list[dict[str, Any]] = []
    raised: list[dict[str, Any]] = []
    for a in articles:
        sym = ticker(a.get("symbol"))
        scopes = scope.get(sym or "")
        if not scopes:
            continue
        existing = catalyst.get(str(a.get("id"))) or {}
        ctype = existing.get("catalyst_type")
        sev = existing.get("severity")
        basis = "catalyst_events"
        if not ctype:
            ctype, sev = classify_untagged(str(a.get("title") or ""), a.get("summary"))
            basis = "news_to_catalyst_keywords"
        material = is_material(sev, policy)
        row = {
            "news_id": int(a["id"]), "symbol": sym, "scopes": list(scopes),
            "catalyst_type": ctype, "severity": str(sev or "").lower(), "material": material,
            "classification_basis": basis, "title": str(a.get("title") or "")[:500],
            "published_at": a.get("published_at"), "created_at": a.get("created_at"),
        }
        tagged.append(row)
        if material:
            raised.append(row)
    # the card ranks by severity then recency, never by the order a query happened to return (two stable sorts)
    rank = {"critical": 0, "high": 1}
    raised.sort(key=lambda r: str(r.get("published_at") or r.get("created_at") or ""), reverse=True)
    raised.sort(key=lambda r: rank.get(r["severity"], 9))
    return tagged, raised


def tag_payload(row: Mapping[str, Any], *, now: datetime, writer: str) -> dict[str, Any]:
    """The `agent_tags` entry this lane owns. It is replaced, not appended, on a re-run (the UPDATE strips the
    previous entry with the same kind+writer before appending this one)."""
    return {
        "kind": TAG_KIND, "writer": writer, "scopes": list(row.get("scopes") or []),
        "material": bool(row.get("material")), "catalyst_type": row.get("catalyst_type"),
        "severity": row.get("severity"), "tagged_at": now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
    }


# ── database reads ──────────────────────────────────────────────────────────────────────────────────────────
def _connect():
    from db_adapter import _get_conn

    return _get_conn()


def _scope_inputs(cur, policy: Mapping[str, Any], store: Mapping[str, Any]) -> tuple[list[str], list[str], list[str]]:
    held = [h.get("symbol") for h in (store.get("holdings") or [])
            if isinstance(h, dict) and h.get("symbol") and not h.get("is_cash")]
    cur.execute("SELECT DISTINCT upper(symbol) FROM trade_closed WHERE pnl < 0 AND close_date >= current_date - %s",
                (int(policy.get("stopped_out_days") or 30),))
    stopped = [r[0] for r in cur.fetchall()]
    cur.execute("SELECT DISTINCT upper(symbol) FROM watchlist_items WHERE status = 'active'")
    watch = [r[0] for r in cur.fetchall()]
    return held, stopped, watch


def _articles(cur, since: datetime, limit: int) -> list[dict[str, Any]]:
    cur.execute(
        """SELECT id, symbol, title, summary, published_at, created_at
             FROM news_articles
            WHERE COALESCE(published_at, created_at) >= %s
              AND NOT COALESCE(is_duplicate, FALSE)
              AND COALESCE(hygiene_status, 'active') = 'active'
            ORDER BY COALESCE(published_at, created_at) DESC
            LIMIT %s""",
        (since, limit),
    )
    cols = ("id", "symbol", "title", "summary", "published_at", "created_at")
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def _catalyst_by_news(cur, since: datetime) -> dict[str, dict[str, Any]]:
    cur.execute(
        """SELECT raw_payload->>'news_article_id' AS nid, catalyst_type, severity
             FROM catalyst_events
            WHERE COALESCE(published_at, created_at) >= %s AND raw_payload ? 'news_article_id'
            ORDER BY created_at DESC""",
        (since,),
    )
    out: dict[str, dict[str, Any]] = {}
    for nid, ctype, sev in cur.fetchall():
        if nid and nid not in out:  # newest first is not guaranteed; the first row per article wins
            out[str(nid)] = {"catalyst_type": ctype, "severity": sev}
    return out


def _open_market_episode(cur) -> str | None:
    cur.execute("SELECT episode_id FROM market_event_episodes WHERE state <> 'CLOSED' AND scope = 'market' "
                "ORDER BY opened_at DESC LIMIT 1")
    row = cur.fetchone()
    return str(row[0]) if row else None


# ── database writes (reached only under --apply) ────────────────────────────────────────────────────────────
def _tag(cur, row: Mapping[str, Any], payload: dict[str, Any], writer: str) -> int:
    """Append this lane's tag, replacing any earlier one. One statement, so a concurrent append cannot be lost:
    entry = COALESCE(tags,'[]') minus (kind+writer), then || the new entry."""
    cur.execute(
        """UPDATE news_articles
              SET agent_tags = (
                    SELECT COALESCE(jsonb_agg(e), '[]'::jsonb)
                      FROM jsonb_array_elements(COALESCE(agent_tags, '[]'::jsonb)) e
                     WHERE NOT (e->>'kind' = %s AND e->>'writer' = %s)
                  ) || %s::jsonb
            WHERE id = %s""",
        (TAG_KIND, writer, json.dumps([payload]), row["news_id"]),
    )
    return cur.rowcount


def _raise_catalyst(cur, row: Mapping[str, Any], now: datetime) -> int:
    """Insert the catalyst row only when the canonical lane has none; a present row is already the truth and is
    never rewritten here (severity stays the classifier's)."""
    cur.execute(
        """INSERT INTO catalyst_events
             (symbol, catalyst_type, headline, severity, confidence, impact_score, source, published_at, raw_payload)
           VALUES (%s, %s, %s, %s, NULL, NULL, %s, %s, %s::jsonb)
           ON CONFLICT (symbol, headline) DO NOTHING""",
        (row["symbol"], row["catalyst_type"], row["title"], row["severity"], LANE,
         row.get("published_at"), json.dumps({"news_article_id": row["news_id"], "writer": LANE,
                                              "scopes": row["scopes"],
                                              "raised_at": now.astimezone(timezone.utc).isoformat()})),
    )
    return cur.rowcount


def _raise_candidate(cur, episode_id: str, row: Mapping[str, Any], now: datetime) -> int:
    """Provenance-only candidate: never ranked, never overwriting the lane's own row (ON CONFLICT DO NOTHING)."""
    cur.execute(
        """INSERT INTO market_event_candidates (episode_id, symbol, source, reason_evidence, state, updated_at)
           VALUES (%s, %s, ARRAY[%s]::text[], %s::jsonb, 'WATCH', %s)
           ON CONFLICT (episode_id, symbol) DO NOTHING""",
        (episode_id, row["symbol"], LANE,
         json.dumps({"raised_by": LANE, "news_ids": [row["news_id"]], "scopes": row["scopes"],
                     "catalyst_type": row["catalyst_type"], "severity": row["severity"],
                     "as_of": now.astimezone(timezone.utc).isoformat()}), now),
    )
    return cur.rowcount


def run(now: datetime | None = None, *, apply: bool = False, hours: int | None = None,
        policy: Mapping[str, Any] | None = None, connect=None, store_loader=None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    policy = policy or load_policy()
    if not policy.get("enabled", True):
        return {"mode": "REFUSED", "reason": "disabled_by_config", "produced_count": 0}
    # "since last close" is the lane's floor; --hours is an explicit manual override, never a quieter default
    since = last_close(now) if hours is None else now - timedelta(hours=int(hours))
    store_loader = store_loader or (lambda: __import__("lib.portfolio_positions", fromlist=["load_store"]).load_store())
    conn = (connect or _connect)()
    cur = conn.cursor()
    try:
        if not apply:
            from lib.lane_last_receipt import enforce_readonly

            enforce_readonly(conn)
        store = store_loader() or {}
        held, stopped, watch = _scope_inputs(cur, policy, store)
        scope = build_scope(held, stopped, watch)
        articles = _articles(cur, since, int(policy.get("max_articles") or 5000))
        tagged, raised = plan_raises(articles, _catalyst_by_news(cur, since), scope, policy)
        episode = _open_market_episode(cur)
        out = {
            "mode": "APPLY" if apply else "DRY",
            "as_of": now.astimezone(timezone.utc).isoformat(),
            "since": since.isoformat(),
            "scope_symbols": len(scope),
            "scopes": {k: sum(1 for v in scope.values() if k in v) for k in ("held", "stopped_out", "watchlist")},
            "articles_seen": len(articles),
            "tagged": len(tagged),
            "tagged_by_scope": {s: sum(1 for r in tagged if s in r["scopes"])
                                for s in ("held", "stopped_out", "watchlist")},
            "raised": len(raised),
            "raised_symbols": sorted({r["symbol"] for r in raised}),
            "episode_id": episode,
            "applied": {"tagged": 0, "catalyst_events": 0, "candidates": 0},
            "produced_count": len({(r["news_id"], r["symbol"]) for r in raised}),
            "sample": [{k: r[k] for k in ("symbol", "scopes", "catalyst_type", "severity", "material", "news_id")}
                       for r in raised[:20]],
        }
        if apply:
            writer = str(policy.get("tag_writer") or LANE)
            raise_cfg = policy.get("raise") or {}
            for row in tagged:
                if raise_cfg.get("tag_articles", True):
                    out["applied"]["tagged"] += _tag(cur, row, tag_payload(row, now=now, writer=writer), writer)
            for row in raised:
                if raise_cfg.get("catalyst_events", True) and row["classification_basis"] == "news_to_catalyst_keywords":
                    out["applied"]["catalyst_events"] += _raise_catalyst(cur, row, now)
                if raise_cfg.get("market_event_candidates", True) and episode:
                    out["applied"]["candidates"] += _raise_candidate(cur, episode, row, now)
            conn.commit()
        else:
            conn.rollback()
        return out
    except Exception:
        _rollback_quietly(conn)
        raise
    finally:
        _close_quietly(cur, conn)


def _write_receipt(out: Mapping[str, Any], started: str) -> None:
    from lib.lane_last_receipt import write_lane_receipt

    # a receipt names counts, so a run that did not produce them is a programming error here, not a zero
    produced = int(out["produced_count"])
    write_lane_receipt(
        LANE, ok=True, exit_code=0, started_at=started, script="scripts/news_risk_raise.py",
        summary={k: out.get(k) for k in ("since", "scope_symbols", "scopes", "articles_seen", "tagged",
                                         "tagged_by_scope", "raised", "raised_symbols", "episode_id", "applied")},
        produced_count=produced, attempted_count=int(out["tagged"]),
        empty_reason=None if produced else "no_new_input",
        output_evidence=[{"kind": "db_rows", "ref": "news_articles.agent_tags + catalyst_events"}] if produced else [],
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--apply", action="store_true", help="write tags/raises and the lane receipt (default: dry run)")
    ap.add_argument("--dry-run", action="store_true", help="explicit dry run (the default)")
    ap.add_argument("--now", help="ISO timestamp to evaluate as (default: wall clock)")
    ap.add_argument("--hours", type=int, help="lookback ceiling in hours (default: the policy's 72)")
    ap.add_argument("--json", action="store_true", help="print only the JSON report")
    a = ap.parse_args(argv)
    now = None
    if a.now:
        now = datetime.fromisoformat(a.now.replace("Z", "+00:00"))
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
    started = datetime.now(timezone.utc).isoformat()
    apply = bool(a.apply) and not a.dry_run
    out = run(now, apply=apply, hours=a.hours)
    if apply and out.get("mode") == "APPLY":  # a REFUSED run wrote nothing: no receipt may say otherwise
        _write_receipt(out, started)
    print(json.dumps(out, indent=2, default=str, sort_keys=not a.json))
    return 0


if __name__ == "__main__":
    os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    raise SystemExit(main())
