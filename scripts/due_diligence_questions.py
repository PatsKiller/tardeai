#!/usr/bin/env python3
"""due_diligence_questions.py — read what we already hold, say what it looks like,
and decide what to ask next.

Stages 3-5 of docs/architecture/MATERIAL_CHANGE_TO_QUESTIONS.md. Advisory only:
never sizes, orders, stops, or writes to a broker.

WHY THIS EXISTS
---------------
The 2026-09-06 alert said "AOUT: 64 articles, 70 catalysts; no prior research" — and
then nothing happened. Nothing read the corpus, nothing formed a question, nothing
requested research. Measured the same day: ZERO rows in hermes_external_research had
ever been requested because a name moved. Research is swept on a clock; it has never
been driven by a change.

This is the piece that closes it:

    MaterialChange -> dossier (ranked by usefulness) -> ONE model call
      -> narrative + questions -> research request -> answer -> usefulness
      -> re-ranks the next dossier

The last arrow is the only part that compounds.

ONE MODEL CALL, TWO OUTPUTS
---------------------------
The narrative and the questions come from a single call, not two. They are the same
act of reading; splitting them doubles the spend and lets the question drift from the
description it is supposed to follow from.

CURATION LANE ORDER (operator-set 2026-09-06)
---------------------------------------------

    1. deepseek-v4-flash   paid, ~$0.000133/call, governed by the bridge caps
    2. free OAuth          grok / chatgpt
    3. deepseek-v4-pro     paid, stronger, still under the same caps
    4. ASK THE OPERATOR    hard STOP before any further paid API

This inverts the house default (free first) on purpose. Curation is a structured task
— read a bounded dossier, emit strict JSON whose citations this code parses and
enforces. Consistency matters more than being free, and flash answers the same way
every time for a fraction of a cent. The OAuth lanes are free but rate-limited and
variable: fine for prose, poor for a parsed contract. They remain step 2, so nothing
is lost when flash is capped or unavailable.

Step 4 is a hard STOP, not a preference, and a failed notification is never treated
as permission to spend.

This inversion applies to CURATION ONLY. The research that follows goes out through
the normal research lanes and the free web providers; nothing here changes that.

GROUNDING IS ENFORCED, NOT REQUESTED
------------------------------------
Every sentence and every question must cite a dossier item id. Uncited output is
DROPPED here, in code — not merely discouraged in the prompt. A model instructed not
to invent will still occasionally invent, and this system has paid for that before.

    python3 scripts/due_diligence_questions.py                 # dry run
    python3 scripts/due_diligence_questions.py --apply
    python3 scripts/due_diligence_questions.py --apply --route  # + request research
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

SCHEMA_NARRATIVE = "SubjectStateNarrative@v1"
SCHEMA_QUESTION = "DueDiligenceQuestion@v1"
AUTHORITY = "READ_ONLY_ADVISORY"

MAX_CHANGES = int(os.getenv("DDQ_MAX_CHANGES", "5"))
MAX_ROUTED = int(os.getenv("DDQ_MAX_ROUTED", "2"))
DOSSIER_NEWS = int(os.getenv("DDQ_DOSSIER_NEWS", "12"))

#: SubjectStateNarrative@v1 and DueDiligenceQuestion@v1 are written and read within
#: this module — the narrative is cited by the questions, and route() reads back
#: unrouted questions on a later run. What has NO consumer yet is the answer side:
#: nothing reads a question's answer_ids to supersede it, and nothing surfaces open
#: questions to the operator. Those are the remaining pieces of the lifecycle
#: (EXPIRED / SUPERSEDED / RETIRED in
#: docs/architecture/MATERIAL_CHANGE_TO_QUESTIONS.md). Declared rather than left
#: dark: an undeclared contract is indistinguishable from one whose caller was
#: forgotten, which is the defect check_dark_contracts exists to catch.
NO_CONSUMER_REASON = (
    "questions and narratives are read within this module (citation + routing "
    "backlog); the answer-side consumers — supersede-on-answer and the open-question "
    "digest — are the unbuilt tail of the lifecycle"
)

DDL = """
CREATE TABLE IF NOT EXISTS subject_state_narratives (
    id             BIGSERIAL PRIMARY KEY,
    narrative_guid UUID UNIQUE NOT NULL,
    subject_guid   UUID,
    issuer_guid    UUID,
    change_guid    UUID,
    symbol         TEXT NOT NULL,
    sentences      JSONB NOT NULL,
    cited_ids      JSONB NOT NULL,
    dossier_size   INTEGER,
    lane           TEXT,
    model          TEXT,
    schema_version TEXT NOT NULL,
    authority      TEXT NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS due_diligence_questions (
    id                  BIGSERIAL PRIMARY KEY,
    question_guid       UUID UNIQUE NOT NULL,
    subject_guid        UUID,
    issuer_guid         UUID,
    change_guid         UUID,
    narrative_guid      UUID,
    supersedes_guid     UUID,
    symbol              TEXT NOT NULL,
    question            TEXT NOT NULL,
    why_now             TEXT,
    what_would_settle_it TEXT,
    cited_ids           JSONB NOT NULL,
    status              TEXT NOT NULL DEFAULT 'ASKED',
    routed_at           TIMESTAMPTZ,
    answer_ids          JSONB,
    lane                TEXT,
    model               TEXT,
    schema_version      TEXT NOT NULL,
    authority           TEXT NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ddq_subject_idx ON due_diligence_questions (subject_guid);
CREATE INDEX IF NOT EXISTS ddq_status_idx ON due_diligence_questions (status);
ALTER TABLE material_changes ADD COLUMN IF NOT EXISTS questioned_at TIMESTAMPTZ;
"""

#: Prior research talks about OUR conviction, watchlist rank and composite score.
#: The prototype duly asked "what would move the internal composite score higher?" —
#: grounded, well-formed, and about this system rather than about the company. Those
#: lines are stripped from the dossier so the model cannot mistake them for subject
#: matter.
_INTERNAL_NOISE = re.compile(
    r"(composite score|watchlist rank|internal rank|conviction level|hermes_rank"
    r"|rank #?\d+|scored by|usefulness)", re.I)


def _db():
    import psycopg2

    for line in (ROOT / ".env").read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())
    return psycopg2.connect(
        host=os.getenv("DB_HOST"), port=os.getenv("DB_PORT"), dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"), password=os.getenv("DB_PASSWORD"))


def _guid(namespace: str, value: str) -> str:
    """Same minting as the rest of the spine — a pure function of its inputs."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"tradeai:{namespace}:{value}"))


def question_guid(subject_guid, change_guid, text: str) -> str:
    """Deterministic on (subject, trigger, normalised text).

    Same question, same subject, same trigger -> same id, so it dedupes instead of
    accumulating. Same words after a NEW trigger -> new id, which is correct: "is the
    thesis intact?" after an earnings miss is a different question from last month.
    """
    norm = " ".join(str(text or "").lower().split())
    return _guid("question", f"{subject_guid}|{change_guid}|{norm}")


def pending_changes(cur, limit: int) -> list[dict]:
    cur.execute(
        """SELECT change_guid, subject_guid, issuer_guid, symbol, kind, magnitude,
                  baseline, observed_value, observed_at
             FROM material_changes
            WHERE questioned_at IS NULL AND subject_guid IS NOT NULL
              -- A change the notifier refused to announce must not be reasoned
              -- about either. On the first run this picked JEPI and BND — both
              -- corrupt prices suppressed as UNCORROBORATED — and the model
              -- faithfully wrote "JEPI showed a large price excursion", describing
              -- a fiction because the row said so. The loop inherits the detector's
              -- errors, so it must inherit its rejections too.
              AND coalesce(notify_outcome, '') NOT LIKE 'UNCORROBORATED%%'
            ORDER BY magnitude DESC NULLS LAST LIMIT %s""", (limit,))
    cols = ["change_guid", "subject_guid", "issuer_guid", "symbol", "kind",
            "magnitude", "baseline", "observed_value", "observed_at"]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def dossier(cur, subject_guid) -> list[dict]:
    """Everything we hold on one subject, ranked, each item citable.

    Prior research is ordered by usefulness_score, not recency. Recency reliably
    surfaces the most recent noise; usefulness surfaces the work that turned out to
    be worth having. That ordering is the reason the backfill mattered.
    """
    items: list[dict] = []
    cur.execute("""SELECT id, published_at::date, left(coalesce(title,''),150)
                     FROM news_articles WHERE subject_guid=%s AND title IS NOT NULL
                    ORDER BY published_at DESC NULLS LAST LIMIT %s""",
                (subject_guid, DOSSIER_NEWS))
    items += [{"id": f"news:{r[0]}", "date": str(r[1]), "text": r[2]} for r in cur.fetchall()]

    cur.execute("""SELECT id, published_at::date, catalyst_type,
                          left(coalesce(headline,''),150)
                     FROM catalyst_events WHERE subject_guid=%s
                    ORDER BY published_at DESC NULLS LAST LIMIT 10""", (subject_guid,))
    items += [{"id": f"catalyst:{r[0]}", "date": str(r[1]),
               "text": f"[{r[2]}] {r[3]}"} for r in cur.fetchall()]

    cur.execute("""SELECT id, created_at::date, usefulness_score,
                          left(coalesce(question,''),110), left(coalesce(recommendation,''),220)
                     FROM hermes_external_research
                    WHERE subject_guid=%s AND recommendation IS NOT NULL
                    ORDER BY usefulness_score DESC NULLS LAST, created_at DESC LIMIT 8""",
                (subject_guid,))
    for r in cur.fetchall():
        items.append({"id": f"research:{r[0]}", "date": str(r[1]),
                      "usefulness": float(r[2]) if r[2] is not None else None,
                      "text": f"ASKED: {r[3]} | ANSWERED: {r[4]}"})

    cur.execute("""SELECT id, created_at::date, thesis_type, left(coalesce(headline,''),150)
                     FROM research_insights WHERE subject_guid=%s
                    ORDER BY created_at DESC LIMIT 6""", (subject_guid,))
    items += [{"id": f"insight:{r[0]}", "date": str(r[1]),
               "text": f"[{r[2]}] {r[3]}"} for r in cur.fetchall()]

    # Strip our own scoring chatter — see _INTERNAL_NOISE.
    for it in items:
        it["text"] = _INTERNAL_NOISE.sub("[internal]", it["text"] or "")
    return items


PROMPT = """A tracked company just did something unlike itself. Below is everything
this research system already holds on it.

WHAT CHANGED
{change}

EVIDENCE (each item has an id; you may ONLY cite these ids):
{evidence}

Return ONLY JSON:
{{
  "narrative": [{{"sentence": "one plain sentence describing what this looks like now",
                 "cites": ["news:123"]}}],
  "questions": [{{"question": "the next due-diligence question worth asking",
                 "why_now": "what in the evidence makes this newly worth asking",
                 "what_would_settle_it": "the observation that would answer it either way",
                 "cites": ["catalyst:45"]}}]
}}

RULES:
- Every sentence and question MUST cite at least one id above.
- Never invent a fact, filing, number or date that is not in the evidence.
- Ask about THE COMPANY AND ITS WORLD. Never ask about this system's own scores,
  ranks, conviction levels or watchlist position — those are not due diligence.
- State absence as a fact about THIS EVIDENCE, not about the world.
- Write about the COMPANY, never about this system's detection. Do not mention
  "catalyst_new", "3.0x spike", "baseline", "observed at", or any trigger mechanic —
  the reader does not know what those are and they crowd out the actual news. Say
  what happened to the business or the stock.
- If the evidence supports no new question, return "questions": [].
- Describe and ask. Never recommend, size, or advise trading.
- At most 4 narrative sentences and 4 questions."""


#: Curation model. Cheap, and — more importantly — consistent: this output is parsed
#: and its citations are enforced, so a lane that answers the same way every time is
#: worth $0.000133 a call.
CURATION_MODEL = os.getenv("DDQ_CURATION_MODEL", "deepseek-v4-flash")

#: Research lanes, RANKED BY MEASURED PERFORMANCE — never one hardcoded default.
#:
#: A fixed default is wrong twice over: it goes stale, and it optimises for whoever
#: wrote it. Two failures already came from exactly that. `hermes_external_researcher`
#: shipped with `--lane claude` as its default; claude has been credits_required since
#: 2026-08-01, so the first routed question returned [CREDITS_REQUIRED] — correctly
#: created, correctly stored, answering nothing. Replacing it with `grok` because grok
#: was demonstrably alive then picked the WORST lane by answer quality.
#:
#: Measured 2026-09-06 over 11,116 scored answers and 30 days of delivery:
#:
#:     lane      sent/30d   failures        avg_usefulness
#:     chatgpt      2,384   13 (0.5%)               0.616
#:     grok         2,441   17 (0.7%)               0.470
#:     deepseek       896   2,629 (75% error)           -
#:     claude           0   credits_required        0.618 (n=39, stale)
#:
#: So the order is computed, not declared: recent success rate gates the lane, measured
#: usefulness ranks it. claude is excluded — it has answered nothing since 2026-08-01.
#: Note the capability cache disagrees, calling chatgpt "interactive-only"; that entry
#: was tested 2026-06-07, is three months old, carries retest_recommended=True, and is
#: contradicted by 2,384 delivered answers. Live delivery beats a stale cache.
RESEARCH_LANE_CANDIDATES = tuple(
    x.strip() for x in os.getenv("DDQ_RESEARCH_LANES", "chatgpt,grok,deepseek").split(",")
    if x.strip())
#: Below this recent success rate a lane is not offered, whatever its quality score.
MIN_LANE_SUCCESS = float(os.getenv("DDQ_MIN_LANE_SUCCESS", "0.5"))


def rank_research_lanes(cur) -> list[tuple[str, float, float]]:
    """Available lanes, best first. Returns (lane, success_rate, usefulness).

    Quality is only meaningful among lanes that actually deliver, so success gates
    and usefulness ranks. A lane with no scored history sorts last rather than being
    excluded — unmeasured is not the same as bad.
    """
    cur.execute(
        """SELECT lane,
                  count(*) FILTER (WHERE status='sent')::numeric
                    / nullif(count(*), 0)                       AS success,
                  count(*) FILTER (WHERE status='sent')          AS sent
             FROM hermes_external_research
            WHERE created_at > now() - interval '30 days' AND lane IS NOT NULL
            GROUP BY lane""")
    recent = {r[0]: (float(r[1] or 0), int(r[2] or 0)) for r in cur.fetchall()}
    cur.execute(
        """SELECT lane, avg(usefulness_score) FROM hermes_external_research
            WHERE usefulness_score IS NOT NULL AND lane IS NOT NULL GROUP BY lane""")
    quality = {r[0]: float(r[1] or 0) for r in cur.fetchall()}

    ranked = []
    for lane in RESEARCH_LANE_CANDIDATES:
        success, sent = recent.get(lane, (0.0, 0))
        if sent == 0 or success < MIN_LANE_SUCCESS:
            continue
        ranked.append((lane, success, quality.get(lane, -1.0)))
    ranked.sort(key=lambda x: (-x[2], -x[1]))
    return ranked


#: Step 3. Stronger and dearer than flash; still inside the bridge's four caps, so it
#: cannot run away. Reached only when flash AND both free lanes have failed.
CURATION_MODEL_PRO = os.getenv("DDQ_CURATION_MODEL_PRO", "deepseek-v4-pro")


#: The DeepSeek cap check runs IN THIS PROCESS, not in the bridge.
#:
#: call_governed_deepseek goes through llm_lane.generate -> gate_and_generate, which
#: reads LLM_GLOBAL_DAILY_USD_CAP from the CALLER's environment. The bridge's value is
#: irrelevant on this path. Demonstrated 2026-09-06 — the same call, the same second:
#:
#:     (no env)                          -> COST_CAP_EXCEEDED: global cap
#:     LLM_GLOBAL_DAILY_USD_CAP=7.00     -> OK
#:
#: A cron job inherits nothing, so scheduled curation would refuse EVERY call with a
#: message that reads like a budget problem and is actually a missing variable. Say so
#: once, loudly, instead of failing silently on every change.
def cap_env_warning() -> str | None:
    if os.environ.get("LLM_GLOBAL_DAILY_USD_CAP"):
        return None
    return ("LLM_GLOBAL_DAILY_USD_CAP is unset in THIS process. The DeepSeek cap check "
            "runs here, not in the bridge, so curation will refuse every call with "
            "COST_CAP_EXCEEDED regardless of actual spend. Set it in the environment "
            "or the cron entry.")


def _curate_via_deepseek(prompt: str, model: str) -> dict | None:
    """One governed DeepSeek attempt. None means "try the next lane".

    The bridge applies the four caps and the circuit breaker, so a cap breach
    surfaces as a refusal (429, non-retryable) rather than an outage — it degrades
    the lane, it does not fail the run.
    """
    try:
        sys.path.insert(0, str(ROOT / "scripts"))
        from hermes_external_researcher import call_governed_deepseek

        text = call_governed_deepseek(model, prompt, max_tokens=1500)
        return {"text": text, "lane": model} if text else None
    except Exception as exc:  # noqa: BLE001
        print(f"    curation lane {model} unavailable "
              f"({type(exc).__name__}: {str(exc)[:80]})", file=sys.stderr)
        return None


#: OAuth escalation order. chatgpt BEFORE grok — measured, not assumed.
#:
#: Four-way bake-off on one real dossier (AOUT, 30 items, identical prompt),
#: 2026-09-06. All four returned valid JSON with zero ungrounded citations and zero
#: questions about our own scoring, so the prompt plus code-side enforcement holds
#: across lanes and the escalation is safe. They are not equal on substance:
#:
#:     lane             secs   narrative   questions   citations
#:     deepseek-flash    6.4       4           4          15
#:     deepseek-pro      5.9       4           4          15
#:     chatgpt-oauth    19.1       1           4          15
#:     grok-oauth       28.3       3           2           8
#:
#: DeepSeek is 3-5x faster AND more complete than either free lane, which is why the
#: operator's flash-first order is the right one. Between the two free lanes, grok is
#: the weakest curator on every axis that matters here — slowest, half the citations,
#: half the questions — so chatgpt is tried first.
OAUTH_ORDER = tuple(x.strip() for x in
                    os.getenv("DDQ_OAUTH_ORDER", "chatgpt,grok").split(",") if x.strip())


def _curate_via_oauth(prompt: str) -> dict | None:
    """Step 2: the free lanes, best first. Never reaches a paid lane or the operator
    ask — escalation past OAuth is this module's decision, not llm_fallback's."""
    from hermes_external_researcher import LANE_CFG, call_external

    for lane in OAUTH_ORDER:
        cfg = LANE_CFG.get(lane) or {}
        try:
            text = call_external(lane, cfg.get("model"), prompt, max_tokens=1500)
            if text:
                return {"text": text, "lane": f"{lane}-oauth"}
        except Exception as exc:  # noqa: BLE001
            print(f"    curation OAuth lane {lane} unavailable "
                  f"({type(exc).__name__}: {str(exc)[:70]})", file=sys.stderr)
    return None


def ask_model(change: dict, items: list[dict]) -> dict:
    """One call, two outputs. Flash first, OAuth as escalation, then STOP.

    Inverted from the house default on purpose — see the module docstring.
    """
    ev = "\n".join(
        f'  {i["id"]}  ({i["date"]})'
        + (f' [usefulness {i["usefulness"]}]' if i.get("usefulness") is not None else "")
        + f'  {i["text"]}' for i in items)
    desc = (f'{change["symbol"]} {change["kind"]}: observed {change["observed_value"]} '
            f'vs baseline {change["baseline"]} ({change["magnitude"]}x), '
            f'{change["observed_at"]}')
    prompt = PROMPT.format(change=desc, evidence=ev)

    # 1 flash -> 2 free OAuth -> 3 deepseek pro -> 4 ASK. Each step is tried once;
    # a lane that refuses (cap, circuit breaker, rate limit) is skipped, not retried.
    res = (_curate_via_deepseek(prompt, CURATION_MODEL)
           or _curate_via_oauth(prompt)
           or _curate_via_deepseek(prompt, CURATION_MODEL_PRO))
    if res is None:
        # Step 4. run_with_escalation notifies and raises EscalationStopped, which is
        # the hard stop. It is used ONLY for that: every lane it would try has
        # already been tried above.
        from lib.llm_escalation import run_with_escalation

        res = run_with_escalation(
            prompt, purpose=f"due-diligence curation for {change['symbol']} "
                            f"(flash, OAuth and pro all unavailable)")
    text = (res.get("text") or "").strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1].lstrip("json").strip()
    return {"parsed": json.loads(text), "lane": res.get("lane"),
            "model": res.get("model")}


def ground(parsed: dict, items: list[dict]) -> tuple[list, list, dict]:
    """Drop anything that does not cite real evidence.

    Enforced in code, not merely asked for in the prompt. A model told not to invent
    will still occasionally invent, and an ungrounded question is indistinguishable
    from a real one to the person reading it.
    """
    valid = {i["id"] for i in items}
    stats = {"narrative_dropped": 0, "questions_dropped": 0}
    narrative, questions = [], []
    for n in parsed.get("narrative") or []:
        cites = [c for c in (n.get("cites") or []) if c in valid]
        if not cites:
            stats["narrative_dropped"] += 1
            continue
        narrative.append({"sentence": n.get("sentence"), "cites": cites})
    for q in parsed.get("questions") or []:
        cites = [c for c in (q.get("cites") or []) if c in valid]
        if not cites or not q.get("question"):
            stats["questions_dropped"] += 1
            continue
        questions.append({"question": q["question"], "why_now": q.get("why_now"),
                          "what_would_settle_it": q.get("what_would_settle_it"),
                          "cites": cites})
    return narrative, questions, stats


def persist(cur, change: dict, narrative: list, questions: list, meta: dict,
            dossier_size: int) -> tuple[str, int]:
    nguid = _guid("narrative", f'{change["subject_guid"]}|{change["change_guid"]}')
    cur.execute(
        """INSERT INTO subject_state_narratives
             (narrative_guid, subject_guid, issuer_guid, change_guid, symbol,
              sentences, cited_ids, dossier_size, lane, model, schema_version, authority)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
           ON CONFLICT (narrative_guid) DO NOTHING""",
        (nguid, change["subject_guid"], change["issuer_guid"], change["change_guid"],
         change["symbol"], json.dumps(narrative),
         json.dumps(sorted({c for n in narrative for c in n["cites"]})),
         dossier_size, meta.get("lane"), meta.get("model"), SCHEMA_NARRATIVE, AUTHORITY))

    written = 0
    for q in questions:
        qguid = question_guid(change["subject_guid"], change["change_guid"], q["question"])
        cur.execute(
            """INSERT INTO due_diligence_questions
                 (question_guid, subject_guid, issuer_guid, change_guid, narrative_guid,
                  symbol, question, why_now, what_would_settle_it, cited_ids,
                  status, lane, model, schema_version, authority)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'ASKED',%s,%s,%s,%s)
               ON CONFLICT (question_guid) DO NOTHING""",
            (qguid, change["subject_guid"], change["issuer_guid"], change["change_guid"],
             nguid, change["symbol"], q["question"], q.get("why_now"),
             q.get("what_would_settle_it"), json.dumps(q["cites"]),
             meta.get("lane"), meta.get("model"), SCHEMA_QUESTION, AUTHORITY))
        written += cur.rowcount
    return nguid, written


def route(cur, limit: int) -> dict:
    """Send the top unrouted questions out for research.

    hermes_external_researcher is the existing, redaction-hardened request path. It
    is invoked exactly as an operator would, and its answer lands in
    hermes_external_research where usefulness scoring already reaches it — which is
    what makes the loop close on itself.
    """
    cur.execute(
        """SELECT question_guid, symbol, question FROM due_diligence_questions
            WHERE status = 'ASKED' AND routed_at IS NULL
            ORDER BY created_at DESC LIMIT %s""", (limit,))
    rows = cur.fetchall()
    lanes = rank_research_lanes(cur)
    out = {"routed": 0, "failed": 0, "lanes_ranked": [l[0] for l in lanes], "detail": []}
    if not lanes:
        out["detail"].append("no research lane met the minimum success rate")
        return out
    for qguid, symbol, question in rows:
        # Best lane first, then down the ranking. A lane that fails on THIS question
        # is not evidence the question is unanswerable.
        ok, r, used = False, None, None
        for lane, _success, _quality in lanes:
            cmd = [sys.executable, str(ROOT / "scripts" / "hermes_external_researcher.py"),
                   "--lane", lane,
                   "--question", question, "--symbol", symbol, "--apply"]
            try:
                r = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True,
                                   timeout=int(os.getenv("DDQ_ROUTE_TIMEOUT", "300")))
                ok = r.returncode == 0
            except Exception as exc:  # noqa: BLE001
                ok, r = False, type("R", (), {"stderr": f"{type(exc).__name__}: {exc}"})()
            if ok:
                used = lane
                break
            out["detail"].append(f"{symbol}:{lane} failed")
        if ok:
            cur.execute("""UPDATE due_diligence_questions
                              SET status='ROUTED', routed_at=now()
                            WHERE question_guid=%s""", (qguid,))
            # Carry the spine onto the row the researcher just wrote. Without this
            # the answer is orphaned until the */30 identity sweep happens to catch
            # it by symbol — and an answer that cannot be joined to its subject
            # cannot re-rank the next dossier, which is the only part of this loop
            # that compounds.
            cur.execute("""UPDATE hermes_external_research h
                              SET subject_guid = q.subject_guid,
                                  issuer_guid  = q.issuer_guid,
                                  trigger_source = 'material_change',
                                  trigger_reason = 'due_diligence_question'
                             FROM due_diligence_questions q
                            WHERE q.question_guid = %s
                              AND h.symbol = q.symbol
                              AND h.question = q.question
                              AND h.subject_guid IS NULL""", (qguid,))
            out["routed"] += 1
            out.setdefault("used", []).append(f"{symbol}:{used}")
        else:
            # Left ASKED, not marked failed-and-forgotten: an unrouted question is a
            # standing gap and must stay visible to the next run.
            out["failed"] += 1
            out["detail"].append(f"{symbol}: {str(getattr(r, 'stderr', ''))[:120]}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--route", action="store_true",
                    help="also send the top questions out for research")
    ap.add_argument("--limit", type=int, default=MAX_CHANGES)
    args = ap.parse_args()

    conn = _db()
    cur = conn.cursor()
    cur.execute(DDL)
    conn.commit()

    warn = cap_env_warning()
    if warn:
        print(f"  WARN {warn}", file=sys.stderr)

    changes = pending_changes(cur, args.limit)
    result = {"schema": SCHEMA_QUESTION, "authority": AUTHORITY,
              "cap_env_warning": warn,
              "changes_considered": len(changes), "narratives": 0, "questions": 0,
              "dropped": {}, "lanes": [], "rows_produced": None, "routed": None}
    print(f"{SCHEMA_QUESTION} — apply={args.apply} route={args.route} "
          f"changes={len(changes)}")
    if not changes:
        result["rows_produced"] = 0 if args.apply else None
        # Routing must NOT depend on new changes arriving. An earlier version
        # returned here, so a question generated on one run could never be sent on
        # the next — the backlog was unreachable by design.
        if args.apply and args.route:
            result["routed"] = route(cur, MAX_ROUTED)
            conn.commit()
        conn.close()
        print("RESULT: " + json.dumps(result, default=str))
        return 0

    from lib.llm_escalation import EscalationStopped

    total_q = 0
    for ch in changes:
        items = dossier(cur, ch["subject_guid"])
        if not items:
            print(f"  {ch['symbol']}: no dossier — nothing linked in the corpus yet")
            continue
        try:
            got = ask_model(ch, items)
        except EscalationStopped as exc:
            # Hard stop. The operator was asked; do not enter a gated paid lane.
            print(f"  ESCALATION STOPPED: {exc}", file=sys.stderr)
            result["outcome"] = "ESCALATION_STOPPED"
            break
        except Exception as exc:  # noqa: BLE001
            print(f"  {ch['symbol']}: model call failed "
                  f"({type(exc).__name__}: {str(exc)[:90]})", file=sys.stderr)
            continue

        narrative, questions, dropped = ground(got["parsed"], items)
        for k, v in dropped.items():
            result["dropped"][k] = result["dropped"].get(k, 0) + v
        result["lanes"].append(got.get("lane"))

        print(f"\n  {ch['symbol']} — {ch['kind']} x{ch['magnitude']} "
              f"(dossier {len(items)}, lane {got.get('lane')})")
        for n in narrative:
            print(f"    • {n['sentence']}   [{', '.join(n['cites'])}]")
        for q in questions:
            print(f"    Q: {q['question']}")
            print(f"       why now: {q.get('why_now')}")
            print(f"       settles : {q.get('what_would_settle_it')}")

        if args.apply:
            _, n_written = persist(cur, ch, narrative, questions, got, len(items))
            cur.execute("UPDATE material_changes SET questioned_at=now() "
                        "WHERE change_guid=%s", (ch["change_guid"],))
            conn.commit()
            result["narratives"] += 1
            total_q += n_written
        result["questions"] += len(questions)

    result["rows_produced"] = total_q if args.apply else None
    if args.apply and args.route:
        result["routed"] = route(cur, MAX_ROUTED)
        conn.commit()
    conn.close()
    print("\nRESULT: " + json.dumps(result, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
