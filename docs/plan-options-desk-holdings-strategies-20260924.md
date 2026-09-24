# Plan: Options Desk — holdings strategies · open legs · CIO fluency · goals · BUY_READY institutional packet

```
Status: ACTIVE
as_of: 2026-09-24T12:25:00-04:00
Measured at: hub holdings · options_desk_latest V=CC · PR #1215 head 7e02f36eb (1B remote) · local packet+P8+holdings-resolve implement · tests 16 pass · implement + addenda 12:08/12:16/12:17 ET
Canonical store path (parent / SoT):
  /home/johnclaw/.local/state/cursor/agent-stores/cursor_agent_stores/bc-5f36c3f9-c05b-4ca3-983d-4b3c5b7889ec/files/docs/plan-options-desk-holdings-strategies-20260924.md
Repo mirror: docs/plan-options-desk-holdings-strategies-20260924.md
Companion skim: docs/options-desk-operator-contract-20260924.md — linked; **this file is authoritative**
Authority: operator product contract (John) + implement approval 2026-09-24 · holdings-backfill addendum · AXTI ENTRY_NEAR addendum · CreatePlan overview mirrored here (CreatePlan artifact is NOT edited)
Supersedes: 12:10 SoT — adds holdings latest-of-record backfill honesty; AXTI ENTRY_NEAR litmus; ATR/HV structure preference; MAA chrome scrub on entry alerts
See also: AGENTS.md §2/§6/§17 · scripts/lib/cio_options_fluency.py · scripts/lib/cio_entry_state.py · scripts/options_engine.py · scripts/lib/cio_goals.py · artifacts/plans/buy_ready_options_cio_59a1a12f.plan.md (read-only)
Drive: file 1FeLYTz9TIhcd_-j13NoGhVKBYlgaXl3Z · parent 1Zxc20B5Xo24RGZ1Pow1-uW6ldASQJHiR
```

**One-line verdict.** Path B + Schwab chain are **built**. Funnel (1) + open-leg honesty (1B) on PR #1215. This implement wires **institutional BUY_READY/ENTRY_NEAR packet** (equity + options + compare + CIO verdict + P8 + former-holding context), **latest-holdings CC/put backfill with named drop reasons**, and **entry alert chrome scoped to primary symbol** (no MAA bleed). Push/merge still need grants + CI green.

---

## A · Full product contract (P1–P8)

| # | Operator ask | Status | Stage |
|---|---|---|---|
| **P1** | CC/CSP/puts/spreads + Schwab chain + Path B 2FA · **refresh from latest holdings**; propose only when gates+edge clear | PARTIAL/BUILT — generators+chain+Path B; `_load_holdings` now newest-of-record | **1** CLOSED · **2** operator intent |
| **P2** | Open-leg P&L / margins / sell-hold-roll criteria | PARTIAL→1B on PR | **1B** pushed `7e02f36eb` |
| **P3** | CIO knowledgeable on all desk strategies | WIRED — catalog + `options_strategy` intent | **1C** |
| **P4** | CIO advises/opines via real desk / `finalize_operator_reply` | WIRED — house-facts card + packet CIO verdict chrome | **1C** |
| **P5** | Strategy goals → security / sector / industry | Lineage stamps + `create_goal` additive kwargs; **no auto-mint** | **1C** · **2G** operator mint |
| **P6** | **Institutional packet on BUY_READY and ENTRY_NEAR** (and reentry replies) — equity + options alt + compare + CIO Approve/Reject/Modify + Path B | **WIRED** `build_buy_ready_packet` | **1D** |
| **P7** | Holdings funnel (named drop reasons) — **silent omit is a defect**; every owned name gets a status | **CLOSED** + holdings_source stamp | **1** |
| **P8** | Thesis vs structure — PE for thesis; IV/HV/**ATR**/expected-move/Greeks for structure. Elevated ATR vs stop prefers citing defined-risk options. PE ≠ strike picker. | **WIRED** | **1D-indicators** |

**Non-goals:** invent strategies · widen IV/intent · invent margin $ · auto-submit · fake specialists · auto-mint goals · Deep ITM paper as live health · every holding gets an options play.

---

## A1 · Holdings backfill addendum (operator 2026-09-24)

**Rule.** Covered-call / protective-put (and related income/hedge) generation continuously refreshes from **latest holdings of record** (served/persistent preferred over stale worktree sleeve).

| Requirement | Enforcement |
|---|---|
| Latest holdings | `options_engine._load_holdings` picks newest readable `holdings.json` among `portfolio_state_write_targets` + checkout |
| Propose only when gates + economically good | Existing edge/IV/size/POP floors — **not widened** |
| Not every holding gets a play | Funnel names drop: `NEED_100_SHARES` · `IV_BELOW_FLOOR` · `EDGE_BELOW` · `NO_CHAIN` · … |
| Silent omit = defect | `build_holdings_funnel` scans every non-cash row; summary stamps `holdings_source` |
| No unilateral IV/intent widen | Unchanged floors; intent sleeve still operator-owned |

