# Phase 3 — Documentation truth audit (inventory + proposals, no rewrites)

```
Status:      PROPOSED — INVENTORY ONLY, NO DOC WAS EDITED
as_of:       2026-09-05
Measured at: worktree /home/johnclaw/tradeai-wt-cc-header-final, branch wt/cc-header-final
             origin/main f88853e89e53fdd63725acccb064ca1395e0bf34
Authority:   READ_ONLY_ADVISORY. Nothing pushed, merged, deployed, restarted or deleted.
Deliverable: this file only. No other doc in this tree was touched by this pass.
```

**What the operator asked:** *"if stuff has changed please update the documentation to reflect
what's current. either overwrite or decommission any old documentation that's not the true
current state."*

**What this pass does instead, and why.** It inventories and proposes. Every row below names a
file, a line, the exact stale sentence, why it is now false, and the sentence that replaces it —
but nothing is rewritten, because three of the proposals are DECOMMISSION-class and one touches
an operator-signed activation record (`docs/deployment/production-activation.md`). Under
AGENTS.md §0.9 those are propose-and-stop. **Nothing here is deleted; every superseded document
gets a header and a pointer** (§0.6).

---

## 0 · Peer-session notice (stated first, per AGENTS.md §Session protocol)

This worktree moved under me during the audit. At session start `HEAD` was `7d7ed9202`; at
session end it is `0553ee6e0a2915e42254dc0bfd5251f91aecafcf`
("research(brave): 0 is not a ceiling of zero — the module invented a limit"). That commit is
**not mine.** `git status` is clean apart from this file. Two commits sit unpushed on
`wt/cc-header-final` ahead of `origin/main`:

```
0553ee6e0 research(brave): 0 is not a ceiling of zero — the module invented a limit   (peer)
7d7ed9202 research(brave): separate provider capacity from the ceiling we chose
f88853e89 Merge pull request #873 …/wt/comms-wave-c-poller                  <- origin/main
```

Any line-number citation below was read at `0553ee6e0` unless it names a different tree.

---

## 1 · The ground truth this audit judges against

Measured 2026-09-05 on this box. These are the yardstick; a doc is "stale" only where it
contradicts one of them.

| # | Measured fact |
|---|---|
| G1 | `origin/main` = `f88853e89e53fdd63725acccb064ca1395e0bf34`; serving release `f88853e89-main-exact-phase2-20260905-135414`. Build meta, API, service cwd, `origin/main` and release ID **all agree**. |
| G2 | Comms gateway mode is **CANARY** (env-driven), `owned_classes=['ops']`. It was **ACTIVE** earlier the same day. Both were true at their own times. Mode is a *reading*, never a permanent property. |
| G3 | `delivery_owned` was a hardcoded `False`; **FIXED in PR #868** — now derived from `telegram_owned_classes(mode)` (`scripts/communications_portal.py:501-502`). |
| G4 | 57 deliveries: **8 SENT / 44 RESERVED / 5 LEGACY_DELIVERED / 0 FAILED**. |
| G5 | `communication_inbound_checkpoint`: migration **APPLIED**, **0 rows** (never exercised). |
| G6 | Retention **IS** exercised: 24 decisions, 6 tombstones, 4 `agent_consumption_receipts`. |
| G7 | Brave: live headers measured **50 req/sec**; the per-month window reports **0 = UNMETERED, not a ceiling of zero**. "1,000/month free tier" / "850 out of 1000" was an **assumption never observed**, now removed from `scripts/brave_search.py`. |
| G8 | **Two divergent search-budget ledgers exist.** Report, do not merge (§0.5). |
| G9 | Header campaign shipped PRs #857–#867 + #869/#870: `PortfolioAggregate@v2`, `TodayPnl@v1`, `QuoteSelection@v1`, `SetupRunSummary@v1`, `DesignFeatures@v1`, `ResearchProviderTruth@v1`. |

### G8, stated in full — the two ledgers, unmerged

Both files exist on this box right now. They are **not** copies of each other; they are two
sensors that were never reconciled.

| ledger | path | schema | last write | content |
|---|---|---|---|---|
| **live** | `~/trade-ai-releases/persistent-state/data/runtime/search_budget.json` | `SearchBudget@v1` | `2026-09-05T17:30:03Z` | brave 2026-09: 60 calls (`web_research`); daily 2026-09-05: **8** |
| **frozen** | `~/trade-ai-releases/portfolio-server/CURRENT/data/portfolios/state/brave_search_budget.json` | none (ad-hoc dict) | `2026-08-10T05:12:30` | `calls: 25`, `skipped_budget: 46`, monthly 2026-08: 150 |

`scripts/brave_search.py` writes **both**: `_BUDGET_FILE` at `:50` is the frozen ad-hoc path,
while `:84`/`:141` call `lib.search_budget.check` / `record` into the live `SearchBudget@v1`
ledger. The docstring at `scripts/brave_search.py:14` names only the frozen one
("Budget tracked in: `data/portfolios/state/brave_search_budget.json`"), which is the ledger
that stopped moving 26 days ago. **No merge is proposed and none should be attempted by a
machine** — the monthly totals disagree (150 vs 25 for 2026-08) and picking one destroys the
other. This is an operator decision.

