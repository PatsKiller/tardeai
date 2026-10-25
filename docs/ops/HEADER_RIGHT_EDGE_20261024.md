# WP-31 desktop header right-edge correction

Status: Implemented and fixture-tested locally; publication pending
as_of: 2026-10-24
Owner: codex-header-edge-20261024; coordinator owns publication
Design-Task: DSN-20261024-header-right-edge-P1-T1
Source base: 68994d0c20b49c913d9fa7f7f2f3ef778d370fe0

At 1280 and 1440 pixels, the original header placed the rightmost live badge at about
x=1821, outside the viewport. All metric tiles and attention controls shared one scrolling
row, whose scrollbar was hidden. An operator could therefore miss Alerts, Approvals,
Health and live status without a visible scrolling affordance.

`MetricStrip.tsx` now separates the desktop metrics viewport from a nonshrinking right-side
action group. Only the metrics scroll. A visible scrollbar and an overflow-only ↔ cue expose
that behavior; the focusable metrics region supports native horizontal arrow-key and mouse
scrolling. ResizeObserver updates the cue after viewport or content changes. Data selection,
labels, provenance, drills, navigation, alerts modal and live-gate decisions retain their
existing implementations.

The desktop row now has an actual bounding height of 62 pixels, including padding. The
baseline declared 62 pixels with `content-box`, which produced a 74-pixel bounding height.
Desktop border-box sizing and vertical spacing restore the requested 62-pixel height while
keeping label, value and provenance lines inside it. The strip's existing bottom separator
remains separate. At <=820 pixels, transparent wrappers preserve the original collapsed
and expanded layouts; the 412-pixel expanded row remains 251.1875 pixels tall.

The [fixture runner](../../apps/command-center-v3/e2e/header-right-edge.fixture.mjs) bundles
the real component and actual `index.css`, including tokens, global box sizing and terminal
styles. It uses the app-shell layout plus a synthetic banner offset. Every request is
fulfilled inside Chromium; no local server, live API, cookie, credential or broker is used.
The exact baseline component/CSS come from the source-base commit above.

The [evidence packet](packets/header-right-edge-20261024/README.md) contains unedited PNGs
and geometry receipts for 1280, 1440, 1920, 2560, 412 and the 821-pixel desktop breakpoint.
Ten scenarios include 24 health findings/four critical/three approvals, larger counts, and
all three live-badge states. Mobile expansion is captured separately.

The assertions require each of the four action boxes and its text range to fit inside the
viewport, row and action group without overlap or clipping. They require an actual 62-pixel
desktop row, bounded metric text lines, zero page-sideways overflow, a nonvacuous overflow
case at 1280/821, visible cue, reachable horizontal content, and unchanged action/chip bounds
after programmatic, keyboard and mouse scrolling. Mobile compact/expanded behavior is checked.

Validation passed:

- Ten baseline captures and ten fixed scenarios; all seven header APIs mocked, zero real HTTP requests.
- 50 metric-label assertions and UI standards.
- `npm run build`, including its native guards, TypeScript and Vite; existing bundle-size warnings remain.
- 51 existing header/design/journal regressions with `psycopg2` hidden and effective import refusal verified.
- Coverage and host-path guards with zero new unlisted files or host-path violations; docs index and whitespace checks.

The new optional `header-right-edge-fixture` workflow runs the geometry runner on relevant ready
PRs and manual dispatch, with a read-only GitHub token and screenshot/receipt uploads. It starts
no server. Required GitHub checks and deployment remain unmeasured before publication. No
protected policy, `surfaceFreshness.ts`, broker/order/stop code or runtime state changed.
