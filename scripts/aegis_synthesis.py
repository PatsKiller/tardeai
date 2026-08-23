"""
aegis_synthesis.py — Aegis Tier 1E: Local LLM synthesis + covered-call candidates + Steph escalation.

Consumes:
- aegis_symbol_snapshot_nightly (Tier 1B)
- social_sentiment_history (Tier 1C)
- transcript_intel_history (Tier 1D)
- internal portfolio/risk/recovery state

Produces:
- aegis_portfolio_briefs (per-symbol intelligence)
- aegis_covered_call_candidates (options income proposals)
- Steph escalation markers

Entry point: main()
"""
from __future__ import annotations
import json
import os
import sys
import urllib.request
from datetime import date, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = PROJECT_ROOT / "data" / "portfolios" / "state"
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

_env_path = PROJECT_ROOT / ".env"
if _env_path.exists():
    for line in _env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            k, v = k.strip(), v.strip()
            if k and v and k not in os.environ:
                os.environ[k] = v

AGENT = "aegis"
RUN_ID = f"aegis-synthesis-{datetime.now().strftime('%Y%m%d-%H%M%S')}"


def _load_json(p: Path):
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def _db_write(sql, params=None):
    try:
        from db_adapter import _get_conn
        import psycopg2.extras
        conn = _get_conn()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(sql, params)
        conn.commit()
        return True
    except Exception as e:
        print(f"  [aegis-synth] DB write error: {e}")
        try:
            from db_adapter import _get_conn as _gc
            c = _gc()
            if c:
                c.rollback()
        except Exception:
            pass
        return False


def _db_query(sql, params=None, fetch="all"):
    try:
        from db_adapter import _execute, USE_DB
        if not USE_DB:
            return None
        return _execute(sql, params, fetch=fetch)
    except Exception:
        return None


def _llm(prompt: str, max_tokens: int = 400) -> str:
    """Call governed cloud lanes for synthesis. Returns raw text."""
    try:
        from lib.governed_cloud_generation import generate_cloud
        text, _lane = generate_cloud(
            prompt, process_id="aegis_synthesis",
            task_summary="Aegis advisory synthesis", timeout=60,
            max_tokens=max_tokens,
        )
        return text
    except Exception as e:
        print(f"  [llm] Failed: {e}")
        return ""


# ── D1: Per-symbol synthesis ─────────────────────────────────────────────

def synthesize_symbol_briefs(symbols: list[str]) -> int:
    """For each symbol, gather all Aegis intel and produce a brief."""
    written = 0

    # ── ADVISORY cloud review of local-LLM theses (additive, never gates) ──
    # Gated behind CLOUD_REVIEW=1 (default OFF). Reviews only weakening/broken
    # theses, capped at first 8 per run to bound latency/cost.
    cloud_review_enabled = os.environ.get("CLOUD_REVIEW") == "1"
    cloud_reviewed = 0
    CLOUD_REVIEW_CAP = 8

    for sym in symbols:
        # Gather inputs
        snap = _db_query(
            "SELECT price, rsi, sma200_pct, beta, company, sector, change_pct, pct_from_52wk_high FROM aegis_symbol_snapshot_nightly WHERE symbol=%s ORDER BY observed_at DESC LIMIT 1",
            (sym,), fetch="one"
        ) or {}

        sentiment = _db_query(
            "SELECT mention_count, sentiment_score, unusual_spike, top_posts_summary FROM social_sentiment_history WHERE symbol=%s ORDER BY observed_at DESC LIMIT 1",
            (sym,), fetch="one"
        ) or {}

        transcripts = _db_query(
            "SELECT title, summary, stance FROM transcript_intel_history WHERE symbol=%s ORDER BY observed_at DESC LIMIT 3",
            (sym,)
        ) or []

        # Build context for LLM
        price = snap.get("price") or "?"
        rsi = snap.get("rsi") or "?"
        sma200 = snap.get("sma200_pct") or "?"
        company = snap.get("company") or sym
        sector = snap.get("sector") or "?"
        mentions = sentiment.get("mention_count", 0)
        sent_score = sentiment.get("sentiment_score", 0)
        spike = sentiment.get("unusual_spike", False)
        news_titles = "; ".join(t.get("title", "")[:50] for t in transcripts[:3])

        # Only call LLM for symbols with enough data
        has_data = snap.get("price") is not None
        if not has_data:
            continue

        # RAG pre-context for this symbol
        rag_block = ""
        try:
            sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
            from rag_retrieval import get_rag_context, format_rag_context_for_prompt
            rag_results = get_rag_context(symbol=sym, agent_name="aegis", limit=3)
            rag_block = format_rag_context_for_prompt(rag_results, symbol=sym)
        except Exception:
            pass

        # Confluence context for this symbol
        confluence_block = ""
        try:
            from agent_collab import get_confluence_context
            from db_adapter import _get_conn as _gc
            _c = _gc()
            confluence_block = get_confluence_context(sym, _c, profile='swing')
            _c.close()
        except Exception:
            pass

        prompt = f"""Analyze {sym} ({company}, {sector}) for an overnight portfolio brief.
Price: ${price}, RSI: {rsi}, SMA200: {sma200}%, Beta: {snap.get('beta','?')}, 52wk from high: {snap.get('pct_from_52wk_high','?')}%
Social: {mentions} mentions, sentiment {sent_score}, spike={spike}
Recent news: {news_titles or 'none'}
{rag_block}
{confluence_block}

Answer in 3 short lines:
1. THESIS STATUS (intact/improving/weakening/broken):
2. WHAT CHANGED:
3. WHY IT MATTERS for the portfolio:

Be concise. No disclaimers."""

        llm_output = _llm(prompt, max_tokens=200)

        # Parse LLM output
        thesis_status = "intact"
        what_changed = ""
        why_matters = ""
        if llm_output:
            lines = [l.strip() for l in llm_output.split("\n") if l.strip()]
            for l in lines:
                ll = l.lower()
                if "thesis" in ll or "status" in ll:
                    for s in ("broken", "weakening", "improving", "intact"):
                        if s in ll:
                            thesis_status = s
                            break
                if "changed" in ll:
                    what_changed = l[:200]
                if "matters" in ll or "portfolio" in ll:
                    why_matters = l[:200]
            if not what_changed and lines:
                what_changed = lines[0][:200]

        # Determine if Steph review needed
        needs_steph = thesis_status in ("broken", "weakening") or spike or (rsi != "?" and float(rsi) > 75)
        escalation = ""
        if thesis_status in ("broken", "weakening"):
            escalation = f"Thesis {thesis_status} — Steph should validate"
        elif spike:
            escalation = "Unusual social spike — Steph should check"

        confidence = 0.55 if llm_output else 0.35

        ok = _db_write(
            """INSERT INTO aegis_portfolio_briefs
               (run_id, symbol, brief_type, thesis_status, what_changed, why_it_matters,
                technical_drift, news_context, social_context, confidence,
                needs_steph_review, escalation_reason, provenance)
               VALUES (%s,%s,'symbol',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (run_id, symbol, brief_type) DO UPDATE SET
                thesis_status=EXCLUDED.thesis_status, what_changed=EXCLUDED.what_changed,
                confidence=EXCLUDED.confidence, needs_steph_review=EXCLUDED.needs_steph_review""",
            (RUN_ID, sym, thesis_status, what_changed, why_matters,
             f"RSI {rsi}, SMA200 {sma200}%",
             news_titles[:200] if news_titles else None,
             f"{mentions} mentions, score {sent_score}" if mentions else None,
             confidence, needs_steph, escalation,
             json.dumps({"run_id": RUN_ID, "agent": AGENT, "source": "aegis:synthesis", "model": "governed-cloud"}))
        )
        if ok:
            written += 1

        # ── ADVISORY: cloud review of weakening/broken local-LLM theses ──
        # Additive + advisory only. The helper persists each review to
        # llm_feedback_observations; nothing here gates or alters the brief.
        if (cloud_review_enabled
                and thesis_status in ("weakening", "broken")
                and cloud_reviewed < CLOUD_REVIEW_CAP):
            try:
                import cloud_review
                if cloud_review.available():
                    cr = cloud_review.review(
                        task="aegis_thesis_review",
                        local_output=f"thesis {thesis_status}: {what_changed} | {why_matters}",
                        context={
                            "symbol": sym,
                            "rsi": rsi,
                            "sma200": sma200,
                            "pct_from_52wk_high": snap.get("pct_from_52wk_high"),
                            "news": news_titles[:200] if news_titles else None,
                        },
                        symbol=sym,
                        source="aegis_synthesis",
                    )
                    cloud_reviewed += 1
                    consensus = (cr or {}).get("consensus") or {}
                    verdict = consensus.get("verdict", "?")
                    print(f"  [cloud-review] {sym} ({thesis_status}) → consensus {verdict} "
                          f"(agree={consensus.get('agree')}, caution={consensus.get('caution')}, "
                          f"disagree={consensus.get('disagree')})")
            except Exception as e:
                print(f"  [cloud-review] {sym} skipped: {e}")

    return written