---

## 2 · Prioritized inventory

Classification: **OVERWRITE** = right home, wrong content, fix in place (A1A Step 3 — rewrite,
never footnote). **DECOMMISSION** = superseded entirely; add header + pointer, keep the file.
**CURRENT** = no action. **HISTORICAL-OK** = dated evidence record that was true when written;
leave the body alone, add a status line only.

| # | Pri | File:line | Class | One-line verdict |
|---|---|---|---|---|
| 1 | **P0** | `docs/architecture/communication-event.md:62` | OVERWRITE | Says `delivery_owned` is *always False*. Refuted by G3. |
| 2 | **P0** | `docs/architecture/communications-workspace.md:32` | OVERWRITE | Same false invariant, on the operator-facing page doc. |
| 3 | **P0** | `docs/architecture/delivery-ledger.md:79` | OVERWRITE | "do not flip `COMMS_GATEWAY_MODE` for ownership" — already flipped and signed. |
| 4 | **P0** | `docs/testing/unit-results.md:7` | OVERWRITE | "Production mode: remains **OFF**" — production is CANARY. |
| 5 | **P0** | `docs/deployment/production-activation.md:4` | OVERWRITE | "Current production mode: **ACTIVE**" — was true 04:31Z, is not now (G2). |
| 6 | **P0** | `docs/AGENT_ROSTER.md:157` | OVERWRITE | "Brave Search 25/day, 850/month" stated as a budget with no owner — the G7 defect verbatim. |
| 7 | **P0** | `docs/_findings/brave_search_api_usage_audit_2026-05.md:61` | HISTORICAL-OK + header | "1,000/month free tier" — the origin of the assumption. |
| 8 | **P1** | `docs/audit/current-state.md:3,21,69` | **DECOMMISSION** | Whole doc is a pre-gateway snapshot; title claims present tense. |
| 9 | **P1** | `docs/audit/runtime-attestation.md:15-19,90-93` | **DECOMMISSION** | Self-superseded by `live-attest-2026-09-05.md:9`; still cites `17e30dcbb` and 45 bypasses. |
| 10 | **P1** | `docs/audit/live-attest-2026-09-05.md:6,33` | OVERWRITE | Correct method, superseded readings: `faf8c05d9` and `mode: ACTIVE`. |
| 11 | **P1** | `docs/testing/test-plan.md:8` | OVERWRITE | "Production remains **OFF**" as a standing constraint. |
| 12 | **P1** | `docs/deployment/rollout-plan.md:9` | OVERWRITE | "no production ACTIVE cutover" — the cutover happened. |
| 13 | **P1** | `docs/architecture/channel-adapters.md:83` | OVERWRITE | "`COMMS_GATEWAY_MODE` stays **OFF by default**" reads as a live state. |
| 14 | **P1** | `docs/architecture/retention.md:3` + `communications-workspace.md:42-43` | OVERWRITE | Retention/receipts described as placeholder/dry-run. Refuted by G6. |
| 15 | **P1** | `docs/final/implementation-record.md:24,26,29,98` | OVERWRITE | Phase table: retention "no", receipts "no", inbound "not re-attested". G5/G6 sharpen all three. |
| 16 | **P1** | `docs/FINVIZ_INTEGRATION_AND_DATA_SOURCE_MONITORING.md:104,118` | OVERWRITE | "Brave … **Retired** … no-op". The live ledger shows Brave spending **today**. |
| 17 | **P1** | `docs/audits/overnight/W5_SEARCH_COST_PROOFS_2026-09-01.md:63,96` | HISTORICAL-OK + header | `25 / 850` printed as a limit; also the only doc that already names the two-ledger split. |
| 18 | **P2** | `docs/ops/CIO_DATA_ASOF_GAPS_2026-09-01.md:37-41,117` | OVERWRITE | Describes the one-clock header model `PortfolioAggregate@v2` replaced. |
| 19 | **P2** | `docs/ops/litmus/LITMUS_CC_ROUTES_2026-09-01.md:152-153,185` | HISTORICAL-OK + header | Records the SPLIT-clock defect as an open finding; it is now fixed at the producer. |
| 20 | **P2** | `docs/audit/gap-analysis.md:3,15` | OVERWRITE | Cites `faf8c05d9` and "45 producers / 133 violations"; baseline is now empty. |
| 21 | **P2** | `docs/audit/sender-inventory.md:3`, `phase0-signoff.md:3` | HISTORICAL-OK + header | Signed at `17e30dcbb`. Signature is real; the SHA is a baseline, not a current state. |
| 22 | **P2** | `docs/DOCUMENTATION_INDEX.md`, `docs/project/PROJECT_DOC_INDEX.md` | OVERWRITE | **Neither index lists the Communications Gateway program or the header campaign at all.** |
| 23 | **P2** | `docs/CHANGELOG.md:13-20` | CURRENT | Accurate and the only narrative home for `PortfolioAggregate@v2` / `TodayPnl@v1`. |
| 24 | **P2** | `docs/_findings/comms_delivery_owned_contradiction_2026-09-05.md:217` | CURRENT | Already carries `[FIXED 2026-09-05]` and the correct resolution. |
| 25 | **P2** | `docs/_findings/pre_persistent_agent_phase0_evidence_ledger_2026-09-05.md` | CURRENT | Measured today; is the closest thing to a current-state record that exists. |

