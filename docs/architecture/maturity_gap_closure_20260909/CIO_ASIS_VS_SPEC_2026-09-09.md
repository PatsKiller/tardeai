# CIO AS-IS vs SPEC — 2026-09-09 (Maturity Gap Closure)

## AS-IS (recomputed)

| Surface | Truth |
|---|---|
| origin/main | `63dbfcc24` (PR #931 docs closeout; ancestor of served) |
| CURRENT served | `845ce5d88` release `845ce5d88-main-exact-phase2-20260909-083727` |
| Poller | PID 3871776 on `340aaf831` with `/usr/bin/python3.14 (deleted)` — **STALE** |
| Test DB barrier | `aa0cbb705` landed on campaign branch (dynamic pkgutil walk) |
| Research router | Canonical `brave_router.py` only; obsolete research router **absent** |
| MBI | 0 — no broker/order mutation in this campaign |
| Grants | git-push + release-write only |

## SPEC (acceptance)

- Serving process identity == CURRENT for API **and** poller
- Organic gateway SETTLED + inbound on CURRENT poller for CM2
- Provenance quarantine for synthetic provider ids (not channel bans)
- Retention/curation above DOCUMENTATION_ONLY only with full evidence bar
- Judgment/commitments/scoring/self-repair proven on serving SHA without financial mutation