# ── D2: Covered-call candidates ──────────────────────────────────────────

def evaluate_covered_calls() -> int:
    """For eligible holdings, produce covered-call candidate proposals."""
    h = _load_json(STATE_DIR / "holdings.json") or {}
    written = 0

    # Eligible: individual stocks (not ETFs/funds), with 100+ shares, in taxable or IRA
    for p in h.get("holdings", []):
        sym = p.get("symbol", "")
        shares = p.get("shares", 0)
        price = p.get("price", 0)
        acct = p.get("account", "")
        is_fund = p.get("is_fund") or p.get("is_cash")

        if is_fund or shares < 100 or price < 5:
            continue
        if acct == "fidelity_401k":
            continue  # Can't trade options in 401k

        # Get current technicals
        snap = _db_query(
            "SELECT rsi, sma200_pct, beta FROM aegis_symbol_snapshot_nightly WHERE symbol=%s ORDER BY observed_at DESC LIMIT 1",
            (sym,), fetch="one"
        ) or {}

        rsi = float(snap.get("rsi") or 50)
        sma200 = float(snap.get("sma200_pct") or 0)
        beta_val = float(snap.get("beta") or 1.0)

        # Outcome-refined covered-call evaluation (Tier 2J)
        # Check past outcomes for this symbol
        past_outcomes = _db_query(
            "SELECT outcome_label, outcome_score FROM aegis_outcome_tracking WHERE symbol=%s AND category LIKE '%%covered%%' AND status='evaluated' ORDER BY evaluated_at DESC LIMIT 3",
            (sym,)
        ) or []
        past_helpful = sum(1 for o in past_outcomes if o.get("outcome_label") == "helpful")
        past_noise = sum(1 for o in past_outcomes if o.get("outcome_label") in ("noise", "too_early", "incorrect"))
        outcome_note = ""
        if past_outcomes:
            avg_past = sum(float(o.get("outcome_score") or 0) for o in past_outcomes) / len(past_outcomes)
            outcome_note = f" [Outcome history: {len(past_outcomes)} prior calls, avg score {avg_past:.2f}]"

        # Refined thresholds (originally RSI>70, now RSI>72 per approved proposal #1)
        if rsi > 72 and sma200 > 5:
            verdict = "candidate"
            reasoning = f"{sym} RSI {rsi:.0f} (strongly overbought) with positive SMA200 ({sma200:.1f}%). Good candidate for selling calls.{outcome_note}"
            strike_guidance = "Near-the-money or slightly OTM (1-3% above current)"
            time_horizon = "30-45 DTE preferred"
            risk_note = f"Beta {beta_val:.2f}. If stock gaps up past strike, shares get called away."
        elif rsi > 55 and sma200 > 0 and not (past_noise > past_helpful and len(past_outcomes) >= 2):
            verdict = "review_needed"
            reasoning = f"{sym} RSI {rsi:.0f} with constructive trend. Could sell OTM calls, but review thesis/catalyst first.{outcome_note}"
            strike_guidance = "OTM (5-10% above current)"
            time_horizon = "30-45 DTE"
            risk_note = f"Check earnings dates. Beta {beta_val:.2f}."
            if past_noise > 0:
                risk_note += f" Note: {past_noise} prior CC calls on {sym} scored as noise."
        elif rsi < 35 or sma200 < -5:
            verdict = "avoid"
            reasoning = f"{sym} RSI {rsi:.0f}, SMA200 {sma200:.1f}% — technically weak. Avoid selling calls at depressed levels.{outcome_note}"
            strike_guidance = "Not recommended"
            time_horizon = "Wait for technical repair"
            risk_note = "Position needs recovery before options income is appropriate."
            if past_helpful > 0:
                risk_note += f" Prior avoid calls on {sym} scored {past_helpful}/{len(past_outcomes)} helpful."
        else:
            verdict = "review_needed"
            reasoning = f"{sym} neutral technical state (RSI {rsi:.0f}). Manual review recommended."
            strike_guidance = "OTM if writing"
            time_horizon = "30-45 DTE"
            risk_note = f"Beta {beta_val:.2f}."

        # V2: Enrich with thesis/brief context
        brief = _db_query(
            "SELECT thesis_status, needs_steph_review, social_context FROM aegis_portfolio_briefs WHERE symbol=%s ORDER BY observed_at DESC LIMIT 1",
            (sym,), fetch="one"
        ) or {}
        thesis = brief.get("thesis_status", "intact")
        social = brief.get("social_context") or ""

        # Thesis quality assessment
        thesis_quality = "strong" if thesis in ("intact", "improving") else "weak" if thesis == "weakening" else "broken" if thesis == "broken" else "unknown"
        upside_cap = f"Selling calls caps upside. If {sym} rallies past strike, shares called away." if verdict != "avoid" else ""
        catalyst_conflict = ""
        if "spike" in social.lower() or "mentions" in social and int(social.split()[0] or "0") > 3:
            catalyst_conflict = f"Social activity elevated — potential catalyst. Selling calls before catalyst resolution adds risk."

        income_fit = "good" if verdict == "candidate" else "marginal" if verdict == "review_needed" else "poor"
        steph_reason = ""
        if thesis_quality == "weak" and verdict != "avoid":
            steph_reason = f"Thesis weakening but CC not avoided — Steph should validate thesis before income strategy"
        elif catalyst_conflict:
            steph_reason = f"Social catalyst may conflict with income goal — Steph review recommended"

        ok = _db_write(
            """INSERT INTO aegis_covered_call_candidates
               (run_id, symbol, account, verdict, reasoning, strike_guidance, time_horizon,
                risk_note, shares_available, current_price, needs_steph_review, confidence,
                thesis_quality, upside_cap_risk, catalyst_conflict, income_goal_fit, steph_review_reason,
                provenance)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (run_id, symbol) DO UPDATE SET
                verdict=EXCLUDED.verdict, reasoning=EXCLUDED.reasoning, confidence=EXCLUDED.confidence,
                thesis_quality=EXCLUDED.thesis_quality, steph_review_reason=EXCLUDED.steph_review_reason""",
            (RUN_ID, sym, acct, verdict, reasoning, strike_guidance, time_horizon,
             risk_note, shares, price, bool(steph_reason) or verdict != "avoid",
             0.55 if verdict == "candidate" else 0.40 if verdict == "review_needed" else 0.30,
             thesis_quality, upside_cap, catalyst_conflict, income_fit, steph_reason,
             json.dumps({"run_id": RUN_ID, "agent": AGENT, "source": "aegis:covered-calls-v2"}))
        )
        if ok:
            written += 1

    return written


