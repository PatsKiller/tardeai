"""Phase B TIS Telegram digest — coverage SLA + reentry band + material thesis debt.

Authority: READ_ONLY_ADVISORY. Uses CIO-only bot. Never general Maria bot.
IMMEDIATE paths remain situation detector (S6 / S3 ACT_NOW / …).
This script sends DIGEST-class advisories driven by cio_tis_policy telegram.digest.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

AUTHORITY = "READ_ONLY_ADVISORY"
LEDGER_REL = Path("data/cio/cio_tis_digest_ledger.json")


def _load_cio_env_files(*, root: Path | None = None) -> list[str]:
    """Load CIO Telegram credentials the same way converse/canary do.

    Order (first wins only if key unset): runtime SM render → cio-telegram.env →
    project .env. Never logs values.
    """
    uid = os.getuid()
    root = Path(root or ROOT)
    candidates = [
        Path(f"/run/user/{uid}/tradeai/env"),
        Path.home() / ".config" / "tradeai" / "cio-telegram.env",
        root / ".env",
        Path("/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.env"),
    ]
    loaded: list[str] = []
    for p in candidates:
        if not p.is_file():
            continue
        try:
            for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if not k.isidentifier():
                    continue
                if k not in os.environ or not str(os.environ.get(k) or "").strip():
                    os.environ[k] = v
            loaded.append(str(p))
        except Exception:
            continue
    return loaded


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _digest(*parts: Any) -> str:
    blob = "|".join(str(p if p is not None else "") for p in parts)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:20]


def _load_ledger(root: Path) -> dict[str, Any]:
    path = root / LEDGER_REL
    if not path.exists():
        return {"entries": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"entries": {}}
    except Exception:
        return {"entries": {}}


def _save_ledger(root: Path, ledger: dict[str, Any]) -> None:
    path = root / LEDGER_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")


def _hours_since(iso: Optional[str]) -> float:
    if not iso:
        return 1e9
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).total_seconds() / 3600.0
    except Exception:
        return 1e9


def _is_ticker(sym: str) -> bool:
    s = str(sym or "").strip().upper()
    if not s or len(s) > 5:
        return False
    if s[0].isdigit():
        return False
    return s[0].isalpha() and all(c.isalnum() or c in ".-" for c in s)


def build_digest_payload(*, root: Path | None = None) -> dict[str, Any]:
    from scripts.lib.cio_tis_policy import (
        evaluate_coverage_sla,
        load_tis_policy,
        stale_days,
        telegram_rules,
    )
    from scripts.lib.symbol_thesis_coverage import build_coverage_report

    root = Path(root or ROOT)
    pol = load_tis_policy(root=root)
    tg = telegram_rules(pol)
    report = build_coverage_report(root=root, stale_days=stale_days(pol), material_only=False)
    sla = evaluate_coverage_sla(report, policy=pol)

    lines: list[str] = []
    kinds: list[str] = []
    symbols: list[str] = []

    digest_kinds = set(tg.get("digest") or [])
    max_sym = int(tg.get("digest_max_symbols") or 12)

    if "COVERAGE_SLA_BREACH" in digest_kinds and not sla.get("sla_ok"):
        kinds.append("COVERAGE_SLA_BREACH")
        lines.append("TIS coverage SLA breach (thesis parity — not concentration-gated):")
        for b in sla.get("breaches") or []:
            miss = [s for s in (b.get("missing") or []) if _is_ticker(s)]
            symbols.extend(miss[:max_sym])
            lines.append(
                f"  • {b['bucket']}: {b['actual_pct']}% CURRENT "
                f"(target {b['target_pct']}%) — missing e.g. {', '.join(miss[:8]) or '—'}"
            )

    # Reentry READY/NEAR without CURRENT thesis (ticker-only)
    re_debt = [
        r for r in (report.get("rows") or [])
        if _is_ticker(r.get("symbol") or "")
        and any(x in str(r.get("reentry_state") or "").upper() for x in ("READY", "NEAR", "GO", "IN_ZONE"))
        and r.get("coverage_state") != "CURRENT"
    ]
    if re_debt and "REENTRY_BAND_CHANGE" in digest_kinds:
        kinds.append("REENTRY_THESIS_DEBT")
        sample = [r["symbol"] for r in re_debt[:max_sym]]
        symbols.extend(sample)
        lines.append(
            f"Re-entry READY/NEAR without CURRENT thesis ({len(re_debt)}): "
            + ", ".join(sample)
        )

    held_debt = [
        r for r in (report.get("rows") or [])
        if _is_ticker(r.get("symbol") or "")
        and "HELD" in set(r.get("memberships") or [])
        and r.get("coverage_state") != "CURRENT"
    ]
    if held_debt and "THESIS_PUBLISHED_MATERIAL" in digest_kinds:
        kinds.append("HELD_THESIS_DEBT")
        sample = [r["symbol"] for r in held_debt[:max_sym]]
        symbols.extend(sample)
        lines.append(
            f"Held names without CURRENT thesis ({len(held_debt)}): " + ", ".join(sample)
        )

    fp = _digest("tis_digest", *sorted(set(kinds)), *sorted(set(symbols))[:24], sla.get("sla_ok"))
    body = "\n".join(lines).strip()
    return {
        "schema": "CioTisDigest@v1",
        "as_of": _now(),
        "authority": AUTHORITY,
        "telegram_enabled": bool(tg.get("enabled")),
        "kinds": kinds,
        "symbols": sorted(set(symbols))[: max_sym * 2],
        "fingerprint": fp,
        "body": body,
        "sla": sla,
        "cooldown_hours": int(tg.get("digest_cooldown_hours") or 12),
        "should_send": bool(tg.get("enabled") and body and kinds),
        "cc_deep_link": "/v3/cio?tab=tis-layout",
    }


def maybe_send_digest(
    *,
    root: Path | None = None,
    force: bool = False,
    dry_run: bool = True,
) -> dict[str, Any]:
    root = Path(root or ROOT)
    loaded_env = _load_cio_env_files(root=root)
    # Live delivery gates (process-scoped; match converse/canary)
    if not dry_run:
        os.environ.setdefault("AUTHORIZE_P2_LIVE_OPERATOR_DELIVERY", "1")
        os.environ.setdefault("ENABLE_TELEGRAM", "1")
        if os.environ.get("CIO_TELEGRAM_INTERDICT", "").strip() in {"1", "true", "TRUE"}:
            pass  # honor explicit interdict
        else:
            os.environ["CIO_TELEGRAM_INTERDICT"] = "0"

    payload = build_digest_payload(root=root)
    out = {
        "ok": True,
        "dry_run": dry_run,
        "delivered": False,
        "authority": AUTHORITY,
        "env_files_loaded": loaded_env,
        "payload": payload,
    }
    if not payload.get("should_send") and not force:
        out["skip"] = "nothing_to_digest_or_telegram_disabled"
        return out

    ledger = _load_ledger(root)
    entries = ledger.setdefault("entries", {})
    prev = entries.get(payload["fingerprint"]) or {}
    if not force and _hours_since(prev.get("sent_at")) < float(payload.get("cooldown_hours") or 12):
        out["skip"] = "cooldown"
        out["previous"] = prev
        return out

    text = (
        "CIO TIS digest (advisory only)\n\n"
        + (payload.get("body") or "")
        + f"\n\nOpen: {payload.get('cc_deep_link')}\nAuthority: {AUTHORITY}"
    )

    if dry_run:
        out["skip"] = "dry_run"
        out["would_send_text"] = text
        return out

    try:
        from scripts.lib.cio_telegram_transport import send_cio_message
    except Exception:
        from lib.cio_telegram_transport import send_cio_message  # type: ignore

    res = send_cio_message(
        text,
        kind="cio_tis_digest",
        require_live_auth=True,
        force=force,
        dedupe_key=f"tis_digest:{payload['fingerprint']}",
        decision_id=f"dec_tis_digest_{payload['fingerprint']}",
    )
    out["delivery"] = res
    out["delivered"] = bool(res.get("delivered"))
    if out["delivered"]:
        entries[payload["fingerprint"]] = {
            "sent_at": _now(),
            "kinds": payload.get("kinds"),
            "symbols": payload.get("symbols"),
        }
        # prune old
        if len(entries) > 200:
            for k in list(entries.keys())[:-100]:
                entries.pop(k, None)
        _save_ledger(root, ledger)
    return out


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="CIO TIS Phase B Telegram digest")
    ap.add_argument("--apply", action="store_true", help="Actually send via CIO bot")
    ap.add_argument("--force", action="store_true", help="Bypass cooldown / empty skip")
    ap.add_argument("--root", default=str(ROOT))
    args = ap.parse_args(argv)
    result = maybe_send_digest(root=Path(args.root), force=args.force, dry_run=not args.apply)
    print(json.dumps(result, indent=2, default=str))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
