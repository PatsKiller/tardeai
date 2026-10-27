# Breakpoints and layout rules

Operator-approved 2026-10-25 (design workflow §4). The automatic phone checks measure the rules marked **(checked)**.

| Class | Width | Build and verify at | Layout |
|---|---|---|---|
| Phone | ≤ 820 px | 412 × 915 and 390 × 844 | one column |
| Tablet | 821 – 1279 px | (follows desktop) | desktop layout with one fewer column |
| Desktop | ≥ 1280 px | 1440 × 900 | nav rail + content |

The CSS breakpoint used across Command Center v3 is `@media (max-width: 820px)` (`window.matchMedia('(max-width: 820px)')`
in components). Do not add new breakpoints without a design version that says why.

## Phone (≤ 820 px)

- One column. The whole page scrolls; fixed or sticky bars together take at most **15% of the viewport height**
  (≈ 137 px at 412 × 915, ≈ 126 px at 390 × 844). **(checked)**
- List → tap → full-screen sheet with "← Back" (`MobileDetailSheet`). Never a detail panel off-screen.
- Every tap target at least **44 × 44 px**; no hover-only actions. Inline text links inside prose are exempt. **(checked)**
- No sideways scroll of the page. Wide tables scroll inside their own box (`overflow-x: auto` on the table wrapper). **(checked)**
- Times in ET and readable ("Nov 2 10:25 ET"); a raw ISO timestamp only inside a tooltip. **(checked)**
- No empty bullets or empty list items. **(checked)**
- Anything moved behind a tap (menu, "⋯", collapsed section) counts as a hide and needs an approved version.

## Desktop (≥ 1280 px)

- Nav rail plus content; list and detail side by side where the mockup shows it.
- Same data and actions as phone, laid out wider; never desktop-only actions.
- Tables sortable; numbers right-aligned with tabular figures (`numStyle`).

## Both

- Colours, type, spacing, radius and shadows only from `design/system/tokens.json` → `tokens.css` (and the TypeScript
  mirror `src/lib/designTokens.ts`). `scripts/check_design_tokens.sh` refuses raw hex and fonts under 10 px.
- Money through the house formatter (`src/lib/format.ts` `fmt$`, e.g. "−$N,NNN"); every number shows where it came
  from; a gap is shown as a gap with its reason, never as 0.
- Contrast meets `scripts/check_token_contrast.mjs` (WCAG 2.1 AA) in the dark theme the app uses.
