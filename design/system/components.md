# Components

The shared building blocks of Command Center v3 and the tokens they use. A mockup uses these names; a build uses these
components. Token names refer to `design/system/tokens.json` (CSS custom properties in the generated `tokens.css`,
TypeScript mirror `src/lib/designTokens.ts`: `TOKENS`, `toneVars`, `TYPE`, `FONT`, `RADIUS`, `SPACE`, `numStyle`,
`chipStyle`). Watch pages also use `src/lib/watchTokens.ts` (`BB`, `T`, `rowRail`).

## Tones

`success` (positive / ready), `warning` (watch / review), `danger` (risk / loss / error), `info` (informational / links),
`ai` (AI-sourced), `neutral` (nothing notable). Every tone has `-color`, `-bg` and `-border`; `toneVars(tone)` returns
the three. A verdict maps to a tone through `toneFromVerdict`.

## Type and spacing

Type scale is locked to 10 / 11 / 12 / 14 / 18 / 24 px (`TYPE.xs … TYPE.xl`); 10 px is for chips only. Spacing is
the 4-point grid (`--space-1` 4 px … `--space-8` 40 px). Radius `sm` / `md` / `lg` / `pill`. Numbers use `numStyle`
(mono, tabular figures).

## Buttons

- Real `<button>` elements; icon-only buttons carry `aria-label`.
- Primary: tone background from `toneVars(...)`, `RADIUS.md`, 600 weight; min height 40 px on desktop, **44 px on phone**.
- Quiet secondary: transparent background, 1 px `--border-color`, `--text-2`.
- A button that writes anything states what it does ("Approve v004", not "OK"), and is disabled while its request runs.

## Chips

`chipStyle(tone, variant, size)` — soft by default; `TYPE.sm`, padding 2 × 8 px, `RADIUS.sm`. Chips label; they never
act unless they are buttons with a 44 px tap area on phone.

## Sheets

- Phone list → detail: `MobileDetailSheet` (full screen, "← Back" first, focus trapped, Escape closes).
- Desktop: detail beside the list where the mockup shows it.

## Tables

Wrapper scrolls horizontally inside its own box on phone; header cells are sort buttons with `aria-sort` when the table
sorts; numbers right-aligned with `numStyle`.

## Cards

Background `--bg-1`, 1 px `--border-subtle`, `RADIUS.md`; padding 14 × 16 px desktop, 14 px phone; the house row rail
(`rowRail`) on the left edge where a state applies.

## Clocks (freshness)

The DeskPage "Source clocks" strip: each source shows its age and its writer lane state (ACTIVE / PAUSED / RETIRED /
NONE) from the lane registry plus its last successful run. Times render in ET ("Nov 2 10:25 ET") through `fmtAsOf` /
`formatAsOfET`; weekend-aware wording ("Market closed · last broker sync Fri 16:52 ET").

## Empty and gap states

- `DeskGap` (`components/DeskPage.tsx`): a title and the real reason ("Writer paused since …", "Source unavailable:
  …"), with an optional action. A missing value is a gap with its reason — never 0, never a placeholder number.
- Empty list: say what is empty and why ("No designs waiting for you."), not a blank panel or an empty bullet.
