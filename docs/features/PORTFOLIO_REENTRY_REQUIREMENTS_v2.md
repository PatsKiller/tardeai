# Portfolio Re-Entry — Requirements Contract v2

## Purpose

Re-Entry is a persistent decision workstation beneath Portfolio for every position exited during the trailing twelve months. It must answer:

1. What did I exit, when, from which account, and why?
2. What is the symbol's current technical and portfolio state?
3. What must happen before I should review a re-entry?
4. What portfolio role and sub-strategies does the operator assign?
5. Which persistent alerts are armed?

The page is advisory only. It does not create, approve, submit, modify, or cancel an order.

## R1 — Complete trailing-year exit universe

The page must union and deduplicate all available trailing-year sources:

- `GET /api/v2/redeploy/history?days=365` — canonical material SELL transaction coverage;
- `GET /api/v2/redeploy/book?limit=1000&include_dismissed=1` — event details and historical statuses;
- `GET /api/v2/stops/reentry-watch?days=365` — stopped-out lifecycle and re-entry state;
- `GET /api/v2/journal/by-ticker?from=<one-year-ago>` — closed-trade fallback and reconciliation.

A source failure, `ok=false`, or a mismatch between a source-declared sell count and the rendered union is a visible blocking coverage warning. The UI must never present a partial result as “all exits.”

Each exit event must retain, when available:

- symbol;
- account;
- exit date;
- stopped-out, sold/traded-out, or unclassified exit type;
- shares;
- execution/exit price;
- proceeds;
- exit reason;
- source and source status.

Symbols may have multiple exit events. The row is symbol-level; expansion shows every event in the trailing-year window.

## R2 — Independent portfolio requirements

`CORE` is an independent primary requirement, not a mutually exclusive position type.

The following are independent, combinable sub-flags:

- `COMPOUNDING`;
- `DIVIDEND`;
- `SHORT`;
- `SWING`.

Examples that must be representable:

- Core + Compounding;
- Core + Dividend;
- Core + Compounding + Dividend;
- Swing only;
- Short + Swing;
- unclassified/no flags.

The persistent assignment also includes:

- priority;
- active-monitor status;
- target account;
- target portfolio weight;
- operator thesis and invalidation requirements;
- update timestamp;
- alert summary.

Existing v1 assignments using a single `intent` must migrate losslessly into the corresponding independent flag.

## R3 — Current status for every exited symbol

Each row must show a current state, a next action, and a plain-English reason. Required states:

- `READY_TO_REVIEW`;
- `NEAR_ENTRY`;
- `WAIT_FOR_PULLBACK`;
- `OVERSOLD_REVIEW`;
- `OVERBOUGHT_WAIT`;
- `SHORT_PLAN_REQUIRED`;
- `CURRENTLY_HELD`;
- `STALE_DATA`;
- `NO_CURRENT_COVERAGE`.

The row must expose, when available:

- current price;
- exit price and percentage move since exit;
- RSI and oversold/neutral/overbought classification;
- candidate entry range;
- distance above/below or inside the entry range;
- stop and target;
- long/short plan side;
- technical timestamp and age;
- data-quality note;
- current holdings status.

No current coverage is a visible state and action item, not a blank cell or an implied neutral reading.

A `SHORT` flag may never reuse long mechanics. A short-side price alert requires an explicit bearish plan.

## R4 — Persistent alerts

The page may create persistent notifications through the existing Watch alert service for:

- price crossing above or below a threshold;
- RSI crossing above or below a threshold.

Alerts are independent notifications. They do not constitute a re-entry approval and must not initiate broker activity, an order proposal, 2FA, or execution.

## R5 — Clear operating surface

The default table must show:

- symbol and number of exits;
- latest exit date, type, account, and execution context;
- current state, next action, and reason;
- current/exit price relationship;
- RSI;
- pullback distance;
- candidate entry, stop, and target;
- all active portfolio flags;
- priority and target account;
- alert count and monitor state.

The page must provide filters for symbol/account/reason, each independent flag, current state, and exit type.

## R6 — Acceptance tests

Before merge or deployment:

1. A saved symbol can simultaneously be `CORE`, `COMPOUNDING`, and `DIVIDEND`.
2. A saved symbol can be `SHORT` and `SWING` without becoming `CORE`.
3. A legacy `intent=CORE` assignment loads as `core=true` without deleting other stored fields.
4. The rendered union count is at least the canonical source-declared count, or the page shows a blocking coverage warning.
5. Multiple exits for the same symbol remain visible in expansion.
6. A source returning HTTP 200 with `{ok:false,error:...}` produces a visible source error.
7. A symbol absent from Watch renders `NO_CURRENT_COVERAGE`, not empty status fields.
8. A held symbol renders `CURRENTLY_HELD`.
9. A short-flagged symbol without bearish mechanics renders `SHORT_PLAN_REQUIRED` and cannot arm a short-side price-zone alert.
10. No ticker examples are hard-coded into the application.
11. No broker call, proposal, approval, order, or 2FA path is introduced.

## Non-goals

- automatic re-entry;
- automatic portfolio-role assignment;
- broker execution;
- replacing the canonical transaction ledger;
- fabricating RSI, entry levels, or current status when evidence is absent.
