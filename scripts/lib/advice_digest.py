"""Advice digests — non-urgent advice as three HTML digests a day (operator 2026-10-08).

"New CIO decisions, re-entry, anything dealing with a stock upgrade, a downgrade, or advice that's not urgent should
be put into comprehensive digests … ticker, catalyst, rating, entry, target, latest news, and links back to it in the
Command Center — the ticker and the Communication Center. 10 a.m., 3 p.m., and 5 p.m. with anything that has moved up
or moved down. HTML, clearly formatted."

Sources (read-only, no provider calls):
  * new advice — communication_events in the window (every routed send is recorded there even when the router
    archives it) for the configured categories, plus CIO-bot advisory notes held PENDING in the CIO outbox;
  * per ticker — data-broker quote now, CIO opportunity levels + conviction (CIO memory), analyst rating + target
    (yahoo_analyst_targets_history), latest catalyst (catalyst_events) and news headline (news_articles);
  * 17:00 movers — today's price moves, analyst rating/target changes, CIO conviction changes, new catalysts;
  * other updates — the P1 archive (stop warnings, system health …) that the old P1 digest delivered.
Rules in config/advice_digest.yaml. Advisory only (MBI_BEHAVIOR = 0): levels are references, never orders.
"""
from __future__ import annotations

import json
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional

try:
    from scripts.lib.telegram_rich import cc_base, esc, link
except ImportError:  # pragma: no cover - flat import layout
    from lib.telegram_rich import cc_base, esc, link  # type: ignore

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config" / "advice_digest.yaml"
_cfg: dict[str, Any] = {"mtime": None, "cfg": {}}


def load_config() -> dict[str, Any]:
    import yaml

    try:
        m = CONFIG_PATH.stat().st_mtime
    except OSError:
        return {}
    if _cfg["mtime"] != m:
        _cfg["cfg"] = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
        _cfg["mtime"] = m
    return _cfg["cfg"]


def hold(name: str) -> bool:
    """True when advice of this kind should wait for the digest instead of paging (rollback = set false)."""
    try:
        cfg = load_config()
        return bool(cfg.get("enabled")) and bool((cfg.get("holds") or {}).get(name))
    except Exception:
        return False


def _f(v: Any) -> Optional[float]:
    try:
        return None if v is None or v == "" else float(v)
    except (TypeError, ValueError):
        return None


def _usd(v: Any) -> str:
    x = _f(v)
    if x is None:
        return "—"
    return f"${x:,.2f}" if x >= 1 else f"${x:.4f}"


def _ago(ts: Any, now: datetime) -> str:
    try:
        t = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        t = t if t.tzinfo else t.replace(tzinfo=timezone.utc)
    except ValueError:
        return ""
    h = (now - t).total_seconds() / 3600
    return f"{max(1, int(h * 60))}m ago" if h < 1 else (f"{int(h)}h ago" if h < 48 else f"{int(h / 24)}d ago")


# ── links ───────────────────────────────────────────────────────────────────


def ticker_url(sym: str) -> str:
    return f"{cc_base()}/v3/watch?tab=opportunities&opp={sym}"


def comms_url(event_id: Optional[str] = None, symbol: Optional[str] = None) -> str:
    if event_id:
        return f"{cc_base()}/v3/communications?event={event_id}"
    return f"{cc_base()}/v3/communications?q={symbol or ''}"


# ── collection ──────────────────────────────────────────────────────────────


