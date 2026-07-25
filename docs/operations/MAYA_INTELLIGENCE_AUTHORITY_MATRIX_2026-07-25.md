# Maya Intelligence Authority Matrix — 2026-07-25

## Status

Draft, read-only contract work on PR #172. No provider calls, schedules, services, deployment, production writes, packet rebuilds, or execution paths are authorized by this document or its companion code.

Contract: `maya-intelligence-evidence-v1`  
Module: `scripts/maya_intelligence_contract.py`

## Governing principle

Every evidence value must carry a provider, source timestamp, provenance reference, and explicit freshness state before it can influence deterministic research. Missing, malformed, or stale evidence remains visible as missing/stale and is never fabricated.

Analyst ratings, upgrades, downgrades, news ratings, and model opinions are never release authority. They may add context, trigger review, or raise risk, but cannot repair missing arithmetic, provenance, freshness, quality admission, sector/industry methodology, Defense account sizing, or proposal dependencies.

## Field-by-field authority matrix

| Field | Current source/path | Watch | Proposal | Defense | Sector | Industry | Governing authority |
|---|---|---|---|---|---|---|---|
| Trailing P/E | Finviz strip-map, yfinance supplement fallback | Displayed; available to fundamental quality/thesis context | May accompany verified Watch/company research | Constituent context only | Screened-company context only | Candidate context only | Deterministic input only when current and provenance-complete; no standalone release |
| Forward P/E | Finviz/yfinance valuation strip | Displayed and sent to independent review context | Context only | Context only | Context only | Context only | Contextual; forecast-based, never admission/release authority |
| P/B | Finviz/yfinance valuation strip | Displayed | Context only | Context only | Context only | Context only | Contextual; not currently a hard deterministic gate |
| P/S | Finviz/yfinance valuation strip | Used by the deterministic pre-profit quality ceiling when provenance/freshness are valid | Inherited through verified company research | Constituent context | Candidate-screen context | Candidate-screen context | Deterministic Watch quality input; other domains consume only through verified dependencies |
| Support | `portfolio.reentry.resistance.v1` shared cache / packet evidence | Entry, stop, invalidation, and re-entry evidence | Proposal risk evidence | Protect/reduce trigger context | Constituent entry context | Candidate entry context | Deterministic only with methodology version, close/session timestamp, and provenance |
| Resistance | Same shared level cache | Target, reward, invalidation, and re-entry evidence | Proposal reward evidence | Recovery/trim context | Constituent entry context | Candidate entry context | Deterministic only with methodology version, close/session timestamp, and provenance |
| Catalysts/events | News ingestion → catalyst conversion and packet event evidence | Deterministic event block/materiality plus critic context | Required specialized dependency context | Risk/event context | Corroborative context | Corroborative context | Deterministic for event blocks only when sourced, dated, and classified; models cannot invent catalysts |
| News provenance/freshness | Ingestion source URL/provider, publication/ingestion times, catalyst evidence refs | Must be explicit | Must be inherited from each dependency | Must be explicit when news affects a Defense thesis | News remains corroborative to relative-price state | News remains corroborative to same-vendor relative state | Missing or stale provenance blocks use as deterministic evidence |
| News-quality rating | New bounded 1–5 evidence-quality contract | Review priority and evidence confidence | Review confidence | Review confidence | Corroboration confidence | Corroboration confidence | Contextual only; measures source reliability, freshness, primary-source proximity, corroboration, and materiality—not sentiment or trade readiness |
| Analyst consensus | Maya/analyst coverage fields | Display only, separately aged as `STREET DATA >7D` | Corroborative only | Corroborative only | Corroborative only | Corroborative only | Display-only; cannot grant admission, alter arithmetic, or release a proposal |
| Analyst upgrade | Analyst event feed when provenance/date exist | Time-bounded catalyst context | Context through verified dependency | Risk/context | Context | Context | Contextual only; may request review, never override a deterministic failure |
| Analyst downgrade | Analyst event feed when provenance/date exist | Time-bounded negative catalyst/risk context | Context through verified dependency | Risk escalation context | Context | Context | Contextual only; may tighten review posture, never invent or change mechanics |
| Local/OAuth model verdicts | Independent-review packet | Separate critique after deterministic PASS/admission | Review support only | Review support only | Review support only | Review support only | No deterministic override; paid lane remains operator-only |

