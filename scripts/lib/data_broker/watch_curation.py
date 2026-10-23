"""Watch curation — My Watchlist and System Suggests (operator 2026-10-23). Read-only. Zero provider calls.

Operator 2026-10-23 (verbatim): "aesthetically, the watch list looks better, but I don't see stuff that I had starred
that I was watching ... And what's the difference between a proposals and the opportunities? They don't even align
right now. So where is my traditional watch list, the stuff that I was watching, and where is the automated watch
list, the stuff that the system is proposing for me?"

What this returns (``WatchCuration@v1``):

* **My Watchlist** — every operator name (``watch_domains.membership_operator``: stars, the personal watchlist,
  operator watch directives, operator adds), starred first. Never bounded by a lane cap and never dropped by expiry:
  an expired signal only *suggests* a review (``expiry_suggestion``). Each row is the same row the Prospects lanes
  show (``watch_prospects.gather``), so stage, conviction, stance, next trigger and what is missing are identical.
* **System Suggests** — the top N (default 20, max 30) of the ONE ranked list the Full universe shows (the CIO
  opportunity curator's rank, ``cio_opportunity_projection.json``), skipping names you hold, names already on your
  list and names you dismissed — each skip named. Membership rotates with hysteresis (the focus-list rule of the
  scalp focus list, operator 2026-10-23: "a mechanism that's bringing stuff in and out of the top 20"): a name enters
  at position <= N, stays while it ranks inside 1.5 x N, and an entrant displaces the weakest member only when that
  member sits more than N/2 places below N. Every entry and exit carries its reason. The previous membership is
  derived from the curator's own ``rank_history`` (one more key the curator writes on each item), so no new store.
* **Ownership conflicts** — names the curator treats as owned that the broker-synced held reader (positions_store
  reader batch #1, surface "watch") says are not held, and the reverse. Shown with both values, never resolved here
  (AGENTS.md §26.5). Fixes the symptom "NAVN Add-On after it was sold" on Watch while the curator's own held read
  (proposed reader batch #4) awaits the operator.

Dismissals are operator commands recorded in the ``watchlist_events`` log (event_type ``watch_suggest_dismissed`` /
``watch_suggest_restored``) by ``api_v3_watch_commands.post_suggest_decision``; read here, last event wins, 30 days.

``MBI_BEHAVIOR = 0``: a rank is attention, never a size, order, stop or weight.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

SCHEMA = "WatchCuration@v1"
DEFAULT_N = 20
HARD_MAX = 30
EXIT_MULT = 1.5  # stay while inside ceil(1.5 x N)
DISPLACE_MULT = 0.5  # an entrant displaces a member only when that member is > N + ceil(N/2)
DISMISS_DAYS = 30
EVENT_DISMISSED = "watch_suggest_dismissed"
EVENT_RESTORED = "watch_suggest_restored"
LANE_ORDER = {"actionable": 0, "reentry": 1, "forming": 2, "manage": 3, "expired": 4}

HOW = [
    {
        "id": "my_watchlist",
        "title": "My Watchlist",
        "body": "Your names: the ones you starred, your personal watchlist, your watch directives and names you added "
        "or proposed. Starred first. Never dropped by a cap or by expiry — when a signal expires the row says "
        "so and suggests a review; only you remove a name.",
    },
    {
        "id": "suggests",
        "title": "System Suggests",
        "body": "The system's proposals for your list: the top 20 (up to 30) of the same ranked list the Full universe "
        "shows, minus what you hold, what is already yours and what you dismissed. Names rotate in and out with "
        "a reason. Add one to your watchlist, or dismiss it for 30 days.",
    },
    {
        "id": "prospects",
        "title": "Prospects",
        "body": "Every name on Watch (yours and the system's) by stage: Actionable now, Setup forming, Re-entry near, "
        "Manage (held), Expired. Your names are always listed; caps bound only the system's names.",
    },
    {
        "id": "full_universe",
        "title": "Full universe (research)",
        "body": "Everything the CIO curator scored (~1,600 names), ranked by conviction. Research, not a to-do list: "
        "System Suggests is its top, filtered.",
    },
    {
        "id": "proposals",
        "title": "Trading → Proposals",
        "body": "Not a watchlist. A proposal is a sized trade idea waiting for your approve / reject. A name gets "
        "there when you press Propose on an actionable row (or an agent files one). Watching a name never "
        "creates a proposal.",
    },
]


def _f(v: Any) -> Optional[float]:
    try:
        return float(v) if v is not None and v != "" else None
    except (TypeError, ValueError):
        return None


def _ts(v: Any) -> Optional[datetime]:
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    try:
        t = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def clamp_n(n: Any) -> int:
    try:
        v = int(n)
    except (TypeError, ValueError):
        v = DEFAULT_N
    return max(1, min(HARD_MAX, v))


def prev_point(item: dict[str, Any]) -> tuple[Optional[int], Optional[float], Optional[str]]:
    """(rank, conviction, as_of) at the curator's previous run, from the item's rank_history (oldest → newest; the
    newest entry is the current run)."""
    hist = item.get("rank_history") or []
    if not isinstance(hist, list) or len(hist) < 2:
        return None, None, None
    p = hist[-2]
    if not isinstance(p, (list, tuple)) or len(p) < 3:
        return None, None, None
    r = p[1]
    return (int(r) if isinstance(r, (int, float)) else None), _f(p[2]), (str(p[0]) if p[0] else None)


# ── membership with hysteresis (pure) ────────────────────────────────────────


def rotate(now_order: list[str], prev_order: Optional[list[str]], n: int) -> dict[str, Any]:
    """Members now, given the eligible names in rank order now and at the previous run (None = no history).

    The focus-list rule: enter at position <= n while there is room; a previous member stays while its position is
    <= ceil(1.5 n); an entrant at position <= n displaces the worst member only when that member's position is
    > n + ceil(n/2); never more than n members."""
    n = clamp_n(n)
    exit_pos = int(math.ceil(n * EXIT_MULT))
    margin = max(1, int(math.ceil(n * DISPLACE_MULT)))
    pos = {s: i for i, s in enumerate(now_order, 1)}
    if prev_order is None:
        members = list(now_order[:n])
        return {"members": members, "prev_members": None, "exit_pos": exit_pos, "margin": margin, "pos": pos}
    prev_members = list(prev_order[:n])
    members = [s for s in prev_members if s in pos and pos[s] <= exit_pos]
    for s in now_order:
        if len(members) >= n:
            break
        if s not in members:
            members.append(s)
    for s in now_order[:n]:
        if s in members:
            continue
        worst = max(members, key=lambda m: pos[m]) if members else None
        if worst is not None and pos[worst] > n + margin:
            members.remove(worst)
            members.append(s)
        else:
            break
    members.sort(key=lambda m: pos[m])
    return {"members": members, "prev_members": prev_members, "exit_pos": exit_pos, "margin": margin, "pos": pos}


def _top_factor(item: dict[str, Any]) -> Optional[str]:
    best = None
    for key, fx in (item.get("factors") or {}).items():
        if not isinstance(fx, dict) or _f(fx.get("score")) is None:
            continue
        contrib = (_f(fx.get("score")) or 0) * (_f(fx.get("weight")) or 0)
        if best is None or contrib > best[0]:
            best = (contrib, fx.get("label") or key, fx.get("detail"))
    if not best:
        return None
    return f"{best[1]}: {best[2]}" if best[2] else str(best[1])


def suggest(
    opps: dict[str, dict[str, Any]],
    *,
    n: int,
    held: set[str],
    mine: dict[str, dict[str, Any]],
    dismissed: dict[str, dict[str, Any]],
    proj_as_of: Any = None,
) -> dict[str, Any]:
    """Pure: the curator's ranked items → System Suggests (members with reasons, who left and why, what was skipped).

    ``mine`` is membership_operator()["names"]; ``dismissed`` is {SYM: {at, by, reason}}. Timestamps decide whether
    a name was already yours / dismissed at the previous run (so "left: added to your watchlist" is said once)."""
    n = clamp_n(n)
    ranked = sorted(
        (s for s, a in opps.items() if isinstance(a, dict) and isinstance(a.get("rank"), int)),
        key=lambda s: (opps[s]["rank"], s),
    )

    def why_skip(s: str) -> Optional[str]:
        if s in held:
            return "held"
        if s in mine:
            return "mine"
        if s in dismissed:
            return "dismissed"
        return None

    now_order = [s for s in ranked if why_skip(s) is None]
    skipped: dict[str, list[dict[str, Any]]] = {"held": [], "mine": [], "dismissed": []}
    for s in ranked[: max(n * 3, n + 30)]:
        k = why_skip(s)
        if k:
            skipped[k].append({"symbol": s, "universe_rank": opps[s]["rank"]})

    # Previous run: rank order from rank_history, with what was already excluded THEN (held now is assumed then).
    prev_at: Optional[str] = None
    prev_rank: dict[str, int] = {}
    prev_conv: dict[str, Optional[float]] = {}
    for s, a in opps.items():
        r, c, at = prev_point(a)
        if r is not None:
            prev_rank[s], prev_conv[s] = r, c
            prev_at = prev_at or at
    prev_t = _ts(prev_at)

    def excluded_then(s: str) -> bool:
        if s in held:
            return True
        if s in mine:
            ats = [_ts(x.get("at")) for x in (mine[s].get("reasons") or [])]
            first = min((t for t in ats if t), default=None)
            if first is None or prev_t is None or first <= prev_t:
                return True
        if s in dismissed:
            t = _ts(dismissed[s].get("at"))
            if t is None or prev_t is None or t <= prev_t:
                return True
        return False

    prev_order = None
    if prev_rank:
        prev_order = [s for s in sorted(prev_rank, key=lambda x: (prev_rank[x], x)) if not excluded_then(s)]
    rot = rotate(now_order, prev_order, n)
    pos, exit_pos = rot["pos"], rot["exit_pos"]
    prev_members = set(rot["prev_members"] or [])

    members = []
    for s in rot["members"]:
        a = opps[s]
        p = pos[s]
        conv = _f(a.get("conviction"))
        new = rot["prev_members"] is not None and s not in prev_members
        if rot["prev_members"] is None:
            status, reason = (
                "listed",
                f"Universe rank #{a['rank']} · conviction {conv:.0f}"
                if conv is not None
                else f"Universe rank #{a['rank']}",
            )
        elif new:
            was = prev_rank.get(s)
            pc = prev_conv.get(s)
            bits = [f"entered at #{a['rank']}" + (f" (was #{was})" if was else " (new to the ranking)")]
            if conv is not None:
                bits.append(
                    f"conviction {conv:.0f}"
                    + (f" (was {pc:.0f})" if pc is not None and round(pc) != round(conv) else "")
                )
            status, reason = "entered", ", ".join(bits)
        elif p > n:
            status, reason = (
                "holding",
                (f"kept: #{a['rank']} — still inside the exit band (top {exit_pos} of the eligible list)"),
            )
        else:
            status, reason = "steady", f"#{a['rank']} · conviction {conv:.0f}" if conv is not None else f"#{a['rank']}"
        tf = _top_factor(a)
        members.append(
            {
                "symbol": s,
                "universe_rank": a["rank"],
                "position": p,
                "status": status,
                "reason": reason,
                "top_factor": tf,
                "conviction": conv,
                "stance": a.get("stance"),
                "type": a.get("type"),
            }
        )

    left = []
    if rot["prev_members"] is not None:
        member_set = set(rot["members"])
        for s in rot["prev_members"]:
            if s in member_set:
                continue
            a = opps.get(s) or {}
            k = why_skip(s)
            if k == "held":
                reason = "left: you hold it now (see Manage)"
            elif k == "mine":
                reason = "left: added to your watchlist"
            elif k == "dismissed":
                reason = "left: dismissed by you"
            elif not isinstance(a.get("rank"), int):
                reason = "left: no longer ranked by the curator"
            else:
                pc, c = prev_conv.get(s), _f(a.get("conviction"))
                reason = f"left: fell to #{a['rank']} (outside the top {exit_pos} eligible)" + (
                    f", conviction {pc:.0f} → {c:.0f}" if pc is not None and c is not None else ""
                )
            left.append({"symbol": s, "reason": reason, "universe_rank": a.get("rank"), "prev_rank": prev_rank.get(s)})
    return {
        "n": n,
        "n_default": DEFAULT_N,
        "n_max": HARD_MAX,
        "members": members,
        "left": left,
        "skipped": skipped,
        "eligible": len(now_order),
        "ranked": len(ranked),
        "rotation": {
            "available": rot["prev_members"] is not None,
            "previous_run_at": prev_at,
            "current_run_at": proj_as_of,
            "exit_band": exit_pos,
            "displace_margin": rot["margin"],
            "rule": (
                f"enter at position ≤ {n}; stay while inside the top {exit_pos}; an entrant displaces the "
                f"weakest member only when it sits more than {rot['margin']} places below {n}"
            ),
            "unavailable_reason": None
            if rot["prev_members"] is not None
            else "the curator has not recorded a previous rank yet (rank_history) — rotation reasons start with "
            "its next run",
        },
    }


# ── ownership — curator vs the broker-synced held reader (shown, never resolved) ──


def ownership_conflicts(
    opps: dict[str, dict[str, Any]], *, held: set[str], held_source: str, held_detail: Optional[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Names where the curator's position_status and the Watch held reader disagree (AGENTS.md §26.5).

    Only measured against a fresh broker-synced answer (positions_current); against the holdings file the two read
    the same source and a disagreement means nothing."""
    hd = held_detail or {}
    if not str(held_source).startswith("positions_store") or hd.get("stale"):
        return []
    out = []
    for s, a in sorted(opps.items()):
        if not isinstance(a, dict):
            continue
        owned = a.get("position_status") == "owned"
        if owned == (s in held):
            continue
        out.append(
            {
                "symbol": s,
                "kind": "ownership",
                "summary": (
                    "The curator treats it as owned (type {t}, stance {st}); the broker-synced positions say not held"
                    if owned
                    else "Held per the broker-synced positions; the curator treats it as not owned (type {t})"
                ).format(t=str(a.get("type") or "—").replace("_", "-"), st=a.get("stance") or "—"),
                "a": {
                    "value": a.get("position_status"),
                    "source": "cio_opportunity_projection.position_status",
                    "at": a.get("as_of"),
                },
                "b": {"value": "held" if s in held else "not held", "source": held_source, "at": hd.get("as_of")},
                "curator_type": a.get("type"),
                "curator_stance": a.get("stance"),
                "universe_rank": a.get("rank"),
            }
        )
    return out