def collect_comms(db: Callable, since: datetime, until: datetime) -> dict[str, list[dict[str, Any]]]:
    """{section_id: [item]} — the newest event per (section, symbol) in the window."""
    from scripts.lib.comms.classify import headline, symbols_in

    cfg = load_config()
    out: dict[str, list[dict[str, Any]]] = {}
    for sec in cfg.get("sections") or []:
        rows = db("""SELECT event_id, created_at, category, classified_by, symbols, sanitized_body, producer
                       FROM communication_events
                      WHERE direction = 'OUTBOUND' AND created_at > %s AND created_at <= %s AND category = ANY(%s)
                      ORDER BY created_at DESC LIMIT 400""", (since, until, list(sec.get("categories") or []))) or []
        excl = set(sec.get("exclude_rules") or [])
        incl = set(sec.get("include_rules") or [])
        seen: dict[str, dict[str, Any]] = {}
        for r in rows:
            rule = r.get("classified_by") or ""
            if rule in excl or (incl and rule not in incl):
                continue
            syms = list(r.get("symbols") or []) or symbols_in(r.get("sanitized_body") or "")
            if not syms or syms[0] in seen:
                continue
            seen[syms[0]] = {"symbol": syms[0], "event_id": str(r["event_id"]), "at": r.get("created_at"),
                             "headline": headline(r.get("sanitized_body") or ""), "source": "communications"}
        out[sec["id"]] = list(seen.values())[: int(cfg.get("max_items_per_section") or 12)]
    return out


_NOTE_SYM = __import__("re").compile(r"^[•\-\s]*[A-Z][A-Z_]+\s+([A-Z][A-Z0-9]{0,4}(?:\.[A-Z])?)\b")


def collect_held_cio(outbox, since: datetime) -> list[dict[str, Any]]:
    """CIO-bot advisory notes held PENDING for the digest (cio_notification_delivery honours the hold)."""
    from scripts.lib.comms.classify import headline, symbols_in

    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    # One pass over the append-only log for advisory notes enqueued inside the window, then the outbox's own
    # projection (get_notification) for just those few — list_notifications replays the log once per stream.
    cands: dict[str, dict[str, Any]] = {}
    try:
        with open(outbox.event_store_path, encoding="utf-8") as fh:
            for line in fh:
                if '"NOTIFICATION_ENQUEUED"' not in line or '"advisory"' not in line:
                    continue
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                pl = ev.get("payload") or {}
                if pl.get("message_class") != "advisory":
                    continue
                try:
                    at = datetime.fromisoformat(str(pl.get("created_at")).replace("Z", "+00:00"))
                    at = at if at.tzinfo else at.replace(tzinfo=timezone.utc)
                except ValueError:
                    continue
                if at > since:
                    cands[str(pl.get("notification_id"))] = pl
    except OSError:
        return []
    rows = []
    for nid, pl in cands.items():
        cur = outbox.get_notification(nid) or {}
        if cur.get("current_status", "PENDING") == "PENDING":
            rows.append({**pl, **{k: v for k, v in cur.items() if v is not None}})
    for n in sorted(rows, key=lambda r: str(r.get("created_at") or ""), reverse=True):
        try:
            at = datetime.fromisoformat(str(n.get("created_at")).replace("Z", "+00:00"))
            at = at if at.tzinfo else at.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if at <= since:                          # only notes held since the previous digest
            continue
        body = str(n.get("body") or "")
        syms = symbols_in(body)
        if not syms:
            # CIO advisory note shape: "• RE_ENTER_IF AXTI — RE_ENTER_IF" (action token, then the ticker)
            m = _NOTE_SYM.search(body.split("\n", 1)[0])
            syms = [m.group(1)] if m else []
        sym = syms[0] if syms else None
        item = {"notification_id": n.get("notification_id"), "symbol": sym,
                "headline": headline(body) or n.get("subject"), "at": n.get("created_at"), "source": "cio_outbox"}
        if sym and sym in seen:                  # one block per ticker; every note is still marked delivered
            item["duplicate"] = True
        seen.add(sym or "")
        out.append(item)
    return out


