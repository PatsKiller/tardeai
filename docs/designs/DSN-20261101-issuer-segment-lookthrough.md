---
id: DSN-20261101-issuer-segment-lookthrough
title: Issuer segment look-through — split multi-line companies by their filed revenue segments (SEC EDGAR XBRL)
status: PROPOSED
approval: 'pending — the one operator decision is the §7A grant of the issuer_segments store and the widened sec_edgar scope (proposed_domains row in config/data_source_authority.json, this PR). Nothing in this PR calls a source.'
source: 'operator 2026-11-01 (verbatim) "I pointed out SpaceX, but you should have the intelligence or either with your LLMs be able to break apart companies. Similarly, if I was in AT&T, you would know that AT&T or IBM, they have multiple lines of services. It''s just not one."; DSN-20261031-market-risk-engine (look-through, risk budget); PR #2447 (config/issuer_segments.json, APPROVED-only)'
summary: >-
  Replace "one stock = one sector" in the Market Risk Engine with each issuer's own reported revenue segments, pulled from
  the dimensional XBRL facts in its latest 10-K/10-Q (S-1/424B tables for recent IPOs), mapped to the engine's sector and
  theme groups by a deterministic config table, with an offline, cited, confidence-scored LLM classifier only for segment
  names the table cannot place. One new store (issuer_segments, single writer). Only the deterministic engine reads it; no
  model is in the scoring path. The look-through AND the risk budget (single sector, growth style, AI basket) both read the
  same per-symbol split. Refreshed filing numbers apply automatically; only operator overrides need approval.
phases:
- id: DSN-20261101-issuer-segment-lookthrough-P0
  title: Design + §7A proposal (this PR) — STOP for the operator grant
  status: IN_PROGRESS
  tasks:
  - {id: DSN-20261101-issuer-segment-lookthrough-P0-T1, title: 'This design; proposed_domains row issuer_segments + sec_edgar scope amendment (no grant)', status: IN_PROGRESS, areas: [docs/designs/DSN-20261101-issuer-segment-lookthrough.md, config/data_source_authority.json]}
  - {id: DSN-20261101-issuer-segment-lookthrough-P0-T2, title: 'Public repo: remove the hard-coded personal email from the SEC User-Agent (scripts/sec_data_ingest.py L44, scripts/lib/financial_senses/sec_companyfacts_reader.py L17); read config/sec_edgar_client.json; placeholder fails closed, never falls back', status: PROPOSED, areas: [scripts/sec_data_ingest.py, scripts/lib/financial_senses/sec_companyfacts_reader.py, config/sec_edgar_client.json]}
- id: DSN-20261101-issuer-segment-lookthrough-P1
  title: Engine plumbing on fixtures (no network, no store) — look-through + risk budget read one split
  status: PROPOSED
  tasks:
  - {id: DSN-20261101-issuer-segment-lookthrough-P1-T1, title: 'Recorded EDGAR fixtures T, IBM, HON, SPCX + XBRL instance parser (pure function)', status: PROPOSED, areas: [scripts/lib/issuer_segments/xbrl_segments.py, tests/fixtures/edgar/]}
  - {id: DSN-20261101-issuer-segment-lookthrough-P1-T2, title: 'Deterministic map config/issuer_segment_map.json + golden mapping tests', status: PROPOSED, areas: [config/issuer_segment_map.json, scripts/lib/issuer_segments/mapping.py]}
  - {id: DSN-20261101-issuer-segment-lookthrough-P1-T3, title: 'lookthrough.issuer_segments_for reads store rows + overrides with precedence; risk_budget.measure takes the per-symbol split', status: PROPOSED, areas: [scripts/lib/market_risk/lookthrough.py, scripts/lib/market_risk/risk_budget.py, scripts/lib/market_risk/exposure.py, scripts/lib/market_risk/book_precision.py]}
  - {id: DSN-20261101-issuer-segment-lookthrough-P1-T4, title: 'comm group UNKNOWN ("insufficient history") — measure XLC daily bars, fix the bar universe, test', status: PROPOSED, areas: [scripts/lib/market_risk/sectors.py, scripts/lib/market_risk/reader.py]}
- id: DSN-20261101-issuer-segment-lookthrough-P2
  title: Store + writer + lane (after the grant)
  status: PROPOSED
  tasks:
  - {id: DSN-20261101-issuer-segment-lookthrough-P2-T1, title: 'Promote the registry row; migration issuer_segments; writer scripts/lib/writers/issuer_segments_writer.py; SEC client config (project contact); dry run', status: PROPOSED, areas: [config/data_source_authority.json, migrations/, scripts/lib/writers/issuer_segments_writer.py, config/sec_edgar_client.json, AGENTS.md]}
  - {id: DSN-20261101-issuer-segment-lookthrough-P2-T2, title: 'Lane issuer-segments-refresh triggered by sec_filing_events + weekly coverage sweep', status: PROPOSED, areas: [config/lane_registry.json]}