## Cross-domain consumption audit

### Watch

Confirmed deterministic consumers:

- quality admission uses price, float, market capitalization, ATR, technical freshness, deterministic thesis, and pre-profit P/S;
- ticket validation independently recomputes entry/stop/target ordering and R:R;
- catalyst/event evidence may block or require review;
- support/resistance can inform mechanics only when retained with source/methodology/freshness.

Confirmed non-authoritative context:

- analyst consensus and Street age;
- forward P/E and P/B;
- local/OAuth review verdicts.

### Sector

The authoritative state is aligned relative price: RS5, RS20, RS60, RS20 slope, breadth coverage/quality, freshness, and quarantine status. News, analyst data, valuation, and model commentary are corroborative. They must not replace or repair relative-price methodology.

### Industry

The authoritative state requires same-vendor/same-run industry and SPY evidence, relative week/month values, classified quadrant, resolved mapping, coverage, and close-confirmed capture for actionable use. Company valuation, news, and analyst evidence are candidate context only.

### Defense

Release eligibility requires verified sector research, complete account-specific exposure, complete account sizing, realized volatility/correlation, verified industry dependencies where constituents are selected, and SHADOW mode. Company valuation, levels, news, and analyst events may explain or prioritize a defense review but cannot repair missing exposure, sizing, or risk calculations.

### Proposal

Every specialized dependency must be `VERIFIED`. Proposal assembly must preserve each dependency's evidence hash and cannot cherry-pick favorable Watch, Sector, Industry, or Defense conclusions. Opinion fields never satisfy a missing specialized dependency.

## News-quality rating contract

The rating is bounded to 1–5 and uses exactly five explainable ordinal dimensions:

1. source reliability;
2. freshness;
3. proximity to a primary source;
4. independent corroboration;
5. decision materiality.

All dimensions must be valid integers from 1 through 5. Missing or invalid dimensions produce `INSUFFICIENT_EVIDENCE` and no rating. The result is evidence quality—not bullish/bearish sentiment, expected return, or permission to trade.

## Blockers and incomplete integrations

1. The repository has multiple evidence producers but no single live API envelope yet that returns normalized provider, `as_of`, provenance, methodology, freshness, and authority for every field.
2. Trailing/forward P/E, P/B, and P/S are visible in the Watch strip, but source-specific freshness and field-level provenance are not yet uniformly propagated into every persisted decision packet.
3. Support/resistance are shared across surfaces, but all consumers must prove they use the same methodology version and close/session timestamp rather than divergent native card fields.
4. News ingestion and catalyst conversion exist, but a normalized 1–5 evidence-quality rating is not yet persisted or displayed across Watch, Proposal, Defense, Sector, and Industry.
5. Analyst consensus age has a scoped UI label, but upgrades/downgrades need a canonical event record containing firm, action, prior/new rating or target, publication time, provider, and provenance reference.
6. Sector and Industry adapters correctly keep news/models corroborative, but their live producers have not yet been switched to emit this Maya evidence envelope.
7. Defense and Proposal adapters require verified dependencies, but live packet assembly must be audited to prove all evidence hashes and freshness states survive serialization.
8. The exact-ref gate must pass on the new head before any sample rebuild or UI/API rollout.

## Rollout sequence

1. Exact-ref compile/test/build of `maya-intelligence-evidence-v1`.
2. Read-only field coverage census across the current Watch top 200 and representative Proposal, Defense, Sector, and Industry packets.
3. Bounded local-only sample packet rebuild with provider lanes disabled.
4. Read-only before/after authority comparison.
5. Separate read-only API/UI presentation tranche.
6. Separate scheduler/provider decisions only after deterministic and provenance evidence passes.