# ── Rotation alternatives ────────────────────────────────────────────────

def evaluate_rotation_alternatives() -> int:
    """For stopped-out/recovery/weak positions, find stronger alternatives."""
    written = 0

    # Get recovery items
    recovery = _db_query("SELECT symbol, analyst_verdict, analyst_confidence, temp_allocation_verdict FROM stopped_out_watch WHERE is_active=true") or []
    if not recovery:
        return 0

    # Get watchlist with intent
    wl = _load_json(STATE_DIR / "watchlist.json") or {}
    # Get nightly snapshots for comparison
    snaps = _db_query(
        "SELECT symbol, rsi, sma200_pct, confidence FROM aegis_symbol_snapshot_nightly WHERE run_id=(SELECT run_id FROM aegis_symbol_snapshot_nightly ORDER BY observed_at DESC LIMIT 1)"
    ) or []
    snap_map = {r["symbol"]: r for r in snaps}

    for rec in recovery:
        from_sym = rec["symbol"]
        from_verdict = rec.get("analyst_verdict", "wait_monitor")
        from_alloc = rec.get("temp_allocation_verdict", "stay_cash")

        # Find potential rotation targets from watchlist
        candidates = []
        for wl_sym, wl_meta in wl.items():
            if wl_sym == from_sym:
                continue
            ws = snap_map.get(wl_sym, {})
            w_rsi = float(ws.get("rsi") or 50)
            w_sma = float(ws.get("sma200_pct") or 0)
            w_conf = float(ws.get("confidence") or 0)
            intent = wl_meta.get("target_intent", "")

            # Score: prefer constructive technicals + high intent match + outcome history
            score = 0
            if w_rsi < 40:
                score += 2  # Oversold = opportunity
            if w_sma > 0:
                score += 1
            if intent in ("long_term_hold", "growth"):
                score += 1
            if w_conf > 0.5:
                score += 1

            # Check past rotation outcomes for this target
            rot_outcomes = _db_query(
                "SELECT outcome_label FROM aegis_outcome_tracking WHERE symbol=%s AND category LIKE '%%rotation%%' AND status='evaluated'",
                (wl_sym,)
            ) or []
            rot_helpful = sum(1 for o in rot_outcomes if o.get("outcome_label") == "helpful")
            if rot_helpful > 0:
                score += 1  # Bonus for historically good rotation target
            rot_note = f" [Prior rotation outcome: {rot_helpful}/{len(rot_outcomes)} helpful]" if rot_outcomes else ""

            if score >= 2:
                candidates.append({
                    "symbol": wl_sym, "score": score,
                    "rsi": w_rsi, "sma200": w_sma, "intent": intent,
                    "reason": f"{wl_sym} RSI {w_rsi:.0f}, SMA200 {w_sma:+.1f}%, intent={intent}. {'Oversold opportunity.' if w_rsi < 40 else 'Constructive trend.'}{rot_note}"
                })

        candidates.sort(key=lambda c: -c["score"])

        if candidates and from_verdict in ("do_not_reenter", "wait_monitor"):
            best = candidates[0]
            switch_verdict = "consider" if from_verdict == "do_not_reenter" else "not_yet"
            blocker = f"{from_sym} still in {from_verdict} — wait for verdict clarity before deploying" if switch_verdict == "not_yet" else ""
            evidence = f"Freed capital from {from_sym} (currently {from_alloc}). Best alternative: {best['reason']}"

            _db_write(
                """INSERT INTO aegis_rotation_candidates
                   (run_id, from_symbol, from_reason, to_symbol, to_reason, switch_verdict, evidence, blocker, confidence, needs_steph_review, provenance)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (run_id, from_symbol, to_symbol) DO NOTHING""",
                (RUN_ID, from_sym, f"{from_verdict} — {from_alloc}",
                 best["symbol"], best["reason"], switch_verdict, evidence,
                 blocker, 0.45, True,
                 json.dumps({"run_id": RUN_ID, "agent": AGENT, "source": "aegis:rotation"}))
            )
            written += 1

            # Second alternative if available
            if len(candidates) >= 2:
                second = candidates[1]
                _db_write(
                    """INSERT INTO aegis_rotation_candidates
                       (run_id, from_symbol, from_reason, to_symbol, to_reason, switch_verdict, evidence, blocker, confidence, needs_steph_review, provenance)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT (run_id, from_symbol, to_symbol) DO NOTHING""",
                    (RUN_ID, from_sym, f"{from_verdict} — {from_alloc}",
                     second["symbol"], second["reason"], "consider",
                     f"2nd alternative for {from_sym} capital", blocker, 0.35, True,
                     json.dumps({"run_id": RUN_ID, "agent": AGENT, "source": "aegis:rotation"}))
                )
                written += 1
        else:
            # No valid alternative — record explicitly
            _db_write(
                """INSERT INTO aegis_rotation_candidates
                   (run_id, from_symbol, from_reason, to_symbol, to_reason, switch_verdict, evidence, blocker, confidence, needs_steph_review, provenance)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (run_id, from_symbol, to_symbol) DO NOTHING""",
                (RUN_ID, from_sym, f"{from_verdict} — {from_alloc}",
                 None, "No strong watchlist alternative passes threshold", "not_yet",
                 f"Checked {len(wl)} watchlist names — none scored >= 2", "No qualifying alternative",
                 0.30, False,
                 json.dumps({"run_id": RUN_ID, "agent": AGENT, "source": "aegis:rotation"}))
            )
            written += 1

    return written


# ── Steph escalation reasoning ───────────────────────────────────────────