- id: DSN-20261101-issuer-segment-lookthrough-P3
  title: Offline classifier for ambiguous segments (governed model job, OAuth-first)
  status: PROPOSED
  tasks:
  - {id: DSN-20261101-issuer-segment-lookthrough-P3-T1, title: 'llm_process_registry process issuer_segment_classifier + template + schema; quote must be a verbatim substring of the filing text', status: PROPOSED, areas: [config/llm_process_registry.json, scripts/lib/issuer_segments/classifier.py]}
- id: DSN-20261101-issuer-segment-lookthrough-P4
  title: Card + switch-over from APPROVED-only to auto-apply
  status: PROPOSED
  tasks:
  - {id: DSN-20261101-issuer-segment-lookthrough-P4-T1, title: 'Basis chip + source sheet on the market-risk card (390/412 tap tests)', status: PROPOSED, areas: [apps/command-center-v3/src/components/home/MarketRiskActionable.tsx]}
  - {id: DSN-20261101-issuer-segment-lookthrough-P4-T2, title: 'Shadow diff, then issuer_segments.auto_apply true; config/issuer_segments.json becomes overrides-only', status: PROPOSED, areas: [config/market_risk_policy.yaml, config/issuer_segments.json]}
---

# Issuer segment look-through

```
Status:      DRAFT — PROPOSED design; nothing is built and no source is called until the operator grants the §7A row
as_of:       2026-11-01T17:30-05:00
Measured at: origin/main 0971cd9cf; EDGAR responses read 2026-11-01 (§2, every number cited to an accession)
Depends on:  DSN-20261031-market-risk-engine (lookthrough.py, risk_budget.py, sectors.py); PR #2447 (config/issuer_segments.json)
```

## 1 · Why

The engine gives every single stock **one** sector, from `symbol_profiles` (`scripts/lib/market_risk/lookthrough.py`
`_exposure_for`, path 3). Funds are split by factsheet (`config/fund_lookthrough.json`). A company that runs several
businesses is not: SPCX counts as 100% Industrials although its own 10-Q says 12.1% of last quarter's revenue was rockets
and 48.2% was AI compute and software (§2.4). PR #2447 added `config/issuer_segments.json`, but it ships empty and uses only
operator-`APPROVED` entries, so every split waits on a hand approval and nothing refreshes when the next filing lands.

A second gap, found by the SPCX research: `risk_budget.measure()` (`scripts/lib/market_risk/risk_budget.py` L85–L163)
reads `symbol_profiles.sector` directly for the single-sector, growth-style and AI-basket budgets. Even an approved
segment split changes the stressed-groups card but **not** the budgets, which is why the Individual account's 47%
Industrials breach would not clear. This design routes both through one split.

**What the operator asked for.** The system should know, without being told, that AT&T, IBM or SpaceX each have several
lines of business, and count each line where it belongs.

## 2 · Source — SEC EDGAR, verified against real responses (2026-11-01)

### 2.1 What the APIs actually return (measured, not assumed)

| Endpoint | Has segment facts? | Evidence |
|---|---|---|
| `data.sec.gov/api/xbrl/companyconcept/CIK…/us-gaap/Revenues.json` | **No.** Entries carry only `start, end, val, accn, fy, fp, form, filed, frame`; no axis or member. | T (CIK 732717): FY2025 `val 125648000000`, `accn 0000732717-26-000120`; IBM (CIK 51143): FY2025 `val 67535000000`, `accn 0000051143-26-000010` |
| `companyfacts` / `frames` | **No** (same non-dimensional fact model as companyconcept; `frame` is a calendar label such as `CY2025`, not a dimension). | as above |
| Filing archive `…/Archives/edgar/data/<cik>/<accn>/<doc>_htm.xml` (XBRL instance) + `FilingSummary.xml` + `R<n>.htm` | **Yes.** Contexts carry `us-gaap:StatementBusinessSegmentsAxis`, `srt:ProductOrServiceAxis`, `us-gaap:SubsegmentsAxis`, `srt:ConsolidationItemsAxis`. | §2.2–§2.4 |

