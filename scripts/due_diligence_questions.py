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

    1. deepseek-flash   paid, ~$0.000133/call, governed by the bridge caps
    2. free OAuth          grok / chatgpt
    3. deepseek-flash     paid, stronger, still under the same caps
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

GOVERNED BRIDGE (n8n path, 2026-10-15, llm lane batch 3)
--------------------------------------------------------
With TRADEAI_LLM_VIA_BRIDGE=1 (bound by the n8n run executor from the allowlist ``llm_route`` of lane
due-diligence-questions, process SET due_diligence_questions + hermes_external_research) the curation ladder above is
replaced by ONE governed-bridge request as process ``due_diligence_questions``: the bridge walks grok -> chatgpt ->
DeepSeek itself (operator D10), so this module neither picks a lane nor reaches the researcher's provider clients, and
there is no operator-escalation step (a refusal is "model call failed" for that change: no narrative, no questions).
--route asks the researcher ONCE per question (first ranked lane as the label); the child inherits the binding and
calls only the bridge as process hermes_external_research. Grounding is enforced exactly as on the cron path.
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
#: Registry lane id (config/lane_registry.json). The lane receipt is keyed by it:
#: data/runtime/<LANE_ID>_last.json, the output_signal the allowlist declares.
LANE_ID = "due-diligence-questions"

MAX_CHANGES = int(os.getenv("DDQ_MAX_CHANGES", "5"))
MAX_ROUTED = int(os.getenv("DDQ_MAX_ROUTED", "2"))
DOSSIER_NEWS = int(os.getenv("DDQ_DOSSIER_NEWS", "12"))
#: How far past the curated cap one run may look for changes it can actually reason about.
#:
#: The pending queue is ordered by magnitude, and a change whose subject has NOTHING linked can never be
#: reasoned about: the loop skips it, ``questioned_at`` stays NULL, and the next run fetches it again. Five
#: such rows at the head of the queue therefore starved everything behind them — measured 2026-11-07:
#: 1,426 pending changes, the highest-ranked change WITH evidence at rank 6, and the lane had written no
#: question since the cutover while its receipt read ``ok / nothing_due``. The cap counts changes CURATED;
#: the window bounds how many rows a run may examine to find them.
SCAN_MULTIPLIER = int(os.getenv("DDQ_SCAN_MULTIPLIER", "20"))
SCAN_MAX = int(os.getenv("DDQ_SCAN_MAX", "500"))

#: SubjectStateNarrative@v1 and DueDiligenceQuestion@v1 are written and read within
#: this module — the narrative is cited by the questions, and route() reads back
#: unrouted questions on a later run. What has NO consumer yet is the answer side:
#: nothing reads a question's answer_ids to supersede it, and nothing surfaces open
#: questions to the operator. Those are the remaining pieces of the lifecycle
#: (EXPIRED / SUPERSEDED / RETIRED in
#: docs/architecture/MATERIAL_CHANGE_TO_QUESTIONS.md). Declared rather than left
#: dark: an undeclared contract is indistinguishable from one whose caller was
#: forgotten, which is the defect check_dark_contracts exists to catch.
# The answer side is reconciled by reconcile_answers in this owner.
NO_CONSUMER_REASON = "open-question digest remains a presentation consumer"

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
ALTER TABLE due_diligence_questions ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ;
ALTER TABLE due_diligence_questions ADD COLUMN IF NOT EXISTS lifecycle_checked_at TIMESTAMPTZ;
ALTER TABLE due_diligence_questions ADD COLUMN IF NOT EXISTS lifecycle_events JSONB NOT NULL DEFAULT '[]';
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