---

## A2 · Google Notes gap analysis — V BUY_READY + AXTI ENTRY_NEAR

### V BUY_READY (example)

> Entry state BUY_READY for V … price $367.53, zone $364.50–$369.00, stop $357.50, target $410.00, R:R 3.57. Plan source reentry_desk.

| Expectation | Status after this implement |
|---|---|
| Equity + size/R:R | Packet equity block |
| Capital-efficient options alt | Prefer long_call/debit; V cache=CC → `WRONG_STRATEGY_CLASS` honesty |
| Comparative capital / max loss / BE | When alt OK; equity capital hint always |
| CIO Approve/Reject/Modify | `cio_verdict` token on packet |
| P8 thesis / structure | PE in thesis; IV/ATR in structure |
| Path B 2FA | Packet chrome |
| Wrong secondary ticker chrome (MAA) | Entry `operator_send` sets `primary_symbols=[sym]` |

### AXTI ENTRY_NEAR (addendum 12:17 ET)

> ENTRY_NEAR AXTI: price $72.93, zone $62–$66, stop $58.50, target $96.50, R:R 4.07, reentry_desk. Formerly owned. High ATR / daily vol → prefer defined-risk options vs full equity.

| Expectation | Status |
|---|---|
| Same institutional packet on ENTRY_NEAR | `render_operator` / `render_cio` / `format_reentry_symbol_reply` |
| Elevated ATR vs distance-to-stop | `volatility_elevated` → preference note + `APPROVE_OPTIONS_PREFERRED` / `MODIFY_OPTIONS_WANTED` |
| Former-holding context | `former_holding_context` — not silent |
| Litmus test | `test_axti_entry_near_vol_prefers_options` |

---

## A3 · Meta-prompt roles → Trade-AI module map (locked)

| Meta-prompt role | Trade-AI owner | Notes |
|---|---|---|
| Signal Generation | `reentry_desk` + `cio_entry_state_runner` | BUY_READY / ENTRY_NEAR |
| Quant Validation | `options_engine` + Schwab chain / Greeks | Cache-first on notices; live chain on Hub View Chain |
| Options Strategy | `options_engine` STRATEGY_SLOTS + pipeline matcher | long_call / debit / credit / deep_itm paper when gated |
| Portfolio Risk | holdings + desk risk / heat | Attach when available — never invent margin $ |
| CIO Review | `cio_operator_desk_loop` + `finalize_operator_reply` + packet `cio_verdict` | Approve / Reject / Modify — **no fake Iris/Alex** |
| Compliance | Path B preflight; advisory chrome; MBI_BEHAVIOR=0 | |
| Operator Authorization | Path B per-order 2FA | Never bypass |

---

## A4 · Production CIO / options prompt (house text)

```
You are the Trade-AI CIO desk (READ_ONLY_ADVISORY). Review BOTH:
  (A) equity BUY_READY / ENTRY_NEAR packet and (B) any options alternative.
Return exactly one of: APPROVE | REJECT | MODIFY_<what>.
Cite Sources from house facts only. Never invent PE, IV, strikes, or margin $.
If options unsuitable, say so with indicator causes (IV/liquidity/DTE/class/ATR).
When ATR/HV is elevated vs distance-to-stop, prefer citing defined-risk options
as capital-efficient expression — still no orders from chat.
PE/fundamentals grade the equity thesis; IV/ATR/expected-move/Greeks grade structure —
do not use PE to pick strikes. Path B 2FA required before any live submit.
Formerly-held / reentry context must be opined on, not dropped.
No specialist roleplay.
```

---

## B · Diagnosis receipts (measured)

### B1 Holdings / Path B / funnel
Schwab chain + Path B **BUILT**. Funnel API **CLOSED** Stage 1. Holdings load now **newest-of-record**.

### B2 Open legs
Stage 1B honesty pushed `7e02f36eb`.

### B3 CIO fluency / goals
Catalog + `options_strategy` intent. `create_goal` accepts optional `linked_sector` / `linked_industry` / `strategy_id`. **No auto-mint.**

### B4 BUY_READY / ENTRY_NEAR packet
`build_buy_ready_packet` + renders on entry notices and reentry symbol replies. V wrong-class honesty. AXTI vol-prefer. Primary-symbol chrome scrub on entry alerts.

---

## C · Stages

### Stage 0 — Clarity — FIX
Unprotected≠no CC; Deep ITM≠live; “30 need action”≠option closes.

### Stage 1 — Holdings funnel + latest-holdings backfill — **CLOSED** (PR #1215 · `ab2653724`) + load-path fix this implement
Acceptance A1.1–A1.6. Addendum: newest holdings; named drops; no IV widen.