def enrich(db: Callable, symbols: list[str]) -> dict[str, dict[str, Any]]:
    """Per-ticker facts for the digest blocks (one batched read per source)."""
    from lib.data_broker.analyst_detail import get_analyst_targets
    from lib.data_broker.catalyst_record import get_catalyst_record, get_latest_news
    from lib.data_broker.market_quote import get_price_batch
    from lib.data_broker.symbol_profile import get_symbol_profiles

    cfg = load_config()
    syms = sorted({s for s in symbols if s})
    out: dict[str, dict[str, Any]] = {s: {} for s in syms}
    if not syms:
        return out
    q = lambda sql, params=None, fetch="all": db(sql, params, fetch=fetch)  # noqa: E731
    for s, v in (get_price_batch(q, syms, skip_live=True) or {}).items():
        out.setdefault(s, {})["quote"] = v
    for s, v in (get_analyst_targets(q, syms) or {}).items():
        out.setdefault(s, {})["analyst"] = v
    for s, v in (get_latest_news(q, syms, hours=int(cfg.get("news_hours") or 72)) or {}).items():
        out.setdefault(s, {})["news"] = v
    for s, v in (get_symbol_profiles(q, syms) or {}).items():
        out.setdefault(s, {})["profile"] = v
    for s in syms:
        try:
            out[s]["catalyst"] = get_catalyst_record(q, s, days=int(cfg.get("catalyst_days") or 14))
        except Exception:
            pass
    try:
        from scripts.lib.cio_opportunity_store import CIOOpportunityStore

        items = CIOOpportunityStore().read_projection().get("items") or {}
        for s in syms:
            if s in items:
                out[s]["cio"] = items[s]
    except Exception:
        pass
    return out


def collect_movers(db: Callable, today: date, universe: list[str], facts_for: Callable) -> dict[str, list[dict]]:
    """17:00 — what moved up or down today: price, ratings, conviction rank, new catalysts."""
    cfg = load_config().get("movers") or {}
    n = int(cfg.get("max_each") or 8)
    out: dict[str, list[dict]] = {"price": [], "ratings": [], "conviction": [], "catalysts": []}
    q = lambda sql, params=None, fetch="all": db(sql, params, fetch=fetch)  # noqa: E731
    # price — today's change on held + watchlist + top-ranked names
    try:
        from lib.data_broker.market_quote import get_price_batch

        quotes = get_price_batch(q, universe, skip_live=True) or {}
        th = float(cfg.get("price_move_pct") or 4.0)
        moves = [(s, v) for s, v in quotes.items() if v.get("chg_pct") is not None and abs(v["chg_pct"]) >= th]
        moves.sort(key=lambda kv: -abs(kv[1]["chg_pct"]))
        out["price"] = [{"symbol": s, "chg_pct": v["chg_pct"], "price": v["price"]}
                        for s, v in moves[: int(cfg.get("max_price_movers") or n)]]
    except Exception:
        pass
    # material changes today (folded from the 16:15 material-change digest): "N× its normal daily move"
    try:
        rows = db("""SELECT DISTINCT ON (upper(symbol)) upper(symbol) AS s, kind, magnitude
                       FROM material_changes WHERE created_at::date = %s AND symbol IS NOT NULL
                      ORDER BY upper(symbol), magnitude DESC NULLS LAST""", (today,)) or []
        mags = {r["s"]: _f(r.get("magnitude")) for r in rows if r.get("kind") == "price_excursion"}
        have = {m["symbol"] for m in out["price"]}
        for m in out["price"]:
            if mags.get(m["symbol"]):
                m["x_normal"] = mags[m["symbol"]]
        extra = sorted([(s, x) for s, x in mags.items() if x and s not in have], key=lambda kv: -kv[1])
        if extra:
            from lib.data_broker.market_quote import get_price_batch

            qx = get_price_batch(q, [s for s, _ in extra[:n]], skip_live=True) or {}
            for s, x in extra[:n]:
                v = qx.get(s) or {}
                if v.get("chg_pct") is not None:
                    out["price"].append({"symbol": s, "chg_pct": v["chg_pct"], "price": v.get("price"), "x_normal": x})
    except Exception:
        pass
    # ratings — today's snapshot vs the previous one (key change or target move)
    try:
        rows = db("""SELECT upper(symbol) AS s, snapshot_date, recommendation_key, target_mean_price,
                            number_of_analyst_opinions
                       FROM yahoo_analyst_targets_history
                      WHERE upper(symbol) = ANY(%s) AND snapshot_date >= %s - 10
                      ORDER BY upper(symbol), snapshot_date DESC""", (universe, today)) or []
        by: dict[str, list[dict]] = {}
        for r in rows:
            by.setdefault(r["s"], []).append(r)
        tpct = float(cfg.get("rating_target_change_pct") or 5.0)
        for s, rs in by.items():
            if len(rs) < 2 or str(rs[0]["snapshot_date"]) != str(today):
                continue
            cur, prev = rs[0], next((x for x in rs[1:] if str(x["snapshot_date"]) != str(today)), None)
            if not prev:
                continue
            ct, pt = _f(cur.get("target_mean_price")), _f(prev.get("target_mean_price"))
            key_change = (cur.get("recommendation_key") or "") != (prev.get("recommendation_key") or "")
            tgt_change = ct and pt and abs(ct - pt) / pt * 100 >= tpct
            if key_change or tgt_change:
                up = (ct or 0) > (pt or 0) if not key_change else _rank(cur.get("recommendation_key")) < _rank(prev.get("recommendation_key"))
                out["ratings"].append({"symbol": s, "up": up, "from_key": prev.get("recommendation_key"),
                                       "to_key": cur.get("recommendation_key"), "from_target": pt, "to_target": ct})
        out["ratings"] = out["ratings"][:n]
    except Exception:
        pass
    # conviction — CIO opportunity versions written today with a conviction move
    try:
        from scripts.lib.cio_opportunity_store import EVENT_PATH

        delta = float(cfg.get("conviction_delta") or 5)
        last: dict[str, dict] = {}
        moved: dict[str, dict] = {}
        with open(EVENT_PATH, encoding="utf-8") as fh:
            for line in fh:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                s, a = row.get("symbol"), row.get("assessment") or {}
                prev = last.get(s)
                if str(row.get("written_at") or "")[:10] == str(today) and prev and \
                        prev.get("conviction") is not None and a.get("conviction") is not None and \
                        abs(a["conviction"] - prev["conviction"]) >= delta:
                    moved[s] = {"symbol": s, "from": prev["conviction"], "to": a["conviction"],
                                "rank_from": prev.get("rank"), "rank_to": a.get("rank")}
                last[s] = a
        out["conviction"] = sorted(moved.values(), key=lambda m: -abs(m["to"] - m["from"]))[:n]
    except Exception:
        pass
    # new catalysts — created today on the universe
    try:
        rows = db("""SELECT DISTINCT ON (upper(symbol)) upper(symbol) AS s, headline, catalyst_type, severity
                       FROM catalyst_events
                      WHERE upper(symbol) = ANY(%s) AND created_at::date = %s AND catalyst_type <> 'other'
                      ORDER BY upper(symbol), created_at DESC""", (universe, today)) or []
        out["catalysts"] = [{"symbol": r["s"], "headline": r.get("headline"), "type": r.get("catalyst_type")}
                            for r in rows][:n]
    except Exception:
        pass
    return out