def generate_steph_escalations() -> int:
    """Collect all items needing Steph review with rich reasoning."""
    written = 0

    # From briefs
    briefs = _db_query(
        f"SELECT symbol, thesis_status, escalation_reason, social_context FROM aegis_portfolio_briefs WHERE run_id=%s AND needs_steph_review=true",
        (RUN_ID,)
    ) or []
    for b in briefs:
        _db_write(
            """INSERT INTO aegis_steph_escalations (run_id, symbol, category, reason, evidence_summary, unresolved_question, confidence, provenance)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (run_id, symbol, category) DO NOTHING""",
            (RUN_ID, b["symbol"], "thesis_review",
             b.get("escalation_reason") or f"{b['symbol']} thesis {b.get('thesis_status','')}",
             b.get("social_context") or "",
             f"Is {b['symbol']} thesis still intact? Social activity suggests possible change.",
             0.50,
             json.dumps({"agent": AGENT, "source": "aegis:escalation"}))
        )
        written += 1

    # From covered-call conflicts
    cc_conflicts = _db_query(
        f"SELECT symbol, steph_review_reason, catalyst_conflict FROM aegis_covered_call_candidates WHERE run_id=%s AND steph_review_reason IS NOT NULL AND steph_review_reason != ''",
        (RUN_ID,)
    ) or []
    for c in cc_conflicts:
        _db_write(
            """INSERT INTO aegis_steph_escalations (run_id, symbol, category, reason, evidence_summary, unresolved_question, confidence, provenance)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (run_id, symbol, category) DO NOTHING""",
            (RUN_ID, c["symbol"], "covered_call_review",
             c["steph_review_reason"],
             c.get("catalyst_conflict") or "",
             f"Should {c['symbol']} covered calls proceed given current context?",
             0.45,
             json.dumps({"agent": AGENT, "source": "aegis:escalation"}))
        )
        written += 1

    # From rotation candidates
    rotations = _db_query(
        f"SELECT from_symbol, to_symbol, evidence FROM aegis_rotation_candidates WHERE run_id=%s AND needs_steph_review=true",
        (RUN_ID,)
    ) or []
    for r in rotations:
        _db_write(
            """INSERT INTO aegis_steph_escalations (run_id, symbol, category, reason, evidence_summary, unresolved_question, confidence, provenance)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (run_id, symbol, category) DO NOTHING""",
            (RUN_ID, r["from_symbol"], "rotation_review",
             f"Capital rotation from {r['from_symbol']} → {r.get('to_symbol') or 'alternatives'} needs review",
             r.get("evidence") or "",
             f"Should freed capital from {r['from_symbol']} be rotated to {r.get('to_symbol') or 'best alternative'}?",
             0.40,
             json.dumps({"agent": AGENT, "source": "aegis:escalation"}))
        )
        written += 1

    return written


MAX_RETRIES = 5

def _steph_llm(prompt: str, attempt: int = 1, max_tokens: int = 250) -> str:
    """Call governed cloud lanes for Steph review."""
    try:
        from lib.governed_cloud_generation import generate_cloud
        raw, _lane = generate_cloud(
            prompt, process_id="aegis_steph_review",
            task_summary=f"Steph evidence review attempt {attempt}", timeout=90,
            max_tokens=max_tokens,
        )
        return raw
    except Exception as e:
        print(f"  [steph-llm] Attempt {attempt} failed: {e}")
        return ""


def _parse_steph_response(raw: str, default_conf: float):
    """Parse Steph review from LLM response. Tolerant of format variations."""
    verdict = "in_review"
    confidence = default_conf
    reasoning = ""
    next_step = ""
    john_q = ""

    # Try JSON parse first (most reliable if model cooperates)
    try:
        if "{" in raw:
            start = raw.index("{")
            end = raw.rindex("}") + 1
            obj = json.loads(raw[start:end])
            verdict = obj.get("verdict", obj.get("v", "in_review")).lower().replace(" ", "_")
            confidence = float(obj.get("confidence", obj.get("c", default_conf)))
            reasoning = obj.get("reasoning", obj.get("r", ""))
            next_step = obj.get("next_step", obj.get("n", ""))
            john_q = obj.get("john_question", obj.get("j", ""))
            if verdict in ("resolved", "needs_john", "deferred", "in_review"):
                return verdict, confidence, reasoning, next_step, john_q
    except (json.JSONDecodeError, ValueError):
        pass

    # Fallback: line-by-line parsing
    for line in raw.split("\n"):
        cl = line.strip()
        up = cl.upper()
        if up.startswith("VERDICT:") or up.startswith("V:"):
            v = cl.split(":", 1)[1].strip().lower().replace(" ", "_")
            if v in ("resolved", "needs_john", "deferred", "in_review"):
                verdict = v
        elif up.startswith("CONFIDENCE:") or up.startswith("C:"):
            try:
                confidence = float(cl.split(":", 1)[1].strip())
            except ValueError:
                pass
        elif up.startswith("REASONING:") or up.startswith("R:"):
            reasoning = cl.split(":", 1)[1].strip()
        elif "NEXT" in up and ":" in cl:
            next_step = cl.split(":", 1)[1].strip()
        elif "JOHN" in up and ":" in cl:
            john_q = cl.split(":", 1)[1].strip()

    # If no explicit reasoning was parsed, use the full response as reasoning
    if not reasoning and len(raw) > 10:
        reasoning = raw[:300]

    return verdict, confidence, reasoning, next_step, john_q


