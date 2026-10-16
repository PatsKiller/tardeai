# trade-ai-scalp-live as an n8n-driven lane — 2026-10-09

> **Superseded in part — operator directive 2026-10-15 "N8N Cutover Decision" (decision D11).** All lane families are
> approved for n8n cutover except F07 (long-running daemons and `@reboot` services) and all `registry_systemd` assets,
> which stay on the server unchanged (revisit at the next architecture review). Verbatim: "The rationale that these
> workflows should remain host-side, cron-based, or external due to maturity, reliability, operational risk,
> monitoring requirements, or similar concerns is not accepted as a blocker." "If any existing documentation,
> standards, inventory notes, exception records, or implementation guidance state otherwise, consider that guidance
> superseded." Every keep-on-cron / stay-on-cron / §23.14 / `pipeline_excluded_gate` / STAY_HOST / STAY EXTERNAL /
> "not eligible for n8n" statement in this document is kept as history and is superseded for every non-F07,
> non-`registry_systemd` lane. Current dispositions: `docs/implementation/n8n-maturity/LANE_DISPOSITION_20261015.csv`
> (waves CD1-CD6); n8n schedules broker-family lanes but never holds a broker credential or calls an order route
> itself (`docs/architecture/n8n/N8N_REFERENCE_ARCHITECTURE.md` §2a).

> **Update 2026-10-09 15:25 ET — AGENTS.md 4.0.0 ACTIVE.** The operator typed
> "APPROVE_AGENTS_POLICY_4_0_0 and build the finviz API fix". The §23.3 exception below is now policy,
> applied by the follow-up PR to #1573. The allowlist has `live_arg: []`. Live still needs
> activation steps 1, 2 and 3b below, each under its own grant.

**Operator decision (2026-10-09, AskUserQuestion):** "n8n drives a governed lane (Recommended)".
- n8n owns the 5-minute schedule, the heartbeat watch, retries and stall healing.
- It starts the existing `scripts/run_trade_ai_scalp_live.py` through the governed run route: relay → gateway
  `coordination/run` → `n8n_run_executor`.
- The script still reaches Finviz and Hermes through the data broker. n8n never holds the Finviz key.
- The cron line stays as the fallback until n8n has run cleanly for several days.

## What this PR makes true (in code, nothing activated)

| Piece | State |
|---|---|
| Allowlist entry `trade-ai-scalp-live` (`config/n8n_run_allowlist.json`) | **Shadow only.** `dry_run_arg: ["--dry-run"]`, `live_arg: null`. Same `/tmp/tradeai_scalp_live.lock` (`flock -n`) as the cron line, so n8n and cron can never overlap. `timeout_s` 295, `market_gate` true. |
| `--dry-run` | Read-only plan (in RTH?, projection age, last-ok age). It runs no scan and makes no write or send. A test asserts the state root stays empty. |
| Receipt `data/runtime/trade_ai_scalp_live_last.json` (`TradeAIScalpLiveReceipt@v1`) | Written atomically on every completed cycle (`status ok`) and outside-RTH exit (`outside_rth`). `last_ok_at` carries over until the next ok. It is the executor `output_signal` and the registry `output_signal`. |
| Registry row | `output_signal` was the literal `~/trade-ai-releases/…/scalp_universe_latest.json`. `observe_signal` never expands `~`, so the lane monitor read the lane as never producing. It is now the receipt, relative to the state root like the other rows. Cron remains scheduler of record. |
| Workflows | `generated/trade-ai-scalp-live-shadow.json` and `generated/trade-ai-scalp-live.json`, tranche N7, cron `*/5 9-15 * * 1-5` America/New_York (EXACT copy; the script gates 09:30–16:00). Both are inactive. The live one is refused today (`relay_live_not_enabled` / executor `mode_unavailable:live`). |
| Stall watch | `n8n_incident_fanin.py` source 3g. On a trading day, 09:42–16:00 ET, if `last_ok_at` is more than 12 min old, it raises **one** P2 `trade-ai-scalp-live:STALLED` coordination event per UTC day. The event clears itself on the next ok receipt. No Telegram, no LLM. |

## Why live is not enabled here