**Design consequence.** companyconcept/companyfacts are used only to (a) find the newest 10-K/10-Q accession and (b) give
the **consolidated total** the segment rows must reconcile to. The segment split itself is parsed from the filing's XBRL
instance document (`<primary>_htm.xml`, present in every filing checked: `t-20251231_htm.xml`, `ibm-20251231_htm.xml`).
`FilingSummary.xml` names the segment report (`ShortName` contains "Segment"), which is the human-readable citation.

**Tag choice varies by issuer — never hard-code one.** T and IBM tag total revenue `us-gaap:Revenues`. Honeywell's
`us-gaap:Revenues` series ends with the FY2011 10-K (`accn 0000930413-12-000976`); its current filings use
`us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax` (FY2025 `val 37442000000`, `accn 0000773840-26-000013`).
SPCX uses the same contract-revenue tag. The parser takes, per filing, the revenue concept that appears **with**
`StatementBusinessSegmentsAxis`, in this order: `Revenues`, `RevenueFromContractWithCustomerExcludingAssessedTax`,
`RevenueFromContractWithCustomerIncludingAssessedTax`, `SalesRevenueNet` (config list, `issuer_segments.revenue_concepts`).

### 2.2 AT&T (T, CIK 732717)

FY2025 10-K, accession `0000732717-26-000120`, filed 2026-02-09, `R59.htm` "Segment Information (Summary Of Operating
Revenues And Expenses By Segment)", element `us-gaap_Revenues`, $ millions:

| Member (axis) | FY2025 | Share |
|---|---|---|
| `t_MobilityMember` (`us-gaap_SubsegmentsAxis`, under `t_CommunicationsMember` on `StatementBusinessSegmentsAxis`) | 89,482 | 71.2% |
| `t_BusinessWirelineMember` (SubsegmentsAxis) | 17,231 | 13.7% |
| `t_ConsumerWirelineMember` (SubsegmentsAxis) | 14,183 | 11.3% |
| `t_LatinAmericaBusinessSegmentMember` (StatementBusinessSegmentsAxis) | 4,379 | 3.5% |
| `us-gaap_CorporateAndOtherMember` | 373 | 0.3% |
| Total (no axis) | 125,648 | reconciles: 120,896 + 4,379 + 373 |

`R64.htm` (Revenue Categories) adds `srt_ProductOrServiceAxis` members: `t_WirelessServiceMember` 70,099;
`t_BusinessServiceMember` 15,978; `t_IPBroadbandMember` 3,542; `t_LegacyVoiceAndDataMember` 10,362.

**AT&T re-segmented in 2026.** Q3 2026 10-Q, accession `0000732717-26-000372`, filed 2026-10-21, `R39.htm`:

| Member (StatementBusinessSegmentsAxis) | Q3 2026 (3 months) | Share |
|---|---|---|
| `t_AdvancedConnectivitySegmentMember` | 29,481 | 91.2% |
| `t_LegacySegmentMember` | 1,519 | 4.7% |
| `t_LatinAmericaSegmentMember` | 1,240 | 3.8% |
| `us-gaap_CorporateAndOtherMember` | 82 | 0.3% |
| Total | 32,322 | reconciles exactly |

This is the strongest reason the mapping must work on **member names and labels each filing**, not a stored list of
members: the members T used in February no longer exist in October.

### 2.3 IBM (CIK 51143)

FY2025 10-K, accession `0000051143-26-000010`, filed 2026-02-24, `R79.htm` "Segments – Results of Continuing Operations",
element `us-gaap_Revenues`:

| Member (StatementBusinessSegmentsAxis) | FY2025 | Share |
|---|---|---|
| `ibm_SoftwareMember` | 29,962 | 44.4% |
| `ibm_ConsultingMember` | 21,055 | 31.2% |
| `ibm_InfrastructureMember` | 15,718 | 23.3% |
| `ibm_FinancingMember` | 737 | 1.1% |
| Other / unallocated (total − operating segments 67,472) | 63 | 0.1% |
| Total | 67,535 | |

`R84.htm` "Segments – Revenue by Product or Service" carries the finer `srt:ProductOrServiceAxis` split (not fetched).
Newest 10-Q: `0000051143-26-000095`, filed 2026-10-22.

### 2.4 The third conglomerate (Honeywell, HON, CIK 773840) and SPCX (CIK 1181412)

Honeywell FY2025 10-K, accession `0000773840-26-000013`, filed 2026-02-17, `R144.htm`, element
`us-gaap_RevenueFromContractWithCustomerExcludingAssessedTax`: `hon_AerospaceTechnologiesMember` 17,510 (46.8%),
`hon_IndustrialAutomationMember` 9,401 (25.1%), `hon_BuildingAutomationMember` 7,367 (19.7%),
`hon_EnergyAndSustainabilitySolutionsMember` 3,134 (8.4%), corporate 30; total 37,442 (reconciles). Its Q3 2026 10-Q
(`0000773840-26-000143`, filed 2026-10-22) reports quarterly revenue of only 4,994 against roughly 9,400 a quarter in
FY2025. Something structural changed, and I did not fetch its segments. A split frozen at the 10-K would now be wrong.
This is why the design re-pulls after every 10-Q.