# ── my watchlist ─────────────────────────────────────────────────────────────


def my_rows(
    operator: dict[str, dict[str, Any]], row_for: Callable[[str], dict[str, Any]], opps: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    """Every operator name, starred first, then by stage (actionable → re-entry → forming → manage), then conviction.
    Never capped."""
    rows = []
    for s in operator:
        r = dict(row_for(s))
        r["universe_rank"] = (opps.get(s) or {}).get("rank")
        rows.append(r)
    rows.sort(
        key=lambda r: (
            not r.get("starred"),
            LANE_ORDER.get(r.get("lane"), 9),
            r.get("conviction") is None,
            -(r.get("conviction") or 0.0),
            r["symbol"],
        )
    )
    return rows


def build_curation(
    g: dict[str, Any],
    *,
    n: Any = DEFAULT_N,
    dismissed: Optional[dict[str, dict[str, Any]]] = None,
    dismissed_status: str = "ok",
    filters: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Pure over gather() output: the WatchCuration@v1 payload."""
    dismissed = dismissed or {}
    operator = g.get("operator") or {}
    opps = g.get("opps") or {}
    held = set(g.get("held") or ())
    sug = suggest(
        opps, n=n, held=held, mine=operator, dismissed=dismissed, proj_as_of=(g.get("proj_meta") or {}).get("as_of")
    )
    row_for = g["row_for"]
    sug_rows = []
    for m in sug["members"]:
        r = dict(row_for(m["symbol"]))
        r["suggestion"] = m
        r["universe_rank"] = m["universe_rank"]
        sug_rows.append(r)
    mine_all = my_rows(operator, row_for, opps)
    from lib.data_broker import watch_position_facts as wpf

    now = g.get("now") or datetime.now(timezone.utc)
    active = wpf.active_filters(filters or {})
    mine_rows = [r for r in mine_all if wpf.passes(r, active, now=now)] if active else mine_all
    sort = str((filters or {}).get("sort") or "")
    if sort in wpf.SORTS:
        mine_rows = sorted(mine_rows, key=lambda r: (*wpf.sort_key(sort, r, r.get("conviction")), r["symbol"]))
    payload = g.get("payload") or {}
    return {
        "ok": True,
        "schema": SCHEMA,
        "generated_at": (g.get("now") or datetime.now(timezone.utc)).isoformat(),
        "source": payload.get("source"),
        "interim": payload.get("interim"),
        "source_label": payload.get("source_label"),
        "position_facts": payload.get("position_facts"),
        "cio_prospect_status": g.get("cp_status"),
        "ranking": {
            **(g.get("proj_meta") or {}),
            "label": "Full universe rank — the CIO curator's conviction order",
            "same_list_as": "Watch › Full universe (/api/v3/opportunities, sort=conviction)",
        },
        "held": {
            "source": g.get("held_source"),
            "as_of": (g.get("held_detail") or {}).get("as_of"),
            "stale": (g.get("held_detail") or {}).get("stale"),
            "fallback_reason": (g.get("held_detail") or {}).get("fallback_reason"),
        },
        "my_watchlist": {
            "count": len(mine_rows),
            "unfiltered_count": len(mine_all),
            "starred": sum(1 for r in mine_rows if r.get("starred")),
            "rows": mine_rows,
            "sources": (payload.get("operator_sources") or {}),
            "filters": active,
            "position_facets": wpf.facet_counts(mine_all, now=now),
            "position_filters": wpf.FILTERS,
            "position_sorts": wpf.SORTS,
            "never_capped": True,
            "expiry": "an expired signal only suggests a review; only you remove a name",
        },
        "suggests": {
            **{k: v for k, v in sug.items() if k != "members"},
            "rows": sug_rows,
            "dismissed": [{"symbol": s, **d} for s, d in sorted(dismissed.items())],
            "dismissed_status": dismissed_status,
            "actions": {
                "add": {
                    "method": "POST",
                    "path": "/api/v2/watch/directives",
                    "body": {
                        "kind": "ticker",
                        "label": "Watchlist",
                        "spec": {"symbol": "<SYM>"},
                        "created_by": "operator",
                    },
                },
                "dismiss": {
                    "method": "POST",
                    "path": "/api/v3/watch/commands/suggest-dismiss",
                    "body": {"symbol": "<SYM>", "reason": "<optional>"},
                },
                "restore": {
                    "method": "POST",
                    "path": "/api/v3/watch/commands/suggest-restore",
                    "body": {"symbol": "<SYM>"},
                },
            },
        },
        "ownership_conflicts": ownership_conflicts(
            opps, held=held, held_source=str(g.get("held_source") or ""), held_detail=g.get("held_detail")
        ),
        "how": HOW,
        "authority": "READ_ONLY_ADVISORY",
        "mbi_behavior": 0,
        "provider_calls": 0,
    }


# ── dismissals (read) ────────────────────────────────────────────────────────


def read_dismissed(
    db_query: Optional[Callable[..., Any]] = None, *, now: Optional[datetime] = None
) -> tuple[dict[str, dict[str, Any]], str]:
    """({SYM: {at, by, reason}}, status). Latest event per symbol wins; a dismissal lasts DISMISS_DAYS."""
    now = now or datetime.now(timezone.utc)
    if db_query is None:
        try:
            from db_adapter import _execute

            def db_query(sql, params=None):
                return _execute(sql, params, fetch="all")
        except Exception:  # noqa: BLE001
            return {}, "unavailable"
    try:
        rows = (
            db_query(
                """SELECT DISTINCT ON (upper(symbol)) upper(symbol) AS s, event_type, created_at, payload
                 FROM watchlist_events
                WHERE event_type IN (%s, %s) AND created_at > %s
                ORDER BY upper(symbol), created_at DESC, id DESC""",
                (EVENT_DISMISSED, EVENT_RESTORED, now - timedelta(days=DISMISS_DAYS)),
            )
            or []
        )
    except Exception as e:  # noqa: BLE001
        return {}, f"error:{type(e).__name__}"
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        if r.get("event_type") != EVENT_DISMISSED:
            continue
        p = r.get("payload") or {}
        if isinstance(p, str):
            import json

            try:
                p = json.loads(p)
            except ValueError:
                p = {}
        at = r.get("created_at")
        out[str(r["s"]).upper()] = {
            "at": at.isoformat() if hasattr(at, "isoformat") else at,
            "by": p.get("by"),
            "reason": p.get("reason"),
            "until": ((at + timedelta(days=DISMISS_DAYS)).isoformat() if hasattr(at, "isoformat") else None),
        }
    return out, "ok"


def list_watch_curation(query: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """GET /api/v3/data-broker/watch-curation?n=20 — My Watchlist + System Suggests (shares the Prospects cache)."""
    from lib.data_broker.watch_prospects import gather

    q = query or {}
    g = gather(q)
    dismissed, status = read_dismissed()
    out = build_curation(g, n=q.get("n") or DEFAULT_N, dismissed=dismissed, dismissed_status=status, filters=q)
    out["data_broker"] = {
        "package": "scripts/lib/data_broker",
        "projection": "watch_curation",
        "catalog": "/api/v3/data-broker",
        "read_only": True,
        "provider_calls": 0,
    }
    return out


# ── "Add symbol" typeahead (operator 2026-10-23: "I still don't see an area where I can select what I want to
# watch") ───────────────────────────────────────────────────────────────────────────────────────────────────────

SEARCH_LIMIT = 12


def search_symbols(
    q: str,
    *,
    by_symbol: dict[str, Any],
    entities: dict[str, Any],
    names: dict[str, str],
    mine: set[str],
    limit: int = SEARCH_LIMIT,
) -> list[dict[str, Any]]:
    """Pure: ticker or company-name search. Tickers come from the security (identity) registry ``by_symbol``; names
    from the broker instrument feed and the curator projection (``names``: SYM → name). Ranked exact ticker →
    ticker prefix → name prefix → name contains; CUSIP-shaped keys are never offered."""
    from lib.data_broker.watch_domains import looks_like_cusip

    qq = str(q or "").strip().upper()
    if not qq:
        return []
    cands: dict[str, int] = {}
    universe = set(by_symbol) | set(names)
    for s in universe:
        if not s or looks_like_cusip(s):
            continue
        name = str(names.get(s) or "").upper()
        score = None
        if s == qq:
            score = 0
        elif s.startswith(qq):
            score = 1
        elif len(qq) >= 2 and name.startswith(qq):
            score = 2
        elif len(qq) >= 3 and qq in name:
            score = 3
        if score is not None:
            cands[s] = score
    out = []
    for s in sorted(cands, key=lambda x: (cands[x], len(x), x))[:limit]:
        ent = None
        guid = by_symbol.get(s)
        if guid:
            ent = entities.get(guid) or {}
        out.append(
            {
                "symbol": s,
                "name": names.get(s),
                "identity_status": (ent or {}).get("identity_status"),
                "security_guid": (ent or {}).get("security_guid"),
                "in_registry": bool(guid),
                "on_my_list": s in mine,
                "match": ("ticker" if cands[s] <= 1 else "name"),
            }
        )
    return out


def list_symbol_search(query: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """GET /api/v3/data-broker/watch-symbol-search?q= — typeahead for My Watchlist's "Add symbol" box. Read-only."""
    q = str((query or {}).get("q") or "")[:40]
    by_symbol: dict[str, Any] = {}
    entities: dict[str, Any] = {}
    try:
        from lib import identity_registry as ir

        doc = ir.load_cached()
        by_symbol, entities = dict(doc.get("by_symbol") or {}), dict(doc.get("entities") or {})
    except Exception:  # noqa: BLE001
        pass
    names: dict[str, str] = {}
    try:
        try:
            from scripts.lib.company_name_index import _instruments
        except ImportError:  # pragma: no cover
            from lib.company_name_index import _instruments  # type: ignore
        for s, rec in (_instruments() or {}).items():
            if (rec or {}).get("description"):
                names[str(s).upper()] = str(rec["description"])
    except Exception:  # noqa: BLE001
        pass
    mine: set[str] = set()
    try:
        from lib.data_broker.watch_prospects import _curator_projection, gather

        for s, a in ((_curator_projection().get("items")) or {}).items():
            if isinstance(a, dict) and a.get("company") and str(s).upper() not in names:
                names[str(s).upper()] = str(a["company"])
        mine = set((gather({}).get("operator") or {}))
    except Exception:  # noqa: BLE001
        pass
    return {
        "ok": True,
        "schema": "WatchSymbolSearch@v1",
        "q": q,
        "results": search_symbols(q, by_symbol=by_symbol, entities=entities, names=names, mine=mine),
        "sources": {"tickers": "identity registry by_symbol", "names": "broker instrument feed + curator"},
        "read_only": True,
        "provider_calls": 0,
    }
