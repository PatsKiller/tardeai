# WAVE E — Catalyst pipeline (E1→E5) · 2026-08-31

**Authority:** `READ_ONLY_ADVISORY` · behaviour rail = unconditional raise · MBI=0  
**Branch:** `fix/overnight-wave-e-catalyst-pipeline`  
**No deploy. No cron install. Identity guard unchanged.**

Order is load-bearing: filter before register. Registration before filtering
mints junk into the registry permanently.

---

## E1 — Filter research-directive slugs at ingestion `[VERIFIED]`

**Finding.** `topic_ingestion.py` writes `topic_id` into `news_articles.symbol`.
`news_to_catalyst.py` then minted those ids into `catalyst_events`, so identity
bind saw themes as tickers.

Top offenders in `catalyst_events` (distinct symbol × row count):

| symbol | rows |
|---|---|
| D124_EARNINGS_SEASON_OPTION_TRADING_FRAMEWORK | 1865 |
| D107_ENERGY_TRANSITION_AND_TRADITIONAL_ENERGY | 1228 |
| D98_CONSUMER_DEFENSIVE_AND_STAPLES_STABILITY | 809 |
| SU_INDUSTRY_INSURANCE_BROKERS | 498 |
| AI_DATACENTER_BUILDOUT | 410 |

Sources: `topic_google_news_rss`, `topic_yahoo_search`, `topic_duckduckgo`.

**Fix.**
- `is_research_directive_slug()` — structural: any `_` in the token, plus
  `D\d+_` / `K_` / `SU_(INDUSTRY|SECTOR)_` / `AI_` theme prefixes.
  Listed tickers never contain `_` (`[VERIFIED]` against `symbol_profiles`: 0 rows).
- `news_to_catalyst.py` skips before classify/LLM/insert.
- `catalyst_graph.bind_catalyst` refuses before `lookup_symbol` and counts
  `skipped.research_directive_slug` (never `symbol_not_registered`).

Fresh dry-run over newest 40k catalyst rows
(`[VERIFIED]` 2026-08-31T04:50Z):

```
skipped.research_directive_slug = 9884
skipped.symbol_not_registered   = 10720
skipped.entity_has_no_issuer    = 979
node_count = 9991  trace_count = 18417
```

---

## E2 — Constrain extractor to known ticker universe `[VERIFIED]`

**Finding.** English / benefit acronyms scraped from prose entered the symbol
column: SSDI (181), IRMAA (115), NEED (87), FIND (72), TO (83), ASSET (183).
None are in `symbol_profiles`.

**Fix.**
- DENYLIST extended with those tokens (and adjacent junk: HEALTH, BOND, RATES,
  CASH, TAX, NONE, NULL, TRUE, FALSE).
- `gate_catalyst_symbol()` requires `validate_ticker` → `symbol_profiles` hit.
- Real short English tickers that **are** listed (LIVE, GIFT, EW, ROC, SER, …)
  are **not** denylisted — do not widen a rule to catch them.

`[VERIFIED]` dry-run:

```
--register-symbol SSDI → REFUSED: not in symbol_profiles
gate_catalyst_symbol("NEED") with no profile → refused
is_research_directive_slug("LIVE") → False
```

---

## E3 — Real names, deliberate one-at-a-time `[VERIFIED]`

**Finding.** Prior aggregate `symbol_not_registered=35928` collapses, once
directive slugs and non-profile tokens are separated, to a **propose list of
90** symbols that are in `symbol_profiles` but not in the identity registry.

Brief said "~149". Measured today: **90**. Stated honestly.

**Fix (propose over live mint).**
- `mint_identity_registry.py --propose-catalyst-gap` — read-only propose list.
- `--register-symbol SYM` — verifies against `symbol_profiles`, dry-run default;
  `--apply` required to append. Refuses directive slugs and absent-from-universe
  names. Does **not** widen any matching rule.

`[VERIFIED]` dry-run quotes:

```
PROPOSE catalyst registry gap — 90 symbol(s)
  FTRK      catalyst_rows=50
  SUGP      catalyst_rows=37
  VRXA      catalyst_rows=37
  EW        catalyst_rows=35
  MCY       catalyst_rows=35
  ...

DRY RUN — register-symbol FTRK
  verified against symbol_profiles
  entities_added=1
  nothing written. re-run with --register-symbol SYM --apply.

DRY RUN — register-symbol D124_… → REFUSED: research-directive / topic slug
DRY RUN — register-symbol SSDI  → REFUSED: not in symbol_profiles
```

**No live registry write in this PR.** Operator may mint one-at-a-time later.

Full propose list (90): FTRK SUGP VRXA EW MCY RDCM LIVE SXTC BCG SGHT GIFT MSC
MCB KMRK SER SLM TAYD DRMA QS GGR RELL SMC TOMZ OCS RAND MGA VMAR VCEL RYOJ IMCC
ROC TNL BODI UONE ORLY TGL IMNM PS SWVL WH STRC FRGT YOUL GNTX NWS PARA SKHU PUL
YHC HASI WAFU XBIO JDZG OBX SPCF SGMT GLUE SK PDX NCLD FSPC LAFA TCGX QNME METG
THOR XGN SKHL AIX GUAC AMMO RSKD CUVL NTAL TRUO CPTL JMKE RAMZ NQLT FENC SKYE
BNMC RACC YXT OCAC INM ADIG AUST SLE LGHL.

