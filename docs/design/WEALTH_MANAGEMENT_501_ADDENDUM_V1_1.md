# Wealth Management 501 — implementation addendum v1.1

14 November 2026 · User-directed clarifications. Complements v1.0; this is a product standard, not a claim that the features are deployed.

Canonical documents in this repository: v1.0 = `docs/design/WEALTH_MANAGEMENT_501.md` (unchanged); this addendum = `docs/design/WEALTH_MANAGEMENT_501_ADDENDUM_V1_1.md`; binding agent rules = `AGENTS.md` §9.6 "Wealth Management 501 — product and delivery contract".

## Lean institutional investment framework

Adopt the discipline of a professional investment desk without building an enterprise back office. Cover Core/Long-term, Dividend/Income, Tactical/Rotation, Swing, and Protection/Exit Review. Account/position/lot context and mandate define where each thesis applies. Separate horizon-specific advice: a short-term chart signal must not silently cancel a long-term income thesis. Capital proposed in multiple sleeves cannot be counted more than once.

Daily is one view of the same investment framework. Provide weekly, monthly, quarterly, annual and long-term reviews as well. For each horizon, state current holdings/weights, thesis, relevant evidence, expected review date, catalysts, action alternatives, invalidation and actual outcomes. Exit review covers hold, trim, full exit, waiting and rotation, with transaction/tax uncertainty made explicit. Dividend work includes income received versus projected, sourced declaration/ex/record/payment dates, payout/coverage evidence and total return; do not equate high yield to quality or safety.

Do not add advisor billing, sales CRM, commission accounting, blanket ESG/CSRD reporting, institutional voting workflows, full net-worth/property budgeting or a low-code dashboard builder merely because reference products offer them. They require separate user need and acceptance. Existing pages may retain supported functionality; this scope rule is not permission to delete it.

## Daily briefing and research memory

At login, present an already-built briefing, not a model call:

1. Overnight/futures: actual instrument/contract, quoted session, observed time, delayed/closed state and relevant move/reference. Futures are not cash-index prints, and continuous-contract series require roll-method metadata.
2. Yesterday: dated session recap, what moved the user's book, realised events and unresolved decisions. Separate post-close updates from the regular-session result.
3. Today/next session: economic calendar, earnings, dividend events and relevant risk windows; weekends explicitly refer to the next session.
4. Portfolio implications: affected direct and sourced indirect exposures, hold/reduce/rotate/wait proposals, reasons and trigger/invalidator.
5. CIO follow-up: questions, thesis changes, decisions awaiting review and prior recommendations/outcomes.

Inventory the existing backend first. The Stock Trader's Almanac is one possible reference among many. Research documents must carry title/edition/date, source/access rights, usable citation/locator, retrieval time and relevance. Historical/seasonal tendencies are contextual evidence, not current facts, causal proof or predictions. Do not claim access to a document that was not retrieved. Use approved available sources; unsupported resources become explicitly owned gaps.

Persist the briefing's evidence IDs, horizon, policy and recommendation versions in CIO memory, then show changes since the prior brief. Refresh in background on relevant events plus a bounded catch-all. Preserve the canonical source clocks and evidence-keyed model cache.

## Existing capabilities before new modules

The user reports substantial backend data and analysis already exist. Verify an inventory of:

- Canonical account/security/position/lot/transaction models and quote/fundamental feeds.
- Income/dividend, performance/attribution, stop/risk, entry/exit/rotation, calendar/futures and research outputs.
- Historical documents, seasonal references, report archives, CIO questions/decisions/outcomes and memory stores.
- Their exact writers, schedules, read endpoints, schema/calculation versions, coverage and freshness rules.

Classify each requested feature as available-and-exposed, available-but-hidden, stale/unusable, missing calculation/history, missing source, or unproven. Name owner, next step and acceptance. Never infer that a served field is financially correct merely because it exists.

The user reports Anthropic and ChatGPT OAuth paths in the existing LLM router. Inspect effective configured routes, permitted usage, capabilities, limits and entitlement without printing tokens or making unapproved paid/provider probes. OAuth configuration alone proves neither callability nor unlimited/free usage. Reuse the existing router; do not rebuild provider integrations or override the DeepSeek-first development policy. Separate model synthesis from deterministic accounting and trading gates.

## Portal research: what to borrow and omit

Public vendor pages and AMINDIS dashboard screenshots were viewed in the user's Chrome on 14 November 2026. These are design references and vendor descriptions, not independently tested production products or a procurement ranking.

| Reference | Observed pattern | Adopt for Trade-AI | Keep out of current scope |
|---|---|---|---|
| [AMINDIS](https://www.amindis.com/business/client-portal), CP-1/CP-2 images | Portfolio/date scope, WTD/MTD/YTD tiles, allocation and performance drilldowns | Clear scope, prominent period metrics, consistent analytic navigation | Large ESG/reporting menu, low-code platform and on-request heavy calculations |
| [Envestnet](https://www.envestnet.com/wealth-management/client-portal) | Unified account view, high-level summaries with detailed holdings/performance pages | One coherent account model and progressive detail | Household spending, credit/property budgeting and broad planning integrations unless requested |
| [Orion](https://orion.com/advisor-tech/client-portal) | Mobile-focused investor view and advisor/client information alignment | Consistent desktop/mobile data and goals/horizon context | Advisor sales/brand/presentation tooling and automated outbound communications |
| [d1g1t](https://www.d1g1t.com/investor-portal-and-mobile-app/) | Performance/exposure/income/risk with research context and mirrored information | Connect holdings/returns/risk to research and CIO history | Full private-asset/net-worth/document-vault expansion absent a concrete need |

Product judgment: borrow hierarchy and coherent drilldowns, not every module. Investment decisions and trustworthy data take priority over decorative charts and enterprise breadth. Keep existing brand/theme unless a scoped design decision changes it.

## Route migration and retirement

Build a route -> component -> reader -> product map for every actual route, tab and detail, including classic links and version-labelled implementations. A valid /v3 URL or /api/v2 contract is not obsolete merely because of its number.

For each obsolete UI/framework path record canonical replacement, retained capabilities, missing parity, account/security/query/deep-link context, owner/reviewer, tests, live validation and exact retirement step. Preserve accepted functionality until the replacement is verified. Then use consistent compatible redirects and remove redundant navigation/components in a reviewed bounded change. A prior release is rollback; permanent hidden compute fallback is not the migration plan. Keep original data, reports, documents and CIO history.

## Actual project and AGENTS.md integration

Canonical guide must live in the real project's approved versioned design/docs area, with a synchronized durable handoff copy. Update the applicable AGENTS.md by adding a concise reference and enforceable engineering rules; do not replace unrelated policy or edit a protected checkout contrary to its rules. Use the correct authoring worktree and normal integration flow. Report path, diff/checksum and whether the change is worktree-only, integrated or deployed. User authority removes invented grant/GitHub dependencies, not the need for truthful evidence.

The AGENTS.md section is `AGENTS.md` §9.6 "Wealth Management 501 — product and delivery contract" (Policy-Version 32.2.0). Version the standard and preserve user decisions. Reading the guide is not implementation; a receipt is not live acceptance.
