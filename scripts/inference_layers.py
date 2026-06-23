#!/usr/bin/env python3
"""Inference Layers — the four reusable reasoning layers.

Each layer is an independently importable, reusable class with a single contract:
    run(ctx: InferenceContext) -> LayerResult

Layers read every prior layer's structured output from `ctx.store[...].data`, so
they compose into a pipeline driven by inference_layer_engine.InferenceEngine.

    IngestionLayer    (L1)  ingest + structure all sources, region-tag news
    FeatureLayer      (L2)  regime / sentiment / concentration / momentum signals
    RegionalLayer     (L3)  cross-regional synthesis (Asia -> US ETF/CEF impact)
    HigherOrderLayer  (L4)  journal patterns, NAV signals, opportunity/risk,
                            risk-appropriate proposal sizing, proactive gap queries
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
import sys
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from inference_layer_engine import Inference, LayerResult, InferenceContext, remember
import inference_hermes_query as hq

log = logging.getLogger("inference_layers")
STATE_DIR = PROJECT_ROOT / "data" / "portfolios" / "state"


def _db_all(sql, params=None):
    try:
        from db_adapter import _execute, USE_DB
        if not USE_DB:
            return []
        return _execute(sql, params, fetch="all") or []
    except Exception as e:
        log.warning("db query failed: %s", e)
        return []


def _db_exec(sql, params=None):
    try:
        from db_adapter import _execute, USE_DB
        if not USE_DB:
            return False
        return bool(_execute(sql, params, fetch=None))
    except Exception:
        return False


def _holdings() -> list:
    try:
        h = json.loads((STATE_DIR / "holdings.json").read_text())
        return [r for r in h.get("holdings", []) or [] if not r.get("is_cash")]
    except Exception:
        return []


# ══════════════════════════════════════════════════════════════════════════════
# LAYER 1 — Ingestion & Structuring
# ══════════════════════════════════════════════════════════════════════════════
class IngestionLayer:
    name = "ingestion"

    def run(self, ctx: InferenceContext) -> LayerResult:
        cfg = ctx.layer_cfg("ingestion")
        hours = int(cfg.get("news_lookback_hours", 72))
        max_news = int(cfg.get("max_news", 160))
        max_topics = int(cfg.get("max_topics", 60))
        max_closed = int(cfg.get("max_closed_trades", 40))
        res = LayerResult(layer=self.name)

        news = _db_all(
            """SELECT id, symbol, title, summary, source, published_at, created_at, region
               FROM news_articles
               WHERE created_at > now() - (%s || ' hours')::interval
               ORDER BY created_at DESC LIMIT %s""",
            (str(hours), max_news))
        # region-tag any untagged items (Layer 3 capture happens here, cheaply)
        tagged = 0
        for n in news:
            if not n.get("region"):
                region, kws = hq.classify_region(n.get("title", ""), n.get("summary", ""))
                n["region"] = region
                if not ctx.dry_run:
                    if _db_exec(
                        """UPDATE news_articles SET region=%s, geo_keywords=%s,
                           region_tagged_at=now() WHERE id=%s""",
                        (region, json.dumps(kws), n["id"])):
                        tagged += 1

        topics = _db_all(
            """SELECT topic_id, display_name, priority, last_found_count, last_searched
               FROM topic_monitor WHERE enabled = true
               ORDER BY priority DESC NULLS LAST, last_searched DESC NULLS LAST LIMIT %s""",
            (max_topics,))

        proposals = _db_all(
            """SELECT id, symbol, strategy_id, primary_strategy_id, proposed_entry,
                      proposed_stop, proposed_target1, proposed_shares, signal_score,
                      signal_grade, sector, catalyst, rvol, target_account
               FROM paper_trade_proposals WHERE status='PENDING'
               ORDER BY created_at DESC LIMIT 60""")

        closed = _db_all(
            """SELECT symbol, strategy_id, pnl, pnl_pct, r_multiple, exit_reason, exit_time
               FROM paper_trades WHERE status IN ('closed','sold')
               ORDER BY exit_time DESC NULLS LAST LIMIT %s""", (max_closed,))

        positions = _holdings()

        # Aegis safety outputs as a FIRST-CLASS signal: weakening/broken theses + surveillance
        # observations from the production Aegis synthesis/surveillance tiers feed the cycle directly.
        aegis_briefs = _db_all(
            """SELECT symbol, brief_type, thesis_status, what_changed, why_it_matters, confidence, observed_at
               FROM aegis_portfolio_briefs
               WHERE observed_at > now() - interval '4 days'
                 AND thesis_status IN ('weakening','warning','broken','danger','triggered')
               ORDER BY (thesis_status IN ('broken','danger','triggered')) DESC, observed_at DESC LIMIT 20""")
        aegis_obs = _db_all(
            """SELECT symbol, category, observation, confidence, observed_at
               FROM advisor_observations
               WHERE observed_at > now() - interval '4 days'
               ORDER BY observed_at DESC LIMIT 20""")
        aegis = {"briefs": aegis_briefs, "observations": aegis_obs}

        res.data = {"news": news, "topics": topics, "proposals": proposals,
                    "closed_trades": closed, "positions": positions,
                    "news_tagged": tagged, "aegis": aegis}
        res.metrics = {"news": len(news), "topics": len(topics), "proposals": len(proposals),
                       "closed": len(closed), "positions": len(positions), "tagged": tagged,
                       "aegis_briefs": len(aegis_briefs), "aegis_obs": len(aegis_obs)}

        # Surface the highest-priority Aegis safety signals as first-class inferences.
        for b in aegis_briefs[:8]:
            crit = b.get("thesis_status") in ("broken", "danger", "triggered")
            res.inferences.append(Inference(
                inference_type="aegis_thesis", subject=(b.get("symbol") or "portfolio")[:60],
                title=f"Aegis: {b.get('symbol')} thesis {b.get('thesis_status')}",
                body=f"{b.get('what_changed') or ''} {b.get('why_it_matters') or ''}".strip()[:600],
                confidence=float(b.get("confidence") or 0.6),
                severity="critical" if crit else "high", source_lane="aegis",
                evidence=[b.get("brief_type") or "aegis_brief"]))
        res.summary = (f"ingested {len(news)} news ({tagged} region-tagged), {len(topics)} topics, "
                       f"{len(proposals)} pending proposals, {len(positions)} positions, "
                       f"{len(closed)} closed trades, {len(aegis_briefs)} Aegis thesis-flags, "
                       f"{len(aegis_obs)} Aegis observations")

        if len(news) < 5:
            res.inferences.append(Inference(
                inference_type="data_gap", subject="ingestion",
                title="Thin recent news flow",
                body=f"Only {len(news)} news items in the last {hours}h — regional synthesis "
                     "confidence reduced; proactive queries may be triggered.",
                confidence=0.7, severity="medium", source_lane="heuristic"))
        return res


# ══════════════════════════════════════════════════════════════════════════════
# LAYER 2 — Feature Extraction & Indicators
# ══════════════════════════════════════════════════════════════════════════════
_RISK_OFF = ["selloff", "sell-off", "plunge", "crash", "tumble", "war", "invasion",
             "rate hike", "hike", "inflation", "recession", "tariff", "default",
             "downgrade", "sanction", "slump", "panic", "contagion"]
_RISK_ON = ["rally", "record high", "soft landing", "rate cut", "cuts rates", "beat",
            "surge", "rebound", "optimism", "all-time high", "stimulus", "goldilocks"]


class FeatureLayer:
    name = "features"

    def _vix(self) -> Optional[float]:
        for sym in ("^VIX", "VIX", "VIXY"):
            rows = _db_all(
                "SELECT close_price FROM price_cache WHERE symbol=%s ORDER BY price_date DESC LIMIT 1",
                (sym,))
            if rows:
                try:
                    return float(rows[0]["close_price"])
                except Exception:
                    pass
        return None

    def run(self, ctx: InferenceContext) -> LayerResult:
        res = LayerResult(layer=self.name)
        ing = ctx.get("ingestion")
        news = ing.get("news", [])
        positions = ing.get("positions", [])
        closed = ing.get("closed_trades", [])

        # sentiment tally from news text
        ro = rn = 0
        for n in news:
            t = f"{n.get('title','')} {n.get('summary','')}".lower()
            if any(k in t for k in _RISK_OFF):
                rn += 1
            if any(k in t for k in _RISK_ON):
                ro += 1
        total = max(1, ro + rn)
        sentiment = (ro - rn) / total  # -1..1

        vix = self._vix()
        # sector / single-name concentration from holdings
        by_bucket: dict = {}
        port_total = 0.0
        for p in positions:
            mv = float(p.get("market_value") or 0)
            port_total += mv
            by_bucket[p.get("bucket") or "other"] = by_bucket.get(p.get("bucket") or "other", 0) + mv
        top_bucket, top_bucket_pct = "n/a", 0.0
        if port_total > 0 and by_bucket:
            top_bucket = max(by_bucket, key=by_bucket.get)
            top_bucket_pct = round(by_bucket[top_bucket] / port_total * 100, 1)

        # momentum proxy: recent realized win rate
        wins = sum(1 for c in closed if (c.get("pnl") or 0) > 0)
        win_rate = round(wins / len(closed) * 100, 1) if closed else None

        # regime classification (transparent, rule-based; VIX overrides when present)
        regime, conf, why = self._classify(sentiment, vix, win_rate)
        ctx.scratch["regime"] = regime
        ctx.scratch["regime_confidence"] = conf
        ctx.scratch["sentiment"] = round(sentiment, 3)

        # Small-cap / Russell 2000 relative strength (IWM vs SPY) — rotation into small caps
        rot = {}
        try:
            import market_rotation_signals as mrs
            rot = mrs.detect_small_cap_rotation(news=news)
        except Exception as e:
            log.debug("small-cap rotation detect skipped: %s", e)

        res.data = {"regime": regime, "regime_confidence": conf, "sentiment": round(sentiment, 3),
                    "risk_on_hits": ro, "risk_off_hits": rn, "vix": vix,
                    "top_bucket": top_bucket, "top_bucket_pct": top_bucket_pct,
                    "recent_win_rate": win_rate, "small_cap_rotation": rot}
        res.summary = (f"regime={regime} (conf {conf:.0%}) sentiment={sentiment:+.2f} "
                       f"vix={vix} top_bucket={top_bucket} {top_bucket_pct}%")
        remember(f"regime:{ctx.account}", "regime",
                 {"regime": regime, "confidence": conf, "why": why}, salience=0.6)

        sev = "high" if regime in ("risk_off", "high_vol") else "low"
        res.inferences.append(Inference(
            inference_type="market_regime", subject="portfolio",
            title=f"Market regime: {regime.replace('_',' ')}",
            body=why, confidence=conf, severity=sev, source_lane="heuristic",
            reasoning_trace=[f"news sentiment {sentiment:+.2f} ({ro} on / {rn} off)",
                             f"vix={vix}", f"recent win-rate={win_rate}"],
            payload=res.data))

        if top_bucket_pct >= 40:
            res.inferences.append(Inference(
                inference_type="risk", subject=top_bucket,
                title=f"Concentration: {top_bucket_pct}% in {top_bucket}",
                body=f"Portfolio is {top_bucket_pct}% concentrated in the {top_bucket} bucket — "
                     "size new correlated adds conservatively.",
                confidence=0.8, severity="medium", source_lane="heuristic",
                payload={"bucket": top_bucket, "pct": top_bucket_pct}))

        if rot.get("signal") == "small_cap_outperform":
            rs = rot.get("rs_20d") or rot.get("rs_5d") or rot.get("rs_1d")
            conf_rot = min(0.9, 0.55 + float(rot.get("strength") or 0) * 0.35)
            body = (
                f"Russell 2000 / IWM is outperforming large caps (SPY). {rot.get('explain', '')} "
                "Review small-cap swing setups, sector rotation, and watchlist adds — "
                "only trade names with catalyst + edge."
            )
            res.inferences.append(Inference(
                inference_type="sector_rotation", subject="IWM",
                title=f"Small-cap rotation: IWM leading SPY ({rs:+.2f}% RS)" if rs is not None
                      else "Small-cap rotation: IWM leading SPY",
                body=body, confidence=conf_rot, severity="medium", source_lane="heuristic",
                reasoning_trace=[rot.get("explain", "")],
                payload=rot))
            remember("rotation:small_cap", "sector_rotation", rot, salience=0.72)
        return res

    @staticmethod
    def _classify(sentiment: float, vix: Optional[float], win_rate):
        why = []
        if vix is not None:
            why.append(f"VIX={vix}")
            if vix >= 28:
                return "high_vol", 0.8, "; ".join(why + ["VIX>=28 → elevated volatility regime"])
            if vix >= 20:
                base = "risk_off" if sentiment < 0 else "neutral"
                return base, 0.65, "; ".join(why + [f"VIX 20-28 + sentiment {sentiment:+.2f}"])
        # sentiment-driven fallback
        if sentiment <= -0.35:
            return "risk_off", 0.6, "; ".join(why + [f"news sentiment {sentiment:+.2f} (risk-off skew)"])
        if sentiment >= 0.35:
            return "risk_on", 0.6, "; ".join(why + [f"news sentiment {sentiment:+.2f} (risk-on skew)"])
        return "neutral", 0.55, "; ".join(why + [f"balanced news sentiment {sentiment:+.2f}"])


# ══════════════════════════════════════════════════════════════════════════════
# LAYER 3 — Cross-Regional Synthesis
# ══════════════════════════════════════════════════════════════════════════════
class RegionalLayer:
    name = "regional"

    def run(self, ctx: InferenceContext) -> LayerResult:
        res = LayerResult(layer=self.name)
        cfg = ctx.cfg
        reg_cfg = cfg.get("regional", {}) or {}
        regions = ctx.layer_cfg("regional").get("regions", ["US", "Asia", "Europe", "EmergingMarkets"])
        ing = ctx.get("ingestion")
        news = ing.get("news", [])
        positions = ing.get("positions", [])
        held_syms = [p.get("symbol") for p in positions if p.get("symbol")]
        income_funds = reg_cfg.get("income_funds", [])

        # bucket news by region
        by_region: dict = {}
        for n in news:
            r = n.get("region") or "US"
            by_region.setdefault(r, []).append(n)

        signals = 0
        proactive_budget = int((cfg.get("proactive", {}) or {}).get("max_queries_per_run", 3))

        for region in regions:
            if region == "US":
                continue
            items = by_region.get(region, [])
            themes = (reg_cfg.get("asia_themes") if region == "Asia"
                      else reg_cfg.get("europe_themes") if region == "Europe"
                      else reg_cfg.get("em_themes")) or []

            # Asia is the priority mandate: synthesize even when news is thin by
            # firing a proactive query (the "mind of its own" behavior).
            headlines = [i.get("title", "") for i in items[:12]]
            salience = min(1.0, 0.4 + 0.05 * len(items) + (0.25 if region == "Asia" else 0))

            if region == "Asia" and len(items) < 3 \
                    and ctx.scratch.get("proactive_used", 0) < proactive_budget \
                    and (cfg.get("proactive", {}) or {}).get("gap_query_enabled", True):
                q = ("What are the most market-moving developments in Asia right now "
                     "(BOJ/yen, China stimulus/PBOC, semiconductors/TSMC, export controls), "
                     "and how could they transmit to US equities, semiconductor ETFs, and "
                     "income CEFs like PTY over the next 1-2 weeks?")
                pa = hq.proactive_query(ctx, "Asia", q, trigger="regional_gap", salience=0.7,
                                        want_keys=["headline", "us_impact", "direction",
                                                   "affected_symbols", "confidence", "reasoning"])
                headlines = headlines or [pa.get("headline", "Asia macro scan")]

            if not items and region != "Asia":
                continue

            synth = self._synthesize(ctx, region, themes, headlines, held_syms, income_funds)
            if not synth:
                continue

            affected = self._resolve_affected(synth.get("affected_symbols", []),
                                              held_syms, income_funds)
            urls = [{"title": i.get("title"), "url": i.get("source"), "kind": "news"}
                    for i in items[:5]]
            direction = (synth.get("direction") or "mixed").lower()
            conf = float(synth.get("confidence", 0.5) or 0.5)
            theme = synth.get("theme") or (themes[0] if themes else region)
            us_impact = synth.get("us_impact") or synth.get("note") or ""

            if not ctx.dry_run and ctx.run_id is not None:
                _db_exec(
                    """INSERT INTO inference_regional_signals
                       (run_id, region, theme, headline, us_impact, direction,
                        affected_symbols, confidence, source_lane, source_urls)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (ctx.run_id, region, theme[:200], (synth.get("headline") or "")[:500],
                     us_impact[:4000], direction, json.dumps(affected), conf,
                     synth.get("_lane", "local"), json.dumps(urls)))
            signals += 1

            sev = "high" if (conf >= 0.6 and any(a.get("held") for a in affected)
                             and direction in ("bearish", "mixed")) else \
                  ("medium" if conf >= 0.55 else "low")
            res.inferences.append(Inference(
                inference_type="regional_impact", subject=f"{region}/{theme}",
                title=f"{region}: {synth.get('headline','') or theme}"[:200],
                body=us_impact, confidence=conf, severity=sev,
                source_lane=synth.get("_lane", "local"),
                reasoning_trace=synth.get("reasoning", []) if isinstance(synth.get("reasoning"), list) else [],
                evidence=urls,
                payload={"region": region, "theme": theme, "direction": direction,
                         "affected_symbols": affected}))
            remember(f"regional:{region}:{theme}", "regional",
                     {"direction": direction, "us_impact": us_impact[:600], "confidence": conf},
                     salience=min(1.0, conf + (0.2 if any(a.get("held") for a in affected) else 0)))

        res.metrics = {"signals": signals,
                       "proactive_used": ctx.scratch.get("proactive_used", 0)}
        res.summary = f"{signals} cross-regional signals across {len(by_region)} regions"
        return res

    def _synthesize(self, ctx, region, themes, headlines, held, income_funds) -> Optional[dict]:
        hl = "\n".join(f"- {h}" for h in headlines if h) or "(no fresh headlines — use macro knowledge)"
        prompt = (
            f"You are a cross-regional macro analyst for a US-based retirement portfolio.\n"
            f"REGION: {region}\nKEY THEMES TO WEIGH: {', '.join(themes)}\n"
            f"RECENT {region} HEADLINES:\n{hl}\n\n"
            f"Portfolio holds (sample): {', '.join(held[:25])}\n"
            f"Income funds watched: {', '.join(income_funds)}\n\n"
            f"Infer the single most important transmission channel from {region} to US markets "
            f"right now. Be concrete about which US equities, sector/semiconductor ETFs, or income "
            f"CEFs (e.g. PTY) are affected and through what channel (supply chain, rates/yen carry, "
            f"flows, USD). If uncertain, say mixed.")
        out = hq.llm_json(prompt, caller="inference_regional", salience=0.7, cfg=ctx.cfg,
                          want_keys=["headline", "theme", "us_impact", "direction",
                                     "affected_symbols", "confidence", "reasoning"])
        if not out or out.get("_raw_len", 0) == 0:
            return None
        return out

    @staticmethod
    def _resolve_affected(symbols, held, income_funds) -> list:
        held_up = {s.upper() for s in held if s}
        fund_up = {s.upper() for s in income_funds if s}
        out = []
        seen = set()
        for s in symbols or []:
            sym = (s.get("symbol") if isinstance(s, dict) else str(s)).upper().strip()
            if not sym or sym in seen or len(sym) > 6:
                continue
            seen.add(sym)
            out.append({"symbol": sym,
                        "held": sym in held_up,
                        "income_fund": sym in fund_up,
                        "channel": (s.get("channel") if isinstance(s, dict) else None)})
        return out[:12]


