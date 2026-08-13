#!/usr/bin/env python3
"""Fast drain of hermes_directive_hits_staging → watch_directive_hits.

Skips Trade-AI resolve + Finviz enrich so multi-thousand backlogs can clear.
Default: stage-only promote (auto=False) — records honest hermes hits, marks drained,
touches last_serviced_at. Use --promote for full governor/enrich path (slow, lock-prone).

  .venv/bin/python scripts/ops/drain_hermes_directive_staging.py --apply --max 500
  .venv/bin/python scripts/ops/drain_hermes_directive_staging.py --apply --max 5000 --stage-only
  .venv/bin/python scripts/ops/drain_hermes_directive_staging.py --apply --touch-quiet
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
os.chdir(ROOT)


def _load_env() -> None:
    # Prefer SM tmpfs; fall back to disk .env. Only shell-valid keys.
    candidates = [
        Path(os.environ.get("TRADEAI_ENV_FILE", f"/run/user/{os.getuid()}/tradeai/env")),
        ROOT / ".env",
    ]
    for env_file in candidates:
        if not env_file.is_file():
            continue
        for line in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line or line.lstrip().startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k = k.strip()
            if not k or not (k[0].isalpha() or k[0] == "_") or not all(
                c.isalnum() or c == "_" for c in k
            ):
                continue
            v = v.strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
                v = v[1:-1]
            os.environ.setdefault(k, v)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="mutate DB (default dry-run)")
    ap.add_argument("--max", type=int, default=500, help="max staging rows this pass")
    ap.add_argument(
        "--stage-only",
        action="store_true",
        default=True,
        help="force auto=False promote (default; fast hit-only)",
    )
    ap.add_argument(
        "--promote",
        action="store_true",
        help="full promote_directive_lead (enrich + watchpool; slow)",
    )
    ap.add_argument(
        "--touch-quiet",
        action="store_true",
        help="mark active directives with no undrained hermes as serviced (clears stale count)",
    )
    ap.add_argument("--commit-every", type=int, default=100)
    args = ap.parse_args()
    stage_only = not args.promote
    _load_env()

    import psycopg2
    import psycopg2.extras
    import directive_promotion as dp
    from research_critique_pipeline import is_removal_flagged, load_critique_snapshot

    conn = psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", "5432"),
        dbname=os.getenv("DB_NAME", "trade_ai"),
        user=os.getenv("DB_USER", "trade_ai"),
        password=os.getenv("DB_PASSWORD"),
        cursor_factory=psycopg2.extras.RealDictCursor,
    )
    # Avoid multi-minute lock waits on busy watchlist_items
    cur = conn.cursor()
    cur.execute("SET lock_timeout = '3s'")
    cur.execute("SET statement_timeout = '30s'")

    critique = load_critique_snapshot()
    stale_ids = set((critique.get("index") or {}).get("stale_directive_ids") or [])

    cur.execute(
        """SELECT count(*) AS n FROM hermes_directive_hits_staging WHERE NOT drained"""
    )
    before = int(cur.fetchone()["n"])

    cur.execute(
        """SELECT h.id, h.directive_id, h.symbol, h.thesis, h.source_detail, d.label, d.status
           FROM hermes_directive_hits_staging h
           JOIN watch_directives d ON d.id = h.directive_id
           WHERE NOT h.drained AND d.status = 'active'
           ORDER BY h.proposed_at ASC
           LIMIT %s""",
        (max(1, args.max),),
    )
    rows = cur.fetchall() or []

    report = {
        "apply": args.apply,
        "stage_only": stage_only,
        "before_undrained": before,
        "batch": len(rows),
        "drained": 0,
        "discarded_stale": 0,
        "skipped_critique": 0,
        "promoted": 0,
        "staged": 0,
        "errors": 0,
        "error_samples": [],
        "directives_touched": set(),
    }

    auto_flag = False if stage_only else None

    for i, h in enumerate(rows):
        did = h["directive_id"]
        if did in stale_ids:
            report["skipped_critique"] += 1
            if args.apply:
                cur.execute(
                    "UPDATE hermes_directive_hits_staging SET drained=true, drained_at=now() WHERE id=%s",
                    (h["id"],),
                )
                report["discarded_stale"] += 1
            continue

        sym = (h.get("symbol") or "").upper().strip()
        if not sym:
            if args.apply:
                cur.execute(
                    "UPDATE hermes_directive_hits_staging SET drained=true, drained_at=now() WHERE id=%s",
                    (h["id"],),
                )
                report["discarded_stale"] += 1
            continue

        detail = h.get("source_detail")
        if isinstance(detail, str):
            try:
                detail = json.loads(detail)
            except Exception:
                detail = {}
        if is_removal_flagged(detail or {}):
            if args.apply:
                cur.execute(
                    "UPDATE hermes_directive_hits_staging SET drained=true, drained_at=now() WHERE id=%s",
                    (h["id"],),
                )
            report["discarded_stale"] += 1
            continue

        if not args.apply:
            report["drained"] += 1
            continue

        reason = f"hermes:{(h.get('thesis') or '')[:60]}"
        try:
            res = dp.promote_directive_lead(
                sym, did, reason, "hermes", conn=conn, auto=auto_flag
            )
            st = res.get("status")
            if st == "PROMOTED":
                report["promoted"] += 1
            elif st == "STAGED_FOR_REVIEW":
                report["staged"] += 1
            elif st == "ERROR":
                report["errors"] += 1
                if len(report["error_samples"]) < 5:
                    report["error_samples"].append(
                        {"symbol": sym, "error": res.get("error")}
                    )
        except Exception as exc:
            report["errors"] += 1
            if len(report["error_samples"]) < 5:
                report["error_samples"].append({"symbol": sym, "error": str(exc)[:140]})
            # Still mark drained on lock timeout? No — leave for retry unless stage-only
            # hit insert may have partially committed in promote's own commits.
            # Mark drained only if we got past promote without exception; on exception retry.
            continue

        cur.execute(
            "UPDATE hermes_directive_hits_staging SET drained=true, drained_at=now() WHERE id=%s",
            (h["id"],),
        )
        cur.execute(
            "UPDATE watch_directives SET last_serviced_at=now(), updated_at=now() WHERE id=%s",
            (did,),
        )
        report["drained"] += 1
        report["directives_touched"].add(did)

        if (i + 1) % max(1, args.commit_every) == 0:
            conn.commit()

    quiet_touched = 0
    if args.apply and args.touch_quiet:
        # Active directives with zero undrained hermes staging → mark serviced
        # so monitor stale count reflects real backlog only.
        cur.execute(
            """UPDATE watch_directives d
               SET last_serviced_at = now(), updated_at = now()
               WHERE d.status = 'active'
                 AND (d.last_serviced_at IS NULL
                      OR d.last_serviced_at < now() - interval '24 hours')
                 AND NOT EXISTS (
                   SELECT 1 FROM hermes_directive_hits_staging h
                   WHERE h.directive_id = d.id AND NOT h.drained
                 )"""
        )
        quiet_touched = cur.rowcount

    if args.apply:
        conn.commit()

    cur.execute(
        """SELECT count(*) AS n FROM hermes_directive_hits_staging WHERE NOT drained"""
    )
    after = int(cur.fetchone()["n"])
    cur.execute(
        """SELECT count(*) AS n FROM watch_directives WHERE status='active'
           AND (last_serviced_at IS NULL OR last_serviced_at < now()-interval '24 hours')"""
    )
    stale_left = int(cur.fetchone()["n"])
    conn.close()

    out = {
        **{k: v for k, v in report.items() if k != "directives_touched"},
        "directives_touched": len(report["directives_touched"]),
        "quiet_directives_touched": quiet_touched,
        "after_undrained": after,
        "stale_directives_left": stale_left,
        "cleared": before - after,
    }
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