_KEYS = ["strong_buy", "buy", "hold", "underperform", "sell"]


def _rank(k: Any) -> int:
    k = str(k or "").lower().replace(" ", "_")
    return _KEYS.index(k) if k in _KEYS else 9


def collect_other(since_hours: int = 6) -> dict[str, Any]:
    """The P1 archive (folded from p1_digest_sender): stop warnings, system health, … grouped by kind."""
    try:
        import p1_digest_sender as p1
    except ImportError:  # pragma: no cover
        from scripts import p1_digest_sender as p1  # type: ignore
    try:
        return p1.collect(since_hours)
    except Exception:
        return {"rows": [], "watermark": None}


# ── rendering ───────────────────────────────────────────────────────────────

SECTION_KIND = {"entries": "Entry setup", "reentry": "Re-entry", "cio": "CIO decision / research"}


def item_block(it: dict[str, Any], facts: dict[str, Any], now: datetime) -> str:
    sym = it.get("symbol") or "—"
    f = facts.get(sym) or {}
    q, an, cio, news, cat = f.get("quote") or {}, f.get("analyst") or {}, f.get("cio") or {}, f.get("news"), f.get("catalyst")
    company = (f.get("profile") or {}).get("company") or (f.get("profile") or {}).get("name") or cio.get("company") or ""
    rr = cio.get("risk_reward") or {}
    lines = [f"<b>{link('$' + sym, ticker_url(sym))}</b>" + (f" · {esc(company)}" if company else "")
             + (f" — <i>{esc(it.get('kind') or '')}</i>" if it.get("kind") else "")]
    if it.get("headline"):
        lines.append(esc(str(it["headline"])[:140]))
    price = []
    if q.get("price") is not None:
        ch = q.get("chg_pct")
        price.append(f"💲 <b>{_usd(q['price'])}</b>" + (f" {'▲' if ch >= 0 else '▼'}{abs(ch):.1f}%" if ch is not None else ""))
    if an.get("recommendation_key") and str(an["recommendation_key"]).lower() not in ("none", "null", ""):
        price.append(f"Rating <b>{esc(str(an['recommendation_key']).replace('_', ' ').upper())}</b>"
                     + (f" ({an['analyst_count']})" if an.get("analyst_count") else ""))
    if an.get("target_mean") is not None:
        tm = _f(an["target_mean"])
        up = (tm - q["price"]) / q["price"] * 100 if tm and q.get("price") else None
        flag = up is not None and up > 150            # stale or penny-stock target (same rule as the CIO engine)
        price.append(f"Street target {_usd(tm)}" + (f" ({up:+.0f}%{' ⚠ check' if flag else ''})" if up is not None else ""))
    if price:
        lines.append(" · ".join(price))
    lv = []
    zone = rr.get("entry_zone")
    if zone and zone[0] is not None:
        lv.append(f"🎯 Entry {_usd(zone[0])}–{_usd(zone[1])}")
    elif rr.get("entry_ref") is not None:
        lv.append(f"🎯 Entry {_usd(rr['entry_ref'])}")
    if rr.get("invalidation_level") is not None:
        lv.append(f"Stop {_usd(rr['invalidation_level'])}")
    tgt = rr.get("primary_target") or ((rr.get("targets") or [{}])[0]).get("px")
    if tgt is not None:
        lv.append(f"Target {_usd(tgt)}")
    if rr.get("rr") is not None:
        lv.append(f"R:R {rr['rr']:.1f}")
    if cio.get("conviction") is not None:
        lv.append(f"Conviction {cio['conviction']:.0f}" + (f" (#{cio['rank']})" if cio.get("rank") else ""))
    if lv:
        lines.append(" · ".join(lv))
    if cat and cat.get("headline"):
        lines.append(f"⚡ {esc(str(cat['headline'])[:150])}")
    if news and news.get("title"):
        t = esc(str(news["title"])[:130])
        lines.append("📰 " + (link(str(news["title"])[:130], news["url"]) if news.get("url") else t)
                     + f" <i>{esc(news.get('source') or '')} {_ago(news.get('published_at'), now)}</i>")
    links = (f"{link('Ticker in Command Center', ticker_url(sym))} · "
             f"{link('Communication Center', comms_url(it.get('event_id'), sym))}")
    if not lv and not (cat and cat.get("headline")) and not (news and news.get("title")):
        # Nothing beyond a price: one line, so thin items never crowd out the substantive ones.
        return (f"• <b>{link('$' + sym, ticker_url(sym))}</b> " + (" · ".join(price) if price else "")
                + (f" — {esc(str(it.get('headline') or '')[:70])}" if it.get("headline") else "")
                + f" · {link('Comms', comms_url(it.get('event_id'), sym))}")
    lines.append(f"🔗 {links}")
    return "\n".join(lines)