SpaceX Q3 2026 10-Q, accession `0001628280-26-066880`, filed 2026-10-22. **It does tag the segment axis**, so SPCX is
machine-extractable even as a 2026 IPO. `R50.htm` and `R85.htm`, element
`us-gaap_RevenueFromContractWithCustomerExcludingAssessedTax`, 3 months:

| Member | Q3 2026 | Share |
|---|---|---|
| `spcx_SpaceMember` (StatementBusinessSegmentsAxis) | 1,767 | 12.1% |
| `spcx_ConnectivityMember` | 5,248 | 36.0% |
| `spcx_SIMember` | 7,560 | 51.9% |
| ↳ `us-gaap_AdvertisingMember` (ProductOrServiceAxis, within SI) | 538 | 3.7% |
| ↳ `spcx_SISolutionsAndInfrastructureMember` (within SI) | 7,022 | 48.2% |
| Total | 14,575 | reconciles exactly |

These match the independent SPCX research (`agent_scratch/fable-mre/issuer_segments_SPCX_proposal.json`) to the dollar.

### 2.5 Recent IPOs with no XBRL segment facts yet

A registrant's first periodic report is usually its first XBRL segment data. Before that, the source is the S-1/424B
prospectus. Order:

1. **XBRL from any 10-Q/10-K** (as SPCX already has). This is always preferred.
2. **S-1 / 424B HTML segment table, machine-extracted.** Locate the "Segment" note table in the newest 424B (else S-1).
   Parse it with a table parser. Accept it only if the segment rows reconcile to the stated total revenue within
   `issuer_segments.sum_tolerance`. The row gets `extraction: html_table`.
3. **Otherwise** the row gets `status: needs_model_extraction`. The P3 classifier may extract it, with the same quote and
   confidence rules as §3.2. Until then the engine uses the profile sector, with the flag shown.

### 2.6 Client rules

- **User-Agent from config, not code — a required input that fails closed.** `config/sec_edgar_client.json` holds
  `{app, contact, max_rps, spacing_s}`. `contact` ships as the placeholder `"REQUIRED: project contact address (operator)"`.
  Every SEC caller refuses to send a request, with an error that says the contact is missing, when `contact` is empty,
  still the placeholder, or not an address. There is **no fallback** to any other address, and in particular never to
  the operator's personal email. The contact must be a **project address**; the operator has not yet supplied it
  (pending, 2026-11-01). Measured on 2026-11-01: a request with no contact address got **HTTP 403** from `www.sec.gov`,
  so a missing contact cannot silently half-work.
- **P0 fix (public repo).** Two modules hard-code the operator's personal email in the SEC User-Agent today:
  `scripts/sec_data_ingest.py` L44 and `scripts/lib/financial_senses/sec_companyfacts_reader.py` L17. P0-T2 replaces
  both with the config read above, with the same fail-closed rule. Consequence to state plainly: until the operator
  supplies the project address, the existing SEC feeds that use these modules refuse instead of sending. That is the
  intended fail-closed trade, and the P0-T2 PR names it. A test scans `scripts/` for an email literal in any
  User-Agent string.
- **Rate.** SEC's fair-access limit is 10 requests/s. We use 0.15 s spacing per process (about 6.7/s, the existing
  convention) and `max_rps ≤ 8`. Volume is small: about 3 requests per new filing (submissions or companyconcept, then
  `FilingSummary.xml`, then the instance) times the covered issuers, and filings come quarterly.
- **No second poller.** New accessions already arrive in `cio/sec_filing_events.jsonl` (domain `sec_filing_events`,
  writer `scripts/sec_filings_feed.py`). The refresh lane is triggered by those events. A weekly sweep only adds issuers
  that newly entered coverage.

### 2.7 Coverage

The union of the following, resolved to an issuer GUID through the identity registry. A ticker is never treated as an
identity (§7).

- Held positions: symbols only, from the engine's existing positions input.
- Watched and re-entry-watch symbols (`watch_directives`, `scripts/lib/market_risk/reentry_watch.py`).
- Single-stock holdings of held funds whose share in `etf_holdings_snapshot` is at least
  `issuer_segments.fund_holding_min_share` (default 0.03, operator-tunable).

