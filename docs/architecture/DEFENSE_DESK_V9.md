# Defense Desk v9 — The Adjudication Layer (2026-07-18 evening)

Status:      ACTIVE
as_of:       2026-07-18T17:59:53-04:00
Measured at: efcc51365 / not measured

The layer that judges everything else: pre-registered promote criteria (locked
before evidence), a console that assembles evidence nightly, a seat league that
audits the auditors, governance rows with living revoke criteria, governed tuning
that proposes but never adjusts, and a Saturday weekly loop. Zero LLM calls in
this layer — it judges the judges deterministically. It writes only dated
directives; it never promotes, tunes, or revokes anything itself.

Shipped (cc67aace): promote_criteria.json (5 decisions, seeds registered
2026-07-18, LOCK + amendment flow) · defense_adjudication.py (console eval,
league join FIXTURE-TESTED, governance w/ machine-evaluated defensive_lean
revoke criterion, mute suppression counts) · tuning_proposal_engine.py (min-n 20,
±20% hard bound, evidence field-guard — all tested; today correctly silent) ·
oversight_weekly_digest.py (Sat 08:00; first real run: 38 reviews, $3.25) ·
Review console UI (lock → evidence → decide → dated directive).

## THE HONEST STATEMENT: what July 30–31 CAN and CANNOT prove
**CAN prove (n will exist):** GG shadow behavior across ~10 sessions (runs,
would-have-fired mix, incident-free operation); execution-rail integrity (audit
completeness is already 100% and will have ~2 weeks of hops); the oversight
stack's operating character (coverage, cost, OBJECT themes across ~50+ reviews);
whether ladders/rollback conditions evaluated without error; the operator's own
spot-agreement rate IF ratings are entered as advisories land.
**CANNOT prove (n will not exist):** advisory PROFITABILITY — exit_advisory_
outcomes and round_trip/pair outcomes need closes that only trading time
creates (today n=0; +5d/+21d windows mean single digits by the 30th); seat
ACCURACY (league needs ≥10 closed outcomes/seat — months, not weeks); any
tuning proposal (min-n 20 will not clear). July 30–31 is therefore a PROCESS
adjudication — did the machinery behave as specified — not a PERFORMANCE
verdict. The performance verdict has its own pre-registered criteria and will
arrive when the n's do. Anyone claiming more from that review is overreaching,
including us.