#: Two ways a document is linked to a subject, and NEITHER is sufficient alone.
#:
#: news_articles.subject_guid is ONE column. Measured 2026-09-07: 5,079 articles
#: mention more than one security, and 11,602 mentions cannot fit in that column —
#: invisible to any dossier that joins on it. An article about Morgan Stanley that
#: discusses Apple is Apple evidence, and the column can only say one of those.
#:
#: document_mentions holds them all, with a role. But it is a TEXT EXTRACTION and is
#: narrower: for AAPL the column yields 422 articles and mentions yields 106. Swapping
#: one for the other would trade a coverage gap for a bigger one.
#:
#: So: UNION. And carry the role, because they are not equal evidence — an article
#: ABOUT a company outranks one that cites it in passing, and the model should be able
#: to tell.
DOSSIER_SQL = {
    "news": """
        SELECT n.id, n.published_at::date, left(coalesce(n.title,''),150), m.role
          FROM news_articles n
          LEFT JOIN LATERAL (
              SELECT role FROM document_mentions d
               WHERE d.source_table='news_articles' AND d.source_id=n.id
                 AND d.subject_guid=%(sg)s ORDER BY (role='subject') DESC LIMIT 1
          ) m ON true
         WHERE n.title IS NOT NULL
           AND (n.subject_guid=%(sg)s OR m.role IS NOT NULL)
         ORDER BY (m.role='subject') DESC NULLS LAST, n.published_at DESC NULLS LAST
         LIMIT %(lim)s""",
    "catalyst": """
        SELECT c.id, c.published_at::date, c.catalyst_type,
               left(coalesce(c.headline,''),150), m.role
          FROM catalyst_events c
          LEFT JOIN LATERAL (
              SELECT role FROM document_mentions d
               WHERE d.source_table='catalyst_events' AND d.source_id=c.id
                 AND d.subject_guid=%(sg)s ORDER BY (role='subject') DESC LIMIT 1
          ) m ON true
         WHERE (c.subject_guid=%(sg)s OR m.role IS NOT NULL)
         ORDER BY (m.role='subject') DESC NULLS LAST, c.published_at DESC NULLS LAST
         LIMIT 10""",
}


def dossier(cur, subject_guid) -> list[dict]:
    """Everything we hold on one subject, ranked, each item citable.

    Prior research is ordered by usefulness_score, not recency: recency reliably
    surfaces the most recent noise, usefulness surfaces the work that turned out to be
    worth having. That ordering is why the backfill mattered.

    Articles and catalysts come from BOTH the subject_guid column and
    document_mentions — see DOSSIER_SQL. Items where this subject is merely
    `mentioned` are labelled, so a passing citation is not read as company news.
    """
    items: list[dict] = []
    args = {"sg": subject_guid, "lim": DOSSIER_NEWS}

    cur.execute(DOSSIER_SQL["news"], args)
    for rid, day, title, role in cur.fetchall():
        items.append({"id": f"news:{rid}", "date": str(day), "text": title,
                      "role": role or "subject"})

    cur.execute(DOSSIER_SQL["catalyst"], {"sg": subject_guid})
    for rid, day, ctype, headline, role in cur.fetchall():
        items.append({"id": f"catalyst:{rid}", "date": str(day),
                      "text": f"[{ctype}] {headline}", "role": role or "subject"})

    cur.execute("""SELECT id, created_at::date, usefulness_score,
                          left(coalesce(question,''),110), left(coalesce(recommendation,''),220)
                     FROM hermes_external_research
                    WHERE subject_guid=%s AND recommendation IS NOT NULL
                    ORDER BY usefulness_score DESC NULLS LAST, created_at DESC LIMIT 8""",
                (subject_guid,))
    for r in cur.fetchall():
        items.append({"id": f"research:{r[0]}", "date": str(r[1]),
                      "usefulness": float(r[2]) if r[2] is not None else None,
                      "text": f"ASKED: {r[3]} | ANSWERED: {r[4]}", "role": "subject"})

    cur.execute("""SELECT id, created_at::date, thesis_type, left(coalesce(headline,''),150)
                     FROM research_insights WHERE subject_guid=%s
                    ORDER BY created_at DESC LIMIT 6""", (subject_guid,))
    items += [{"id": f"insight:{r[0]}", "date": str(r[1]),
               "text": f"[{r[2]}] {r[3]}", "role": "subject"} for r in cur.fetchall()]

    for it in items:
        it["text"] = _INTERNAL_NOISE.sub("[internal]", it["text"] or "")
    return items


