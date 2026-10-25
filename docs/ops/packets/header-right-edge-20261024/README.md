# Header right-edge fixture evidence

Status: Local fixture proof; no runtime acceptance claim
as_of: 2026-10-24
Design-Task: DSN-20261024-header-right-edge-P1-T1
Baseline: 68994d0c20b49c913d9fa7f7f2f3ef778d370fe0

`before/` and `after/` contain unedited synthetic screenshots and exact geometry JSON.
No screenshot contains live portfolio data. `manifest.json` binds source and evidence digests.

| Width | Before desktop row | After desktop row | Fixed live-badge right edge |
|---:|---:|---:|---:|
| 821 | 74 px | 62 px | 805 px |
| 1280 | 74 px | 62 px | 1264 px |
| 1440 | 74 px | 62 px | 1424 px |
| 1920 | 74 px | 62 px | 1904 px |
| 2560 | 74 px | 62 px | 2544 px |
| 412 | Full row collapsed | Full row collapsed | Compact mobile header retained |

The normal fixture has three approvals and 24 health findings, four critical. Additional
821/1280 scenarios use 125 approvals and 125 findings, 12 critical; 821 also exercises
`AUTO LIVE` and `AUTO BLOCKED`. Every overflowing desktop case proves native ArrowRight and
mouse-wheel horizontal scrolling and stable right-control rectangles. All chips and text
ranges fit without overlap or clipping. At 2560 all metrics fit, so the overflow cue is absent.

To rerun from the worktree:

```bash
cd /home/johnclaw/wt-codex-header-right-edge-20261024/apps/command-center-v3
node e2e/header-right-edge.fixture.mjs /home/johnclaw/.cache/rtc/codex-header-edge-20261024/review-before before
node e2e/header-right-edge.fixture.mjs /home/johnclaw/.cache/rtc/codex-header-edge-20261024/review-after
```

The baseline mode requires the baseline Git object; ordinary CI runs only the candidate
mode. The fixture creates its evidence directory, renders the real component/CSS without a
server and refuses unexpected origins, mutation methods or unconfigured API requests.
API values, clock and banner are synthetic. Source and CI proof remain distinct from release proof.