Funds, ADRs without US segment XBRL, and private-company proxies are out of scope. They keep their existing paths.

## 3 · Mapping segments to group keys

Group keys are the ones in `config/market_risk_policy.yaml` `sectors.groups`. The sector-kind keys are `tech`, `comm`,
`discretionary`, `staples`, `healthcare`, `utilities`, `energy`, `financials`, `industrials`, `materials` and
`real_estate`. The theme keys are `semis` and `ai_basket`.

### 3.1 Deterministic table — `config/issuer_segment_map.json` (reviewed config, git)

The rules are tried in order, and the first match wins:

1. **Issuer-scoped member rules**: `{issuer_guid|symbol, member_qname} → group(s)`. Examples: `ibm_InfrastructureMember →
   tech` (hardware) and `ibm_FinancingMember → financials`. These exist because a word like "Infrastructure" means
   hardware at IBM and buildings at Honeywell.
2. **Standard us-gaap/srt members**: `us-gaap_AdvertisingMember → comm`. `CorporateAndOtherMember` and other
   reconciling items are not mapped. They join the residual (§3.4).
3. **Global label keyword patterns**: case-insensitive regex on the member's standard label. Examples:
   `wireless|mobility|broadband|wireline|connectivity|telecom → comm`;
   `software|cloud|consulting|data processing → tech`;
   `aerospace|defen[cs]e|launch|automation|building → industrials`;
   `financ(ing|ial services)|insurance|bank → financials`.
   A label that matches patterns from two different groups is **ambiguous**. Ambiguous labels never take the first
   pattern; they go to §3.2.
4. **Theme overlays** (`ai_basket`, `semis`) are assigned **only** by an issuer-scoped rule (rule 1), never by a keyword
   or a model. The operator's theme set stays operator-owned (the same principle as `positions.theme_overrides`). The
   SPCX row `spcx_SISolutionsAndInfrastructureMember → tech + ai_basket` lands as an issuer-scoped rule in the P1 PR,
   where it is visible and reviewed.

Unmatched or ambiguous members go to the classifier queue.

### 3.2 Offline classifier for the ambiguous rest (P3)

- **Lane.** The existing governed model-job path (`scripts/lib/n8n_model_job.py`: templates, schema validation,
  forbidden keys) routes OAuth-first per `config/llm_routing_policy.json`. It runs under a new process id
  `issuer_segment_classifier` in `config/llm_process_registry.json`, with a daily cost cap. It uses no new provider and no
  direct key.
- **Input.** The member QName, its label, and the filing's segment-note text, the description of that segment. The
  model gets nothing else.
- **Output schema.** `{group, theme_suggestion|null, confidence 0..1, quote, rationale}`.
- **Deterministic acceptance.** The writer, not the model, accepts or rejects the output:
  - `group` must be a sector-kind key;
  - `quote` must be a **verbatim substring** of the fetched filing text, after whitespace normalisation. If it is not
    found, the result is rejected;
  - `confidence ≥ issuer_segments.model_min_confidence` (default 0.70).
- **Storage.** An accepted result is stored with `basis: model_classified`, `confidence`, `citation: {accession, url,
  quote}`.
- **Theme suggestions.** `theme_suggestion` is stored for display only and never applied (§3.1 rule 4). It becomes a
  proposed map rule for review.
- **Low confidence or rejected.** The segment's share goes to the **profile sector** with
  `flag: segment_unmapped_fallback`. The card shows this, so a fallback is never silent.

### 3.3 No model in detection (DSN-20261031 principle)

The classifier runs offline, in the writer lane, and its result is a **stored, cited row**. `lookthrough.py`,
`risk_budget.py` and the scoring path import no model client and make no call. A P1 test asserts this: the market_risk
package has no import of `n8n_model_job`, `llm_*` or a bridge client. The same split produces the same number every
time.

### 3.4 Residual and denominators

Shares are of **consolidated revenue** for the period:

- Each mapped segment gets its own share.
- Reconciling items, corporate and unmapped rows form the **residual**, which goes to the profile sector with
  `residual: true`.
- When intersegment eliminations are negative, the shares are taken over the sum of the positive reportable segments,
  and the reconciliation gap is recorded.
- Sector-kind shares sum to 1.0 within `sum_tolerance`, the existing rule.

## 4 · Store — `issuer_segments`

**Table `issuer_segments`.** The single writer is `scripts/lib/writers/issuer_segments_writer.py`, and the read path is
projection `issuer_segments` (`scripts/lib/data_broker/catalog.py`). Postgres is chosen over a governed JSON because a
runtime job must refresh it: a git-tracked config file cannot be written by a lane (commit policy), and the engine's
`reader.py` already reads Postgres with a fixture twin (`fixture_reader.py`).