#: The SAME evidence set ``dossier`` assembles, asked of a whole window at once. It is used only to ORDER the
#: queue (see ``evidence_subjects``), never to decide that a change has nothing to say: the loop still calls
#: ``dossier()`` on every change it curates, so a prefilter that disagrees with ``dossier`` can leave an
#: attempt on the table but can never make the lane skip work ``dossier`` would have found.
EVIDENCE_SUBJECTS_SQL = """
    SELECT s.sg FROM (SELECT unnest(%s::uuid[]) AS sg) s
     WHERE EXISTS (SELECT 1 FROM news_articles n
                    WHERE n.subject_guid = s.sg AND n.title IS NOT NULL)
        OR EXISTS (SELECT 1 FROM document_mentions d
                    WHERE d.subject_guid = s.sg AND d.source_table = 'news_articles')
        OR EXISTS (SELECT 1 FROM catalyst_events c WHERE c.subject_guid = s.sg)
        OR EXISTS (SELECT 1 FROM document_mentions d
                    WHERE d.subject_guid = s.sg AND d.source_table = 'catalyst_events')
        OR EXISTS (SELECT 1 FROM hermes_external_research r
                    WHERE r.subject_guid = s.sg AND r.recommendation IS NOT NULL)
        OR EXISTS (SELECT 1 FROM research_insights i WHERE i.subject_guid = s.sg)
"""


def evidence_subjects(cur, subject_guids) -> set:
    """The subset of ``subject_guids`` with at least one item ``dossier`` would return.

    One set-based query, not four singleton queries per change: measuring a 100-row window with
    ``dossier()`` alone took 134 s on 2026-11-07, longer than this lane's own cadence. Returns string GUIDs
    so the caller can compare against a row's ``subject_guid`` however the driver hands it back.
    """
    guids = [str(g) for g in subject_guids if g]
    if not guids:
        return set()
    cur.execute(EVIDENCE_SUBJECTS_SQL, (guids,))
    return {str(r[0]) for r in cur.fetchall()}


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
- An item marked "mentions this company in passing" is weaker evidence — the article
  is about someone else. Do not present it as news about this company.
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
CURATION_MODEL = os.getenv("DDQ_CURATION_MODEL", "deepseek-flash")

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
CURATION_MODEL_PRO = os.getenv("DDQ_CURATION_MODEL_PRO", "deepseek-flash")


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


#: The n8n path's curation process + governed-bridge route (advisory_desk / due_diligence_questions).
BRIDGE_PROCESS_ID = "due_diligence_questions"


def via_bridge() -> bool:
    """The flag the n8n run executor binds from the allowlist llm_route; read directly."""
    return os.environ.get("TRADEAI_LLM_VIA_BRIDGE", "off").strip().lower() in {"1", "on", "bridge"}


def _curate_via_bridge(prompt: str) -> dict:
    """ONE governed-bridge request; raises on a refusal (never a provider client, never an escalation)."""
    from lib.llm_bridge_route import require_text_via_bridge

    text = require_text_via_bridge(BRIDGE_PROCESS_ID, prompt, timeout_s=180, max_tokens=1500)
    return {"text": text, "lane": "bridge", "model": "governed-bridge"}


def ask_model(change: dict, items: list[dict]) -> dict:
    """One call, two outputs. Flash first, OAuth as escalation, then STOP.

    Inverted from the house default on purpose — see the module docstring. On the governed-bridge (n8n) path it is
    ONE bridge request instead (see GOVERNED BRIDGE above).
    """
    ev = "\n".join(
        f'  {i["id"]}  ({i["date"]})'
        + (" [mentions this company in passing]" if i.get("role") == "mentioned" else "")
        + (f' [usefulness {i["usefulness"]}]' if i.get("usefulness") is not None else "")
        + f'  {i["text"]}' for i in items)
    desc = (f'{change["symbol"]} {change["kind"]}: observed {change["observed_value"]} '
            f'vs baseline {change["baseline"]} ({change["magnitude"]}x), '
            f'{change["observed_at"]}')
    prompt = PROMPT.format(change=desc, evidence=ev)

    if via_bridge():
        res = _curate_via_bridge(prompt)
        text = (res.get("text") or "").strip()
        if text.startswith("```"):
            text = text.split("```", 2)[1].lstrip("json").strip()
        return {"parsed": json.loads(text), "lane": res["lane"], "model": res["model"]}
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
        _register_question_on_spine(cur, qguid, change)
    return nguid, written


