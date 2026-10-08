"""aec_narrator.py — the AEC Executive Brief, rendered for the Command Center.

Operator 2026-10-07: the hourly brief is COMMAND CENTER ONLY, with real content. Until then it went to Telegram
every hour (400 of 400 sends accepted) and said nothing: each line printed a memory row's `kind` label
("cio_cycle_status" x5, "cycle touch" x5, "commitment_outcome" x3) because the spines hold only the cycle's own
bookkeeping, and its anti-repeat fingerprint included the timestamp, so every brief looked new.

Now the brief reads existing read-only producers and states facts with their age:
  * Portfolio      — lib/data_broker/portfolio_snapshot (written by the repricer)
  * Data health    — data/portfolios/state/health_agent_status.json (health agent)
  * Positions truth— data/runtime/positions_proof_ledger.jsonl + positions_sync_runs freshness
  * Commitments    — learning spine commitment_outcome rows, aggregated (last 24 h)
  * Agents         — AEC bus event counts
A section whose source is missing says "unavailable (<source>)"; a label is never printed as content.
The fingerprint covers the body WITHOUT the as_of line, so unchanged content is recognised as unchanged.

Constitutional: READ_ONLY_ADVISORY · MBI_BEHAVIOR=0. notify_executive_brief remains (Telegram through the
telegram_alert chokepoint) but the cycle only calls it when config/aec_narrator.yaml telegram: true AND
AEC_NARRATOR_NOTIFY=1 AND --apply (scripts/aec_command_center_cycle.py).
"""
from __future__ import annotations

import collections
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional

# G2: single spelling, no try/except fallback — see the note in aec_agent_bus.
from scripts.lib import aec_agent_bus as bus
from scripts.lib import aec_memory_spines as mem

AUTHORITY = "READ_ONLY_ADVISORY"
MBI_BEHAVIOR = 0
SCHEMA = "AecNarratorBrief@v2"
ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config" / "aec_narrator.yaml"
HEALTH_REL = Path("data") / "portfolios" / "state" / "health_agent_status.json"
PROOF_REL = Path("data") / "runtime" / "positions_proof_ledger.jsonl"


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _fp(text: str) -> str:
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()[:16]


def load_config(path: Optional[Path] = None) -> dict:
    """config/aec_narrator.yaml — `telegram` (default false: Command Center only, operator 2026-10-07)."""
    cfg = {"telegram": False}
    try:
        import yaml
        raw = yaml.safe_load((path or CONFIG_PATH).read_text(encoding="utf-8")) or {}
        cfg.update({k: v for k, v in (raw.get("narrator") or {}).items() if k in cfg})
    except Exception:  # noqa: BLE001 — unreadable config keeps Telegram OFF
        pass
    return cfg


def _age(ts: Any, now: datetime) -> str:
    """Clock time in ET (not a relative age): a brief whose facts did not change keeps its fingerprint."""
    try:
        from zoneinfo import ZoneInfo
        t = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        et = t.astimezone(ZoneInfo("America/New_York"))
        same_day = et.date() == now.astimezone(ZoneInfo("America/New_York")).date()
        return et.strftime("%H:%M ET") if same_day else et.strftime("%b %d %H:%M ET")
    except (TypeError, ValueError):
        return "time unknown"


def _money(x: Any, signed: bool = False) -> str:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return "—"
    sign = ("+" if v > 0 else "−" if v < 0 else "") if signed else ("−" if v < 0 else "")
    return f"{sign}${abs(v):,.0f}"