def auto_generate_steph_reviews() -> int:
    """Automatically generate Steph reviews for all pending/failed-retryable escalations.

    Production-hardened version with:
    - Simplified prompt that small LLMs can handle
    - Up to MAX_RETRIES attempts per item with increasing temperature
    - JSON + line-by-line parse fallback
    - Clear status: generated / failed (with attempt count)
    - Uses Steph persona context from SOUL.md
    """
    # Process both pending_review and failed (retry)
    pending = _db_query(
        "SELECT id, symbol, category, reason, evidence_summary, unresolved_question, confidence "
        "FROM aegis_steph_escalations WHERE review_status IN ('pending_review', 'failed') ORDER BY id"
    ) or []

    if not pending:
        print("  [steph-auto] No pending/retryable escalations")
        return 0

    print(f"  [steph-auto] Reviewing {len(pending)} escalations (max {MAX_RETRIES} attempts each)...")

    # Load context once
    rm = _load_json(STATE_DIR / "risk_management.json") or {}
    holdings = _load_json(STATE_DIR / "holdings.json") or {}
    positions = {h.get("symbol"): h for h in holdings.get("holdings", []) if h.get("symbol")}
    risk_pos = {p.get("symbol"): p for p in rm.get("positions", []) if p.get("symbol")}

    generated = 0
    terminal_failed = 0

    for esc in pending:
        esc_id = esc["id"]
        symbol = esc.get("symbol", "?")
        category = esc.get("category", "?")
        reason = esc.get("reason", "")
        evidence = esc.get("evidence_summary", "")
        question = esc.get("unresolved_question", "")
        base_conf = float(esc.get("confidence") or 0.5)

        # Build compact position context
        pos = positions.get(symbol, {})
        rp = risk_pos.get(symbol, {})
        ctx_parts = []
        if pos:
            ctx_parts.append(f"${pos.get('market_value', 0):,.0f} position, {pos.get('portfolio_pct', 0):.1f}% of portfolio")
        if rp:
            ctx_parts.append(f"risk status: {rp.get('status', '?')}")
            if rp.get("stop_price"):
                ctx_parts.append(f"stop at ${rp['stop_price']}")
        ctx = ". ".join(ctx_parts) if ctx_parts else "No position data"

        # RAG context for Steph escalation
        steph_rag = ""
        try:
            from rag_retrieval import get_rag_context, format_rag_context_for_prompt
            sr = get_rag_context(symbol=symbol, agent_name="steph", limit=3)
            steph_rag = format_rag_context_for_prompt(sr, symbol=symbol)
        except Exception:
            pass

        # Simplified prompt for small LLMs. /no_think disables qwen3 internal reasoning.
        prompt = f"""/no_think
Review this portfolio escalation as Steph (wealth advisor). Respond ONLY with JSON.

{symbol} — {category.replace('_', ' ')}
Reason: {reason[:150]}
Context: {ctx}
{steph_rag}
Question: {question[:100]}

Respond with ONLY this JSON object, no other text:
{{"verdict":"in_review","confidence":0.5,"reasoning":"one sentence assessment","next_step":"one action","john_question":""}}"""

        success = False
        last_error = ""
        for attempt in range(1, MAX_RETRIES + 1):
            raw = _steph_llm(prompt, attempt=attempt)
            if not raw:
                last_error = f"empty response attempt {attempt}/{MAX_RETRIES}"
                continue

            verdict, conf, reasoning, next_step, john_q = _parse_steph_response(raw, base_conf)

            if not reasoning or len(reasoning) < 5:
                last_error = f"unparseable response attempt {attempt}/{MAX_RETRIES}"
                continue

            # Success — persist
            ok = _db_write(
                """UPDATE aegis_steph_escalations SET
                      review_status=%s, steph_verdict=%s, steph_reasoning=%s,
                      steph_confidence=%s, recommended_next_step=%s,
                      send_to_john=%s, john_question=%s,
                      resolved_at=CASE WHEN %s IN ('resolved','deferred') THEN now() ELSE NULL END,
                      reviewed_by='steph_auto'
                   WHERE id=%s""",
                (verdict, verdict, reasoning[:500], conf, next_step[:200] or None,
                 verdict == "needs_john", john_q[:200] or None,
                 verdict, esc_id)
            )
            if ok:
                generated += 1
                flag = " → JOHN" if verdict == "needs_john" else ""
                att = f" (attempt {attempt})" if attempt > 1 else ""
                print(f"  [steph-auto] ✓ {symbol} ({category}): {verdict} conf={conf:.0%}{flag}{att}")
                success = True
                break
            else:
                last_error = f"DB write failed attempt {attempt}"

        if not success:
            _db_write(
                """UPDATE aegis_steph_escalations SET
                      review_status='failed', steph_reasoning=%s, reviewed_by='steph_auto'
                   WHERE id=%s""",
                (f"Auto-review failed after {MAX_RETRIES} attempts: {last_error}", esc_id)
            )
            terminal_failed += 1
            print(f"  [steph-auto] ✗ {symbol} ({category}): FAILED after {MAX_RETRIES} attempts — {last_error}")

    print(f"  [steph-auto] Complete: {generated} generated, {terminal_failed} failed out of {len(pending)}")

    # After all reviews complete, promote failures into actionable queues
    if terminal_failed > 0:
        promoted = promote_failed_reviews()
        print(f"  [steph-auto] Promoted {promoted} failed reviews into John/Ops queues")

    return generated


