# Production bill — what “READY” means for Cross-Asset Decision Intelligence

as_of: 2026-09-29  
Authority: Operator requirement — one security, one research spine, all silos transparent  

## Shared security research — methodology (binding)

See **AGENTS.md → “Shared security research — NO SILOS (CRITICAL PATH, CIO-owned)”**.

That section is the house rule: CIO owns `SecurityResearchSpine@v1`; options / holdings /
watchlists / re-entry **read** via `view_for_silo`; they must not invent private thesis stores.
This production bill only sequences *how* that methodology reaches live (A→E).

| Approval | Meaning |
|---|---|
| **git-push** (#1360) | Code + docs onto GitHub / PR only |
| **Not yet** | Merge, promote to CURRENT, enable spine in live, go-live trading |

Push ≠ production. Production requires the checklist below.

## Your product requirement (acceptance)

> Research must not live in silos. Options, holdings, watchlists, and re-entry must all see the **same** CIO-owned research for a security, persisted in shared memory.

That is `SecurityResearchSpine@v1` (`scripts/lib/cross_asset/security_research_spine.py`):
- **Owner:** `cio`
- **Consumers:** options_desk, watchlist, reentry, holdings, hermes, cross_asset, aegis
- **Write path:** Hermes complete → `upsert_from_hermes` (flag `CROSS_ASSET_SPINE=1`)
- **Read path:** `view_for_silo(symbol, silo)` — same thesis for every silo

## Bill to production — approve these in order

### Bill A — Merge PR #1360 (code on main)
**Grant:** git-push (merge)  
**Does:** lands scaffold on `main`  
**Does not:** change live behavior  

### Bill B — Promote to CURRENT
**Grant:** `release-write` reason must include `prepare and promote #1360` (or merge SHA ≥9 hex)  
**Does:** server runs new modules  
**Does not:** write spines yet (flags still off)

### Bill C — Enable shared spine (this is the transparency bill)
**Grant:** `config-write` (or service restart after env)  
**Set:** `CROSS_ASSET_SPINE=1` on portfolio-server + CIO telegram  
**Wire:** Hermes research COMPLETE → `upsert_from_hermes` via
`scripts/lib/cross_asset/hooks.notify_hermes_result_completed` from
`cio_hermes_research._persist_stamped_result` (**CADI-011 landed**).  
**Read:** `thesis_fields_for_symbol` overlays spine; options `_research_universe_rows`
merges `spine_rows_for_root` first; reentry overlays spine summary (**CADI-012 landed**).  
**Prove:** for NFLX (or any symbol), `view_for_silo` returns identical thesis for options/watch/reentry/holdings  

**Pass criteria for Bill C:**
1. One Hermes result creates one spine row.  
2. Options universe merge includes `cio_research` lane from spine (tested).  
3. Watch / reentry / holdings callers prefer spine via `thesis_fields_for_symbol` overlay + options universe merge (CADI-012).  
4. No silo invents a private thesis when spine is POPULATED.  

**Honesty:** hermetic PASS ≠ OBSERVED. Organic “research once, every desk sees it”
requires promote of the CADI-011/012 PR + `CROSS_ASSET_SPINE=1` on live services +
one completed Hermes result that appends the spine ledger.
### Bill D — Shadow expression ranking (optional same week)
**Set:** `CROSS_ASSET_SHADOW=1`  
**Prove:** SymbolDecisionObject ledger grows; no broker calls  

### Bill E — READY for production recommendation
Only when **all** true:
1. Bill C live ≥7 days with spine coverage metrics (symbols researched → spine present %).  
2. Options + watch + reentry + holdings all call `view_for_silo` (grep gate in CI).  
3. Hermetic + one OBSERVED live canary (operator ask → spine → all silos).  
4. Historical/EV still may be CONDITIONAL — transparency can go live **before** EV ranking.  

**Important:** You can bill **transparency (shared research)** to production before EV/options superiority is READY. Those are different bars:
- **Transparency READY** = Bill C + E.1–E.3  
- **Expression EV READY** = still NOT READY until chain pricing + 30/60/90 metrics  

## Gaps still blocking full EV go-live (not blocking shared research)

- Chain-priced expected value  
- Continuous shadow timer  
- Archive replay superiority rates  
- Collar family  
- UI  

## Immediate next engineering tickets

| ID | Work | Status |
|---|---|---|
| CADI-011 | Hook Hermes complete → `upsert_from_hermes` when `CROSS_ASSET_SPINE=1` | **DONE** (hooks + `_persist_stamped_result`) — hermetic; OBSERVED after promote |
| CADI-012 | Options/watch/reentry/holdings prefer spine (`overlay` / `spine_rows_for_root`) | **DONE** — hermetic; OBSERVED after promote |
| CADI-013 | Coverage metric: % of researched symbols with spine | open |
| CADI-014 | CC API `GET /api/v2/research/spine/{symbol}` | open |

---

When you say “I need this to be production,” approve **Bill A → B → C** for transparency. Say if you want EV ranking in the same bill or as a follow-on.
