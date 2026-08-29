# S0 operator loop — mint, attach, turn_id, rehydrate (2026-08-29)

> The instruction arrived headed "re-run the critique on SPCX", with a body
> whose pins say **no `--backend live`** and **"No Grok hop unless a separate
> prompt says so"**. A critique re-run is exactly that hop, so the body was
> followed and the header flagged rather than silently chosen between.

## The cause of "the desk only knows SCHD"

The live book still shows it. The S0 plan for *"alex what can i reenter n…"*
carries:

    symbols: []

Free-text operator questions minted an `S0_OPERATOR_CONVERSE` with **no
symbol**. No symbol means no `registry[symbol]` load, no thesis, no prior
artifact, no operator history. SCHD looked special only because it already
carried a defer from an earlier, hand-built path.

`extract_symbols` was already written — in `cio_telegram_converse`. It was
**never wired into `cio_converse_core.process_operator_message`**, the
channel-agnostic path that actually mints. No new extractor was written; the
existing one is now reachable from the mint path.

## 1. Mint vs attach

| input | action |
|---|---|
| "what about RTX", no open RTX plan | **mint** one S0 draft, symbol RTX |
| "SCHD defer, wait for price buffer" | **attach** to `plan_schd_s6` |
| explicit `plan_id` (thread reply) | **attach**, `explicit_plan_id` |
| "what should i do today" | **refuse**, `no_symbol_extracted` |
| TEST / CASH / dust | **refuse**, recorded not minted |

**Attach beats refuse.** An ack on a dust name still means something when a
plan is already open — refusing there would drop a real operator signal.

**Closed plans are not attach targets**, so a cancelled plan cannot silently
swallow a new turn.

This is what stops a second SCHD S6 opening every time the operator defers.

## 2. Rehydrate before research

`rehydrate(symbol)` returns open plans and kinds, prior research outcome and
artifact ids, latest artifact, bound lessons, and the operator's last turn — in
one read, each field degrading independently so a missing store narrows the
bundle rather than emptying it.

`gate_input_from()` shapes it for `ResearchNeedDecision@v2`, and critically
carries `prior_outcome` — so a subject with a tainted or already-VALID artifact
is routed by the ladder instead of paying for a fresh first pass. A test asserts
an `execution_language` history routes to `skip`.

## 3. `operator_turn_id`

Stable id from `(symbol, text_hash, timestamp)`. Persisted to
`data/cio/cio_operator_turns.jsonl` with `plan_id`, `symbol`, `text_hash`,
`intent`, `created_at`.

**The store keeps a hash, not the words.** A product surface therefore cannot
leak an operator message it was never asked to display — asserted by test.

`operator_last_line()` generalises the SCHD pattern: *"operator last: defer
(2026-08-29)"*, intent and date only.

## 4. Symbol thesis honesty

`thesis_coverage()` reports held non-dust names with and without a symbol
thesis. Missing reads `RESEARCH_REQUIRED`; `auto_minted` is `False` and tested.

Stamping `desk@v5` on twenty names the desk has never reasoned about would make
coverage look complete and mean nothing. **The gap is the finding.**

## 5. Product

S0 rows are visible on the Command Center block (`s0_operator_turns`,
`s0_open_n` — 6 open today), while the notification policy **suppresses** S0:
notifying the operator about their own message is noise by definition.
`would_send` stays false.

## Verification

29 S0 tests; 626 green across the S0 / 3B / 3C / 3E / question-id surface;
acceptance green with dark contracts clean.

Dry eligible unchanged — **4 (2 flash, 2 grok_critique), 0 paid calls**. No
explosion into 36 Flash jobs.

`cio_command_center.py` is CRLF; edited via `safe_text_edit`, 1475 → 1489 CRLF,
**0 stray LF**.

## Not done

No critique re-run, no `--backend live`, no Grok hop, no notify-on, no new
Telegram send or digest cron, no cap raise, no R1 widen, no checkpoint history
rewritten, no theses auto-minted. MBI 0, ROTATE advisory-only.