| Column | Meaning |
|---|---|
| `issuer_guid`, `symbol` | identity (GUID from the registry; symbol for display) |
| `period_start`, `period_end`, `period_kind` | `Q` (3 months) or `FY` |
| `as_of` | `period_end`; `filed_at` kept separately |
| `accession`, `form`, `source_url` | 10-K / 10-Q / S-1 / 424B; the URL of the R page or document cited |
| `segment_member`, `segment_label`, `parent_member` | QName + standard label; parent for ProductOrService / Subsegment lines |
| `revenue_usd`, `revenue_share` | share of consolidated revenue (never named `weight`, a market-risk `BEHAVIOR_FIELDS` key) |
| `group`, `theme_groups[]` | mapped sector key; overlays from issuer-scoped rules only |
| `basis` | `deterministic` · `model_classified` · `operator_override` (overrides are read from config, never written here) |
| `extraction` | `xbrl` · `html_table` · `model_extraction` |
| `confidence` | 1.0 for deterministic; model value for model_classified |
| `citation` | `{rule_id}` or `{accession, url, quote}` |
| `status` | `current` · `superseded` · `needs_model_extraction` · `refused` (did not reconcile) |
| `ingested_at`, `run_id` | provenance (§5) |

**Rows are append-only per accession.** A newer accession marks the issuer's older rows `superseded`; nothing is deleted
(§0 rule 6).

**Staleness.**
- A re-pull is triggered by every new 10-Q/10-K accession for the issuer.
- Past `stale_after_days` (120, existing key) the split is used and marked `stale`.
- Past `hard_stale_days` (new key, default 200, roughly two missed quarters) the engine falls back to the profile sector
  and flags it.

**Precedence in the engine:**
1. `operator_override`: a `status: APPROVED` entry in `config/issuer_segments.json`;
2. `current` store rows, deterministic or model_classified at or above the confidence floor;
3. the `symbol_profiles` sector, flagged when the issuer is covered but has no usable split.

**Only overrides need approval.** Refreshed filing numbers apply without anyone approving them, once
`issuer_segments.auto_apply` is true.

### 4.1 Transition from "APPROVED entries only"

| Step | `config/issuer_segments.json` | Engine | Who |
|---|---|---|---|
| Today | `APPROVED` only; empty | profile sector for everyone | — |
| P1 merged | unchanged | reads overrides + fixture-backed store reader; `auto_apply: false`; computes the store split in **shadow** and reports `segment_shadow_diff` per symbol in the snapshot | agent |
| Grant (P2) | unchanged | writer fills the table; shadow diff visible on real filings | **operator: the one approval** |
| P4-T2 | `_comment` rewritten: "operator OVERRIDES only; refreshed filing splits apply automatically from the issuer_segments store"; `PROPOSED` status retired from the schema (a proposal is now just a store row) | `auto_apply: true` | agent, after one shadow day with every covered issuer reconciled or flagged |

`issuer_segments.auto_apply: false → true` is a policy value that the grant decides. It is not a second approval: the
grant's `decision` text names it (proposed_domains row).

## 5 · Engine and card

### 5.1 `scripts/lib/market_risk/lookthrough.py`

- `issuer_segments_for(sym, …)` gains a `store_rows` input, read through the reader or fixture, and applies the
  precedence in §4. Its return value adds `basis_kind` (`filing` · `model_classified` · `override` · `profile_fallback`),
  `source` (form, filed date and URL), `flags[]` and `segments[]` (label, share, group, basis), for the card.
- `_exposure_for` path 3 (single stock) calls it **before** the profile-sector branch. That already happens for
  APPROVED config entries (L118–L124). The fund path and the IPO-overrides-stale-fund rule are unchanged.
- `exposure_for(..., themes=…)` keeps operator theme overrides on top.

### 5.2 `scripts/lib/market_risk/risk_budget.py` — one split for every budget

`measure()` takes a new `lookthrough: dict[symbol, exposure]` argument, built once by `exposure.py` and `book_precision.py`
through `lookthrough.exposure_for`.

- **single_sector_pct**: the sector tally becomes `Σ mv × groups[g]` over sector-kind group keys, replacing
  `sectors[prof.sector] += mv`. Profile-sector strings map through `SECTOR_TO_GROUP`, so both paths use one key space.
- **growth_style_pct**: `mv × Σ groups[g]` for `g` in the growth sector keys. `classification.growth_sectors` is
  translated to group keys, and defensive keys are excluded. The name-token rule still applies to profile-fallback
  symbols only.
