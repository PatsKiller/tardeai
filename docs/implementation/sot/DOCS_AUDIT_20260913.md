# One Source of Truth — documentation and governance audit (Phase 8)

```
Status:      ACTIVE
as_of:       2026-09-13T18:30:00-04:00
Measured at: e8a173e7d (origin/main, PR #994 merge) + branch feat/sot-docs-governance-audit / live pin not measured
```

**Operator instruction (verbatim):** *"audit to make sure that all of this is documented and that the
AGENTS.md file is updated with what owns the authoritative sources of data, how they are written, if
there's a secondary/backup resource, and if any agent needs to write a new source they need to get a
grant from the operator for approval and it needs to meet the methodology that you just developed."*

**Method.** For each deliverable of Phases 0–8, find where it is documented (file + heading) or write it.
Every row below is checkable by the grep quoted under it; the greps were run from the repo root on this
branch after the edits (`bash` transcript in the "Evidence" section — output quoted verbatim, cut to 150
columns). `present` = documented on `origin/main` at `e8a173e7d` before this audit; `added` = written by
this audit; `gap` = still not documented, stated as such.

**Commits.** `4882df7ea` = governance (registry v2 + gate + renderer + AGENTS.md §7A/§17 + rendered
`docs/SOURCE_OF_TRUTH.md`). The documentation commit that carries this file, `docs/MASTER_SYSTEM_DOCUMENTATION.md`
§5.7, `docs/HEALTH_AGENT.md` and `docs/GAP_RESOLUTION.md` cannot name its own SHA (a hash cannot live in
the content it hashes — AGENTS.md, document-control block); it is the commit after `4882df7ea` on this
branch, titled `docs(sot): …`. Phase commits are cited from `git log origin/main`.

## Summary

| status | count |
|---|---|
| present (already documented before this audit) | 6 |
| added (documented by this audit) | 10 |
| gap (left open, stated) | 2 |

The two open gaps are not documentation gaps but honest states the documents now state: (1) the five
monitor timers are **declared, not installed** — installation is operator-only and unmeasured here;
(2) the health-decay view has **no market calendar**; only the broker envelope carries a closed-market
window, and only for `quote_price`. Both are written down where a reader will look.

## The table

