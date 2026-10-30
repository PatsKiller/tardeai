# Watch page repair

Status: Live verification pending release
**Date:** 2026-10-25
**Owner:** grok session grok-pages-20261025
**Design:** none. No `design/pages/watch/versions/v001` on this branch. The private Watch row board is `watch-row-redesign-20261024`.

| Element | Approved design says | Live shows (412/1440) | Verdict | Root cause (file:line) | Fix / owner PR |
|---|---|---|---|---|---|
| Ask the CIO | The button asks through the existing Ask the CIO pipeline and shows asked, answering, then answered, with a thread link and the CIO stance | The button only appended a thesis-queue request. Acquisition is scheduled and usually blocked, so the card did not change | BROKEN | `CioReview.useCioReview` called only `requestCioReview` | Ask goes to `POST /api/v2/cio/ask` first. The thesis queue remains a separate note. A missing structured stance is the gap "CIO stance was not in this answer." |
| Request times | Readable Eastern Time | Request chips sliced the timestamp and appended UTC | BROKEN | `reviewStateText` and the legacy flag clock | `etStamp`. An unzoned value says timezone unavailable |
| Next step while the check is unavailable | Do not say Resolve conflict when the conflict check itself is a gap | Detail said "Next: Resolve conflict" | BROKEN | `Detail` printed `next_action.label` even when the section was only a gap | `detailNextLine` says "Conflict check unavailable" and keeps the Ask button |
| Level footnote | One footnote: levels, source, and the stored time or "time unknown" | "levels: Master · time unknown" while a timestamp was stored | BROKEN | The footnote hid `as_of` unless `as_of_basis` was one of two labels | `levelFootnoteTime` shows a stored instant in ET. A date-only value stays a date |
| Desktop detail | The record sits beside the list | The detail panel was fixed over the list | LAYOUT | `.watch-card-detail` was `position: fixed` | At 821px and wider, inside the list viewport, the detail is sticky and in flow. The phone sheet stays full screen |
| Quote freshness | A gap stays a gap | "Time / freshness unknown" when the freshness verdict is missing | OK | `pricePresentation` already says that | Unchanged. The footnote no longer contradicts a stored clock |
| Tabs | My Watchlist, System Suggests, Prospects, Full universe, Watchpool, Sectors, Pullback/MACD, Classic, Discovery | All nine routes still render | OK | `WatchHub` tab row and `/watch/discovery` | None removed |
| Card actions | Phone keeps a 44px primary action and More | Already present | OK | `WatchRecordCard.css` phone grid | Kept |

NOT NEEDED: none. No tab or panel removed.

RESTORE: none.

Conviction sort and filter stay on the server. `scripts/lib/data_broker/watch_position_facts.py` is held by the perf claim, so this PR does not change it.

Live verification pending release.