def render(slot: str, sections: dict[str, list[dict]], held: list[dict], facts: dict[str, Any],
           movers: Optional[dict[str, list[dict]]], other: dict[str, Any], now: datetime) -> list[str]:
    """HTML messages (split at block boundaries, never mid-tag)."""
    cfg = load_config()
    label = ((cfg.get("slots") or {}).get(str(slot)) or {}).get("label") or f"{slot}:00 digest"
    blocks: list[str] = []
    n_items = sum(len(v) for v in sections.values()) + sum(1 for h in held if h.get("symbol") and not h.get("duplicate"))
    head = (f"📋 <b>{esc(label.upper())}</b> · {now.astimezone(_et()).strftime('%a %b %d · %H:%M ET')}\n"
            f"{n_items} advice item{'s' if n_items != 1 else ''}"
            + (" · movers today" if movers else "")
            + f" · {link('Open Communication Center', comms_url())}")
    blocks.append(head)
    for sec in cfg.get("sections") or []:
        items = sections.get(sec["id"]) or []
        if sec["id"] == "cio":
            have = {i.get("symbol") for i in items}
            items = items + [h for h in held if h.get("symbol") and not h.get("duplicate") and h["symbol"] not in have]
        if not items:
            continue
        blocks.append(f"━━━━━━━━━━━━━━━━━━\n{sec.get('icon', '')} <b>{esc(sec['title'].upper())}</b> · {len(items)}")
        for it in items:
            blocks.append(item_block({**it, "kind": it.get("kind") or SECTION_KIND.get(sec["id"])}, facts, now))
    if movers:
        mv = []
        if movers.get("price"):
            mv.append("<b>Price</b>\n" + "\n".join(
                f"{'📈' if m['chg_pct'] >= 0 else '📉'} {link('$' + m['symbol'], ticker_url(m['symbol']))} "
                f"{_usd(m['price'])} {'▲' if m['chg_pct'] >= 0 else '▼'}{abs(m['chg_pct']):.1f}%"
                + (f" · {m['x_normal']:.1f}× its normal daily move" if m.get('x_normal') else "") for m in movers["price"]))
        if movers.get("ratings"):
            mv.append("<b>Ratings</b>\n" + "\n".join(
                f"{'⬆️' if r['up'] else '⬇️'} {link('$' + r['symbol'], ticker_url(r['symbol']))} "
                + (f"{esc(str(r['from_key']).upper())} → {esc(str(r['to_key']).upper())}" if r['from_key'] != r['to_key'] else "")
                + (f" · target {_usd(r['from_target'])} → {_usd(r['to_target'])}" if r.get('to_target') else "")
                for r in movers["ratings"]))
        if movers.get("conviction"):
            mv.append("<b>CIO conviction</b>\n" + "\n".join(
                f"{'⬆️' if c['to'] > c['from'] else '⬇️'} {link('$' + c['symbol'], ticker_url(c['symbol']))} "
                f"{c['from']:.0f} → <b>{c['to']:.0f}</b>" + (f" · rank #{c['rank_from']} → #{c['rank_to']}" if c.get('rank_to') else "")
                for c in movers["conviction"]))
        if movers.get("catalysts"):
            mv.append("<b>New catalysts</b>\n" + "\n".join(
                f"⚡ {link('$' + c['symbol'], ticker_url(c['symbol']))} {esc(str(c.get('headline') or '')[:120])}"
                for c in movers["catalysts"]))
        if mv:
            blocks.append("━━━━━━━━━━━━━━━━━━\n📊 <b>MOVED TODAY</b>")
            blocks.extend(mv)
    rows = other.get("rows") or []
    if rows:
        kinds = Counter((r[2] or "other") for r in rows)
        blocks.append("━━━━━━━━━━━━━━━━━━\n🗂 <b>OTHER UPDATES</b> · " + str(len(rows)) + "\n" + "\n".join(
            f"• {esc(k)} ×{n}" for k, n in kinds.most_common(8)))
    blocks.append("<i>Advisory only — nothing is ordered. Scalp alerts, approvals and stop/protection alerts still "
                  "arrive immediately.</i>")
    limit = int(cfg.get("max_message_chars") or 3800)
    msgs, cur = [], ""
    for b in blocks:
        if cur and len(cur) + len(b) + 2 > limit:
            msgs.append(cur)
            cur = ""
        cur = (cur + "\n\n" + b) if cur else b
    if cur:
        msgs.append(cur)
    if len(msgs) > 1:
        msgs = [m + f"\n<i>({i + 1}/{len(msgs)})</i>" for i, m in enumerate(msgs)]
    return msgs


def _et():
    from zoneinfo import ZoneInfo

    return ZoneInfo("America/New_York")
