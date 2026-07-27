# /v3-next Accessibility Report — Stage 6

- Landmarks: session strip `role="banner"`; each panel is a `<section aria-label=...>`; nav is
  `<nav aria-label="workspace switch">`; Moomoo badge `role="status"`.
- Disabled actions carry `disabled` + `aria-disabled="true"` + a title explaining read-only.
- Symbol selector is a labeled native `<select>` (keyboard accessible).
- Tables use `<thead>/<th>` headers.
- Responsive: main grid uses CSS grid (`gridTemplateColumns: 1fr 1fr 1fr`) that reflows; relative
  units; no fixed-width overflow. (Full WCAG audit deferred; this is a dev workspace.)
- Automated checks: the vitest suite asserts landmark testids and disabled/aria-disabled actions.
