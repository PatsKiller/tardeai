# Claude Code Execution Prompt — Defense Desk Redesign (Stage DD-S0 + S1)

**Target:** ms01-openclaw · `/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild` · `.venv`
**Page:** `/v3/defense`
**Status:** operator-approved design, 2026-07-29. You are implementing an approved visual
specification. You are not designing.

---

## STEP 0 — PULL THE CONTRACT AND VERIFY IT

Drive folder: `Trade_AI_Docs_v2 / docs / defense_desk_redesign_v1`
Folder ID: `1dszqf6r8aCEJC_rs3iyavuxQCeVMUAB0`

| File | Drive file ID |
|---|---|
| `VISUAL_CONTRACT_defense_desk_v1.md` | `1_uZM0zap0HwWweg1yxOwyRE6KC9vLfs3` |
| `defense_desk_redesign_v1.html` | *(operator upload — see below)* |

```bash
cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
mkdir -p docs/_design/defense_desk_redesign_v1
export GOG_KEYRING_PASSWORD="$(cat ~/.openclaw/credentials/gog_keyring_password)"
# never echo, log, or commit this value
```

Download both files into `docs/_design/defense_desk_redesign_v1/`, using the same authenticated
GOG pattern `scripts/sync-docs-to-drive.sh` already uses.

**Verify the checksum. This is a hard gate:**

```bash
md5sum docs/_design/defense_desk_redesign_v1/defense_desk_redesign_v1.html
# MUST equal: 388f0ad091ad886be631b5b56d34defb
```

If it does not match, **STOP**. You have the wrong file or a corrupted download. Do not proceed on
a file you cannot verify.

**Then open the HTML in a browser and look at it.** Not `cat`, not a parse — render it. It is the
specification. Everything else is an index to it.

---

## THE ONE RULE

**The HTML file is the specification.** The visual contract document is an index. If they ever
disagree, the HTML wins.

The previous round of this work drifted because two design artifacts existed, disagreed, and
neither was authoritative. That is fixed by there being exactly one, with a checksum.

---

## HARD CONSTRAINTS

1. **IRON RULE — state check before any deploy, extraction, or cleanup:**
   ```bash
   python3 -c "import json;d=json.load(open('data/portfolios/state/holdings.json'));print(d['portfolio_totals']['total_value'],len(d.get('holdings',[])))"
   ```
   Total = 0 or count = 0 → **STOP**.
2. **Read-only page.** GET endpoints only. No POST/PUT/PATCH/DELETE. No `paper_trade_proposals`.
   No broker adapter import. Nothing on this page places, stages, or approves an order.
3. **Do not modify any strategy YAML, threshold, or screener definition.**
4. **Structure and style are frozen. Data is live.** See §1 of the contract. Replace every number;
   replace no column.
5. **Do not add anything that is not in the mockup.** Good ideas from the previous round are now in
   it. Anything else is out of scope — propose, do not build.
6. **Live schema wins.** Only `psql`, live config, and live API responses are evidence.
7. **Nulls render via the `unk` class** — italic, dim, reason on hover. Never an em-dash, never a
   zero, never a blank.
8. **No secrets** in logs, commits, screenshots, or output.

---

# PHASE DD-S0 — RECON (no UI code, stops for sign-off)

## S0.1 — Token mapping `[do this before anything visual]`

The contract lists 15 literal color values. `/v3/defense` already defines CSS variables.

```
- For each of the 15, find the existing variable on the page carrying that value
- Report the mapping as a table: mockup literal -> existing var -> exact match Y/N
- Where no existing variable matches, say so — do NOT create a near-duplicate
```

This is the specific failure from last round: the reference JSX named `--at-*` (Active Trader
tokens) while `/v3/defense` runs the v3 slate family. Settle it here, in writing, before a line of
component code.

## S0.2 — Data availability per section

Nine sections. For each, report what already has an endpoint, what needs one, and what cannot be
sourced at all.

Specific items to check, because the mockup shows them and they may not exist:

```
- Sector rank per position (Your book column 3) — does the join exist?
- "Read" text per transition (Transitions column 6) — generated or authored?
- Rank-change arrows on the 11-sector picker strip
- Industry composite % ("composite +11.8%")
- Freshness age per data source, for the command-strip chips
- "2 sectors stale >5d" — is staleness computed anywhere, or does the card compute it?
```

Anything unsourceable renders through `unk` with a reason. Report which ones that will be.

## S0.3 — What already exists

```
- The current /v3/defense component tree: files, component names, how sections are composed
- Which sections in the mockup map to an existing component that can be restyled
- Which require new components
- The Sector Leaders card shipped at da237c2b — how much survives the restyle?
- The quadrant and ranked lists — confirm they are PRESERVED, not rebuilt (contract §5)
```