| # | Deliverable | Where documented (file → heading) | Status | Commit |
|---|---|---|---|---|
| 1a | Served-copy split monitor (`check_served_copy_split.py`, LINKED-only, hourly) | `AGENTS.md` §7A "The rules, enforced" rule 2 · `docs/SOURCE_OF_TRUTH.md` → "Where every served store lives", "Monitors", "Enforcement" · `docs/MASTER_SYSTEM_DOCUMENTATION.md` §5.7 → "Monitors" | present (AGENTS, SOT) · added (MASTER) | `87906632a`, `e08d85eec` · MASTER: docs commit |
| 1b | Phase-1 reconcile archive + tripwire (`archive_tripwire`, `TRIPPED`) | `AGENTS.md` §7A closing paragraph (archive path, receipt, "any reference … trips the split monitor") · `docs/SOURCE_OF_TRUTH.md` → "Enforcement" row for `check_served_copy_split.py` | present | `87906632a` |
| 2a | Registry `config/data_source_authority.json` | `AGENTS.md` §7A opening + "Ownership and the grant" · `docs/SOURCE_OF_TRUTH.md` (rendered, header line names schema) · `docs/MASTER_SYSTEM_DOCUMENTATION.md` §5.7 → "What the registry declares, per domain" | present · added (grant, MASTER) | `87906632a` · `4882df7ea` · docs commit |
| 2b | Gate `check_data_source_authority.py` (+ `UNAPPROVED_SOURCE`, actionable `UNDECLARED_PROVIDER`) | `AGENTS.md` §7A "Ownership and the grant", "Adding or changing a source" · `docs/SOURCE_OF_TRUTH.md` → "Enforcement" · MASTER §5.7 → "The grant", "Gates that bind" | present (gate) · added (grant checks) | `87906632a` · `4882df7ea` |
| 2c | Renderer `render_source_of_truth.py` (AGENTS table + doc are views) | `AGENTS.md` §7A step 5 "Re-render … never by hand" · `docs/SOURCE_OF_TRUTH.md` line 3 "Rendered from … Do not edit by hand" and "Enforcement" row `render_source_of_truth.py --check` · MASTER §5.7 "Gates that bind" | present · added (procedure step, enforcement row; renderer said "§7B", a section that never existed — fixed) | `87906632a` · `4882df7ea` |
| 3 | Retired-providers module + retirement of finnhub/polygon/fmp/newsapi (archived, manifest row) | `AGENTS.md` §7A rule 4 · `docs/SOURCE_OF_TRUTH.md` → "Providers" (status `retired (2026-09-13)` + Approval `retired by operator`), "Approval records" · `archive/ARCHIVE_MANIFEST.json` item `retired_providers_20260913/…/polygon_source.py` · MASTER §5.7 → "Providers and retirements" | present · added (MASTER, approval) | `87906632a` · `4882df7ea` · docs commit |
| 4a | Health decay view `data_source_health_view.py` + `check_data_source_health.py` | `docs/HEALTH_AGENT.md` → "Data-source health decays — the view (2026-09-13)" · `AGENTS.md` §7A rule 6 · `docs/SOURCE_OF_TRUTH.md` → "Enforcement", "Monitors" · MASTER §5.7 | present (AGENTS rule) · **added** (HEALTH_AGENT section, SOT enforcement row) | `bd27aea44` · docs commit · `4882df7ea` |
| 4b | Weekday / closed-market clock | `docs/HEALTH_AGENT.md` → same section, paragraph "The clock": the view has no calendar; envelope `market_closed` + `stale_after_hours_closed` (quote_price only); weekend `[weekend]` convention; weekend decay to `unknown` is by design | **added**, stated as a **gap** in the mechanism (no calendar in the view) | docs commit |
| 5a | Broker envelope (`as_of`, `age_hours`, `source`, `stale`, `gap`) | `AGENTS.md` §7A rule 3 · MASTER §5.7 row `projection` · `docs/SOURCE_OF_TRUTH.md` rule 3 | present · added (MASTER) | `4e47a837c` · docs commit |
| 5b | Projection catalog — **23** projections measured (`len(PROJECTIONS)` = 23, not the 22 the brief said) + dead-desk gaps (`desk_feeds`, `agent_opinion`, `watch_discovery` → `gap.kind=no_producer`) | MASTER §5.7 row `projection` (states 23, measured at `e8a173e7d`) and §24 changelog; catalog descriptions in `scripts/lib/data_broker/catalog.py` | **added** (the count was documented nowhere; the 22 was wrong) | docs commit |
| 6 | Brave spill + registry budgets + `resolve_backup` / `spill_on` | `docs/SOURCE_OF_TRUTH.md` → "Providers" (`brave` `active_paid`; budgets are registry fields `providers.brave.budget`) · `docs/GAP_RESOLUTION.md` vector 3 · MASTER §5.7 → "Providers and retirements" (caps 120/day, 1,500/month; denial reasons; SearXNG → Tavily) | present (partial) · **added** (MASTER: caps, spill, chain) | `b1b2726aa` · docs commit |
| 7 | `account_state` (LIVE / STALE / SERVICE_DOWN / NO_API_MANUAL) + account registry keys in `assets/portfolio_accounts.yaml` | MASTER §5.7 → "Accounts: absent is not zero" · `AGENTS.md` §7A rule 5 (`per_account_state_never_zero`) · `assets/portfolio_accounts.yaml` header comment lines 13–17 document the keys · `docs/SOURCE_OF_TRUTH.md` row `holdings_accounts` | present (registry, yaml comment) · **added** (MASTER) | `023407274` · docs commit |
| 8 | Gap resolver + `docs/GAP_RESOLUTION.md` + `check_gap_resolution.py` | `docs/GAP_RESOLUTION.md` (all sections) · `AGENTS.md` §7A ("Ownership and the grant" methodology bullet names `on_gap`; procedure step 1) · `docs/SOURCE_OF_TRUTH.md` rule 8, "Enforcement" · MASTER §5.7 → "Gap resolution (Phase 7)" (distinguishes it from §5.5's `data_gap_resolver.py`) | present · **corrected** (GAP_RESOLUTION said the registry was owned elsewhere and chains were only proposed — false since `fee3e7737`; §14 header added; correction kept in) · added (MASTER) | `0a5454a85`, `fee3e7737` · docs commit |
| 9 | Five monitor timers + `lane_registry` / `expected_services` declarations | `docs/SOURCE_OF_TRUTH.md` → "Monitors" (rendered from `expected_services.json` units whose `_why` names the campaign, joined to lanes and timer `OnCalendar`) · MASTER §5.7 → "Monitors (declared, operator installs)" · `config/lane_registry.json` lanes `*-audit` · `config/expected_services.json` 5 units | **added** (was declared in config only, documented nowhere) · **gap**: installed state unmeasured, operator-only | `4882df7ea` · docs commit |
| 10 | UNCONSOLIDATED writer ceilings (`config/data_source_authority_baseline.json`) | `AGENTS.md` §7A rule 1 and "Ownership and the grant" · `docs/SOURCE_OF_TRUTH.md` → "Writer ceilings — stores not yet consolidated" (7 stores, counts, targets) and the domain table's writer cell (`UNCONSOLIDATED → target (n writers today)` — previously rendered as "none — dead feed", which was wrong) · MASTER §5.7 row `writer`, §24 "Known remaining gaps" | present (rule) · **added** (ceilings table; writer-cell fix) | `87906632a` · `4882df7ea` |
| 11 | **Governance: the grant** — `approval` on every row, `UNAPPROVED_SOURCE`, §17 item, propose-and-stop procedure | `AGENTS.md` §7A rule 7 + "Ownership and the grant" + procedure · `AGENTS.md` §17 · `AGENTS.md` version history (1.2.0 PROPOSED, MAJOR row 2026-09-13) · `docs/SOURCE_OF_TRUTH.md` rule 9 + "Ownership and the grant" + "Approval records" · MASTER §5.7 → "The grant" · `docs/GAP_RESOLUTION.md` "How to add a vector" step 1 | **added** | `4882df7ea` · docs commit |
| 12 | Adapters (`CLAUDE.md`, `.cursor/rules`, `.github/copilot-instructions.md`) | Each restates only §0 and points at §17 by number ("The list is §17"); §14/§20 require adapters to mirror §0 only → **unchanged by design** | present (no change required) | — |

## Evidence — greps, verbatim

Run from the repo root on this branch. Only the lines that carry the claim are kept; `cut -c1-150`.

### 1 served-copy split monitor + Phase-1 archive/tripwire

```
$ grep -n 'served_copy_split\|served_copy_split_20260913\|archive_tripwire\|TRIPPED' AGENTS.md docs/SOURCE_OF_TRUTH.md docs/MASTER_SYSTEM_DOCUMENTATION.md | cut -c1-160
AGENTS.md:1198:   tree. `check_served_copy_split.py` (hourly, `[PLATFORM_AVAILABILITY]`) alerts the moment they do
AGENTS.md:1314:the archive is `/home/johnclaw/trade-ai-releases/archive/served_copy_split_20260913/` and any
docs/SOURCE_OF_TRUTH.md:138:| `served-copy-split-audit` | `tradeai-served-copy-split.timer` | `*-*-* *:42:00` | `data/runtime/served_copy_split_last_run.json` |
docs/SOURCE_OF_TRUTH.md:158:| `check_served_copy_split.py` | any linked dir resolves to two directories from dev vs served · anything references the reconcile
docs/MASTER_SYSTEM_DOCUMENTATION.md:785:| `served-copy-split-audit` | `tradeai-served-copy-split.timer` | hourly (:42) | `data/runtime/served_copy_split_last_ru

$ grep -c 'served-copy-split' config/lane_registry.json config/expected_services.json
config/lane_registry.json:2
config/expected_services.json:1
```

### 2 registry + gate + renderer

```
$ grep -n 'data_source_authority.json\|check_data_source_authority.py\|render_source_of_truth.py' AGENTS.md | cut -c1-140 | head -8
1171:**`config/data_source_authority.json` is the only place that says which store, which writer,
1173:`scripts/check_data_source_authority.py` enforces it in `ai_local_acceptance` and CI;
1227:- **The registry names the owner.** For every authoritative store, `config/data_source_authority.json`
1241:- **The gate makes an ungranted source fail the build.** `check_data_source_authority.py` reports
1244:  approval record; do not add the host.* `render_source_of_truth.py --check` fails when the rendered
1269:   `scripts/render_source_of_truth.py` in the same PR — never by hand.

$ grep -n 'Rendered from\|render_source_of_truth' docs/SOURCE_OF_TRUTH.md | cut -c1-140
3:**Rendered from `config/data_source_authority.json` by `scripts/render_source_of_truth.py`. Do not edit by hand.**
157:| `render_source_of_truth.py --check` | this document or the `AGENTS.md` §7A table differs from the registry | `ai_local_acceptance`, P

$ grep -n 'data_source_authority\|render_source_of_truth' docs/MASTER_SYSTEM_DOCUMENTATION.md | cut -c1-140 | head -6
720:**Source of record:** `config/data_source_authority.json` (`DataSourceAuthority@v2`) · rendered view
747:`check_data_source_authority.py` fails an ungranted row (`UNAPPROVED_SOURCE`) and tells an agent that
797:`check_data_source_authority.py` · `render_source_of_truth.py --check` · the test files registered in
```

### 3 retired providers

```
$ grep -n 'retired_providers.py\|RETIRED_CALL_SITE' AGENTS.md docs/SOURCE_OF_TRUTH.md docs/MASTER_SYSTEM_DOCUMENTATION.md docs/GAP_RESOLUTION.md | cut -c1-150
AGENTS.md:1205:   `RETIRED_CALL_SITE` fails on any reference outside the secret-hygiene allowlist. Chains consult
AGENTS.md:1206:   `scripts/lib/retired_providers.py` (which reads the registry) and refuse a retired slot up
docs/SOURCE_OF_TRUTH.md:14:5. A retired provider has zero call sites outside scripts/lib/retired_providers.py and the secret-hygiene scanners.
docs/MASTER_SYSTEM_DOCUMENTATION.md:756:`archive/ARCHIVE_MANIFEST.json`), and `RETIRED_CALL_SITE` proves zero call sites outside the