---

## E4 — Re-measure catalyst family completion from source `[VERIFIED]`

Command:

```bash
python scripts/cio_event_lifecycle_census.py \
  --root /home/johnclaw/trade-ai-releases/portfolio-server/CURRENT
```

Output (`[VERIFIED]` 2026-08-31T04:50:56+00:00):

```
as_of=2026-08-31T04:50:56+00:00  authority=READ_ONLY_ADVISORY  MBI=0
HEADLINE  mean_full_lifecycle=67.16%  weighted_full_lifecycle=2.17%
          accepted_total=39752  processed_total=835  recoverable_total=862

family                              accept    norm persist process    arch   recov   full%   proc%
catalyst_earnings                    39478     585     588     561     534     588    1.49    1.42

drop_reasons: catalyst_graph_skip:symbol_not_registered=35928,
              catalyst_graph_skip:entity_has_no_issuer=2962, …
note: graph_traces=1110 graph_nodes=452 hermes_files=62 skip_total=38890
```

**Honest reading.** The served projection (`catalyst_graph_latest.json`,
generated_at 2026-08-27) still carries the pre-filter skip tally. A fresh
dry-run from `catalyst_events` with E1 in place (E1 section above) reclassifies
~9.9k of those skips as `research_directive_slug` and leaves ~10.7k true
`symbol_not_registered` in the 40k window — of which 90 distinct names are the
genuine registry gap (E3). Family completion **1.49%** is the number from the
served source as-of now; it will move only after a deliberate `--apply` rebuild
(operator-gated; not done here) plus E3 mints.

---

## E5 — Stale catalyst source / served path `[VERIFIED]`

Command:

```bash
python scripts/build_catalyst_graph.py --diagnose-staleness
```

Output (`[VERIFIED]` 2026-08-31T04:50:42+00:00):

```
as_of=2026-08-31T04:50:42+00:00
state_root=/home/johnclaw/trade-ai-releases/persistent-state
graph  exists=True  age_h=82.9  scheduled=False
       path=…/persistent-state/data/cio/catalyst_graph_latest.json
       build_catalyst_graph.py is NOT in crontab.
momentum_jsonl  files=62  latest=2026-08-26_catalysts.jsonl  age_h=110.3
       path=…/persistent-state/data/hermes/momentum_catalysts
       CURRENT/data/hermes is NOT symlinked to persistent-state;
       writer uses checkout data/hermes — fix is resolution layer, not cron cwd.
```

| writer | scheduled? | write target | reaches served? |
|---|---|---|---|
| `build_catalyst_graph.py` | **No** | `production_state_root` / `data/cio/…` | Path correct; **not run** → 83h stale |
| `news_to_catalyst.py` | Yes | Postgres `catalyst_events` | Yes (DB) |
| `catalyst_momentum_engine.py` | Yes | DB + now served last-run marker | Engine yes; see note |
| `hermes_momentum_catalyst_researcher.py` | Yes (scalp) | **checkout** `data/hermes/…` | **No** — CURRENT/hermes not linked; persistent copy stopped 2026-08-26 |

**Code fixes at resolution layer (no cron install):**
- `build_catalyst_graph.projection_path` / `momentum_catalysts_dir` / diagnose
  already bind to `production_state_root`.
- `catalyst_momentum_engine` kill-switch and `catalyst_momentum_last_run.json`
  resolve via served state root (`data/cio` is symlinked under CURRENT).
- Hermès jsonl writer remaining checkout-relative is documented; changing that
  file is outside this FILE SET — follow-up is to point it at
  `production_state_root()/data/hermes/momentum_catalysts` (same class of fix,
  not a cron cwd patch).

---

## Rails checklist

| rail | status |
|---|---|
| AGENTS.md | obeyed |
| MBI=0 / BehaviorWriteRefused | untouched |
| Identity guard (refuse unrecognized) | **kept exactly** |
| No cron install | yes |
| No secrets | yes |
| No PR #736 | n/a |
| No widen rules for real names | yes — propose list only |
| Store writes dry-run default | yes — no live mint, no graph `--apply` |

---

## FILE SET touched

- `scripts/lib/hermes_discovery/symbol_validation.py`
- `scripts/news_to_catalyst.py`
- `scripts/lib/catalyst_graph.py`
- `scripts/build_catalyst_graph.py`
- `scripts/catalyst_momentum_engine.py`
- `scripts/mint_identity_registry.py` (E3 deliberate register helper)
- `tests/test_overnight_wave_e_catalyst.py` + CI allowlist
- `docs/audits/overnight/WAVE_E_CATALYST_2026-08-31.md`
