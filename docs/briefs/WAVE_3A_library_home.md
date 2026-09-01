<!-- Recovered verbatim from the operator's own message in the session
     transcript. Everything below the rule is the brief as sent: not
     summarised, not reordered, not corrected. Provenance header added by
     the rules-install package; it is the only text here that is not the
     operator's. -->

# Wave 3A — institutional library home

**Status:** recovered verbatim
**Source:** session transcript, operator message 011

---

Claude Code — WAVE 3A only: institutional library home + seasonality off fixtures.
Repo PatsKiller/tardeai. Exact-main. CURRENT pin must contain #636.
READ_ONLY_ADVISORY. MBI=0. No notify-on. No ROTATE. No book merge.
No cap raise. No cio_run LLM. No second freshness table.
No second corpus store if cio_research_library / cio_corpus_index exist — extend them.

DO NOT start Wave 3B (notify, council, MBI, ROTATE).

## 0) Pin check
#636 on origin/main and on CURRENT file content (not git log inside CURRENT).
ResearchNeedDecision@v2 present. research_source_index still the freshness law.

## 1) Seasonality out of tests/  (do this first)
Live grade=B numbers must not be sourced from
  tests/fixtures/us_equity_monthly_sample.csv
Move/copy the 901-row 1950→ series to a data path under data/cio/library/
(or the existing library root you find). Tests may symlink or copy.
Add a test that fails if operator seasonality resolve() still points at tests/.
Dry: home.seasonality numbers unchanged after the move (same hash).
Document old path → new path in docs/ops/CIO_LIBRARY_HOME_{date}.md

## 2) Hunt the 20–30 publications (search, do not invent)
Search repo + CURRENT data + any existing KB/RAG/Hermes artifact dirs +
docs for: almanac, Stock Trader's Almanac, seasonality, Yale Hirsch,
Ned Davis, AAII, Ibbotson, Dimson, Siegel, Bogle, Graham, Damodaran,
earnings calendar pubs, cited PDF/md libraries.
Write a census table: title, path or MISSING, bytes, as_of, already in
library_facts? y/n, proposed family, proposed grade A/B/C/D/X.

If Drive has files in TradeAI CIO Ops / other folders, list IDs only.
Do not download the open web. Do not mint 30 stub PDFs.

CORPUS_UNLOCATED stays the honest label until the census is attached.

## 3) Registry (one index)
Extend cio_research_library / cio_corpus_index:
  source_id, family, title, path, content_hash, as_of,
  evidence_grade, application_law, dimension_scope (context|entity),
  freshness via research_source_index.decide() ONLY.
Ingest only files that already exist on disk and hash-stable.
Grade D / C cannot corpus_hit.
Entity-level dimensions still cannot be corpus-closed.
Fired event still overrides SKIP_FRESH.

## 4) Decision wiring
ResearchNeedDecision@v2 corpus_hit only when:
  reproduced A/B + context-level dimension + source_index not stale.
Add 1–2 fixtures using the relocated seasonality file.
No new model calls. Host dry: 445→eligible still in the same ballpark
(collapse remains; do not re-expand S5 into 36 Flash jobs).

## 5) Bounded discover (dry only)
Propose up to 3 NEW candidate sources the census showed MISSING
(title/why/family/suggested grade). Store as CANDIDATE refs. No ingest.
No Telegram.

## 6) Docs + promote
docs/ops/CIO_WAVE3A_LIBRARY_{date}.md
docs/ops/CIO_LIBRARY_CENSUS_{date}.md
Scoreboard row WAVE3A.
One PR or two if seasonality move is cleaner alone.
Exact-main promote. Live: /health /v3/cio 200, telegram_sent false,
cio_run DETERMINISTIC_PRODUCT, cash surfaces still agree.

STOP. Do not start Wave 3B. Do not raise caps. Do not enable notify.
