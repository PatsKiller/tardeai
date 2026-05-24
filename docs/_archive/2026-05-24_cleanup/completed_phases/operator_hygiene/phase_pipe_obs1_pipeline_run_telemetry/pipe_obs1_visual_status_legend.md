# Pipeline Status Color / Icon Legend

| Color | Icon | Status | Meaning | Operator Action |
|-------|------|--------|---------|-----------------|
| Green | ✅ | Healthy | Ran successfully with telemetry | None needed |
| Blue | 🕒 | Waiting | Before scheduled window | Wait for schedule |
| Yellow | ⚠️ | Needs Attention | Window passed, no run/data | Review scheduler or run dry-run |
| Orange | 🟠 | Blocked | Dependency or gate blocked | Check dependency/provider |
| Red | ⛔ | Failed | Ran and failed | Check logs, fix error |
| Gray | ◻ | Manual/On-Demand | Weekly or manual only | No daily action expected |
| Purple | 🧪 | Dry-Run | Test only, not production | Informational |

## Accessibility

- Every color has an icon + text label
- Never rely on color alone
- Dark theme readable
- High contrast borders