## S0.4 — The flag discrepancy `[open defect]`

The deployed bundle reads *"behind SECTOR_LEADERS_V1, **default on**"*, while the handoff reported
the flag as OFF. Determine which is true in the running config and report it. The operator has been
seeing the card without opting in.

## S0.5 — The dispersion bug `[contract §6]`

Production renders `buy names` for Oil & Gas Integrated: spread 38.1pp, top-quartile excess
**−9.14pp** vs XLE, n=14. A wide spread whose top quartile underperforms the ETF is not a buy
signal.

```
- Locate the verdict logic and quote it
- Confirm spread and excess are being read independently
- Propose the fix: negative excess must veto "buy names" at any spread
```

Do not fix it in S0. Report it.

## S0 DELIVERABLE

`docs/_findings/defense_redesign_recon_<YYYY-MM-DD>.md` with every section above, command run, and
actual output. Plus the token mapping table, the per-section data availability matrix, and an
explicit answer on the flag state.

**Stop. Report in chat. Do not begin S1 without sign-off.**

---

# PHASE DD-S1 — IMPLEMENTATION (after sign-off)

## Build order

1. Token mapping applied — no new variables where existing ones match
2. Section 6 preserved, container styling matched only
3. Sections in mockup order, one at a time, each verified in the browser before the next
4. Dispersion logic fix with a test asserting negative excess vetoes "buy names"
5. Everything behind a single feature flag, **default OFF in committed config**

## Acceptance is a screenshot comparison, not a judgment

Run the identical harness on both sides:

```python
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={'width': 1760, 'height': 1200}, device_scale_factor=2)
    pg.goto(URL)              # file:// for the mockup, http:// for the build
    pg.wait_for_timeout(600)
    pg.screenshot(path=OUT, full_page=True)
    b.close()
```

Deliver `reference.png` and `build.png` side by side. Then walk all nine sections and state
**match / deviation / not built** for each.

## Deviation log — mandatory

Reality will not fit the mockup everywhere. Write it down rather than deciding silently. Per
contract §8, record what the mockup shows, what you built, why, and whether it needs sign-off.

**Always needs sign-off before shipping:** a section omitted · a column added, removed, or
reordered · a token value not in the manifest · any change to what a chip color means.

**Log but proceed:** real data producing different row counts · a field rendered via `unk` because
the API cannot supply it · text wrapping differently with real strings.

---

## WHAT NOT TO DO

- Do not proceed if the md5 does not match.
- Do not design. Every visual decision is already made.
- Do not add a feature, column, section, or control that is not in the mockup.
- Do not substitute a palette because it seems to fit better.
- Do not rebuild the quadrant or the ranked lists.
- Do not render a null as an em-dash, a zero, or a blank.
- Do not add a write endpoint of any kind.
- Do not leave the feature flag ON in committed config.
- Do not fix unrelated bugs — log under `INCIDENTAL OBSERVATIONS`.
- Do not mark DONE without both screenshots and the nine-section walk.

---

## ACCEPTANCE CRITERIA

**S0:**
- [ ] IRON RULE state check, output shown, non-zero
- [ ] `md5sum` matches `388f0ad091ad886be631b5b56d34defb` — paste it
- [ ] Token mapping table, all 15 values
- [ ] Per-section data availability matrix
- [ ] Explicit flag-state answer (S0.4)
- [ ] Dispersion logic located and quoted (S0.5)
- [ ] Findings doc written; **stopped for sign-off**

**S1:**
- [ ] `reference.png` and `build.png`, same harness, same viewport, side by side
- [ ] Nine-section walk: match / deviation / not built
- [ ] Deviation log complete
- [ ] Dispersion fix with a test asserting negative excess vetoes "buy names"
- [ ] Numbers render in mono with tabular-nums — screenshot a column of figures
- [ ] A null renders via `unk` with a hover reason — screenshot
- [ ] Quadrant and ranked lists unchanged in substance — screenshot
- [ ] `grep` proof no POST/PUT/PATCH/DELETE added
- [ ] Flag OFF in committed config after deploy — show the config
- [ ] Full suite with baseline comparison — paste both numbers
- [ ] `git status` clean outside authorized files

---

## SCOPE ESTIMATE

| Phase | Effort |
|---|---|
| S0 recon | 2–3 h — token mapping and data matrix are most of it |
| S1 sections 1–4 | 3–4 h |
| S1 section 5 | 2–3 h — partly built already at da237c2b |
| S1 sections 7–9 | 2–3 h |
| S1 comparison + deviation log | 1 h |

Two sessions with a sign-off between. Deploy after the close.
