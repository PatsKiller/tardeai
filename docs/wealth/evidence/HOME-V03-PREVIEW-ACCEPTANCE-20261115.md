# Home v03 static preview: acceptance record (2026-11-14, ~19:00 ET)

**Scope accepted:** the v03 static Home markup update on the approved preview link only. **Not accepted:** real data, backend wiring, or a whole-site audit.

| Item | Value |
|---|---|
| Source (operator reference) | sha256 6c248c9641137e32cbbfa1a06739625c285fd41785ca01f125cc4522110aafc8 (129040 B) |
| Served wrapper | sha256 bbbaa8bd04d90c5a961a5a99bc85623e7a05c7edf11c2feb40832bf4f1be3267 (130256 B) |
| Release dir | ~/deploy/wealth/releases/preview-20261114T2354Z (receipt PREVIEW-RECEIPT.json) |
| Rollback | ln -sfn to releases/preview-20261114T2320Z, then an atomic mv -T to `current` |

## Independent review (operator, connected Chrome; reviewer is not the author)
- All 3 retained sections are present (book & watch movers, what to read first, protection plan), with the v03 banner and the fictional-data banner.
- Scope: mover cards and reading/protection membership honour All/IRA/Taxable. Taxable excludes the Aurora/Nova movers; IRA excludes Orbital.
- Nova's 500 uncovered-share exception is consistent. The no-change/exempt disclosure expands and collapses and shows both cards.
- The Aurora mover opens the right account/security drawer with the same session move, quantity, cost and valuation.
- Desktop screenshot: compact cards match the intended direction.
- Mobile geometry at an effective CSS innerWidth of 390 (corrected for 80% browser zoom): **PASS**. No horizontal overflow; the mover grid is 2 columns and reading/protection is 1 column.
- Independent phone visual capture: **NOT_TESTED** (two captures timed out). This is not recorded as a pass.

## Author-side headless evidence (claude-lead, kept separate)
Playwright at 1440 and 412: 0 console errors, 0 external requests, all 3 sections present, no overflow. Tailnet and loopback both 200, served sha = wrapper.

## Next (runbook)
Trace each module's real backend before wiring (owner cc-deepseek-4, reviewer cc-deepseek-3). Rows #home/today:book-movers, :read-first and :protection-plan stay UNMAPPED until then.
