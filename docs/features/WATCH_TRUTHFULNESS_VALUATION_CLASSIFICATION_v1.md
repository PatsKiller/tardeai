# Watch Truthfulness, Valuation, and Re-Entry Classification v1

## Observed production defects

The July 23 saved production pages established four separate facts:

1. Re-Entry rendered `CLASSIFY` controls, but a click could fail without producing a modal or an error.
2. The trailing exit universe included unresolved identifiers such as CUSIP-like strings alongside supported tickers.
3. Watch rendered a rich technical and decision packet but did not expose P/E, forward P/E, PEG, or their source/freshness.
4. Ticket verification listed deterministic, local, Grok OAuth, ChatGPT OAuth, and premium lanes, but the only operator control was a generic free-review button. Premium remained hard-coded `NOT RUN` even though estimate/run endpoints existed.

## P/E truth

P/E is already persisted upstream in the Finviz ticker enrichment cache. The blind-facts compiler whitelists:

```text
pe
forward_pe
peg
pb
ps
pfcf
```

These fields are evidence for valuation and long-term thesis review. They are not action states, rankings, or quality scores.

The UI now searches the current Watch item, Finviz strip, symbol card, and immutable decision-packet fundamentals. It shows:

- trailing P/E;
- forward P/E;
- PEG;
- source;
- as-of age;
- `UNAVAILABLE` when a source does not provide the value;
- `N/A` for fund/ETF instruments where company P/E is not the correct semantic field.

No P/E is estimated from price, EPS text, analyst targets, or an LLM response.

## Classification modal contract

The primary Re-Entry table emits a classification request. A page-level overlay intercepts that request before the legacy workbench listener and:

1. writes the target to `?classify=SYMBOL[,SYMBOL]`;
2. renders through `document.body` at a fixed top-level z-index;
3. reloads saved mandate/event/disposition preferences;
4. fetches current Watch evidence for editable starting context;
5. displays explicit deterministic source coverage and valuation provenance;
6. saves persistent mandate data even when the full-fidelity exit event is missing;
7. never fabricates an event-specific record without an event key.

CUSIP-like or otherwise unresolved identifiers are shown as `UNRESOLVED IDENTITY` and cannot be saved as ticker classifications.

## Favorite versus automated Watch lanes

A star is an operator-priority marker. It is not evidence of quality and does not change deterministic validation.

### Operator favorites

- displayed in a distinct lane;
- retain their exact underlying origin;
- can be refreshed, reviewed, unstarred, or opened in Re-Entry;
- receive no automatic deterministic promotion merely because they are starred.

### Automated discoveries

- display the exact `origin_system`/source;
- receive no implied operator endorsement;
- can be promoted to favorite explicitly;
- use the same freshness, valuation, validation, and review truth gates as favorites.

## Review lane hierarchy

The Watch truth desk exposes separate controls for:

- deterministic validator state;
- local-only critic;
- Grok OAuth critic;
- ChatGPT OAuth critic;
- all free critics;
- paid expert cost/capability preview and exact typed confirmation.

Model outputs are critiques. The deterministic validator and reconciler retain authority. Agreement among local, OAuth, or paid models cannot override a deterministic failure.

Local-only review must remain local; silent cloud fallback is not accepted as a local vote. OAuth lanes remain separately visible so correlated or unavailable routes are not mistaken for independent consensus.

## Paid review

The paid-review control always calls the estimate endpoint first. It displays provider/model, estimated token use, estimated cost, latency, daily/monthly budget, immutable ticket hash, and the exact required confirmation phrase.

No paid call occurs without exact typed confirmation. If no provider is enabled, credentials are absent, or dispatch is not implemented, the UI states that condition and does not imply a completed review.

## Safety

This work is advisory and classificatory only. It does not submit or modify orders, approve proposals, move capital, request 2FA, or allow an LLM to alter deterministic mechanics.
