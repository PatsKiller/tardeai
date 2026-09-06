# The governed model bridge — caps, callers, and how it fails

**Status:** documented 2026-09-06 after a full-day outage of the paid lane
**Service:** `cio-governed-bridge.service` (systemd **user** unit) on `127.0.0.1:8766`
**Code:** `scripts/lib/cio_governed_model_bridge.py`

---

## 1. What it is

Every paid model call goes through this one process. It resolves policy, reserves budget, enforces
caps, settles actual cost, and runs a circuit breaker. It is the chokepoint that makes
`LLM_GLOBAL_DAILY_USD_CAP` mean anything.

It is **one Python process**. Restarting it is:

```bash
systemctl --user restart cio-governed-bridge     # scope: service. NOT sudo, NOT a reboot.
```

`:8766` is unavailable for a few seconds. Nothing else is touched.

## 2. Caller identity is server-side and is NEVER taken from the caller

```
client sends   X-TradeAI-Agent: advisory_desk        (HERMES_BRIDGE_AGENT, default advisory_desk)
bridge maps    CALLER_PROCESS_MAP[advisory_desk] -> advisory_desk_opinion
```

**A caller-supplied `process_id` or `model_id` is never trusted.** That is deliberate: if a script
could name its own budget it could name one with no cap. The consequence is that **you cannot give
a job its own budget by relabelling it** — the mapping is code, and code changes need a restart.

## 3. There are FOUR caps, and they are not all about money

Enforced in `llm_consumption.reserve_projected_cost`:

| cap | source | failure |
|---|---|---|
| process dollar | `llm_process_config.daily_cost_cap_usd` | `COST_CAP_EXCEEDED: process cap` |
| global dollar | `LLM_GLOBAL_DAILY_USD_CAP` (env, `.env`) | `COST_CAP_EXCEEDED: global cap` |
| **process REQUEST COUNT** | `llm_process_config.daily_soft_cap` | `COST_CAP_EXCEEDED: daily request cap` |
| circuit breaker | in-process | breaker open |

**The request-count cap is the one that surprises you.** On 2026-09-06 the usefulness backfill
stopped dead after exactly 200 calls having spent **$0.0742 of a $0.30 budget** — 25% of the money,
100% of the count. Every caller saw `HTTP 500`, which reads like a broken provider and is not.

**Read the error body before diagnosing.** The status is 500; the cause is in the JSON:

```json
{"error": {"code": "RESERVATION_FAILED",
           "message": "COST_CAP_EXCEEDED: daily request cap", "status": 500}}
```

The bridge's own log records only `"POST /v1/chat/completions HTTP/1.1" 500 -` with no reason, so
the log will not tell you. Nor will a `curl` without `X-TradeAI-Agent` — that returns 401 and looks
like an auth problem instead.

## 4. Projections are ~17× actual, so a dollar cap bites ~17× early

`ledger_paid_usd_today` counts `projected_usd` for **reserved** holds and `actual_usd` for
**settled** ones. Measured on 2026-09-06:

```
200 reservations   projected $1.2639   actual $0.0742   ->  17x over-estimate
```

The cause is `HERMES_CLOUD_MAX_TOKENS` (default **4096**) reserving for a response that is a
one-sentence JSON of roughly **60 tokens**. A caller with a small, known response should pass a
realistic value:

```bash
HERMES_CLOUD_MAX_TOKENS=256 python3 scripts/hermes_external_feedback_loop.py --apply
```

**Fixing the estimate is worth more than raising the cap.** At a true rate of ~$0.00006 per call,
`$0.50/day` buys about 8,000 calls; against a 17× projection it buys about 470.

## 5. Reservations that never settle hold budget for ever

Policy in `ledger_paid_usd_today`: `reserved` counts projected, `settled` counts actual, `released`
counts zero. A hold that is never settled therefore consumes budget permanently.
`recover_stale_reservations(max_age_minutes=30)` runs on each reserve, which is what stops that
becoming a slow leak. The docstring records a real incident: sixteen `test_*` rows carrying
synthetic amounts were 99% of one day's apparent $2.72 spend against $0.0141 of real production
cost, and two never settled and blocked a live hop.

## 6. Operational facts that cost time on 2026-09-06

- **It had been running 10 days**, from the release of 2026-08-27, and logs into *that* release's
  `logs/` directory — not the current one. A bridge code change is not live until it is restarted,
  and `journalctl` shows almost nothing because output is redirected.
- **`GET /health` returns 501.** It is POST-only. A 501 there is not a fault.
- **`curl` without `X-TradeAI-Agent` returns 401**, and with an unmapped agent returns
  `Unknown caller … not in server-side mapping`. Neither is the bug you are chasing.

## 7. Changing a cap

Dollar and request caps are **rows**, read per request — no restart needed:

```sql
SELECT process_id, mode, daily_soft_cap, daily_cost_cap_usd
  FROM llm_process_config WHERE process_id = 'advisory_desk_opinion';

UPDATE llm_process_config
   SET daily_soft_cap = 30000            -- 2026-09-06: was 200, raised on operator direction
 WHERE process_id = 'advisory_desk_opinion';
```

**Record the previous values in the change.** `advisory_desk_opinion` was `200 / $0.30` before
2026-09-06.

Adding a *new* process, by contrast, needs a code change to `CALLER_PROCESS_MAP` **and** a restart,
because caller identity is server-side. That is the price of not letting callers name their own
budget, and it is the right trade.
