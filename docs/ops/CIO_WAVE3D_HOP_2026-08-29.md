# Wave 3D — the one live hop, executed (2026-08-29)

    plan_id       plan_477c33c065ec  (SPCX)
    research_id   res_557cfaab8c34
    lane          deepseek-v4-flash      process_id  hermes_external_research
    verdict       PARTIAL                attachable  false      ATTACHED: NO
    cost_usd      $0.0005                calls       1
    telegram_sent false                  would_channel  none

Global paid spend $2.0446 → $2.0451. `provider_cost` events 2767 → 2768.
Exactly one vendor call.

## Correction: DeepSeek was configured all along

I reported it "not configured on this host". That was wrong, and the operator
said so. Evidence they were right: `model=deepseek-v4-flash` on 147 results,
most recent **today at 08:15 UTC**.

The mistake: I searched for `DEEPSEEK_API_KEY`. The canonical env name is
`deepseek_tradeai` — `DEEPSEEK_API_KEY` is only a compatibility alias, as
`llm_model_registry.get_deepseek_api_key()` states. And I searched the release
worktree, while `llm_lane` loads `.env` relative to its own location, which is
`$PROJ` = `trade-ai-v12-rebuild`.

Searching for the obvious name in the wrong root and concluding "absent
everywhere" is a bad inference, not a missing file.

**No grok policy change was needed or made.** The correct lane was the one the
system already uses.

## The cap

The first two attempts returned `COST_CAP_EXCEEDED: global cap` while
`usd_spent_today()` read $0.0172 — which looked spurious. It was not: the gate
compares `ledger_paid_usd_today(None)`, which read **$2.0446** against a
**$0.50** cap. Genuinely 4× over; the refusal was correct both times.

The operator asked for $2.00. That is *below* $2.0446, so it could not have
worked — flagged before spending, and $2.25 authorised instead. Set for the run
only; `.env` still reads `0.50` and no file was edited.

## The critique

`PARTIAL`, not attachable, and substantively right:

1. The artifact answers `q1/q2/q3`, not the requested `q_thesis`/`q_bear` — a
   real question_id mismatch.
2. No execution instruction present, but it flagged a `recommendation` field
   containing "maintain the current HOLD stance" as *interpretable* as one —
   correctly distinguishing a recommendation from an instruction rather than
   failing it outright.
3. Internally consistent; attachable **once the question_id mapping is fixed**.

`attachable: false` → existing attach rules → **nothing attached**. Persisted as
`SpecialistArtifact` `provider=grok_critique outcome=PARTIAL`, plus a
`DeliveryReceipt` with `would_channel: none`, `would_send: false`
(`s1_observational_default_suppressed`).

## Bitwarden deletion guard

`render_env.py` renders Bitwarden **Secrets Manager** → tmpfs cache. It guarded
against SM returning *zero* secrets. It did **not** guard against SM returning
*one fewer*.

A key deleted in the SM UI comes back as a perfectly successful render that is
one key short, and the atomic write takes the credential with it — every
consumer loses it simultaneously, with no error anywhere. That is precisely how
`deepseek_tradeai` could disappear from a live system with nothing failing
until the next call site needed it.

Fix: compare the incoming shell key set against the last good render. If keys
disappeared, **refuse and keep last-known-good** — the same posture the module
already takes for a transport failure, because a silent deletion is the more
dangerous of the two. A stale cache costs nothing; a missing key fails later
and further from the cause.

- baseline read from the manifest, falling back to the cache file, so it works
  on a host whose manifest was cleared
- first-ever render is never blocked (empty baseline = no guard)
- growth is fine; only disappearance is refused
- deliberate removal: `--allow-key-removal`
- the manifest stores **key names only** — a test asserts no value can reach it
- Telegram alert reuses the module's existing `_telegram`, names only, no values

9 tests, including one asserting the cache still contains the dropped key after
a refused render.

## Pins

MBI 0, ROTATE advisory-only, notify off, INTERDICT on, `telegram_sent` false,
no policy widened, no R1 widen, `.env` unedited, nothing attached, no
escalation to Pro/OpenAI. 3E not started.