def promote_failed_reviews() -> int:
    """Promote failed Steph stop reviews into John decision queue or Ops visibility.

    Rules:
    - triggered/danger failures → John decision queue (urgent/high priority)
    - warning/intact failures → lower-priority John item (still visible, not buried)
    - Deduped by symbol + date so reruns don't spam
    - Links back to escalation_id and stop brief
    """
    failed = _db_query(
        """SELECT e.id, e.symbol, e.category, e.reason, e.steph_reasoning, e.run_id,
                  b.thesis_status as stop_status, b.provenance as brief_provenance
           FROM aegis_steph_escalations e
           LEFT JOIN aegis_portfolio_briefs b ON b.symbol = e.symbol AND b.brief_type = 'stop_brief'
                AND b.run_id = (SELECT run_id FROM aegis_portfolio_briefs WHERE brief_type='stop_brief' ORDER BY observed_at DESC LIMIT 1)
           WHERE e.review_status = 'failed' AND e.category = 'stop_review'
           ORDER BY e.id"""
    ) or []

    if not failed:
        return 0

    today = datetime.now().strftime("%Y-%m-%d")
    promoted = 0

    for f in failed:
        sym = f.get("symbol", "?")
        esc_id = f["id"]
        stop_status = f.get("stop_status") or "unknown"
        failure_reason = (f.get("steph_reasoning") or "Auto-review failed")[:200]
        brief_prov = f.get("brief_provenance") or {}
        if isinstance(brief_prov, str):
            try:
                brief_prov = json.loads(brief_prov)
            except (json.JSONDecodeError, TypeError):
                brief_prov = {}

        resolved_price = brief_prov.get("resolved_current_price", 0)
        stop_price = brief_prov.get("stop_price", 0)
        market_value = brief_prov.get("market_value", 0)

        # Priority based on stop status
        if stop_status in ("triggered",):
            priority = "urgent"
            title = f"{sym} — Stop triggered, auto-review failed"
            desc = f"{sym} stop is triggered (price ${resolved_price:.2f} vs stop ${stop_price:.2f}). " \
                   f"Steph auto-review failed: {failure_reason}. " \
                   f"John must decide: hold, exit, or adjust stop."
            followup = "Verify broker stop status. Decide exit/hold. Update stop if needed."
            route = f"/risk?symbol={sym}"
        elif stop_status in ("danger",):
            priority = "high"
            title = f"{sym} — Near stop, auto-review failed"
            desc = f"{sym} is in danger zone (${resolved_price:.2f} near stop ${stop_price:.2f}). " \
                   f"Steph auto-review failed: {failure_reason}. " \
                   f"Review stop integrity and position thesis."
            followup = "Review stop level. Monitor for trigger. Consider adjustment."
            route = f"/risk?symbol={sym}"
        else:
            priority = "normal"
            title = f"{sym} — Stop review automation failed"
            desc = f"{sym} stop review could not be auto-generated: {failure_reason}. " \
                   f"Position value ${market_value:,.0f}."
            followup = "Manual review of stop adequacy when convenient."
            route = "/recovery"

        # Dedupe: don't create if a pending task already exists for this symbol+category
        existing = _db_query(
            "SELECT id FROM john_decision_queue WHERE symbol=%s AND category='failed_stop_review' "
            "AND status='pending_john' LIMIT 1",
            (sym,), fetch="one"
        )
        if existing:
            # Update the existing task with fresh data instead of creating a duplicate
            _db_write(
                """UPDATE john_decision_queue SET description=%s,
                   provenance=provenance || %s::jsonb, updated_at=NOW()
                   WHERE id=%s""",
                (desc, json.dumps({"last_refreshed": str(today),
                                   "resolved_price": resolved_price,
                                   "stop_price": stop_price}),
                 existing["id"])
            )
            continue

        ok = _db_write(
            """INSERT INTO john_decision_queue
               (category, symbol, title, description, steph_recommendation,
                steph_confidence, aegis_source_id, priority, status,
                due_by, required_followup, linked_route, linked_symbols, provenance)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            ("failed_stop_review", sym, title, desc,
             "Auto-review failed — manual review required", 0,
             esc_id, priority, "pending_john",
             today if priority in ("urgent", "high") else None,
             followup, route, [sym],
             json.dumps({"source": "aegis:failed-review-promotion",
                         "escalation_id": esc_id, "stop_status": stop_status,
                         "failure_reason": failure_reason,
                         "resolved_price": resolved_price, "stop_price": stop_price,
                         "market_value": market_value, "run_id": RUN_ID}))
        )
        if ok:
            promoted += 1
            print(f"  [queue-promote] {sym} ({stop_status}) → John queue as {priority}")

    return promoted


# ── D3: Portfolio-wide summary ───────────────────────────────────────────

def generate_portfolio_summary() -> bool:
    """Generate a portfolio-wide overnight summary brief."""
    rm = _load_json(STATE_DIR / "risk_management.json") or {}
    h = _load_json(STATE_DIR / "holdings.json") or {}

    heat = rm.get("portfolio_heat_pct", 0)
    triggered = len([p for p in rm.get("positions", []) if p.get("status") == "TRIGGERED"])
    unprotected = len([p for p in rm.get("positions", []) if p.get("status") == "NO STOP"])
    total_value = sum(p.get("market_value", 0) for p in h.get("holdings", []))

    # Count escalation candidates from briefs
    steph_count = _db_query(
        f"SELECT COUNT(*) as cnt FROM aegis_portfolio_briefs WHERE run_id=%s AND needs_steph_review=true",
        (RUN_ID,), fetch="one"
    ) or {}
    steph_items = steph_count.get("cnt", 0)

    # Count covered-call candidates
    cc_count = _db_query(
        f"SELECT verdict, COUNT(*) as cnt FROM aegis_covered_call_candidates WHERE run_id=%s GROUP BY verdict",
        (RUN_ID,)
    ) or []
    cc_summary = {r["verdict"]: r["cnt"] for r in cc_count}

    summary = f"Portfolio ${total_value:,.0f}. Heat {heat:.1f}%. {triggered} stops triggered, {unprotected} unprotected. "
    summary += f"{steph_items} items flagged for Steph review. "
    summary += f"Covered calls: {cc_summary.get('candidate',0)} candidates, {cc_summary.get('review_needed',0)} need review, {cc_summary.get('avoid',0)} avoid."

    return _db_write(
        """INSERT INTO aegis_portfolio_briefs
           (run_id, symbol, brief_type, thesis_status, what_changed, confidence,
            needs_steph_review, escalation_reason, provenance)
           VALUES (%s, 'PORTFOLIO', 'summary', 'n/a', %s, 0.60, %s, %s, %s)
           ON CONFLICT (run_id, symbol, brief_type) DO UPDATE SET what_changed=EXCLUDED.what_changed""",
        (RUN_ID, summary, steph_items > 0,
         f"{steph_items} items need Steph review" if steph_items > 0 else None,
         json.dumps({"run_id": RUN_ID, "agent": AGENT, "source": "aegis:synthesis"}))
    )


# ── Main ─────────────────────────────────────────────────────────────────

# ── Tier 2C: Evidence ledger + bias check ────────────────────────────────

def build_evidence_ledger(symbols: list[str]) -> int:
    """For each synthesized symbol, audit evidence quality and check for bias."""
    written = 0

    for sym in symbols:
        # Gather all evidence sources for this symbol
        snap = _db_query("SELECT sources_used, confidence FROM aegis_symbol_snapshot_nightly WHERE symbol=%s ORDER BY observed_at DESC LIMIT 1", (sym,), fetch="one") or {}
        sentiment = _db_query("SELECT source_family, mention_count, sentiment_score, unusual_spike FROM social_sentiment_history WHERE symbol=%s ORDER BY observed_at DESC LIMIT 1", (sym,), fetch="one") or {}
        transcripts = _db_query("SELECT source_family, stance, confidence FROM transcript_intel_history WHERE symbol=%s ORDER BY observed_at DESC LIMIT 5", (sym,)) or []
        brief = _db_query("SELECT thesis_status, confidence, needs_steph_review FROM aegis_portfolio_briefs WHERE symbol=%s ORDER BY observed_at DESC LIMIT 1", (sym,), fetch="one") or {}

        # Count sources by family
        families = set()
        tier_mix = {}
        source_count = 0
        if snap.get("sources_used"):
            for s in snap["sources_used"]:
                families.add(s)
                tier = "A" if s in ("holdings", "technical_snapshot") else "A" if s == "finviz" else "A" if s == "yahoo" else "C"
                tier_mix[tier] = tier_mix.get(tier, 0) + 1
                source_count += 1
        if sentiment.get("source_family"):
            families.add("social")
            tier_mix["C"] = tier_mix.get("C", 0) + 1
            source_count += 1
        for t in transcripts:
            families.add(t.get("source_family", "transcript"))
            tier = "B" if t.get("source_family") == "article_index" else "D"
            tier_mix[tier] = tier_mix.get(tier, 0) + 1
            source_count += 1

        # Bias checks
        bias_flags = []
        bias_score = 0.0

        # 1. Single-source dominance
        if source_count > 0 and len(families) == 1:
            bias_flags.append("single_source_dominance")
            bias_score += 0.3

        # 2. Social overweight
        social_mentions = sentiment.get("mention_count", 0) or 0
        if social_mentions > 3 and source_count <= 2:
            bias_flags.append("social_overweight")
            bias_score += 0.2

        # 3. One-sided bull/bear
        stances = [t.get("stance") for t in transcripts if t.get("stance")]
        if stances and len(set(stances)) == 1 and len(stances) >= 2:
            bias_flags.append(f"one_sided_{stances[0]}")
            bias_score += 0.2

        # 4. High confidence / low evidence
        brief_conf = float(brief.get("confidence") or 0)
        if brief_conf > 0.6 and source_count < 3:
            bias_flags.append("high_confidence_low_evidence")
            bias_score += 0.25

        # 5. Stale evidence
        snap_conf = float(snap.get("confidence") or 0)
        if snap_conf < 0.4 and source_count > 0:
            bias_flags.append("low_data_quality")
            bias_score += 0.15

        bias_score = min(round(bias_score, 2), 1.0)

        # Evidence sufficiency
        if source_count >= 4 and len(families) >= 3:
            sufficiency = "strong"
        elif source_count >= 2 and len(families) >= 2:
            sufficiency = "adequate"
        elif source_count >= 1:
            sufficiency = "weak"
        else:
            sufficiency = "insufficient"

        # Counterevidence check for high-impact items
        needs_counter = brief.get("needs_steph_review") or bias_score > 0.4
        counter_summary = None
        conflict = False
        if needs_counter:
            # Check for contradictory stances
            bull_count = sum(1 for t in transcripts if t.get("stance") == "bullish")
            bear_count = sum(1 for t in transcripts if t.get("stance") == "bearish")
            sent_score = float(sentiment.get("sentiment_score") or 0)
            if bull_count > 0 and bear_count > 0:
                counter_summary = f"Mixed transcript stances: {bull_count} bullish, {bear_count} bearish"
                conflict = True
            elif sent_score > 0.3 and any(t.get("stance") == "bearish" for t in transcripts):
                counter_summary = "Social bullish but transcript bearish — conflicting signals"
                conflict = True
            elif sent_score < -0.3 and any(t.get("stance") == "bullish" for t in transcripts):
                counter_summary = "Social bearish but transcript bullish — conflicting signals"
                conflict = True

        # Determine statement type for the brief
        if brief.get("thesis_status") in ("intact", "improving", "weakening", "broken"):
            stmt_type = "inference"  # Thesis status is always an inference
        elif source_count == 0:
            stmt_type = "fact"  # Just reporting no data
        else:
            stmt_type = "recommendation" if brief.get("needs_steph_review") else "inference"

        # If bias is high, downgrade the brief confidence
        if bias_score > 0.4 and brief.get("confidence"):
            new_conf = max(0.25, float(brief["confidence"]) - 0.15)
            _db_write("UPDATE aegis_portfolio_briefs SET confidence=%s, needs_steph_review=true WHERE symbol=%s AND run_id=%s",
                       (new_conf, sym, RUN_ID))

        ok = _db_write(
            """INSERT INTO aegis_evidence_ledger
               (run_id, output_type, symbol, source_families, source_count, tier_mix,
                supporting_count, contradictory_count, evidence_confidence,
                statement_type, bias_score, bias_flags, needs_counterevidence,
                evidence_sufficiency, counterevidence_summary, conflict_flag,
                steph_review_required, raw_evidence)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (run_id, output_type, symbol) DO UPDATE SET
                bias_score=EXCLUDED.bias_score, bias_flags=EXCLUDED.bias_flags,
                evidence_sufficiency=EXCLUDED.evidence_sufficiency, conflict_flag=EXCLUDED.conflict_flag""",
            (RUN_ID, "brief", sym, list(families), source_count, json.dumps(tier_mix),
             source_count, 1 if conflict else 0, round(snap_conf, 2),
             stmt_type, bias_score, bias_flags, needs_counter,
             sufficiency, counter_summary, conflict,
             conflict or bias_score > 0.5,
             json.dumps({"families": list(families), "tier_mix": tier_mix, "social_mentions": social_mentions,
                         "transcript_stances": stances, "bias_flags": bias_flags}))
        )
        if ok:
            written += 1

    return written


def _resolve_price(sym: str, holdings_by_sym: dict, enrichment: dict,
                    finviz_cache: dict, rm_price: float) -> tuple:
    """Canonical price resolver. Returns (price, source, valid).

    Resolution order:
    1. holdings.json (repriced daily via Finviz/Yahoo)
    2. finviz_quote_cache.json (latest Finviz fetch)
    3. enrichment cache
    4. risk_management.json
    5. unavailable
    """
    # 1. Holdings price (most recently repriced)
    sym_holdings = holdings_by_sym.get(sym, [])
    for hh in sym_holdings:
        p = hh.get("price", 0)
        if p and p > 0:
            return p, "holdings", True

    # 2. Finviz quote cache
    fq = finviz_cache.get(sym, {})
    if isinstance(fq, dict):
        fp = fq.get("price", 0)
        if isinstance(fp, (int, float)) and fp > 0:
            return fp, "finviz_cache", True

    # 3. Enrichment cache
    ec = enrichment.get(sym, {})
    if isinstance(ec, dict):
        ep = ec.get("price", 0)
        if ep and ep > 0:
            return ep, "enrichment", True

    # 4. Risk management
    if rm_price and rm_price > 0:
        return rm_price, "risk_mgmt", True

    return 0, "unavailable", False


def generate_stop_coverage_briefs() -> dict:
    """Evaluate EVERY stop-protected position with canonical price resolution
    and same-run Steph escalation for triggered/danger items.

    Returns coverage stats dict.
    """
    rm = _load_json(STATE_DIR / "risk_management.json") or {}
    h = _load_json(STATE_DIR / "holdings.json") or {}
    enrichment = _load_json(STATE_DIR / "ticker_enrichment_cache.json") or {}
    finviz_cache = _load_json(STATE_DIR / "finviz_quote_cache.json") or {}

    positions = rm.get("positions", [])
    with_stop = [p for p in positions if p.get("stop_price")]

    if not with_stop:
        print("  [stop-coverage] No stop-protected positions found")
        return {"total": 0}

    holdings_by_sym = {}
    for hh in h.get("holdings", []):
        sym = hh.get("symbol", "")
        if sym:
            holdings_by_sym.setdefault(sym, []).append(hh)

    # Dedupe by symbol
    seen = set()
    unique_stops = []
    for p in with_stop:
        sym = p.get("symbol", "")
        if sym and sym not in seen:
            seen.add(sym)
            unique_stops.append(p)

    print(f"  [stop-coverage] Evaluating {len(unique_stops)} stop-protected positions...")

    stats = {"total": len(unique_stops), "fresh": 0, "failed": 0,
             "triggered": 0, "danger": 0, "warning": 0, "intact": 0,
             "price_unavailable": 0, "steph_escalated": 0}

    for p in unique_stops:
        sym = p.get("symbol", "")
        stop_price = p.get("stop_price", 0)
        rm_price = p.get("current_price", 0)
        rm_status = (p.get("status") or "OK").upper()

        # ── Canonical price resolution ──
        price, price_source, price_valid = _resolve_price(
            sym, holdings_by_sym, enrichment, finviz_cache, rm_price)

        # Holdings market value
        sym_holdings = holdings_by_sym.get(sym, [])
        total_mv = sum(hh.get("market_value", 0) for hh in sym_holdings)
        if total_mv == 0:
            total_mv = p.get("market_value", 0)

        # ── Distance calculation with valid price only ──
        if price_valid and price > 0 and stop_price > 0:
            distance_pct = round((price - stop_price) / price * 100, 2)
        else:
            distance_pct = None

        # ── Classify stop status ──
        if not price_valid:
            stop_status = "price_unavailable"
            stats["price_unavailable"] += 1
            priority = 2  # treat as danger-equivalent
        elif price < stop_price:
            stop_status = "triggered"
            stats["triggered"] += 1
            priority = 1
        elif rm_status == "TRIGGERED":
            stop_status = "triggered"
            stats["triggered"] += 1
            priority = 1
        elif rm_status == "DANGER" or (distance_pct is not None and distance_pct < 3):
            stop_status = "danger"
            stats["danger"] += 1
            priority = 2
        elif rm_status == "WARNING" or (distance_pct is not None and distance_pct < 5):
            stop_status = "warning"
            stats["warning"] += 1
            priority = 3
        else:
            stop_status = "intact"
            stats["intact"] += 1
            priority = 4

        # ── Build brief text with resolved price (never $0.00) ──
        needs_steph = stop_status in ("triggered", "danger", "price_unavailable")

        if not price_valid:
            what_changed = f"Price unavailable for {sym} — stop at ${stop_price:.2f}, cannot verify status"
            why = "No valid price source found. Stop status cannot be confirmed."
            conf = 0.2
        elif priority <= 2:
            # Triggered/danger: LLM brief
            prompt = f"""/no_think
Assess this stop-protected position. One sentence each.

{sym}: ${price:.2f} (from {price_source}), stop ${stop_price:.2f}, {stop_status}, ${total_mv:,.0f} position

Reply ONLY JSON:
{{"what_changed":"assessment","why_it_matters":"risk impact","confidence":0.5}}"""
            raw = _steph_llm(prompt, attempt=1, max_tokens=150)
            if raw:
                try:
                    obj = json.loads(raw[raw.index("{"):raw.rindex("}") + 1])
                    what_changed = obj.get("what_changed", f"{sym} {stop_status} at ${price:.2f}")
                    why = obj.get("why_it_matters", "")
                    conf = float(obj.get("confidence", 0.5))
                except (json.JSONDecodeError, ValueError):
                    what_changed = f"{sym} {stop_status} — ${price:.2f} vs stop ${stop_price:.2f}"
                    why = raw[:200]
                    conf = 0.4
            else:
                dist_str = f"{distance_pct:.1f}% from stop" if distance_pct is not None else ""
                what_changed = f"{sym} {stop_status} — ${price:.2f} vs stop ${stop_price:.2f} {dist_str}".strip()
                why = f"Position ${total_mv:,.0f}. Requires review."
                conf = 0.3
        else:
            # Warning/intact: template
            dist_str = f"{distance_pct:.1f}%" if distance_pct is not None else "N/A"
            what_changed = f"{sym} stop intact — ${price:.2f} vs stop ${stop_price:.2f}, distance {dist_str}"
            why = "Position within normal parameters"
            conf = 0.7

        # ── Persist brief ──
        provenance = {
            "agent": AGENT, "source": "aegis:stop-coverage",
            "stop_price": stop_price,
            "resolved_current_price": price,
            "price_source": price_source,
            "price_valid": price_valid,
            "raw_rm_price": rm_price,
            "distance_pct": distance_pct,
            "market_value": total_mv,
            "stop_status": stop_status,
            "priority": priority,
        }

        ok = _db_write(
            """INSERT INTO aegis_portfolio_briefs
               (run_id, symbol, brief_type, thesis_status, what_changed, why_it_matters,
                confidence, needs_steph_review, escalation_reason, provenance)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (run_id, symbol, brief_type) DO UPDATE SET
                thesis_status=EXCLUDED.thesis_status, what_changed=EXCLUDED.what_changed,
                why_it_matters=EXCLUDED.why_it_matters, confidence=EXCLUDED.confidence,
                needs_steph_review=EXCLUDED.needs_steph_review, provenance=EXCLUDED.provenance""",
            (RUN_ID, sym, "stop_brief", stop_status, what_changed[:500], why[:500],
             conf, needs_steph,
             f"Stop {stop_status}" if needs_steph else None,
             json.dumps(provenance))
        )
        if ok:
            stats["fresh"] += 1
        else:
            stats["failed"] += 1

        # ── SAME-RUN Steph escalation for triggered/danger/price_unavailable ──
        if needs_steph:
            esc_ok = _db_write(
                """INSERT INTO aegis_steph_escalations
                   (run_id, symbol, category, reason, evidence_summary, unresolved_question,
                    confidence, provenance)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (run_id, symbol, category) DO NOTHING""",
                (RUN_ID, sym, "stop_review",
                 what_changed[:200],
                 f"Stop ${stop_price:.2f}, price ${price:.2f} ({price_source}), value ${total_mv:,.0f}",
                 f"Is {sym} stop still valid? Should John hold, exit, or adjust the stop?",
                 conf,
                 json.dumps({"agent": AGENT, "source": "aegis:stop-coverage-escalation",
                             "stop_status": stop_status, "priority": priority}))
            )
            if esc_ok:
                stats["steph_escalated"] += 1
                print(f"  [stop-coverage] → Steph escalation created for {sym} ({stop_status})")

    coverage_pct = round(stats["fresh"] / max(stats["total"], 1) * 100, 1)
    print(f"  [stop-coverage] Complete: {stats['fresh']}/{stats['total']} covered ({coverage_pct}%)")
    print(f"  [stop-coverage] Triggered:{stats['triggered']} Danger:{stats['danger']} Warning:{stats['warning']} Intact:{stats['intact']} Failed:{stats['failed']} Escalated:{stats['steph_escalated']}")

    _db_write(
        """INSERT INTO aegis_portfolio_briefs
           (run_id, symbol, brief_type, thesis_status, what_changed, confidence, provenance)
           VALUES (%s,%s,%s,%s,%s,%s,%s)
           ON CONFLICT (run_id, symbol, brief_type) DO UPDATE SET
            what_changed=EXCLUDED.what_changed, confidence=EXCLUDED.confidence""",
        (RUN_ID, "COVERAGE", "stop_coverage_summary", "complete" if stats["failed"] == 0 else "partial",
         json.dumps(stats), coverage_pct / 100,
         json.dumps({"agent": AGENT, "source": "aegis:stop-coverage-summary"}))
    )

    return stats


def main():
    print(f"[aegis-synthesis] Starting — {RUN_ID}")

    from aegis_nightly_ingestion import resolve_universe
    universe = resolve_universe()
    symbols = [u["symbol"] for u in universe]
    print(f"  Universe: {len(symbols)} symbols")

    # D1: Per-symbol briefs (top 15 by priority to stay within LLM budget)
    priority = sorted(symbols, key=lambda s: (
        0 if any("recovery" in u["reasons"] for u in universe if u["symbol"] == s) else
        1 if any("watchlist" in u["reasons"] for u in universe if u["symbol"] == s) else 2
    ))[:15]
    briefs = synthesize_symbol_briefs(priority)
    print(f"  Symbol briefs: {briefs}")

    # D2: Covered-call candidates (v2 with thesis/catalyst context)
    cc = evaluate_covered_calls()
    print(f"  Covered-call candidates: {cc}")

    # D3: Rotation alternatives
    rot = evaluate_rotation_alternatives()
    print(f"  Rotation alternatives: {rot}")

    # D4: Portfolio summary
    generate_portfolio_summary()
    print(f"  Portfolio summary: written")

    # D5: Steph escalation reasoning
    esc = generate_steph_escalations()
    print(f"  Steph escalations: {esc}")

    # D6: Full stop-coverage briefs for every stop-protected position
    # Runs BEFORE Steph reviews so same-run escalations get picked up
    stop_stats = generate_stop_coverage_briefs()
    print(f"  Stop coverage: {stop_stats.get('fresh', 0)}/{stop_stats.get('total', 0)}")

    # D5b: Automatic Steph review generation — processes ALL pending escalations
    # including same-run escalations created by stop coverage above
    steph_reviewed = auto_generate_steph_reviews()
    print(f"  Steph auto-reviews: {steph_reviewed}")

    # Tier 2C: Evidence ledger + bias check
    ev_count = build_evidence_ledger(priority)
    print(f"  Evidence ledger: {ev_count} entries")

    print(f"[aegis-synthesis] Complete — {datetime.now().isoformat()}")
    return {"briefs": briefs, "covered_calls": cc, "rotations": rot, "steph_escalations": esc,
            "steph_reviews": steph_reviewed, "stop_coverage": stop_stats,
            "evidence_entries": ev_count, "run_id": RUN_ID}


if __name__ == "__main__":
    main()