- **ai_basket_pct**: `mv × groups.get("ai_basket", 0)`, the same overlay the stressed-groups card uses. Basket members
  stay at 1.0.
- `drivers` lists `SYM (segment share)`, so a breach names the line of business.
- **Effect on SPCX** (Q3 2026 split): its Industrials contribution falls from 100% to 12.1% of its value. The Individual
  account's 47% Industrials breach is expected to fall by roughly 0.88 × SPCX's share of that account. The P1 shadow run
  reports the actual figure; I have not computed it here, because I read no positions.

### 5.3 The card (`apps/command-center-v3/src/components/home/MarketRiskActionable.tsx`)

This is an addition to home v005; nothing is removed (UI change-control rule). Each row under "Your positions in stressed
groups" gets a basis chip:

- `split from 10-Q 2026-10-21` or `split from 10-K 2026-02-09`. Tapping it opens a full-screen sheet on a phone with the
  segment table (label, share, group) and a link to the cited filing page.
- `model-classified — tap for source`. The sheet shows the quoted filing sentence, the confidence and the accession.
- `sector only — no filing split` (fallback flag) or `stale split (Q2)` when past `stale_after_days`.
- `your override` for operator_override.

Tap tests run at 390 and 412 px. The mockup is attached to the P4 PR.

### 5.4 SPCX first

The sourced SPCX proposal is the first golden fixture. Its recorded `R50` and `R85` responses must parse to Space 0.1212,
Connectivity 0.3601, SI-Advertising 0.0369 and SI-Solutions 0.4818, with an ai_basket overlay of 0.4818 from the
issuer-scoped rule. Once the grant is in, the store row from the live filing replaces any config entry. The
capital-spending-weighted AI overlay (83.9%) offered in the SPCX research is an operator **override** choice, not a filing
split. If the operator wants it, it goes in `config/issuer_segments.json` as `APPROVED`.

## 6 · §7A

- **Registry row.** `proposed_domains[issuer_segments]` in `config/data_source_authority.json` (this PR), status
  `proposed`, `approval: null`. It covers the table, the single writer target, the lane, the projection, the required
  fields, `no_coverage: fall_back_to_profile_sector_with_flag` and on_gap. Its `provider_amendment` block widens
  `providers.sec_edgar` from `form4, filings` to `form4, filings, xbrl_segments`. No host is added: `sec.gov` is already
  matched. `check_data_source_authority.py`: findings=0. `render_source_of_truth.py --check`: no change, because proposed
  rows do not render.
- **The one approval.** The operator grants the store and the widened provider scope together. The grant is recorded in
  the row's `approval` at promotion. With it come `auto_apply`, the writer, the lane schedule and the classifier process
  (cost-capped, OAuth-first). After that, the only thing that ever needs the operator is an override.
- **AGENTS.md.** Promoting the row adds a line to the generated §7A table (`render_source_of_truth.py`). By the
  precedent of #2448 (29.2.0 → 29.2.1), that is an AGENTS.md **PATCH** bump, "generated §7A table refreshed, no
  rule-text change". AGENTS.md is a held class, so the promotion PR is named to the operator. No rule text changes. This
  design PR does not touch AGENTS.md.
- **Same promotion PR.** As in #2448:
  - the store joins the `stores_pg_public` backup class;
  - the dictionary row and `docs/architecture/DATA_DICTIONARY.md` are re-rendered;
  - the refusal test proves the gate on a proposed copy.

## 7 · Phased build plan and tests

