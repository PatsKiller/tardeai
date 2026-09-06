# Document mentions, subject vs. passing reference, and LLM escalation

**Status:** design, approved 2026-09-06 · **Authority:** READ_ONLY_ADVISORY · **Financial action:** none

---

## 1. The problem, measured

Identity tagging today is **one tag per row**, taken from the row's `symbol` column. It never
reads the body. Measured over 60 recently tagged news articles:

| | |
|---|---|
| mention **other** tickers in the body | **58%** |
| additional issuers, currently untagged | **64** |

```
tagged=AAPL  body also mentions MS, NDAQ   "Morgan Stanley estimates Apple foldable iPhone…"
tagged=JEPI  body also mentions IOR        "How JPMorgan Equity Premium Income ETF (JEPI)…"
```

And most content stores carry no identity at all:

| store | rows | tagged |
|---|---|---|
| `hermes_research_intelligence` | 33,298 | 16,594 |
| `news_articles` | 113,153 | 27,263 |
| `catalyst_events` | 135,988 | **0 — no column** |
| `analyst_consensus_history` | 130,814 | **0 — no column** |
| `agent_recommendation_registry` | 454,058 | 0 |
| `fused_signals` | 747,910 | 0 |
| `hermes_score_history` | 166,777 | 0 |
| `content_embeddings` | 843,108 | 0 |

## 2. The insight that shapes the design

Look again at the Apple headline. It mentions `MS` and `NDAQ`, but the article is **about Apple** —
Morgan Stanley is the *source of the estimate*, not the subject.

**Extraction is deterministic. Deciding which mention is the SUBJECT is judgment.**

Tagging all three as equal subjects would attach the article to issuers it is not about, and every
downstream join inherits the error. That is the same wrong-issuer failure the identity work exists
to prevent — a wrong tag is worse than no tag, because it looks like coverage.

So the design splits on exactly that line.

## 3. Schema — `document_mentions`

One row per **(document, issuer, role)**. Additive; no existing column changes meaning.

```sql
CREATE TABLE document_mentions (
    id              BIGSERIAL PRIMARY KEY,
    observed_at     TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- what document, in which store
    source_table    TEXT NOT NULL,      -- 'news_articles', 'catalyst_events', …
    source_id       BIGINT NOT NULL,

    -- who
    symbol          TEXT,
    subject_guid    UUID,
    issuer_guid     UUID,
    identity_status TEXT,               -- CONFIRMED | CANDIDATE | UNRESOLVED

    -- SUBJECT vs MENTIONED. The whole point of the table.
    role            TEXT NOT NULL CHECK (role IN ('subject','mentioned','unresolved')),
    role_source     TEXT NOT NULL CHECK (role_source IN ('deterministic','model','operator')),
    role_confidence NUMERIC,            -- NULL when deterministic

    matched_via     TEXT,               -- 'ticker' | 'company_name'
    matched_text    TEXT,               -- the document's own words
    UNIQUE (source_table, source_id, issuer_guid, role)
);
```

`role_source` is mandatory. Without it, a model's guess and a deterministic fact are
indistinguishable a month later, and nobody can re-audit the model's output separately.

## 4. Pipeline — deterministic first, model only on the residual

```
document text
   │
   ├─► [1] DETERMINISTIC extraction        lib/inbound_identity_tagger
   │       $TICKER, bare tickers, company names via the broker feed
   │       → every mention, with subject_guid / issuer_guid
   │
   ├─► [2] DETERMINISTIC role, where it is unambiguous
   │       · exactly one mention          → role='subject'
   │       · mention == the row's own symbol column → role='subject'
   │       · everything else              → role='mentioned'
   │
   └─► [3] MODEL, only when [2] cannot decide
           · two or more candidate subjects
           · a reference with no ticker and no name ("the payments company")
           → writes role_source='model', role_confidence, NEVER role='subject'
             above CONFIRMED evidence
```

**Step 3 runs on the residual only.** On the sample above, step 2 resolves the majority: most
documents have one mention, or a mention matching their own `symbol`.

### What the model may and may not do

| may | may not |
|---|---|
| rank subject vs. mentioned | mint a GUID |
| resolve "the iPhone maker" → CANDIDATE | promote CANDIDATE → CONFIRMED |
| explain its choice | overwrite a deterministic role |

Only a deterministic identifier promotes to `CONFIRMED` — the registry's one-way rank already
enforces this and is not modified.

## 5. LLM lane escalation — free, then paid, then **ask before paying more**

Operator-set, 2026-09-06:

```
  1. FREE OAUTH LANES          grok  →  chatgpt
        │  all failed
        ▼
  2. DEEPSEEK FLASH            the one paid lane that may be entered automatically
        │  failed
        ▼
  3. NOTIFY THE OPERATOR       Telegram, and STOP.
        │  operator approves
        ▼
  4. any further paid API      never automatic
```

**Step 3 is a hard stop, not a warning.** The batch yields nothing and waits. Silently walking up
a cost ladder is how a research backlog becomes a bill nobody authorised, and this system already
has a daily provider spend cap for the same reason.

Escalation is per-run, not per-call: one notification for a batch, not one per document.

Implementation notes:

- extends `lib/llm_fallback`, which already has `FREE_CHAIN = ("grok","chatgpt")`,
  `PAID_CHAIN = ("deepseek-flash",)`, `NEVER_CHAIN = {local, gemma, ollama}`
- `NEVER_CHAIN` is unchanged: local models never make judgment calls
- the consumption gate (`process_id=`) is passed on every attempt, so a fallback cannot become a
  way around the spend cap
- the notification must **bypass the router** — an escalation prompt suppressed into a digest is
  the failure already recorded for approval requests

## 6. Order of work

1. `document_mentions` + the deterministic extractor over `news_articles`
   — the store with a measured 58% gap and identity columns already present
2. `catalyst_events` (135,988) — the lifecycle spine; see issue #896
3. `analyst_consensus_history` (130,814)
4. the model residual pass, behind the escalation policy above
5. `content_embeddings` (843,108) last — largest, lowest marginal value per row

## 7. How this gets verified

Same standard as the rest of this subsystem — measured, not asserted:

- extraction: a fixture set of real articles with hand-checked expected mentions
- **role**: the Apple case is the canonical test — `AAPL` must be `subject`, `MS` must be
  `mentioned`, and a test fails if `MS` is ever `subject`
- escalation: a firing test that the operator is notified **before** a second paid lane is
  entered, and that the run stops rather than proceeding
- coverage: reported as a number that can only improve, like `alarm_firing_baseline.txt`