def _register_question_on_spine(cur, qguid: str, change: dict) -> None:
    """Register this question_guid on the subject spine, on the same cursor.

    Same transaction as the question itself, so the question and its edge commit
    together or not at all. The guid is unchanged -- it stays the uuid5 over
    `subject_guid|change_guid|text` this module has always minted; what it gains
    is a row that joins it to the gap and the goal about the same subject.

    The change already carries a resolved `subject_guid`, so nothing is looked
    up and nothing is minted. Fail-safe: a link is never worth losing a question.
    """
    sguid = change.get("subject_guid")
    if not sguid:
        return
    try:
        from scripts.lib.cio_identity_spine import register_on_spine

        register_on_spine("due_diligence_questions", qguid, str(sguid),
                          cur=cur, semantic_subject=change.get("symbol"))
    except Exception:  # noqa: BLE001
        pass


def answer_state(answers: list[dict], *, expires_at=None, now=None) -> dict:
    """Evidence-grounded completion; no response, success code or age implies an answer."""
    from datetime import datetime, timezone
    now = now or datetime.now(timezone.utc)
    ids, accepted = [], []
    for answer in answers:
        if answer.get("id") is not None:
            ids.append(f"hermes_external_research:{answer['id']}")
        if answer.get("status") == "sent" and str(answer.get("recommendation") or "").strip():
            accepted.append(answer)
    for answer in accepted:
        evidence = answer.get("evidence_json") or []
        if isinstance(evidence, str):
            try:
                evidence = json.loads(evidence)
            except ValueError:
                evidence = []
        rows = evidence if isinstance(evidence, list) else [evidence]
        if any(isinstance(e, dict) and any(e.get(k) for k in ("url", "source_id", "evidence_id", "source_ref")) for e in rows):
            return {"status": "ANSWERED", "reason": "accepted_answer_with_cited_evidence", "answer_ids": ids}
    if accepted:
        return {"status": "PARTIALLY_ANSWERED", "reason": "answer_lacks_verifiable_source_references", "answer_ids": ids}
    if expires_at:
        try:
            expiry = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
            if expiry.tzinfo and expiry <= now:
                return {"status": "EXPIRED", "reason": "recorded_deadline_elapsed_without_answer", "answer_ids": ids}
        except ValueError:
            pass
    return {"status": "UNRESOLVED", "reason": "no_accepted_answer", "answer_ids": ids}


def reconcile_answers(cur, *, limit: int = 100, apply: bool = False) -> dict:
    """Join by the originating question id, never by ticker or prose similarity."""
    cur.execute("""SELECT question_guid, status, answer_ids, expires_at
                     FROM due_diligence_questions
                    WHERE status IN ('ASKED','ROUTED','UNRESOLVED','PARTIALLY_ANSWERED')
                    ORDER BY lifecycle_checked_at ASC NULLS FIRST, created_at ASC
                    LIMIT %s""", (limit,))
    questions = cur.fetchall()
    out = {"considered": len(questions), "transitions": [], "applied": apply}
    for qguid, status, old_ids, expires_at in questions:
        if apply:
            cur.execute("UPDATE due_diligence_questions SET lifecycle_checked_at=now() WHERE question_guid=%s", (qguid,))
        cur.execute("""SELECT h.id, h.status, h.recommendation, h.evidence_json
                         FROM hermes_external_research h JOIN due_diligence_questions q
                           ON (h.trigger_reason = 'due_diligence_question:' || q.question_guid::text
                               OR (h.trigger_reason='due_diligence_question'
                                   AND h.subject_guid=q.subject_guid AND h.question=q.question
                                   AND h.created_at >= q.created_at
                                   AND 1=(SELECT count(*) FROM due_diligence_questions q2
                                           WHERE q2.subject_guid=q.subject_guid AND q2.question=q.question)))
                        WHERE q.question_guid=%s AND h.symbol=q.symbol
                          AND (h.subject_guid=q.subject_guid OR h.subject_guid IS NULL)
                        ORDER BY h.created_at, h.id""", (qguid,))
        answers = [dict(zip(("id", "status", "recommendation", "evidence_json"), row)) for row in cur.fetchall()]
        state = answer_state(answers, expires_at=expires_at)
        # Unrouted work retains eligibility. A deadline can explicitly expire it.
        if not answers and status == "ASKED" and state["status"] == "UNRESOLVED":
            continue
        if status == state["status"] and sorted(old_ids or []) == sorted(state["answer_ids"]):
            continue
        event = {"from": status, **state, "question_guid": str(qguid)}
        out["transitions"].append(event)
        if apply:
            cur.execute("""UPDATE due_diligence_questions SET status=%s, answer_ids=%s::jsonb,
                             lifecycle_events=lifecycle_events || jsonb_build_array(%s::jsonb || jsonb_build_object('at', now()))
                            WHERE question_guid=%s AND status=%s""",
                        (state["status"], json.dumps(state["answer_ids"]), json.dumps(event), qguid, status))
    return out