def _span(seconds: float) -> str:
    m = int(seconds // 60)
    return f"{m}m" if m < 120 else f"{m // 60}h"


# ── sources (read-only; each returns None when unavailable) ─────────────────

def _src_portfolio() -> Optional[dict]:
    from scripts.lib.data_broker.portfolio_snapshot import read_portfolio_snapshot
    return read_portfolio_snapshot()


def _state_root() -> Path:
    try:
        from scripts.lib.persistent_overlay import overlay_data_source
        return Path(overlay_data_source(canonical_source=ROOT))
    except Exception:  # noqa: BLE001
        return ROOT


def _src_health() -> Optional[dict]:
    p = _state_root() / HEALTH_REL
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None


def _src_proof() -> Optional[list]:
    p = _state_root() / PROOF_REL
    if not p.is_file():
        return None
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def _src_sync_freshness() -> Optional[dict]:
    import positions_sync as ps  # type: ignore
    conn = ps._conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT max(finished_at) FROM positions_sync_runs WHERE status = 'complete' AND promoted")
            last = cur.fetchone()[0]
        return ps.freshness(last, ps.load_sync_config())
    finally:
        conn.rollback()


SOURCES: dict[str, Callable[[], Any]] = {
    "portfolio": _src_portfolio, "health": _src_health, "proof": _src_proof, "sync": _src_sync_freshness,
}


def _read(name: str, sources: dict) -> Any:
    try:
        return sources[name]()
    except Exception:  # noqa: BLE001 — a failed source renders as unavailable, never as a guess
        return None


# ── sections (pure) ─────────────────────────────────────────────────────────

def section_portfolio(snap: Optional[dict], now: datetime) -> list[str]:
    if not snap or not snap.get("totals"):
        return ["- unavailable (data_broker/portfolio_snapshot.json)"]
    t = snap["totals"]
    pct = t.get("day_change_pct")
    out = [f"- Value {_money(t.get('total_value'))} · today {_money(t.get('day_change'), signed=True)}"
           + (f" ({float(pct):+.2f}%)" if pct is not None else "") + f" · as of {_age(snap.get('computed_at'), now)}"]
    accts = ((snap.get("account_states") or {}).get("accounts") or {})
    # Only accounts that SHOULD be live and are not (a closed/manual account is not news every hour).
    not_live = sorted(f"{k} {v.get('state')}" for k, v in accts.items() if v.get("state") in ("STALE", "SERVICE_DOWN"))
    if not_live:
        out.append("- Accounts stale or down: " + ", ".join(not_live))
    return out


def section_health(h: Optional[dict], now: datetime) -> list[str]:
    if not h:
        return [f"- unavailable ({HEALTH_REL})"]
    sev = collections.Counter(str(f.get("severity")) for f in (h.get("findings") or []))
    crit = sorted({str(f.get("type")) for f in (h.get("findings") or []) if f.get("severity") == "critical"})
    line = (f"- Score {h.get('overall_score')} ({h.get('status')}) · {sev.get('critical', 0)} critical · "
            f"{sev.get('warning', 0)} warning · checked {_age(h.get('captured_at'), now)}")
    return [line] + ([f"- Critical: {', '.join(crit[:6])}"] if crit else [])


def section_positions(ledger: Optional[list], fresh: Optional[dict], now: datetime) -> list[str]:
    out = []
    if fresh is None:
        out.append("- Sync freshness unavailable (positions_sync_runs)")
    else:
        last = fresh.get("last_complete")
        out.append(f"- Positions sync {'STALE' if fresh.get('stale') else 'fresh'} · last complete "
                   f"{'never' if not last else _age(last, now)} (stale after {_span(fresh['limit_s'])})")
    if not ledger:
        out.append(f"- Proof ledger unavailable ({PROOF_REL})")
    else:
        last = sorted(ledger, key=lambda r: r["date"])[-1]
        try:
            import positions_proof_daily as pd  # type: ignore
            cfg = pd.load_proof_config()
            from datetime import date as _d
            n = pd.proof_day_number(ledger, _d.fromisoformat(last["date"]), _d.fromisoformat(str(cfg["start"])))
            total = int(cfg["days"])
        except Exception:  # noqa: BLE001
            n, total = None, 10
        failed = [k for k, v in (last.get("checks") or {}).items() if not v.get("ok")]
        out.append(f"- Proof {last['date']}: {'PASS' if last.get('pass') else 'FAIL (' + ', '.join(failed) + ')'}"
                   + (f" · day {n} of {total}" if n is not None else ""))
    return out


def section_commitments(learning: list[dict], now: datetime) -> list[str]:
    since = (now - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = [r for r in learning if r.get("kind") == "commitment_outcome" and str(r.get("recorded_at") or "") >= since]
    if not rows:
        return ["- No commitments settled in the last 24 h"]
    c = collections.Counter(str(r.get("outcome") or "UNKNOWN") for r in rows)
    evidenced = sum(n for k, n in c.items() if k not in ("INSUFFICIENT_EVIDENCE", "EXPIRED", "UNKNOWN"))
    detail = " · ".join(f"{n} {k.lower().replace('_', ' ')}" for k, n in c.most_common())
    return [f"- {len(rows)} settled in 24 h · {evidenced} with evidence · {detail}"]


def section_agents(recent: list[dict], now: datetime) -> list[str]:
    since = (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    last_hour = [r for r in recent if str(r.get("as_of") or "") >= since]
    by = collections.Counter(str(r.get("agent_id")) for r in last_hour)
    if not by:
        return ["- No agent bus events in the last hour"]
    return ["- Last hour: " + ", ".join(f"{a} {n}" for a, n in sorted(by.items()))]


def _dedupe(lines: list[str]) -> list[str]:
    seen, out = set(), []
    for l in lines:
        if l.startswith("- ") and l in seen:
            continue
        seen.add(l)
        out.append(l)
    return out


def render_executive_brief(
    *,
    subject_key: str | None = None,
    recent_limit: int = 200,
    sources: Optional[dict[str, Callable[[], Any]]] = None,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Compose the brief from read-only producers (no send)."""
    now = now or datetime.now(timezone.utc)
    src = dict(SOURCES, **(sources or {}))
    snap = mem.load()
    recent = bus.read_recent(limit=recent_limit)
    content = ["Portfolio"] + section_portfolio(_read("portfolio", src), now) + [""]
    content += ["Data health"] + section_health(_read("health", src), now) + [""]
    content += ["Positions truth"] + section_positions(_read("proof", src), _read("sync", src), now) + [""]
    content += ["Agent commitments"] + section_commitments(list(snap.spines.get("learning") or []), now) + [""]
    content += ["Agents"] + section_agents(recent, now)
    content = _dedupe(content)
    header = ["Trade AI — Executive Brief", f"subject: {subject_key or 'PORTFOLIO'}", ""]
    footer = ["", "Authority: READ_ONLY_ADVISORY · MBI_BEHAVIOR=0 · Command Center only"]
    stable = "\n".join(header + content + footer)
    fp = _fp(stable)                                   # no timestamp: unchanged content keeps its fingerprint
    as_of = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    body = "\n".join(header[:1] + [f"as_of: {as_of}"] + header[1:] + content + footer)
    repeated = mem.seen_claim(snap, fp) or any(
        (r.get("topic") == "cycle.narrator.brief" and (r.get("payload") or {}).get("claim_fp") == fp)
        for r in recent[-3:])
    return {
        "schema": SCHEMA,
        "as_of": as_of,
        "subject_key": subject_key,
        "body": body,
        "claim_fp": fp,
        "suppressed_repeat": repeated,
        "authority": AUTHORITY,
        "mbi_behavior": MBI_BEHAVIOR,
        "financial_action": False,
        "would_telegram": False if repeated else bool(load_config().get("telegram")),
    }


def notify_executive_brief(
    brief: dict[str, Any],
    *,
    apply: bool = False,
) -> dict[str, Any]:
    """Send brief via telegram chokepoint. Default apply=False → dry-run receipt."""
    out = dict(brief)
    out["notify_attempted"] = False
    out["telegram"] = "dry_run"
    if brief.get("suppressed_repeat"):
        out["telegram"] = "suppressed_repeat"
        return out
    if not apply:
        return out
    out["notify_attempted"] = True
    try:
        from telegram_alert import send_telegram  # noqa: WPS433 — production chokepoint

        sent = send_telegram(
            brief["body"],
            bypass_router=True,
            message_class="operator_alert",
        )
        out["telegram"] = "accepted" if sent else "send_returned_false"
    except Exception as e:  # noqa: BLE001 — receipt must record failure class
        out["telegram"] = f"error:{type(e).__name__}:{e}"
    return out
