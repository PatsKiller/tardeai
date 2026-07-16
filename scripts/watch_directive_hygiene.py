#!/usr/bin/env python3
"""Watch Desk v2 (B2): weekly directive hygiene.

Sunday cron: auto-apply dedup tiers 1–2 (malformed + dead — reversible archives
by design), then dry-run tier 3 (family merges) and Telegram the plan for
one-tap operator review. Never applies tier 3 automatically.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except Exception:
    pass


def _run(args: list[str]) -> str:
    cp = subprocess.run([sys.executable, str(ROOT / "scripts" / "watch_directive_dedup.py"), *args],
                        capture_output=True, text=True, timeout=600, cwd=str(ROOT))
    return (cp.stdout or "") + (cp.stderr or "")


def _expire_ttl() -> str:
    """Watch Desk v4 (C2): enforce ttl_days — stored since v2 but never enforced anywhere
    (diagnosis 0.2). active + past TTL → status='expired' (visible fold in UI, never
    deleted; operator resume un-expires). Returns a one-line summary for the Telegram plan."""
    try:
        from db_adapter import _execute
        rows = _execute("""UPDATE watch_directives
                           SET status='expired', updated_at=now()
                           WHERE status='active' AND ttl_days IS NOT NULL
                             AND created_at < now() - (ttl_days || ' days')::interval
                           RETURNING id, label""", fetch="all") or []
        if not rows:
            return "TTL expiry: none due"
        return ("TTL expiry: " + str(len(rows)) + " directive(s) → expired: "
                + ", ".join(f"#{r['id']} {str(r['label'])[:40]}" for r in rows[:8])
                + (" …" if len(rows) > 8 else ""))
    except Exception as e:
        return f"TTL expiry: FAILED ({str(e)[:80]})"


def main() -> int:
    applied = _run(["--apply", "--tier", "1", "--tier", "2"])
    ttl_line = _expire_ttl()
    plan3 = _run(["--tier", "3"])

    def _summary(txt: str) -> str:
        for line in txt.splitlines():
            if line.startswith("Would") or line.startswith("Relabeled") or "archive" in line.lower():
                return line.strip()[:220]
        return (txt.strip().splitlines() or ["(no output)"])[-1][:220]

    merge_lines = [ln.strip() for ln in plan3.splitlines() if ln.strip().startswith("#") or "survivor" in ln][:10]
    # Watch Desk v3 (A4): source league line — evidence for the cull decision
    league = ""
    try:
        from db_adapter import _execute
        rows = _execute("""SELECT source_type, count(*) FILTER (WHERE alpha_21d IS NOT NULL) AS n,
                                  round((percentile_cont(0.5) WITHIN GROUP (ORDER BY alpha_21d)
                                    FILTER (WHERE alpha_21d IS NOT NULL))::numeric,2) AS a
                           FROM watch_candidate_events GROUP BY 1 ORDER BY 1""", fetch="all") or []
        league = "\nSource league (21d α median): " + " · ".join(
            f"{r['source_type']} {('%+.1f%%' % r['a']) if r['a'] is not None else 'n/a'} (n={r['n']})" for r in rows)
    except Exception:
        pass

    msg = ("🧹 Watch-directive hygiene (Sunday)\n"
           f"Tiers 1–2 applied: {_summary(applied)}\n"
           f"{ttl_line}\n"
           "Tier-3 family merges awaiting operator approval:\n"
           + ("\n".join(f"  {ln[:100]}" for ln in merge_lines) if merge_lines else "  none")
           + "\nApprove via: python scripts/watch_directive_dedup.py --apply --tier 3"
           + league)
    try:
        from telegram_alert import send_telegram
        send_telegram(msg)
    except Exception:
        pass
    print(msg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