def route(cur, limit: int) -> dict:
    """Send the top unrouted questions out for research.

    hermes_external_researcher is the existing, redaction-hardened request path. It
    is invoked exactly as an operator would, and its answer lands in
    hermes_external_research where usefulness scoring already reaches it — which is
    what makes the loop close on itself.
    """
    cur.execute(
        """SELECT q.question_guid, q.symbol, q.question FROM due_diligence_questions q
            LEFT JOIN material_changes m ON m.change_guid=q.change_guid
            WHERE q.status = 'ASKED' AND q.routed_at IS NULL
              AND (q.expires_at IS NULL OR q.expires_at > now())
              AND NOT EXISTS (SELECT 1 FROM hermes_external_research h
                   WHERE h.trigger_reason='due_diligence_question:' || q.question_guid::text)
            ORDER BY least(100,greatest(0,coalesce(m.magnitude,0))) + extract(epoch FROM now()-q.created_at)/3600 DESC,
                     q.created_at ASC, q.question_guid
            LIMIT %s FOR UPDATE OF q SKIP LOCKED""", (limit,))
    rows = cur.fetchall()
    lanes = rank_research_lanes(cur)
    if via_bridge():
        lanes = lanes[:1]  # the governed bridge chooses the provider: one researcher call per question
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
                   "--question", question, "--symbol", symbol,
                   "--trigger", f"due_diligence_question:{qguid}", "--apply"]
            try:
                r = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True,
                                   timeout=int(os.getenv("DDQ_ROUTE_TIMEOUT", "300")))
                # The researcher exits zero for budget/auth/cache skips too.
                # A stored row closes this attempt; reconciliation reports its real status.
                cur.execute("SELECT id FROM hermes_external_research WHERE trigger_reason=%s ORDER BY id DESC LIMIT 1",
                            (f"due_diligence_question:{qguid}",))
                ok = bool(cur.fetchone())
                if r.returncode == 0 and not ok:
                    break
            except Exception as exc:  # noqa: BLE001
                ok, r = False, type("R", (), {"stderr": type(exc).__name__})()
                # Unknown completion is not permission for another paid attempt.
                cur.execute("""UPDATE due_diligence_questions SET status='UNRESOLVED', routed_at=now(),
                                 lifecycle_events=lifecycle_events || jsonb_build_array(jsonb_build_object(
                                   'at', now(), 'state', 'UNRESOLVED', 'reason', 'route_outcome_unknown'))
                                WHERE question_guid=%s""", (qguid,))
                break
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
                                  trigger_source = 'material_change'
                             FROM due_diligence_questions q
                            WHERE q.question_guid = %s
                              AND h.trigger_reason = 'due_diligence_question:' || q.question_guid::text
                              AND h.symbol = q.symbol
                              AND h.subject_guid IS NULL""", (qguid,))
            out["routed"] += 1
            out.setdefault("used", []).append(f"{symbol}:{used}")
        else:
            # Left ASKED, not marked failed-and-forgotten: an unrouted question is a
            # standing gap and must stay visible to the next run.
            out["failed"] += 1
            out["detail"].append(f"{symbol}: {str(getattr(r, 'stderr', ''))[:120]}")
    return out


def _write_lane_receipt(*, ok: bool = True, exit_code: int = 0, produced_count: int | None = 0,
                        empty_reason: str | None = None, error: str | None = None,
                        started_at: datetime | None = None) -> None:
    """LaneRunReceipt for data/runtime/due-diligence-questions_last.json — a REAL run only.

    The cron twin's ``>> logs/due_diligence_questions.log`` redirect proves only that cron opened a file
    (AGENTS.md §9.3, §0 rail 8), so the registry output_signal is this receipt's ``ok_at`` instead. Never
    called from the ``--dry-run`` branch above: a dry run cannot reach the write (AGENTS.md §6). The helper
    never raises into the caller, so a receipt failure cannot change this run's result or exit code.

    ``ok`` is the RUN's verdict, not "the process reached the end": an escalated stop is a deliberate halt on
    found work, a run whose every model call failed produced nothing for a reason that is not an empty lane, and
    a run where SOME calls failed and nothing was written could not ask what it found. All of them write
    ``ok=False`` so ``ok_at`` stays where the last good run left it and the lane goes stale
    (``lane_last_receipt`` carries ``previous_ok_at`` forward), instead of reporting ``nothing_due`` — a green
    over work the lane saw and did not do.
    """
    try:
        from lib.lane_last_receipt import write_lane_receipt
    except ImportError:  # imported from the repo root rather than with scripts/ on sys.path
        from scripts.lib.lane_last_receipt import write_lane_receipt
    write_lane_receipt(LANE_ID, ok=ok, exit_code=exit_code, started_at=started_at,
                       script="due_diligence_questions.py", produced_count=produced_count,
                       empty_reason=empty_reason, error=error)


def main(argv=None) -> int:
    started = datetime.now(timezone.utc)
    ap = argparse.ArgumentParser(allow_abbrev=False)
    ap.add_argument("--dry-run", action="store_true", help="offline plan; takes precedence over --apply/--route")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--route", action="store_true",
                    help="also send the top questions out for research")
    ap.add_argument("--limit", type=int, default=MAX_CHANGES)
    args = ap.parse_args(argv)
    if args.dry_run:
        window = max(args.limit, min(args.limit * SCAN_MULTIPLIER, SCAN_MAX))
        print(f"DRY-RUN due-diligence-questions: would curate up to {args.limit} changes out of a scan window "
              f"of up to {window} route={args.route}; no lock, DB, schema, researcher, model or writes")
        return 0

    try:
        return _apply_run(args, started)
    except Exception as exc:  # noqa: BLE001 -- a crash still has to say so in the receipt
        # Without this the previous run's ok_at stands and a crashing lane reads fresh until the freshness
        # window expires. The receipt carries previous_ok_at forward, so this makes the lane go stale now.
        _write_lane_receipt(ok=False, exit_code=1, produced_count=None, empty_reason=None,
                            error=type(exc).__name__, started_at=started)
        raise


def _apply_run(args, started: datetime) -> int:
    """The real run. Returns the process exit code; writes the lane receipt on every path that reached the DB."""
    conn = _db()
    cur = conn.cursor()
    # ddl_guard: see scripts/lib/ddl_guard.py — third contender for the same lock.
    from scripts.lib.ddl_guard import apply_ddl
    if args.apply:
        apply_ddl(cur, DDL)
        conn.commit()
    else:
        conn.set_session(readonly=True)
        cur.execute("SELECT to_regclass('due_diligence_questions')")
        if not cur.fetchone()[0]:
            print(json.dumps({"dry_run": True, "schema_required": True, "external_calls": 0, "writes": 0}))
            conn.close()
            return 0

    warn = cap_env_warning()
    if warn:
        print(f"  WARN {warn}", file=sys.stderr)

    # Look past the curated cap for changes this run can actually reason about. The queue is ordered by
    # magnitude, so without this the same dossier-less rows are fetched, skipped and fetched again, and
    # nothing behind them is ever reached (see SCAN_MULTIPLIER). The prefilter ORDERS the queue; it does not
    # decide that a change is uncurateable — dossier() is still called on everything this run takes, and an
    # unlinked row is only ever skipped by that answer. So when the window holds fewer linked changes than
    # the cap, the remaining slots are filled anyway.
    scan_n = max(args.limit, min(args.limit * SCAN_MULTIPLIER, SCAN_MAX))
    changes = pending_changes(cur, scan_n)
    with_evidence = evidence_subjects(cur, [c.get("subject_guid") for c in changes]) if changes else set()
    linked = [c for c in changes if str(c.get("subject_guid")) in with_evidence]
    unlinked = [c for c in changes if str(c.get("subject_guid")) not in with_evidence]
    curated = (linked + unlinked)[:args.limit]
    result = {"schema": SCHEMA_QUESTION, "authority": AUTHORITY,
              "cap_env_warning": warn,
              "changes_pending_window": len(changes), "scan_window": scan_n,
              "scan_truncated": bool(changes) and len(changes) >= scan_n,
              "changes_considered": len(curated), "narratives": 0, "questions": 0,
              "skipped": {"no_dossier": 0},
              "no_dossier_sample": [c.get("symbol") for c in unlinked[:5]],
              "window_without_evidence": len(unlinked),
              "dropped": {}, "lanes": [], "rows_produced": None, "routed": None}
    if not args.apply:
        result.update(dry_run=True, external_calls=0, writes=0)
        conn.close()
        print("RESULT: " + json.dumps(result, default=str))
        return 0
    result["answer_lifecycle"] = reconcile_answers(cur, apply=True)
    conn.commit()
    print(f"{SCHEMA_QUESTION} — apply={args.apply} route={args.route} "
          f"changes={len(curated)} (queue window {len(changes)} of up to {scan_n}, "
          f"{len(unlinked)} without evidence)")
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
        _write_lane_receipt(ok=True, exit_code=0, produced_count=0, empty_reason="nothing_due",
                            started_at=started)
        return 0

    from lib.llm_escalation import EscalationStopped

    total_q = 0
    attempted_calls = 0
    failed_calls = 0
    stopped = False
    for ch in curated:
        items = dossier(cur, ch["subject_guid"])
        if not items:
            # The window said this subject had evidence and dossier() found none. Prefilter and dossier can
            # only disagree at the margin; count it rather than let it leave a silent hole in the receipt.
            result["skipped"]["no_dossier"] += 1
            print(f"  {ch['symbol']}: no dossier — nothing linked in the corpus yet")
            continue
        attempted_calls += 1
        try:
            got = ask_model(ch, items)
        except EscalationStopped as exc:
            # Hard stop. The operator was asked; do not enter a gated paid lane.
            print(f"  ESCALATION STOPPED: {exc}", file=sys.stderr)
            result["outcome"] = "ESCALATION_STOPPED"
            stopped = True
            break
        except Exception as exc:  # noqa: BLE001
            failed_calls += 1
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

    # The run's verdict, not "we got to the end". An escalation stop is a deliberate halt on work it found
    # (asking again next tick would re-spend what the ladder just refused); every call failing is a broken
    # provider route, not an empty lane. Neither may report `nothing_due` or advance ok_at.
    all_failed = attempted_calls > 0 and failed_calls == attempted_calls and total_q == 0
    if stopped:
        _write_lane_receipt(ok=False, exit_code=3, produced_count=total_q, empty_reason=None,
                            error="escalation_stopped", started_at=started)
        return 3
    # The lane HAD work and could reason about none of it: every change it took had nothing linked in the
    # corpus. That is a coverage gap in the evidence, not an empty lane, and `nothing_due` would advance
    # ok_at over it — measured 2026-11-07: five dossier-less rows at the head of the queue hid 1,426 pending
    # changes and the receipt read `ok / nothing_due` on every run.
    if attempted_calls == 0 and result["skipped"]["no_dossier"]:
        _write_lane_receipt(ok=False, exit_code=1, produced_count=0, empty_reason=None,
                            error="no_dossier_evidence", started_at=started)
        return 1
    if all_failed:
        _write_lane_receipt(ok=False, exit_code=1, produced_count=total_q, empty_reason=None,
                            error="all_model_calls_failed", started_at=started)
        return 1
    # A PARTIAL failure is not an empty lane either. A provider that answers some calls and rejects others
    # leaves the desk with nothing written for the calls it could not make; `nothing_due` would say there was
    # nothing to ask about and advance ok_at over work the lane could not do. It is its own error so the
    # operator can tell a degraded route from a broken one.
    if failed_calls > 0 and total_q == 0:
        _write_lane_receipt(ok=False, exit_code=1, produced_count=total_q, empty_reason=None,
                            error="partial_model_call_failure", started_at=started)
        return 1
    _write_lane_receipt(ok=True, exit_code=0, produced_count=total_q,
                        empty_reason=None if total_q else "nothing_due", started_at=started)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
