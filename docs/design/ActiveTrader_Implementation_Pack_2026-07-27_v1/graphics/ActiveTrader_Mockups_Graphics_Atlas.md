Status:      ACTIVE
as_of:       2026-07-28T00:17:07-04:00
Measured at: efcc51365 / not measured

ActiveTrader Mockups — Graphics Atlas

Canonical graphics folder:
https://drive.google.com/drive/folders/1kyRRCNDAYtyUfW0ucJYMoaj\_dz1ln5ux

FIGURE 1 — ACTIVE TRADE WINDOW
PNG: https://drive.google.com/file/d/147v0AYtruh5f6AJwSrlzdqHr5T4UwXDk/view
SVG: https://drive.google.com/file/d/1OMtLtPoL65QNxQYqi5QYG8uXLxsh-WIz/view

Purpose: evidence-first single-symbol review card. The initial implementation keeps the order grid display-only and changes the authority footer to MANUAL\_PAPER\_TEST\_ONLY. Operator quantity and tier-derived quantity remain separate.

FIGURE 2 — PERMISSION QUEUE
PNG: https://drive.google.com/file/d/1Gs1wlHGQwNPOIvwoHH899-4aA\_q24xUR/view
SVG: https://drive.google.com/file/d/1XQ5fmOIZc5lULzWP8-VGM0vdiVmKTB19/view

Purpose: rapid triage while retaining vetoed signals and explicit failure reasons. Rows select the review card; they do not arm or route an order.

FIGURE 3 — ACCOUNT ALLOCATION POPUP
PNG: https://drive.google.com/file/d/17TiXVVH9yvqjsjMI95UmTdBTGN415qwB/view
SVG: https://drive.google.com/file/d/1FFvKXdnpSbKICNDYHTt1WHB07Gp1mNEF/view

Purpose: account and venue visibility with per-account share entry and restrictions. For the first implementation, only a verified Alpaca Paper account may be selectable. Schwab and Alpaca Live remain disabled/read-only; Moomoo/OpenD is displayed as data-plane only; Thinkorswim is a separate manual handoff.

IMPLEMENTATION NOTE
Use the SVGs as the precise spacing and visual references. Build semantic React components using Command Center tokens; do not embed these graphics as the production interface.