# ══════════════════════════════════════════════════════════════════════════════
# LAYER 4 — Higher-Order Inferences & Autonomy
# ══════════════════════════════════════════════════════════════════════════════
class HigherOrderLayer:
    name = "higher_order"

    def run(self, ctx: InferenceContext) -> LayerResult:
        res = LayerResult(layer=self.name)
        cfg = ctx.cfg
        journal_edge = {}
        try:
            journal_edge = self._journal(ctx, res)
        except Exception as e:
            log.warning("journal analysis failed: %s", e)
        try:
            self._nav_signals(ctx, res)
        except Exception as e:
            log.warning("nav signals failed: %s", e)
        try:
            self._opportunity_risk(ctx, res)
        except Exception as e:
            log.warning("opportunity/risk synthesis failed: %s", e)
        try:
            n = self._sizing(ctx, res, journal_edge)
            res.metrics["sizing_recs"] = n
        except Exception as e:
            log.warning("sizing failed: %s", e)
        try:
            import inference_autonomy as autonomy
            res.metrics["autonomy"] = autonomy.run_autonomy(ctx, res)
        except Exception as e:
            log.warning("autonomy pass failed: %s", e)
        res.summary = (f"journal_setups={len(journal_edge)} "
                       f"sizing_recs={res.metrics.get('sizing_recs',0)} "
                       f"autonomy={res.metrics.get('autonomy',{}).get('acted',0)} "
                       f"inferences={len(res.inferences)}")
        return res

    # — deep journal analysis —
    def _journal(self, ctx, res) -> dict:
        days = int(ctx.layer_cfg("higher_order").get("journal_days", 180))
        try:
            import journal_analytics_engine as jae
            data = jae.run(account=None, days=days)
        except Exception as e:
            log.warning("journal engine unavailable: %s", e)
            return {}
        if not data or not data.get("ok"):
            return {}
        sb = data.get("setup_breakdown", {})
        by_strategy = sb.get("by_strategy", [])
        by_emotion = sb.get("by_emotion", [])
        overall = data.get("overall", {})

        # journal_edge per strategy in [-1, 1] (win-rate vs 50% blended w/ pnl sign)
        edge = {}
        for row in by_strategy:
            n = row.get("trades", 0)
            if n < 2:
                continue
            wr = row.get("win_rate", 0)
            net = row.get("net_pnl", 0)
            e = max(-1.0, min(1.0, (wr - 50) / 50.0))
            if net < 0:
                e = min(e, -0.1)
            # dampen low-sample
            e *= min(1.0, n / 8.0)
            edge[(row.get("strategy") or "untagged").lower()] = round(e, 3)
        ctx.scratch["journal_edge"] = edge

        # LLM synthesis of the patterns (best/worst setup, emotion edge)
        prompt = (
            "Analyze this trade-journal summary for a swing/position retirement trader and infer "
            "the 1-3 highest-value, actionable patterns (best & worst setups, emotional edge, "
            "what to repeat / stop). Be specific and concise.\n\n"
            f"OVERALL: {json.dumps(overall, default=str)}\n"
            f"BY STRATEGY: {json.dumps(by_strategy[:8], default=str)}\n"
            f"BY EMOTION: {json.dumps(by_emotion[:6], default=str)}\n"
            f"TOP MISTAKES: {json.dumps(sb.get('top_mistakes', [])[:6], default=str)}")
        out = hq.llm_json(prompt, caller="inference_journal", salience=0.5, cfg=ctx.cfg,
                          want_keys=["patterns", "repeat", "stop", "confidence", "reasoning"])
        patterns = out.get("patterns") or []
        if isinstance(patterns, str):
            patterns = [patterns]
        conf = float(out.get("confidence", 0.5) or 0.5)
        body_lines = []
        if patterns:
            body_lines += [f"• {p}" for p in patterns[:4]]
        if out.get("repeat"):
            body_lines.append(f"Repeat: {out['repeat']}")
        if out.get("stop"):
            body_lines.append(f"Stop: {out['stop']}")
        # data-grounded fallback line
        if by_strategy:
            best = by_strategy[0]
            worst = by_strategy[-1]
            body_lines.append(
                f"Data: best strategy '{best.get('strategy')}' net ${best.get('net_pnl')} "
                f"({best.get('win_rate')}% / {best.get('trades')}t); "
                f"worst '{worst.get('strategy')}' net ${worst.get('net_pnl')}.")

        res.inferences.append(Inference(
            inference_type="journal_pattern", subject="journal",
            title="Trade journal: actionable patterns",
            body="\n".join(body_lines)[:6000], confidence=conf,
            severity="medium" if (overall.get("net_pnl", 0) or 0) < 0 else "low",
            source_lane=out.get("_lane", "local"),
            reasoning_trace=out.get("reasoning", []) if isinstance(out.get("reasoning"), list) else [],
            payload={"overall": overall, "journal_edge": edge,
                     "by_emotion": by_emotion[:6]}))
        remember("journal:patterns", "journal",
                 {"net_pnl": overall.get("net_pnl"), "edge": edge}, salience=0.55)
        return edge

    # — CEF/ETF NAV premium/discount signals —
    def _nav_signals(self, ctx, res) -> None:
        funds = (ctx.cfg.get("regional", {}) or {}).get("income_funds", [])
        if not funds:
            return
        import inference_financial_modeling as fm
        scan = fm.scan_income_funds(funds, ctx=ctx, cfg=ctx.cfg)
        for r in scan:
            if r["signal"] in ("unknown", "fair"):
                continue  # only surface actionable premium/discount reads
            sev = "high" if (r["signal"] == "rich_premium" and r.get("held")) else "medium"
            measured = "measured" if r["measured"] else "qualitative estimate"
            res.inferences.append(Inference(
                inference_type="nav_signal", subject=r["symbol"],
                title=f"{r['symbol']}: {r['signal'].replace('_',' ')} "
                      f"({r['premium_pct']:+.1f}% vs NAV)" if r["premium_pct"] is not None
                      else f"{r['symbol']}: {r['signal'].replace('_',' ')} ({measured})",
                body=r["note"], confidence=float(r["confidence"]),
                severity=sev if r.get("held") else "low",
                source_lane=r["source"] if r["measured"] else r.get("lane", "local"),
                reasoning_trace=r.get("reasoning", []),
                payload={k: r[k] for k in ("price", "nav", "premium_pct", "measured",
                                           "held", "direction", "source")}))

    # — opportunity / risk synthesis (fuse regime + regional + journal + nav) —
    def _opportunity_risk(self, ctx, res) -> None:
        feat = ctx.get("features")
        reg = ctx.store.get("regional")
        regional_infs = [i for i in (reg.inferences if reg else [])
                         if i.inference_type == "regional_impact"]
        top_regional = sorted(regional_infs, key=lambda i: -i.confidence)[:4]
        nav_infs = [i for i in res.inferences if i.inference_type == "nav_signal"]
        journal_infs = [i for i in res.inferences if i.inference_type == "journal_pattern"]

        _aeg = (ctx.get("ingestion") or {}).get("aegis") or {}
        context = {
            "regime": ctx.regime,
            "regime_detail": feat,
            "regional": [{"title": i.title, "dir": i.payload.get("direction"),
                          "conf": i.confidence} for i in top_regional],
            "nav": [{"sym": i.subject, "title": i.title} for i in nav_infs],
            "journal": [i.body[:400] for i in journal_infs],
            "aegis_safety": [{"sym": b.get("symbol"), "status": b.get("thesis_status"),
                              "why": (b.get("why_it_matters") or "")[:160]}
                             for b in (_aeg.get("briefs") or [])[:8]],
        }
        prompt = (
            "You are the chief synthesizer. Given the current regime, cross-regional signals, "
            "fund NAV reads, journal patterns, and the Aegis safety flags (weakening/broken theses) "
            "below, produce: (1) the single best OPPORTUNITY and (2) the single most important RISK for "
            "this US retirement portfolio over the next 1-2 weeks. Weight the Aegis safety flags heavily "
            "for the RISK. Be specific and tie each to the evidence.\n\n"
            f"{json.dumps(context, default=str)[:6000]}")
        out = hq.llm_json(prompt, caller="inference_synthesis", salience=0.7, cfg=ctx.cfg,
                          want_keys=["opportunity", "opportunity_confidence",
                                     "risk", "risk_confidence", "reasoning"])
        if out.get("opportunity"):
            res.inferences.append(Inference(
                inference_type="opportunity", subject="portfolio",
                title="Top opportunity (synthesized)",
                body=str(out["opportunity"])[:4000],
                confidence=float(out.get("opportunity_confidence", out.get("confidence", 0.5)) or 0.5),
                severity="medium", source_lane=out.get("_lane", "local"),
                reasoning_trace=out.get("reasoning", []) if isinstance(out.get("reasoning"), list) else []))
        if out.get("risk"):
            rc = float(out.get("risk_confidence", out.get("confidence", 0.5)) or 0.5)
            res.inferences.append(Inference(
                inference_type="risk", subject="portfolio",
                title="Top risk (synthesized)",
                body=str(out["risk"])[:4000], confidence=rc,
                severity="high" if rc >= 0.6 else "medium",
                source_lane=out.get("_lane", "local")))

    # — risk-appropriate proposal sizing —
    def _sizing(self, ctx, res, journal_edge: dict) -> int:
        ing = ctx.get("ingestion")
        proposals = ing.get("proposals", [])
        if not proposals:
            return 0
        import inference_sizing as siz
        regime = ctx.regime
        regime_conf = float(ctx.scratch.get("regime_confidence", 0.55))
        n = 0
        for p in proposals[:25]:
            strat = (p.get("strategy_id") or p.get("primary_strategy_id") or "").lower()
            jedge = float(journal_edge.get(strat, 0.0))
            # blended confidence: signal score + regime confidence
            sscore = (p.get("signal_score") or 50) / 100.0
            confidence = round(min(0.95, 0.5 * sscore + 0.5 * regime_conf), 3)
            # FOMO heuristic: high RVOL chase in a non-risk-on tape
            fomo = bool((p.get("rvol") or 0) and float(p.get("rvol")) >= 5 and regime != "risk_on")
            rec = siz.recommend(p, regime=regime, confidence=confidence, cfg=ctx.cfg,
                                account=p.get("target_account"), journal_edge=jedge, fomo=fomo)
            if not ctx.dry_run:
                siz.persist_recommendation(ctx.run_id, rec)
            n += 1
            # surface notable resizes as inferences
            base, recsh = rec.get("base_shares"), rec.get("recommended_shares")
            if base is not None and recsh is not None and base != recsh:
                pct = (recsh - base) / base * 100 if base else 0
                if abs(pct) >= 15 or recsh == 0:
                    res.inferences.append(Inference(
                        inference_type="sizing", subject=p.get("symbol"),
                        title=f"{p.get('symbol')}: size {recsh} sh "
                              f"({'BLOCKED' if recsh==0 else f'{pct:+.0f}% vs base {base}'})",
                        body=rec.get("rationale", ""), confidence=confidence,
                        severity="high" if recsh == 0 else "medium",
                        source_lane="heuristic",
                        reasoning_trace=rec.get("sizing_basis", {}).get("tilt_reasoning", []),
                        payload={"proposal_id": p.get("id"), "tilt": rec.get("tilt"),
                                 "base_shares": base, "recommended_shares": recsh,
                                 "risk_flags": rec.get("risk_flags", [])}))
        return n
