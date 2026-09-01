# CC_REMEDIATION_2026-09-01

**Agent:** Cursor · Wave 3  
**Branch:** `agent/cursor-bisect-trade-2026-09-01`  
**as_of:** 2026-08-31T17:12Z  
**Authority:** push/PR only — no merge, no deploy

## What did not ship (and why)

1. **Finviz / scanner fill** — upstream; owned by Claude Code (bisect handoff).
2. **Watch Intelligence → InstrumentRecord wiring** — architectural; proposal only
   (`CC_WI_SPINE_WIRING_PROPOSAL_2026-09-01.md`). Wave 3 labels provenance instead.
3. **Drive upload via Cursor** — `gog` keyring needs TTY; no agent uploader
   (third mechanism forbidden). Artifacts under `/tmp/coord_run/` + worktree docs;
   Claude Code / operator sync.
4. **Deleting the accidental sync script** — `file-delete` guard blocked removal of
   `/tmp/coord_run/sync_cursor_docs_to_drive.sh`; ledgered, do not use it.
5. **Broad STALE chrome for all 25 census endpoints** — Wave 3 fixed the glance
   surfaces (MetricStrip / Home setups / TradingHub banner). Per-hub banners for
   SystemHub May–Jun freezes, Research staged, etc. remain follow-on.

## What shipped (this branch, unpushed until PR)

| change | why |
|---|---|
| `surfaceFreshness.ts` + `.test.ts` (20 checks, in `npm run build`) | Shared honesty: API `stale`+`cached_at` beats healed `run_date`; overview oldest-contributor age; WI provenance constants |
| `MetricStrip.tsx` | Visible ⚠ STALE + `as_of` under tiles; SETUPS shows STALE for empty 08-28-class cache |
| `TradingHub.tsx` | Stale banner uses same freshness; copy clarifies upstream empty ≠ missing route |
| `HomeHub.tsx` | Setups stale uses `tradeAiSurfaceFreshness` |
| `WatchIntelligenceUnified.tsx` | Synopsis provenance line (decision_projection, not spine) |
| Overnight docs | bisect, census, watch wiring, proposal, this remediation |

## Merge notes for Claude Code

- Frontend-only; no producer / lane_registry / notify / deploy scripts.
- Do **not** regenerate `docs/INDEX.md` from this branch.
- Dry-run: `node apps/command-center-v3/src/lib/surfaceFreshness.test.ts` then
  `npm run build` in `apps/command-center-v3`.
- No dollar-amount logic touched.