---

## 3 · The five named hunts, in detail

### Hunt A — "delivery_owned is always false"

Three docs state a **structural invariant** that the code no longer holds, and one of them is
the page an operator reads to decide whether the gateway is sending.

**A1 · `docs/architecture/communication-event.md:62`** — OVERWRITE
> `PublishResult.delivery_owned` is **always False** in Phase 1, even if `COMMS_GATEWAY_MODE=ACTIVE`.

Also `:78-81`, the Phase-1 mode table, which renders CANARY and ACTIVE ownership as
"Not yet implemented in client".

*Why now false:* G3. `scripts/communications_portal.py:501-502` derives it:
`owned_classes = telegram_owned_classes(mode)`; `delivery_owned = mode in ("CANARY","ACTIVE") and bool(owned_classes)`.
`scripts/lib/comms/channel_adapters.py:396` sets `base["delivery_owned"] = True` once the mode
gate and the Telegram class allowlist both pass.

*Correct statement to write:*
> `delivery_owned` is **derived, not constant.** It is `True` when the gateway mode is `CANARY`
> or `ACTIVE` **and** the Telegram class allowlist for that mode is non-empty
> (`telegram_owned_classes(mode)`), and `False` otherwise — fail-closed on `OFF`/`SHADOW` and on
> an empty allowlist. Measured 2026-09-05: `mode=CANARY`, `owned_classes=['ops']`,
> `delivery_owned=true`. The one-line `PublishResult.delivery_owned` stub in
> `scripts/lib/comms/client.py` remains `False` because that Phase-1 publish path never delivers;
> that is a property of *that path*, not of the gateway.

**A2 · `docs/architecture/communications-workspace.md:32-35`** — OVERWRITE
> `health().delivery_owned` is always `false` while gateway mode is OFF/SHADOW (Phase 1–7). The UI banner states: *Ledger-backed · gateway does not own delivery while OFF/SHADOW*

*Why now false:* the sentence is true as far as it goes and then presents one of three banners as
*the* banner. `communications_portal.py:505-514` emits three: the OFF/SHADOW one, the owned one
(`"Ledger-backed · gateway owns Telegram classes: ops"`), and a third for
`mode CANARY/ACTIVE but no allowlist (deliver fail-closed)`. An operator reading this doc against
the live page today sees a banner the doc says cannot appear.

**A3 · `docs/architecture/delivery-ledger.md:79`** — OVERWRITE
> `| CANARY / ACTIVE | Yes | Yes | **Not yet** — do not flip COMMS_GATEWAY_MODE for ownership |`

and `:17`
> the gateway does **not** claim egress ownership (`PublishResult.delivery_owned` stays `False`)

*Why now false:* the flip this line forbids was performed and signed
(`docs/deployment/canary-results.md:70`, operator johnclaw, 2026-09-05T04:31:04Z). A live
instruction not to do a thing that has been done is worse than silence — it invites a reader to
"correct" production back.

---

### Hunt B — comms mode asserted as a permanent fact

**This is the highest-value structural finding in the audit, and it is not a list of wrong
values.** Ten documents state the gateway mode as a property of the system. It is an
**environment reading** (`env:COMMS_GATEWAY_MODE`, systemd `32-comms-gateway-mode.conf`) that
changed twice on 2026-09-05 alone: ACTIVE at 04:31Z, CANARY by the afternoon. Any document that
writes a mode in the present tense is guaranteed to be false eventually — which is why the fix
below is a *form* change, not just a value change.

| file:line | stale sentence | reading it asserts |
|---|---|---|
| `docs/testing/unit-results.md:7` | "**Production mode:** remains **OFF**" | OFF |
| `docs/testing/test-plan.md:8` | "**Constraint:** Production remains **OFF**." | OFF |
| `docs/deployment/rollout-plan.md:7` | "**Default forever until operator flip:** **OFF**" | OFF |
| `docs/deployment/rollout-plan.md:9` | "**Phase 11 posture:** … **no production ACTIVE cutover**" | OFF |
| `docs/architecture/channel-adapters.md:83` | "`COMMS_GATEWAY_MODE` stays **OFF by default**. Phase 10 does not flip ACTIVE." | OFF |
| `docs/architecture/delivery-ledger.md:7` | "**Gateway mode:** remains `OFF` by default; Phase 3 is SHADOW recording only." | OFF |
| `docs/deployment/production-activation.md:3-4` | "**ACTIVE authorized** … **Current production mode:** **ACTIVE**" | ACTIVE |
| `docs/deployment/pre-go-live-checklist.md:3,5` | "**Status:** Live on CURRENT · **ACTIVE for `ops` only**" | ACTIVE |
| `docs/deployment/canary-results.md:5` | "**Production mode now:** **ACTIVE**" | ACTIVE |
| `docs/final/implementation-record.md:7,85` | "**Production activation:** **ACTIVE for Telegram `ops` only**" | ACTIVE |
| `docs/audit/live-attest-2026-09-05.md:33` | `"mode": "ACTIVE"` | ACTIVE |

