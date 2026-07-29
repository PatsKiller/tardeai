# Visual Contract — Defense Desk redesign v1

Approved by the operator 2026-07-29. This document governs implementation of
`defense_desk_redesign_v1.html`.

---

## 0. THE RULE THAT MATTERS

**The HTML file is the specification. This document is not.**

`defense_desk_redesign_v1.html`
md5 `388f0ad091ad886be631b5b56d34defb`

If this document and the HTML ever disagree, **the HTML wins**. Everything below
is an index to help you find things in it, not a substitute for opening it.

Verify the checksum before you start. If it does not match, you have the wrong
file — stop and report.

### Why this rule exists

The previous iteration of this work drifted because two design artifacts existed
(a chat mockup and a JSX file), they disagreed, and neither was declared
authoritative. The JSX also named the wrong CSS variables. The implementation
that resulted was structurally correct and visually wrong, and nobody could say
which artifact it had failed to match.

One artifact. One checksum. One approval.

---

## 1. WHAT IS FROZEN AND WHAT IS LIVE

| Frozen — do not change | Live — must be wired |
|---|---|
| Section order | Every number, symbol, price, percentage |
| Which sections exist | Row counts in every table |
| Column headers and their order | Chip presence and state |
| Colors, type sizes, spacing, radii | Verdict text and reasons |
| Chip shapes and semantics | `data_gaps` contents |
| Table structure | Account routable/blocked lists |
| Copy that is a LABEL | Copy that is a VALUE |

The mockup contains hardcoded sample data taken from the live 2026-07-29 page.
**Replace the data. Do not replace the structure.**

Test for the label/value distinction: "Your weight" is a label and is frozen.
"3.9%" is a value and must come from the API.

---

## 2. SECTION INVENTORY — all nine, in this order

```
1. COMMAND STRIP        title, freshness chips, refresh control
2. WHERE TO ACT         4 tiles: rank vs weight mismatches
3. MARKET STATE         6 metric cells + one-line tape summary
4. TRANSITIONS          table, 6 columns, includes a Read column
5. SECTOR LEADERS       timeframe toggle, 11-sector picker strip, expanded card
6. QUADRANT + LISTS     UNCHANGED FROM PRODUCTION — see section 5 below
7. YOUR BOOK            table, 6 columns, includes Sector rank
8. SHORT SIDE + HEDGES  two panels, side by side
9. OVERSIGHT            strongest objection + one counterpoint
```

A section that renders empty must say why it is empty. It must never render as
absent.

---

## 3. TOKEN MANIFEST

These are the literal values in the mockup. **Before using them, map each to the
existing CSS variable on `/v3/defense` that already carries that value.** Report
the mapping in your findings. Do not introduce a second set of variables that
duplicates the page's own.

```
--bg0    #0a0e1a    page background
--bg1    #111827    panel surface
--bg2    #161d2e    raised surface
--sunk   #0d121f    inset / footer surface
--line   #1e293b    hairline border
--line2  #2a3750    emphasized border
--t0     #f8fafc    headings, primary values
--t1     #e2e8f0    body text
--t2     #94a3b8    muted / labels
--t3     #64748b    dim / metadata
--green  #22c55e    leading, pass, routable
--red    #ef4444    lagging, blocked, veto
--amber  #ffb000    warning, stale, trim, directive
--blue   #60a5fa    selected state, held-position chip
--purple #a855f7    reserved, unused in v1
--mono   "JetBrains Mono", ui-monospace, Consolas, monospace
--sans   Inter, system-ui, -apple-system, "Segoe UI", sans-serif
```

**Every number renders in `--mono` with `font-variant-numeric: tabular-nums`.**
This is not decorative — columns of figures must align vertically. Check it.

### Component classes

`panel` `ph` `chip` `chip.g` `chip.r` `chip.a` `chip.b` `btn` `btn.p` `bar`
`mono` `muted` `dim` `unk` `grid` `sec` `wrap`

`unk` is the null-rendering class: italic, `--t3`, 12px, with the reason on
`title`. Every unsourced value uses it. A null must never render as an em-dash,
a zero, or a blank.

---

## 4. TABLE COLUMNS — exact, in order

```
Transitions    Sector | Change | RS 5d | Breadth | Your exposure | Read
Constituents   Name | Price | RS vs ind | 52w high | ADV20 | Position & flags
Your book      Position | Value | Sector rank | Stance | Account | Ladder
Short side     Name | Entry | Buy-stop | vs 200DMA | Industry
Hedges         Pair | Thesis | Entry | State
```

Do not add columns. Do not reorder. Do not rename.

---

## 5. SECTION 6 IS PRESERVED, NOT REBUILT

The rotation quadrant and both ranked lists are **explicitly approved as they
already exist in production**. The mockup redraws them only so the page reads as
a whole.

Keep the production implementations. Match their container styling to the rest
of the page — panel background, border, radius, header treatment — and change
nothing else about them. If the production versions already match, touch nothing.

---

## 6. ONE KNOWN BUG TO CARRY FORWARD

The mockup renders Oil & Gas Integrated as
`wide spread, leaders still trail XLE`.

Production currently renders `buy names` for the same data: spread 38.1pp, top
quartile **−9.14pp** vs XLE, n=14.

A wide spread whose top quartile *underperforms* the ETF is not a buy signal.
The threshold logic reads spread and excess independently when a negative excess
should dominate regardless of spread.

**Fix the logic, not just the string.** When top-quartile excess is negative, the
verdict cannot be "buy names" at any spread. Add a test.

---

## 7. ACCEPTANCE — screenshot comparison, not judgment

"It renders" is not acceptance. Run the same harness on both sides:

```python
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={'width': 1760, 'height': 1200}, device_scale_factor=2)
    pg.goto(URL)              # file:// for the mockup, http:// for the build
    pg.wait_for_timeout(600)
    pg.screenshot(path=OUT, full_page=True)
    b.close()
```

Produce `reference.png` from the mockup and `build.png` from the running page,
at the identical viewport. Deliver them side by side.

Then walk the nine sections and state, per section: **match / deviation / not
built**. A deviation is not a failure — an *undeclared* deviation is.

---

## 8. DEVIATION LOG — mandatory

Reality will not fit the mockup everywhere. When it does not, **write it down
rather than deciding silently**. For each deviation record:

```
- what the mockup shows
- what you built instead
- why the mockup could not be followed
- whether it needs operator sign-off
```

Deviations that ALWAYS need sign-off before shipping:
- a section omitted
- a column added, removed, or reordered
- a token value not present in the manifest
- any change to what a chip color means

Deviations that do NOT need sign-off, but must still be logged:
- real data producing different row counts than the sample
- a field the API cannot supply, rendered via `unk` with a reason
- text wrapping differently because real strings are longer

---

## 9. FORBIDDEN

- **Do not add features that are not in the mockup.** Additions in the previous
  round were good ideas and are now IN the mockup. Anything not in it is out of
  scope for this stage. Propose it; do not build it.
- Do not substitute a palette because it "matches the page better." The mockup
  was built on the page's own slate family. Map to existing variables; do not
  re-choose.
- Do not render a null as an em-dash, a zero, or a blank.
- Do not place, stage, or approve an order from anything on this page.
- Do not rebuild the quadrant or the ranked lists.
- Do not mark DONE without `reference.png` and `build.png` side by side.