| Phase | Work | Tests (all offline; fixtures under `tests/fixtures/edgar/`) |
|---|---|---|
| **P1** (no grant needed: no source called, no store) | XBRL instance parser (pure); mapping engine + `issuer_segment_map.json`; lookthrough precedence; `risk_budget.measure` on the per-symbol split; shadow diff; comm fix | **Recorded fixtures**: the `_htm.xml` instance, `FilingSummary.xml` and companyconcept JSON for T (`0000732717-26-000120`, `…-000372`), IBM (`0000051143-26-000010`), HON (`0000773840-26-000013`) and SPCX (`0001628280-26-066880`). They are recorded once at P2 under the grant, and committed with their sha256 and the request date. Until then P1 uses hand-built minimal instances that reproduce the §2 numbers. **Parser goldens**: the §2 tables to the dollar, the reconciliation pass, T's re-segmentation (two accessions, different members, both parse), and HON's tag choice (`Revenues` absent, contract-revenue tag used). **Mapping goldens**: T → comm 1.0 (Q3 2026: three telecom segments 0.997 + 0.003 corporate residual to the profile sector, also comm); IBM → tech 0.989, financials 0.011; SPCX → industrials 0.1212, comm 0.3970, tech 0.4818, ai_basket 0.4818; HON → industrials 0.916, `hon_EnergyAndSustainabilitySolutionsMember` ambiguous → classifier queue. **Ambiguity**: a label that hits two keyword groups is never auto-mapped. **Fallback path**: a missing split, a sub-floor confidence, a rejected quote or a hard-stale split each give the profile sector plus a visible flag; nothing is silent. **Budget routing**: SPCX in a fixture book moves single_sector_pct off Industrials, and growth and AI budgets read the same split as the card. **BEHAVIOR_FIELDS guard**: `contract.assert_no_behavior_fields` runs over the look-through, the budget and the card payloads. `weight` is a forbidden key, so store and payload fields are `revenue_share`/`share`, and a test feeds a config entry using `weight` (the #2447 schema) and asserts the output carries no `weight` key. **No model in scoring**: an import scan of `scripts/lib/market_risk/`. **comm**: a fixture with ≥ 60 XLC sessions yields a non-UNKNOWN comm row. |
| **P1-T4 comm** | Today `comm` shows UNKNOWN "insufficient history" although XLC has data. `sectors.measure` marks a group UNKNOWN when its index has < 60 sessions (`sectors.py` L126). `reader.daily_bars` reads `market_ohlcv_bars` (timeframe daily) and adds quote closes. **Hypothesis, not measured**: XLC is short of 60 daily bars in `market_ohlcv_bars` because it is outside the daily-bar writer's universe. First step: count XLC daily rows read-only (`SELECT count(*) … WHERE symbol='XLC' AND timeframe=…`). Then backfill through the existing bar writer, adding the sector ETFs in `sectors.groups` to its universe, and pin it with the test above. Matters because about 40% of SPCX lands in comm. | |
| **P2** (after the grant) | Promote the row; migration; writer (dry-run first, quote the output); `config/sec_edgar_client.json` (contact supplied by the operator; P0-T2 already made it fail closed); lane `issuer-segments-refresh` (lane registry row + `output_signal`); record the real fixtures | Writer dry run on T/IBM/HON/SPCX prints rows and writes nothing. A single-writer scan (`WRITER_COUNT_ROSE`). The User-Agent refusal when the contact is empty or the placeholder (no fallback address). A 403 surfaces as a refusal on the lane, not a silent zero. |
| **P3** | Classifier process, template and schema; deterministic acceptance | A quote not in the text → rejected. Confidence below the floor → fallback flag. A theme suggestion is never applied. Cost cap respected (the governed bridge's reservation test). |
| **P4** | Card chip + source sheet; shadow review; `auto_apply: true`; `issuer_segments.json` comment and schema switch | Playwright tap tests at 390 and 412 (chip → full-screen sheet → filing link). Snapshot test: `auto_apply` false gives identical numbers to today's. |

## 8 · What the operator would see (from the 2026-11-01 responses)

| Holding | Today | With this design | Chip |
|---|---|---|---|
| **T** | 100% Communications | still about 100% Communications: Advanced Connectivity 91.2%, Legacy 4.7%, Latin America 3.8% (all telecom). The sector does not move; the card lists the lines | `split from 10-Q 2026-10-21` |
| **IBM** | 100% Technology | Technology 98.9% (Software 44.4%, Consulting 31.2%, Infrastructure 23.3%), Financials 1.1% | `split from 10-K 2026-02-24` (the Q3 10-Q, filed 2026-10-22, replaces it once its segment note is parsed) |
| **SPCX** | 100% Industrials | Technology 48.2% (+ AI basket 48.2%), Communications 39.7%, Industrials 12.1% | `split from 10-Q 2026-10-22` |

Honest note: for AT&T and IBM the businesses mostly sit in one sector, so their sector exposure barely changes. What they
gain is the line-by-line view, and automatic correction when they re-segment, as T did this year. The big change is for
true straddlers: SPCX, and companies like Honeywell whose Energy & Sustainability line is not industrial.

## 9 · Open questions for the build (not operator approvals)

- **Period basis.** Latest quarter (`issuer_segments.period_basis: latest_quarter`, the default and the SPCX research's
  recommendation) or trailing four quarters. Trailing four quarters smooths seasonality but breaks across a
  re-segmentation, as T shows. Default: latest quarter; trailing four quarters only where members are unchanged across
  all four.
- **Revenue vs operating income.** Revenue is what the operator asked for ("lines of services"). Operating income is
  noisier and can be negative. Revenue it is.