The live cycle (`continuous_runner.run_live_cycle`) does three things the run list currently forbids:
- it ingests the Finviz screener (`finviz_ingestion.load_live_candidates`);
- it writes `trade_ai_scans`;
- it sends Telegram on a new GO (`send_telegram`, `continuous_runner.py:725`).

AGENTS.md 3.0.0 §23.3 says the allowlist "may never contain a … sender … or authoritative-ingest command", and
the version policy (§ version table) classes widening that list as **MAJOR**. A MAJOR change needs a ratification
token, not an agent PATCH. So this PR adds only the shadow mode, which is read-only.

### Proposed §23.3 amendment (for operator ratification)

Add after the allowlist bullet:

> **Exception — `trade-ai-scalp-live` (operator 2026-10-09).** This one lane may run in `live` mode from n8n
> although it ingests the Finviz screener through the data broker, writes `trade_ai_scans` and the scalp
> projection, and sends through `send_telegram`. Conditions:
> - It runs the exact cron argv under the cron line's lock.
> - n8n holds no provider key.
> - The send stays the host chokepoint, with GO de-duplication persisted in
>   `state/trade_ai_scalp_live_state.json`.
> - The cron line stays live until n8n has 3 market days of `RUN_DONE` with no `STALLED` finding. It is then
>   retired as `# RETIRED <date> n8n-cutover trade-ai-scalp-live`.

Ratify with `APPROVE_AGENTS_POLICY_4_0_0 <PR> <sha>`. A follow-up PR then sets `live_arg: []`.

## Activation steps (operator, each under its own grant)

1. Deploy this PR (release grant) so the receipt starts being written; the registry signal turns fresh.
2. Import both workflows into `m8m-n8n` and activate **only** `trade-ai-scalp-live-shadow` (config-write grant
   naming the workflow id from `generated/INDEX.json`). Watch `n8n_runs/` receipts: `RUN_DONE` or
   `RUN_SKIPPED_LOCK` (cron holds the lock) every 5 min.
3. ~~Ratify the §23.3 amendment~~ **done 2026-10-09 (4.0.0)**. The `live_arg: []` PR is the follow-up to #1573.
   3b. Under a config-write grant, append `trade-ai-scalp-live` to `TRADEAI_N8N_RELAY_LIVE_LANES` in
   `~/.config/tradeai/n8n-relay.env`, then `systemctl --user restart tradeai-n8n-run-relay`. Under a grant naming the
   workflow id, activate the live workflow. Cron and n8n now share the lock, and whichever fires first runs.
4. After 3 clean market days, retire the cron line (cron grant, archive the crontab first) and flip the
   registry row to `kind n8n`.

## Healing, honestly

- **Retry:** the 5-minute schedule re-requests every cycle. A run skipped on the lock or timed out is followed
  by the next request.
- **Progress across killed runs:** PR #1564 writes the catalyst cache through per symbol, so a timed-out run
  still saves its lookups. The cold-cache stall of 2026-10-09 13:30–15:00 was exactly this.
- **Detection:** the fan-in `STALLED` event.
- **Not built:** an automatic extra run with a longer budget when the lane is stalled. A host script cannot
  request a run, because only the relay holds the `coordination_run` scope. Granting that scope to another
  caller is a §23.3 change.

## Registry-dispatch eligibility (2026-10-09)

The B5 registry dispatcher (`scripts/lib/lane_dispatch.py`, PR #1595) refuses any lane whose command carries a
`pipeline_manifest.FORBIDDEN_COMMAND_TOKENS` entry. This lane wraps `scripts/market_day_gate.sh`, so it was
ineligible. `config/lane_dispatch_policy_exceptions.json` (AGENTS.md 4.0.0 §23.3; operator 2026-10-09 ~18:05 ET
"Okay to everything except extending the scout to closing") exempts this lane from **that token only**, and from
the B1 reconciler's `stay_on_cron` marker of class `pipeline_excluded_gate` naming it (PR #1597). Any other
forbidden token, stay-behind or sender rule still blocks it, and a missing or malformed exception file means no
exception. Eligibility is not dispatch: the registry row has no `dispatch` block, so its mode stays `off`.