### Stage 1B — Open-leg honesty — **CLOSED on remote** (`7e02f36eb`)

### Stage 1C — CIO fluency + strategy goals — **WIRED**
Catalog; intent; lineage stamps; additive `create_goal` fields; no auto-mint.

### Stage 1D — Institutional packet — **WIRED (local; push pending)**
BUY_READY **and** ENTRY_NEAR (entry renders + reentry reply when inside/near zone):

1. Equity packet  
2. Options alt or honest NONE (`WRONG_STRATEGY_CLASS` · `NONE_ON_CACHE`)  
3. Comparative capital / max loss / breakeven when alt OK  
4. CIO verdict token  
5. Path B chrome  
6. Former-holding / reentry note  

### Stage 1D-indicators (P8) — **WIRED (local; push pending)**
Thesis: PE / fwd PE / PEG / catalyst / sector. Structure: IV / ATR / expected-move / Greeks / OI / DTE. Elevated ATR→options preference citation. PE≠strike (test A1D.P8.4).

### Stage 2 / 2G / 3 / 4 / 5
Unchanged: intent map operator-only; mint options goals operator-only; low-VIX policy; protective-put funnel expansions; out-of-scope list.

---

## D · Action map

```
Force scan → proposals from latest holdings (no orders; not every name)
View Chain → Schwab RO
Sell/Buy/Spread ARMED → preflight → 2FA (Path B)
BUY_READY / ENTRY_NEAR notice → institutional packet → operator chooses → Path B
CIO options ask → house facts + finalize_operator_reply
```

---

## E · Test / acceptance matrix

T1–T6 Stage 1 · T8–T11 Stage 1B · T12–T17 Stage 1C · T18–T23+A1D.7–9 Stage 1D · A1D.P8.* · **AXTI ENTRY_NEAR litmus** · **V BUY_READY litmus** · T24 Path B · T25 Unprotected · T26 Drive SoT · holdings_source on funnel.

**Binding litmus:**
- **V BUY_READY** — equity + alt **or** unsuitable with causes; CIO verdict; PE thesis / IV+ATR structure; Path B; no wrong-class as “good alt.”
- **AXTI ENTRY_NEAR** — same packet; elevated ATR cites options preference; formerly-held noted; compare when alt OK.

---

## F · Immediate operator read

1. Schwab + Path B work. 2. Funnel+1B on #1215. 3. Packet+P8+AXTI wired locally — **need git-push grant** to land on PR. 4. Merge/promote when CI green (no `--admin`). 5. No IV widen / no invented margin / no fake specialists / no auto goals.

---

## G · Evidence commands

```bash
curl -sS http://127.0.0.1:7777/api/v2/options/holdings-funnel | jq .data.summary
PYTHONPATH=scripts:. python3 -c "from scripts.lib.cio_options_fluency import build_buy_ready_packet as b; print(b({'symbol':'V','state':'BUY_READY','price':367.53,'entry_low':364.5,'entry_high':369,'stop':357.5,'target':410,'rr':3.57,'plan_source':'reentry_desk'},{'pe':31,'held':True,'atr':4})['cio_verdict'])"
PYTHONPATH=scripts:. python3 -m pytest tests/test_cio_options_fluency_20260924.py tests/test_options_holdings_funnel.py -q
```

---

## H · Develop now vs later

| Work | Now? |
|---|---|
| SoT P6/P8 + holdings backfill + AXTI | **Done this pass** |
| Stage 1D packet + P8 + chrome scrub | **Done local** |
| Stage 1C lineage stamps | **Done local** |
| Push commits onto PR #1215 | When git-push granted |
| Merge+promote #1215 | When CI green; no --admin |
| Stage 2 / 2G / 3 | Operator |

---

## I · Drive sync

```bash
gog drive upload --replace 1FeLYTz9TIhcd_-j13NoGhVKBYlgaXl3Z \
  <parent-store>/docs/plan-options-desk-holdings-strategies-20260924.md
```

Never `gog drive upload --dry-run`.

---

## J · Stage closure receipts

| Stage | Status | Evidence |
|---|---|---|
| Stage 1 funnel + latest holdings | **CLOSED** + load fix | PR #1215 · `ab2653724` · `_load_holdings` newest-of-record |
| Stage 1B open-leg | **CLOSED remote** | `7e02f36eb` |
| Stage 1C fluency/goals | **WIRED** | catalog + lineage + create_goal kwargs |
| Stage 1D packet | **WIRED local** | `build_buy_ready_packet` · V+AXTI tests |
| Stage 1D-indicators P8 | **WIRED local** | thesis/structure · A1D.P8.4 |
| Stage 2 / 2G | **OPEN — operator** | |
| Promote | **PENDING** | CI green + merge + release-write |
| Drive SoT | **THIS REVISION** | replace after write |
