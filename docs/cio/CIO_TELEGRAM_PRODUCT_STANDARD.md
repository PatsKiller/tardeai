# CIO Telegram Product Standard

Authority: `READ_ONLY_ADVISORY`. This is the operator-facing language and layout
standard for the CIO Telegram desk. It changes how Alex talks, not what Alex
decides.

## Order

Every card obeys:

1. **DECISION FIRST** — the operator question/standing call.
2. **REASON** — why.
3. **WHAT CHANGED** — what actually moved (only when something did).
4. **WHAT THE OPERATOR SHOULD DO** — only when actionable.
5. **WHAT CHANGES THE CALL** — the invalidation condition.
6. **NEXT REVIEW** — when follow-up is genuinely due.
7. **EVIDENCE LINK** — button to Command Center / Evidence.

## Immediate-card style

```
Alex · CIO

SCHD — WAIT / REVALIDATE

Why:
Concentration is still above the desk limit, but the current evidence is
conflicted, so I am not asking you to trim now.

Since your REJECT:
No material new evidence. I am keeping this quiet.

Next review:
When the data conflict clears or the concentration thesis materially changes.

[Open CIO] [Evidence]
```

If there is no material change since REJECT, do **not** send even this card.

## Cash digest style

```
Alex · CIO

Cash remains high, but I still have no governed use that is actionable now.

Free investable: $322k
Deploy now: $0
Call: hold cash

What would change the call:
A candidate becomes genuinely actionable or cash returns inside the governed band.

[Open Capital Plan]
```

## Re-entry style

```
Alex · CIO

No re-entry is actionable now.

A few names are close, but none has a candidate-specific governed RE_ENTER
verdict.

I will notify you when one actually clears the gate.
```

Do not send this every ten minutes.

## P0 send gates (2026-08-22, freeze window)

Suppression only — `docs/ops/TELEGRAM_FEED_REMEDIATION_2026-08-22.md`.

- Never print `R:R 0.0:1`. Compute from entry/stop/target or print `R:R UNAVAILABLE` and do not mark ACTIONABLE.
- Long invalidation must be below price (short: above) or **do not send** the card.
- `Quote: alpaca ❌` / execution-ineligible → withhold the proposal.
- Markdown parse failure must **edit** the original message (idempotency key), never a second send.

## Formatting rules (hard)

- No broken Markdown/HTML.
- No accidental underscore italics.
- No machine enums in the headline unless operator-relevant.
- No duplicated WHAT CHANGED / WHY prose.
- No mid-word or mid-sentence truncation.
- No raw internal path, raw token, raw auth URL, or debug payload.
- `parse_mode=None` (plain text) or one rigorously escaped format.

## Sentence-safe length budgeting

Build the concise content first. If a field must be shortened, use
sentence-safe truncation at a word boundary (never `(Re-`), bullet-safe
truncation, or `max N symbols + "+X more"`. The renderer uses
`_sentence_truncate()` which cuts at word boundaries and appends `…`.

## Action-button discipline

- Non-action / informational cards: `OPEN CIO` + `EVIDENCE` only.
- Actionable cards (act_now and unblocked): disposition controls (ACK / DEFER /
  DONE / REJECT / RATE).
- Never attach disposition controls to repetitive WAIT telemetry.
- Never expose broker / order / stop actions.

`build_cio_keyboard()` implements this: disposition controls only when
`act_now and not blocking`.

## Machine tokens to keep out of operator copy

`ACT_NOW=`, `READY=`, `NEAR=`, `WAIT=`, `STALE_REFRESH_REQUIRED`,
`DATA_UNAVAILABLE`, `operator_challenge_status=`, `challenge_review=`,
`decision_input_digest=`, `decision_evidence_digest=`. Raw enums may still
appear in Evidence/Command Center.

`lint_cio_text()` flags these and truncation/underscore/length defects so a
defective body can be suppressed or fallbacked before send.
