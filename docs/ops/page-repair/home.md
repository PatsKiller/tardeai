# Home page repair — Board 14

Status: Live verification pending release
**Date:** 2026-10-25
**Owner:** grok session grok-pages-20261025
**Design:** private Board 14 (`desks-redesign-20261024` SPEC addendum and Home mockup). No `design/pages/home/versions/v001` on this branch.

Served footer at survey was not `03ad8b71d`. This branch is based on that commit. Live checks wait for the coordinator release.

| Element | Approved design says | Live shows (412/1440) | Verdict | Root cause (file:line) | Fix / owner PR |
|---|---|---|---|---|---|
| Do now kinds | STOP, REVIEW, ENTRY, INFO chips on CIO-ranked rows, max 7 | Rows had title and reason only | BROKEN | `cio_truth.do_now_for` items have no kind | `home_board14.shape_do_now` tags STOP and REVIEW. ENTRY and INFO are not invented |
| No-stop roll-up | One REVIEW row, "N names / no broker stop" | One row per unprotected name | BROKEN | `do_now_for` emits one item per name | Same shaper. Awaiting-fill and pending activation stay separate STOP rows |
| Protection link | "Set stops" / review opens the stop review view, never a broker action | Protection card links to Risk | OK | Existing Risk link | Kept. A single protection id still opens that Risk position. Roll-up opens the Risk list |
| Holdings weekend wording | "Market closed · last broker sync … · next …". Stale only when a scheduled sync was missed | Age only | BROKEN | Holdings clock had no closed-market phrase | `holdings_market_note` from the schwab-position-sync cron `7,22,37,52 9-16 * * 1-5` |
| Jobs source clock | "all ran on schedule" only when the monitor says so | No Jobs chip | MISSING | Home sources omitted the watchdog receipt | Jobs chip reads `cron_outage_watchdog_latest.json`. `homeDeskMount` adds that clock from the page payload. Missing receipt is a gap, never an all-clear |
| Regime since | "Regime [label] since [date]" | Snapshot time only | BROKEN | Classifier snapshot has no start column | Since is the earliest current label after a different label in history. Otherwise a gap. `generated_at` is not "since" |
| VIX | VIX number, or a gap that does not hide the regime label | One gap replaced the section when VIX was null | BROKEN | `regime_for` gap reason covers the whole section | Label stays. VIX null keeps "VIX input unavailable for classifier snapshot" |
| Waiting on you | Approvals count, questions answered N new, releases to merge N | Approvals count. Questions and releases were links without counts | MISSING | No count on the Home payload | Questions: answer versions since yesterday 00:00 ET, count only. Releases: hygiene receipt `open_prs`. Missing source is a gap, not 0 |
| Phone shell sideways overflow | Page scrolls vertically, no sideways scroll | #2126 focused-playwright failed on horizontal overflow | BROKEN | `phoneShell.css` overflow at 390px | Not this PR. Claim `20261025T203044Z-claude-abf8a6f7` holds `phoneShell.css` and `HomeHub.tsx` for phone shell v2 (heartbeat 2026-10-25T20:30Z). This PR does not edit those files |

NOT NEEDED: none. No panel removed.

RESTORE: none on this branch. The paused CIO decision-engine lane id stays on this branch; #2126 removes it.

Live verification pending release.