*Why all of them are now false, in the same way:* G2. Measured today —
`mode=CANARY, reason=env:COMMS_GATEWAY_MODE, COMMS_GATEWAY_CANARY_CLASSES=ops,
COMMS_GATEWAY_CANARY_CHATS=6993102664,8797974247`, `delivery_owned=True`,
`owned_classes=['ops']`. The OFF group was overtaken at 04:31Z; the ACTIVE group was overtaken
later the same day.

**Neither group is a lie about history.** `production-activation.md` records a real,
operator-signed cutover at a real timestamp. What is wrong is the *tense*.

*Proposed form for every row above — one shape, applied uniformly:*
> **Mode is environment-driven and is not a property of this document.** `COMMS_GATEWAY_MODE`
> is set per host via systemd (`32-comms-gateway-mode.conf`) and can change without a deploy.
> The repository default is `OFF`; **the live value is whatever
> `GET /api/v2/communications/health` returns right now** — read it, do not cite this file.
> Last reading recorded here: `CANARY`, `owned_classes=['ops']`, `delivery_owned=true`,
> 2026-09-05. Earlier the same day: `ACTIVE`, `ACTIVE_CLASSES=ops`, signed 04:31:30Z. Both are
> true at their own times.

For `production-activation.md` specifically — **operator-signed, so propose and stop (§0.9).**
Do not overwrite the signature block or the checked gates. The single proposed edit is to `:4`:
change `**Current production mode:** **ACTIVE**` to
`**Mode at signing (2026-09-05T04:31:30Z):** ACTIVE, ACTIVE_CLASSES=ops. Current mode is
environment-driven — read /api/v2/communications/health.` The authorization ("ACTIVE authorized
for message class `ops` only") stays exactly as written: it is a grant, and a grant does not
expire because the current reading is CANARY.

---

### Hunt C — the Brave "1,000/month free tier" assumption

G7 is the cleanest case in this audit: a number nobody ever measured, propagated into five
documents and one roster, and read by every downstream consumer as a provider constraint.

**C1 · `docs/AGENT_ROSTER.md:157`** — OVERWRITE, highest priority in this hunt
> `- **Budget:** Brave Search 25/day, 850/month with per-caller caps`

*Why now false:* not the numbers — those are unchanged and correct — but the **authority** they
are presented under. `scripts/lib/research_provider_truth.py:237-256` now names them for what
they are: `BRAVE_LOCAL_COST_POLICY`, `owner="operator (John) — Trade AI research cost control"`,
`authority="LOCAL — chosen by this system, not imposed by the provider"`. The roster is the doc
an agent reads to learn its constraints; it is exactly where "a ceiling we chose" must not read
as "a ceiling they impose".

*Correct statement:*
> **Budget:** Brave Search 25/day, 850/month — a **LOCAL cost policy** owned by the operator
> (`lib/research_provider_truth.BRAVE_LOCAL_COST_POLICY`), not a Brave plan limit. Provider
> capacity is parsed live from `X-RateLimit-*` response headers: measured 2026-09-05 at
> **50 req/sec**, with the per-month window reporting **0 = UNMETERED** — which is the absence of
> a monthly ceiling, **not a ceiling of zero.**

**C2 · `docs/_findings/brave_search_api_usage_audit_2026-05.md:61`** — HISTORICAL-OK + header
> `| Brave Search API | EXHAUSTED | brave_search.py | 1,000/month free tier |`

also `:9` ("Requests this month: 1,000 (limit reached, 100%)"), `:41` ("vs 1,000 limit"),
`:66` ("cap at 30/day (900/month with buffer)").

*Why it must not be overwritten:* this is the **provenance** of the assumption. It is a dated
May-2026 finding and its `Status: HISTORICAL` header is already correct. Rewriting it would erase
the audit trail of how a guess became a fact. It needs one inserted line, not a rewrite.

*Note:* the `$5.00 / $5.00` spend figure at `:8,10` is an observation of a billing surface and is
**not** refuted by G7 — G7 refutes the inference that $5 ⇒ a 1,000-request monthly plan. Mark the
spend as observed, the 1,000 as inferred.

**C3 · `docs/audits/overnight/W5_SEARCH_COST_PROOFS_2026-09-01.md:63`** — HISTORICAL-OK + header
> `| **brave** | **25 / 25** | **25 / 850** (2.9%) | **3** | ok |`

*Why:* the table is a faithful dump of `all_status()` and stays. The `850` column head reads as a
provider limit. One footnote resolves it. **This doc is also the only place in the repo that
already documents G8** (`:96`: *"Legacy file `data/portfolios/state/brave_search_budget.json`
still exists (`date=2026-08-10`) — stale parallel sensor; authoritative ledger is
`data/runtime/search_budget.json` `[VERIFIED]`"*). That line is **CURRENT and correct** — it
should be promoted, not edited.

**C4 · `docs/FINVIZ_INTEGRATION_AND_DATA_SOURCE_MONITORING.md:104,118`** — OVERWRITE
> **Brave (topic) → HTTP 402 Payment Required** … **Retired**: `search_brave_news` no-ops behind `TOPIC_BRAVE_ENABLED` (default off)
> `[4/5] Brave (retired no-op) →`

and `:68`
> Brave read dead — correctly: its free tier was exhausted (returned 0 items)

*Why now false:* two ways. (a) "free tier was exhausted" restates the C1/C2 assumption as the
diagnosis. (b) **Brave is not retired at the system level.** The live ledger records
`web_research: 60` Brave calls in 2026-09 and 8 today, `last_call 2026-09-05T17:30:03Z`. The
retirement was scoped to the *topic-ingestion lane* (`search_brave_news`), and the doc's own
§4 scoping is correct — but the summary line "Brave off-board" reads system-wide and is what a
reader carries away.

*Correct statement:*
> **Brave is retired from the topic-ingestion lane only.** `search_brave_news` no-ops behind
> `TOPIC_BRAVE_ENABLED` (default off). Brave remains **live for research callers** —
> `web_research`, `aegis_social_sentiment`, `aegis_transcript_discovery` — metered through
> `SearchBudget@v1` (60 calls in 2026-09 as of 2026-09-05). The 2026-07-02 lane failure was
> HTTP 402 on a lapsed account; it was not proof of a monthly free-tier ceiling, and no Brave
> response observed by this system has ever stated one.

**C5 · already correct, no action:** `scripts/lib/research_provider_truth.py:9,12,204,237` and
`scripts/run_cio_hardening_ci.py:618` and `tests/test_research_provider_truth.py:3,64,156` all
quote the "1,000/month" string **as the defect they exist to refuse**. A naive grep-and-replace
would destroy the fix. Any remediation pass must read the surrounding sentence before editing a
hit. Likewise `docs/_findings/pre_persistent_agent_phase0_evidence_ledger_2026-09-05.md:141-144`
quotes the pre-fix source deliberately.

---

### Hunt D — old header contracts / v1 shapes

**The finding here is an absence, and it is the biggest documentation gap this audit found.**

Six contracts shipped in PRs #857–#867 + #869/#870 (G9). Searching all 1,996 markdown files under
`docs/` for their names returns:

| contract | doc mentions | canonical doc home |
|---|---|---|
| `PortfolioAggregate@v2` | 1 (`docs/CHANGELOG.md:13`) | **none** |
| `TodayPnl@v1` | 1 (`docs/CHANGELOG.md:14`) | **none** |
| `QuoteSelection@v1` | **0** | **none** |
| `SetupRunSummary@v1` | **0** | **none** |
| `DesignFeatures@v1` | **0** | **none** |
| `ResearchProviderTruth@v1` | **0** | **none** |

Four of the six contracts are **undocumented outside their own source file**. The
`docs/architecture/` convention that the comms program follows — one short doc per contract,
naming code path, migration, tests and mode semantics — was never applied to the header campaign.
This is not a stale-doc problem; it is a missing-doc problem, and the operator should decide
whether to fill it before the next campaign inherits the same gap.

Meanwhile, three docs still describe the **model the v2 contracts replaced**:

**D1 · `docs/ops/CIO_DATA_ASOF_GAPS_2026-09-01.md:37-41`** — OVERWRITE
> `MetricStrip.tsx` rendered a hardcoded `as_of {value}` … The label is now per-tile (`asOfLabel`), defaulting to `as_of` … and set to `data_as_of` for PORTFOLIO and

*Why now false:* this doc's fix — relabelling the tile — is precisely the fix that
`PortfolioAggregate@v2` documents as insufficient. `scripts/lib/portfolio_aggregate_contract.py:30-36`:
*"Three clocks, one label, and the label named none of them. No amount of UI wording can fix
that: the producer only ever emitted one number, so the UI had nothing truthful to render."*
The doc's `:117` table (`data_as_of | 2026-08-03 | 2026-09-01`) presents a **single** portfolio
clock as the answer.

Worse, `docs/CHANGELOG.md:18` records that the *assertion* protecting this doc's fix
("required both money tiles to carry `asOfLabel: 'data_as_of'`") **passed while the header was at
its most misleading.** A doc whose fix was pinned by an assertion that has since been inverted
must say so.

*Correct statement:*
> The per-tile `asOfLabel` fix described here was **necessary and insufficient**, and was
> superseded at the producer on 2026-09-04 by `PortfolioAggregate@v2` (PR #857). A single
> `data_as_of` cannot date an aggregate whose contributors were observed months apart. v2
> publishes four named clocks per account — `position_observation_time` (share counts),
> `valuation_time` (when `total_value` was computed), `reported_total_as_of` (the custodian's own
> total and its date), `received_time` (when the bytes arrived) — and adds aggregate
> `coverage.at_newest_pct` / `value_dated_pct`: the share of aggregate **value** the headline date
> is entitled to describe (0.4% on the captured book). The v1 names are retained as **exact
> aliases**, documented as the position clock they always were
> (`scripts/lib/portfolio_aggregate_contract.py:155-156, 247-248, 472-475`). The `asOfLabel`
> assertion this doc relies on was inverted in PR #869/#870 because it passed on the defect.

**D2 · `docs/ops/litmus/LITMUS_CC_ROUTES_2026-09-01.md:152-153,185`** — HISTORICAL-OK + header
> `| MetricStrip PORTFOLIO | /api/v2/overview | as_of | … | **SPLIT** | Block as_of is holdings snapshot date; repricing is today …`
> `| Overview as_of | Doc implies single freshness | Live: as_of 2026-08-29, data_as_of 2026-09-01, last_repriced today | SPLIT — doc does not describe triple clock |`

*Why:* this is a **correct diagnosis** of the exact defect v2 fixed — it identified the triple
clock three days early. It is dated litmus evidence and its body must not be rewritten. It needs
one line saying the SPLIT it found is now closed at the producer, so a reader does not chase a
resolved finding.

**D3 · `docs/ui_redesign/API_CONTRACTS_AND_PAYLOADS.md`** — HISTORICAL-OK, header already correct
`Status: HISTORICAL`, `as_of: 2026-05-25`. `LITMUS_CC_ROUTES_2026-09-01.md:169,181-182` already
records that its endpoint table is wrong in three places. The header is doing its job; no action,
but it should not be cited as a contract source. (It currently is not.)

**D4 · `docs/COMMAND_CENTER_PAGE_MATRIX.md:328`** and
`docs/audits/overnight/CC_PAGE_CENSUS_2026-09-01.md:83-86` — CURRENT-ish, unassessed
Both describe MetricStrip tiles by their pre-v2 producers. Neither makes a claim G1–G9 refutes
directly; both would be wrong in detail after #857/#869. Flagged for the remediation pass, not
scored here — I did not verify their tile-by-tile claims against the served build.

---

### Hunt E — `account_summaries` as authoritative for position clocks

The literal phrasing the brief asked me to hunt — a doc asserting `account_summaries` **is** the
authority for position clocks — **does not appear anywhere in `docs/`.** All seven `docs/` hits
for `account_summaries` are incidental (a phantom zero-value account, a retired moomoo account, a
cash residual timestamp). Reported as a negative result, not a silent omission.

The **substance** of the concern is real, and it lives in code rather than docs:
`scripts/lib/portfolio_aggregate_contract.py:209-211` falls back to
`account_summaries.reported_total_as_of` as a position observation when no better stamp exists,
and records `obs_source = "account_summaries.reported_total_as_of"` so the borrow is visible.
That is the honest form — a named fallback with its source recorded, not an authority claim.
`:182-187` states the rule explicitly: *"It is still NOT the valuation clock … never borrow the
valuation clock to date a position."*

**Where the concern does bite is D1.** `CIO_DATA_ASOF_GAPS_2026-09-01.md:164` describes
`compute_data_as_of` as *"the oldest row across the entire"* book — a single derived clock
presented as the portfolio's freshness. That is the `account_summaries`-shaped error in its real
form, and it is already scored as P2 #18 above. No separate row is warranted.

---

## 4 · DECOMMISSION proposals — exact header text

Two documents are superseded **entirely**. Neither is deleted (§0.6). Both keep their bodies as
the historical record and gain a header block at the very top, above the existing `# title`.

### D-1 · `docs/audit/current-state.md`

Superseded because the document is a Phase-0 snapshot whose title claims the present tense and
whose central table now inverts. `:21` says `| Universal CommunicationEvent | NOT PROVEN (ABSENT) |`
and `:25` says `| /v3/communications workspace | NOT PROVEN (ABSENT) |`; `:69` says
"`CommunicationEvent@v1/v2` type, tables, or client" does not exist. All three are refuted:
13 `communication_*` tables are applied in production, the ledger holds 58 events / 57 deliveries,
and `/v3/communications` returns HTTP 200. `:26` says "45 bypass producers"; the Telegram
chokepoint baseline is now empty (`docs/audit/telegram-bypass-zero-closeout.md`).

```markdown
> **DECOMMISSIONED 2026-09-05 — superseded, retained as the Phase 0 baseline record.**
>
> This document is the **pre-gateway** snapshot, attested at `17e30dcbb`. It is no longer a
> statement of current state and its title should be read as *"Current State, as of Phase 0"*.
> Every row in its `NOT PROVEN (ABSENT)` column for `CommunicationEvent`,
> `/v3/communications`, and zero-bypass has since been closed.
>
> **Current truth lives in:**
> - Runtime readings — `docs/audit/live-attest-2026-09-05.md` (method), and
>   `docs/_findings/pre_persistent_agent_phase0_evidence_ledger_2026-09-05.md` (latest values)
> - Contract behaviour — `docs/architecture/communication-event.md`, `delivery-ledger.md`,
>   `retention.md`, `agent-contracts.md`
> - Activation grant — `docs/deployment/production-activation.md`
> - **Live mode — read `GET /api/v2/communications/health`. Do not cite any document for it.**
>
> Retained because it is the baseline the Phase 0 sign-off
> (`docs/audit/phase0-signoff.md`) was granted against. Do not delete; do not cite as current.
```

### D-2 · `docs/audit/runtime-attestation.md`

Superseded by its own successor: `docs/audit/live-attest-2026-09-05.md:9` already says
*"Supersedes `docs/audit/runtime-attestation.md`"* — but the superseded file carries no notice,
so a reader arriving directly has no signal. It still asserts `CURRENT` = `17e30dcbb…` at `:15-19`,
`producers bypassing the chokepoint: 45 … ratchet PASS — NOT zero` at `:90-93`, and
`| CommunicationEvent tables | Not present | ABSENT |` at `:37`.

Note its own `:25` rule — *"Do not claim `741207cc` is still served"* — is exactly the rule this
header enforces against `17e30dcbb`.

```markdown
> **DECOMMISSIONED 2026-09-05 — superseded by `docs/audit/live-attest-2026-09-05.md`.**
>
> This attestation is pinned to `17e30dcbb` (served 2026-09-04). It is **not** the current
> served build: `origin/main` and the serving release are both
> `f88853e89e53fdd63725acccb064ca1395e0bf34`
> (`f88853e89-main-exact-phase2-20260905-135414`), agreeing across build meta, API, service cwd
> and release ID.
>
> Its §5 bypass debt (45 producers / 133 violations) is closed — the Telegram chokepoint
> baseline is empty (`docs/audit/telegram-bypass-zero-closeout.md`). Its §2
> `CommunicationEvent tables — ABSENT` is closed: the tables are applied and populated.
>
> This file's own §1 rule applies to itself: **do not claim `17e30dcbb` is still served.**
> Retained as the attestation record for that release. Re-attestation procedure in §7 is still
> correct and still the right way to produce a successor.
```

### Not decommissioned, deliberately

`docs/audit/phase0-signoff.md` and `docs/audit/sender-inventory.md` cite `17e30dcbb` but are
**signature and disposition records**, not state claims. A signature does not go stale — it
records what was accepted, when, against which baseline. Proposal: one clarifying line each
("`17e30dcbb` is the baseline this sign-off was granted against, not a current-state claim"),
and nothing else.

Likewise `docs/_findings/P0_WORKING_TREE_IS_PRODUCTION_2026-07-29.md` and the other dated
`_findings/` entries: these are the incident record. They are already `_findings`-scoped and
dated in their filenames. Leave them.

---

## 5 · Canonical homes — where truth should live going forward

The operator asked where truth belongs. Filling in the blanks is a decision, not a finding, so
the third column is proposed and the "none" rows are the ones needing a call.

| contract / subject | code | canonical doc home | state |
|---|---|---|---|
| `CommunicationEvent@v2` | `scripts/lib/comms/event.py`, `client.py` | `docs/architecture/communication-event.md` | exists · needs OVERWRITE (#1) |
| `ChannelDelivery@v1` | `scripts/lib/comms/delivery.py` | `docs/architecture/delivery-ledger.md` | exists · needs OVERWRITE (#3) |
| `SubjectThread@v1` | `scripts/lib/comms/subject_memory.py` | `docs/architecture/subject-memory.md` | exists · CURRENT |
| `CurationReceipt@v1` | `scripts/lib/comms/curation.py` | `docs/architecture/curation-and-provenance.md` | exists · CURRENT |
| `RetentionDecision@v1` | `scripts/lib/comms/librarian.py` | `docs/architecture/retention.md` | exists · needs OVERWRITE (#14) |
| `AgentConsumptionReceipt@v1` | `scripts/lib/comms/agent_contracts.py` | `docs/architecture/agent-contracts.md` | exists · needs OVERWRITE (#14) |
| gateway enforcement / ratchets | `scripts/lib/comms/enforcement.py` | `docs/architecture/gateway-enforcement.md` | exists · stale at `:35` (~45 files / ~133 violations; now zero) |
| gateway channel adapters | `scripts/lib/comms/channel_adapters.py` | `docs/architecture/channel-adapters.md` | exists · needs OVERWRITE (#13) |
| `/v3/communications` page | `scripts/communications_portal.py` | `docs/architecture/communications-workspace.md` | exists · needs OVERWRITE (#2) |
| **live gateway mode / ownership** | — | **`GET /api/v2/communications/health` — the endpoint, not a file** | see Hunt B |
| **`PortfolioAggregate@v2`** | `scripts/lib/portfolio_aggregate_contract.py` | **none — propose `docs/architecture/portfolio-aggregate.md`** | **MISSING** |
| **`TodayPnl@v1`** | `scripts/api_v2.py` | **none — propose `docs/architecture/today-pnl.md`** | **MISSING** |
| **`QuoteSelection@v1`** | `scripts/lib/quote_selection_contract.py` | **none — propose `docs/architecture/quote-selection.md`** | **MISSING** |
| **`SetupRunSummary@v1`** | `scripts/lib/setup_run_contract.py` | **none — propose `docs/architecture/setup-run-summary.md`** | **MISSING** |
| **`DesignFeatures@v1`** | `scripts/lib/design_features.py` | **none — propose `docs/architecture/design-features.md`** | **MISSING** |
| **`ResearchProviderTruth@v1`** | `scripts/lib/research_provider_truth.py` | **none — propose `docs/architecture/research-provider-truth.md`** | **MISSING** |
| Brave local cost policy (25/day, 850/mo) | `research_provider_truth.BRAVE_LOCAL_COST_POLICY` | that constant is the single explanation site; `docs/AGENT_ROSTER.md` must cite it, not restate it | needs OVERWRITE (#6) |
| search budget ledger | `scripts/lib/search_budget.py` | `docs/audits/overnight/F3_SEARCH_BUDGET_2026-08-31.md` + `W5_…_2026-09-01.md:96` | ledger split unresolved — **operator decision** |
| header campaign narrative | — | `docs/CHANGELOG.md:7-20` | CURRENT · today the *only* home for two of six contracts |

**Standing rule worth writing into `docs/A1A.md`, proposed:** a contract that ships without a
`docs/architecture/<name>.md` is not finished. Four of the six header contracts shipped without
one, and the campaign that produced them was specifically about producers telling the truth about
themselves.

---

## 6 · Two mechanical constraints on any remediation pass

1. **`docs/INDEX.md` is generated and CI-gated.** Its first line reads
   `<!-- GENERATED by scripts/report_docs_inventory.py — do not hand-edit -->`, and
   `scripts/run_cio_hardening_ci.py:914` fails the build on `docs_index_drift`. Adding, renaming
   or removing any file under `docs/` — including the six proposed contract docs — **requires**
   `python3 scripts/report_docs_inventory.py --write-index` in the same commit. This file
   (`phase3_documentation_truth_audit_2026-09-05.md`) is uncommitted and therefore has not yet
   drifted the index; committing it will.

2. **The two hand-maintained narrative indexes do not know either campaign exists.**
   `docs/DOCUMENTATION_INDEX.md` (Updated 2026-08-27) and `docs/project/PROJECT_DOC_INDEX.md`
   (`as_of 2026-08-26`) contain **zero** entries for `docs/audit/`, `docs/architecture/communication-event.md`,
   `docs/deployment/`, `docs/testing/`, `docs/final/`, or any header-campaign contract. Both
   declare themselves authoritative for *what is current*
   (`docs/INDEX.md:7-8`: *"Hand-maintained narrative indexes remain authoritative for what is
   current"*), and `docs/A1A.md` Step 5 makes updating them mandatory. Roughly 25 documents
   from the last two days are invisible to the indexes a reader is told to trust. Scored as
   P2 #22; arguably it belongs higher, because it is the reason a reader would find
   `current-state.md` before `live-attest-2026-09-05.md` in the first place.

   Unverified: `docs/DOCUMENTATION_INDEX.md:4` declares
   `Scope: Project root = /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild`. That path is
   a live worktree (`git worktree list`, detached at `077d1b2d8`), but whether it is still the
   intended canonical root for this index is **not something I measured**.

---

## 7 · Requires Drive access — unassessed

Flagged, not judged. None of these were opened; no verdict is implied either way.

| item | why unassessed |
|---|---|
| `Trade_AI_Docs_v2/governance/agent-policy/AGENTS.md` (Drive mirror) | Named at `AGENTS.md:11` as `Drive-Mirror-Path`. Whether the mirror carries the current PROPOSED 1.2.0 is unknown. `docs/ops/AGENTS_DRIVE_MIRROR_MANIFEST.json` is the stated reconciliation artifact. |
| "Drive truth index stale" (P1) | Carried as open in `docs/_findings/pre_persistent_agent_phase0_evidence_ledger_2026-09-05.md:170`, which states plainly: *"not assessed here; requires Drive access"*. Unchanged by this pass. |
| Drive "gateway remediation plan" | Cited as the design source by `docs/architecture/curation-and-provenance.md:6` and `docs/audit/gap-analysis.md:4`. Whether the repo docs still match it is unknown. |
| Drive closeouts referenced by `docs/audit/runtime-attestation.md:7` | That line subordinates Drive closeouts to runtime measurement, which is the right rule; it does not tell us whether the Drive copies were corrected. |
| `Trade_AI_v12_Reference_Architecture.docx` | Canonical per the memory index, updated per version. Not in this tree. |
| `docs/project/SYSTEM_FACTS_LATEST.md` | Declared Drive-synced and gitignored on main by `docs/LIVE_SYSTEM_FACTS.md:19`. |

---

## 8 · Recommended order, if the operator approves

Sequenced so that each step's output is what the next step cites.

1. **Hunt B form change** across all 11 mode-asserting docs (#4, #5, #11, #12, #13, and the
   delivery-ledger/pre-go-live/canary-results/implementation-record/live-attest rows). One shape,
   applied uniformly. This is the change that stops the class of defect recurring, and it makes
   every later step's citations stable.
2. **The three `delivery_owned` invariants** (#1, #2, #3) — a false safety invariant on an egress
   control is the highest-consequence wrong sentence in the set.
3. **The two DECOMMISSION headers** (§4) — cheap, purely additive, and they stop a reader
   landing on `current-state.md` and believing `CommunicationEvent` is ABSENT.
4. **Brave authority** (#6, #7, #16, #17). Note #16 is a genuine behavioural correction
   ("retired" vs. spending today), not just a framing fix.
5. **G6 corrections** (#14, #15) — retention and receipts are documented as darker than they are;
   under-claiming is a smaller harm than over-claiming but it still misdirects the next audit.
6. **Header-contract doc homes** (§5, six missing files) — needs an operator call on whether to
   create them, and carries the `docs/INDEX.md` regeneration requirement from §6.1.
7. **The two narrative indexes** (#22) — last, so it indexes the finished state rather than a
   moving one.

**Not in scope and not proposed:** merging the two search-budget ledgers (§1, G8 — §0.5 forbids a
machine picking one), any edit to the signed gates in `docs/deployment/production-activation.md`
beyond the single tense fix in Hunt B, and any deletion anywhere.