$ grep -n 'finnhub\|polygon\|newsapi' docs/SOURCE_OF_TRUTH.md | grep -c retired
3

$ grep -n 'retired_providers_20260913' archive/ARCHIVE_MANIFEST.json docs/MASTER_SYSTEM_DOCUMENTATION.md | cut -c1-140
archive/ARCHIVE_MANIFEST.json:7:      "path": "archive/retired_providers_20260913/discovery_sources/polygon_source.py",
docs/MASTER_SYSTEM_DOCUMENTATION.md:755:were archived, not deleted (`archive/retired_providers_20260913/`, manifest row in
```

### 4 health decay view + clock + check_data_source_health

```
$ grep -n 'data_source_health_view\|check_data_source_health\|stale_after_hours_closed\|market_closed\|weekend' docs/HEALTH_AGENT.md | cut -c1-150
185:   staleness vs `max_stale_minutes`; weekend = info + `[weekend]` per house convention. When
216:**Fix — a read-side view, one place (`scripts/lib/data_source_health_view.py`).** Pure functions, no I/O:
227:column returned as `raw_status`), and the monitor `scripts/check_data_source_health.py` (hourly
235:(1) the broker envelope (`scripts/lib/data_broker/envelope.py`) accepts `market_closed=True` and then
236:uses the domain's `stale_after_hours_closed` (declared today only for `quote_price`: 0.25h open → 72h
239:whose registry window is shorter than a weekend and whose producer is Mon–Fri only **will decay to

$ grep -n 'check_data_source_health\|Health decays' AGENTS.md docs/SOURCE_OF_TRUTH.md | cut -c1-140
AGENTS.md:1213:6. **Health decays.** A `data_source_health` row is *healthy* only if it succeeded inside its
docs/SOURCE_OF_TRUTH.md:159:| `check_data_source_health.py` | a source with a scheduled caller is not *effectively* healthy (decayed to unkn
```

### 5 broker envelope + projections + dead-desk gaps

```
$ grep -n 'envelope\|no_producer\|projections' docs/MASTER_SYSTEM_DOCUMENTATION.md | grep -i 'broker\|envelope\|catalog\|no_producer' | cut -c1-150 | head -6
738:| `projection` | **the one read path** — hubs read through `scripts/lib/data_broker/` (23 projections in `catalog.py`, measured `e8a173e7d`), ne
2617:  unknown (Phase 3). **Broker envelope** on every projection; dead desks declare `gap.no_producer`

$ grep -n 'as_of`, `age`, `source`, `stale`\|data_broker' AGENTS.md | cut -c1-140 | head -4
1201:   (`scripts/lib/data_broker/`), never `FROM <table>` directly. `DIRECT_READ_ROSE` fails when a hub
1203:   `as_of`, `age`, `source`, `stale`.

$ python3 -c "import sys; sys.path.insert(0,'scripts'); from lib.data_broker.catalog import PROJECTIONS; print(len(PROJECTIONS))"
23
```

### 6 Brave spill + budgets + resolve_backup

```
$ grep -n 'spill\|resolve_backup\|1,500\|120/day' docs/MASTER_SYSTEM_DOCUMENTATION.md docs/GAP_RESOLUTION.md | cut -c1-150 | head -8
docs/MASTER_SYSTEM_DOCUMENTATION.md:757:secret-hygiene allowlist. **Brave** is live and paid (caps 120/day, 1,500/month read from the registry);
docs/MASTER_SYSTEM_DOCUMENTATION.md:758:denials (`DAILY_EXHAUSTED`, `MONTHLY_EXHAUSTED`, `HTTP_429`) spill to the registry's `web_search.backup`
docs/GAP_RESOLUTION.md:40:| 3 | `governed_search` | metered | `brave_router.search()` — the router owns budget, cache and the SearXNG spill | touch

$ grep -n '"budget"' -A3 config/data_source_authority.json | grep -n 'daily\|monthly' | head -4
2:211-        "daily": 120,
3:212-        "monthly": 1500,

$ grep -n 'brave' docs/SOURCE_OF_TRUTH.md | grep -c 'active_paid'
1
```

### 7 account_state + account registry keys

```
$ grep -n 'account_state\|NO_API_MANUAL\|SERVICE_DOWN\|sync_kind\|manual_as_of' docs/MASTER_SYSTEM_DOCUMENTATION.md docs/SOURCE_OF_TRUTH.md AGENTS.md | cut -c1-150 | head -8
docs/MASTER_SYSTEM_DOCUMENTATION.md:763:`scripts/lib/account_state.py` classifies every account in `assets/portfolio_accounts.yaml` as
docs/MASTER_SYSTEM_DOCUMENTATION.md:764:`LIVE` · `STALE` · `SERVICE_DOWN` · `NO_API_MANUAL` from the registry keys `sync_kind`, `service_unit`,
AGENTS.md:1211:   (`say_so`, `refuse_up_front`, `carry_last_with_date`, `per_account_state_never_zero`) —

$ grep -n 'sync_kind\|service_unit\|service_receipt\|sync_window_hours\|manual_as_of' assets/portfolio_accounts.yaml | head -5 | cut -c1-120
13:#   sync_kind:         api | manual   (manual = no retail API; value is a statement entry)
14:#   service_unit:      systemd --user unit the read sync depends on (detected, never repaired here)
15:#   service_receipt:   health-probe JSON for that unit, relative to the project root
16:#   sync_window_hours: LIVE if the last sync landed inside this window, else STALE
17:#   manual_as_of:      last manual statement / entry date (manual accounts only)
```

### 8 gap resolver + doc + monitor

```
$ grep -n 'gap_resolver\|check_gap_resolution\|RETIRED_RAN' docs/GAP_RESOLUTION.md docs/MASTER_SYSTEM_DOCUMENTATION.md docs/SOURCE_OF_TRUTH.md | cut -c1-150 | head -10
docs/GAP_RESOLUTION.md:11:**Code:** `scripts/lib/gap_resolver.py` · desk wiring `scripts/lib/cio_operator_desk_loop.py` ·
docs/GAP_RESOLUTION.md:12:projection hook `scripts/lib/data_broker/gap_hook.py` · monitor `scripts/check_gap_resolution.py`
docs/GAP_RESOLUTION.md:122:* `RETIRED_RAN` — a receipt whose provider is retired and whose outcome is not `retired_skipped`. **Must be 0.**
docs/MASTER_SYSTEM_DOCUMENTATION.md:648:| `data_gap_resolver.py` | `scripts/` | Hourly worker that dispatches resolution actions |
docs/MASTER_SYSTEM_DOCUMENTATION.md:772:When a projection or the operator desk meets a stale or missing answer, `gap_resolver.resolve()` walks

$ grep -n 'on_gap' AGENTS.md docs/SOURCE_OF_TRUTH.md | cut -c1-140 | head -4
AGENTS.md:1248:  `no_coverage`, a declared `on_gap` chain, decaying health. A source that cannot fill those fields
docs/SOURCE_OF_TRUTH.md:17:8. Every domain declares on_gap: the ordered, budgeted vectors the gap resolver may run when the store is stale o
```

Accuracy check of `docs/GAP_RESOLUTION.md` against code (all true at `e8a173e7d`): `scripts/lib/data_broker/gap_hook.py`
exists; `CIO_GAP_RESOLVER` flag at `scripts/lib/cio_operator_desk_loop.py:1373`; `RECEIPTS_PATH = data/cio/gap_resolution_receipts.jsonl`
(`gap_resolver.py:67`); `VECTORS` (`:78`), `DEFAULT_ON_GAP` (`:101`), `normalise_chain` (`:305`), `resolve` (`:674`);
`is_answerable` at `cio_operator_desk_loop.py:1780`; the highlighted chains match the registry (`quote_price` refresh 24 → backup 24 →
operator_ask; `research_thesis` … hermes 6 …; `watch_discovery` operator_ask only; `private_company` empty). The one false statement
— "the registry itself is owned by a parallel agent and is not edited here" — was corrected and the correction kept in the document.

### 9 five monitor timers + declarations

```
$ grep -n 'tradeai-.*\.timer' docs/SOURCE_OF_TRUTH.md | cut -c1-150
docs/SOURCE_OF_TRUTH.md:138:| `served-copy-split-audit` | `tradeai-served-copy-split.timer` | `*-*-* *:42:00` | `data/runtime/served_copy_split_last_r
docs/SOURCE_OF_TRUTH.md:139:| `expected-services-audit` | `tradeai-expected-services.timer` | `*-*-* *:12:00` | `data/runtime/expected_services_last_r
docs/SOURCE_OF_TRUTH.md:140:| `data-plausibility-audit` | `tradeai-data-plausibility.timer` | `*-*-* 06:20:00` | `data/runtime/data_plausibility_last_
docs/SOURCE_OF_TRUTH.md:141:| `data-source-health-audit` | `tradeai-data-source-health.timer` | `*-*-* *:27:00` | `data/runtime/data_source_health_las
docs/SOURCE_OF_TRUTH.md:142:| `gap-resolution-audit` | `tradeai-gap-resolution.timer` | `*-*-* *:07,37:00` | `data/runtime/gap_resolution_last_run.jso

$ grep -c 'One Source of Truth' config/expected_services.json
5

$ grep -n '"lane_id": "\(served-copy-split\|expected-services\|data-plausibility\|data-source-health\|gap-resolution\)-audit"' config/lane_registry.json
1413:      "lane_id": "expected-services-audit",
1428:      "lane_id": "data-plausibility-audit",
1443:      "lane_id": "served-copy-split-audit",
1458:      "lane_id": "data-source-health-audit",
1473:      "lane_id": "gap-resolution-audit",

$ ls config/systemd/user | grep -c 'served-copy-split\|expected-services\|data-plausibility\|data-source-health\|gap-resolution'
10
```

### 10 UNCONSOLIDATED writer ceilings

```
$ grep -n 'Writer ceilings\|UNCONSOLIDATED' docs/SOURCE_OF_TRUTH.md | cut -c1-150 | head -10
53:| **quote_price** | ingested | `market_quotes` | UNCONSOLIDATED → `scripts/external_market_data_ingest.py` (3 writers today; ceiling may only fal
64:| **research_thesis** | native | `hermes_research_intelligence` | UNCONSOLIDATED → `scripts/lib/hermes_librarian/librarian.py` (32 writers today;
78:## Writer ceilings — stores not yet consolidated to one writer

$ grep -n 'data_source_authority_baseline\|WRITER_COUNT_ROSE' AGENTS.md docs/MASTER_SYSTEM_DOCUMENTATION.md | cut -c1-150
AGENTS.md:1193:   `INSERT`s or `UPDATE`s that store is a defect; `WRITER_COUNT_ROSE` fails the build when the
AGENTS.md:1231:  writer count is a ceiling in `config/data_source_authority_baseline.json` that may only fall.
docs/MASTER_SYSTEM_DOCUMENTATION.md:2622:  `config/data_source_authority_baseline.json` may only fall); the five monitor timers are declared but
```

### 11 governance: the grant

```
$ grep -n 'Ownership and the grant\|UNAPPROVED_SOURCE' AGENTS.md docs/SOURCE_OF_TRUTH.md docs/MASTER_SYSTEM_DOCUMENTATION.md docs/GAP_RESOLUTION.md | cut -c1-150
AGENTS.md:1219:### Ownership and the grant
AGENTS.md:1242:  `UNAPPROVED_SOURCE` for any provider or domain without a complete approval, and its
AGENTS.md:2918:| 1.2.0 | 2026-09-13 | PROPOSED | MAJOR | §7A gains "Ownership and the grant" and rule 7; §17 gains **adding, replacing or retiring a
docs/SOURCE_OF_TRUTH.md:20:## Ownership and the grant
docs/MASTER_SYSTEM_DOCUMENTATION.md:742:| `approval` | **the operator's grant**: `approved_by`, `approved_on`, `reference`, `scope` (retired: `retired

$ grep -n 'adding, replacing or\|retiring a data source' AGENTS.md | cut -c1-150
1235:- **Adding, replacing or retiring a data source — or a writer of an authoritative store — is an
2528:overnight LLM window · merging divergent copies of any authoritative store · **adding, replacing or
2529:retiring a data source, or a writer of an authoritative store** (§7A — an agent proposes the

$ grep -c '"approval"' config/data_source_authority.json
46            # 22 providers + 24 domains

$ grep -n '"schema"' config/data_source_authority.json
2:  "schema": "DataSourceAuthority@v2",

$ grep -rn 'DataSourceAuthority@v1' scripts tests config docs AGENTS.md --include='*.py' --include='*.json' --include='*.md' | grep -v 'docs/implementation/sot/DOCS_AUDIT' | cut -c1-140
tests/test_data_source_authority_20260913.py:249:    reg["schema"] = "DataSourceAuthority@v1"      # the negative control: the gate must refuse a v1 file
```

### 12 adapters

```
$ grep -c 'Operator-only decisions: propose and stop' CLAUDE.md .github/copilot-instructions.md .cursor/rules/00-tradeai-work-policy.mdc
CLAUDE.md:1
.github/copilot-instructions.md:1
.cursor/rules/00-tradeai-work-policy.mdc:1
```

## What this audit got wrong on the way (kept in, §14)

- The brief said **22 projections**; `len(PROJECTIONS)` is **23** at `e8a173e7d`. The documents say 23 and cite the measurement.
- The registry's `_rules`, the renderer and `docs/SOURCE_OF_TRUTH.md` all said **"AGENTS.md section 7B"**. There is no §7B; the
  table is §7A and is rendered. Fixed at the source (registry + renderer), re-rendered.
- The rendered writer column showed **"none — dead feed"** for seven `UNCONSOLIDATED` stores (`quote_price`, `symbol_identity`,
  `catalyst_news`, `technicals`, `research_thesis`, `watch_directives`, `macro`) — stores with 2–32 live writers. The renderer now
  says `UNCONSOLIDATED → target (n writers today; ceiling may only fall)`, and a test pins it.
- `docs/GAP_RESOLUTION.md` still described the pre-integration state of the registry (see row 8).

## Gates run for this audit

Quoted verbatim in the PR body / session report: `check_data_source_authority.py` (findings=0, grants 22/22 + 24/24),
`render_source_of_truth.py --check` (stale: none), the five SOT test files (132 passed), neighbouring SOT + AGENTS policy files
(191 passed), `check_dark_contracts.py` (0 new), `check_test_coverage.py` (exit 0), `check_line_endings.py --range origin/main..HEAD`
(none), `validate_sop_evidence_integrity.py` (rebound after the `AGENTS.md` edit — see the `chore(sop)` commit), `report_docs_inventory.py
--write-index` (twice, second run stable), `ai_local_acceptance.sh`.
