"""CIO opportunity store — curated OpportunityAssessment@v1 per symbol, persisted in CIO memory.

Investment Command Center (operator 2026-10-08): "make sure all data is curated by and persistent in CIO memory".
Two files under data/cio (a symlink into persistent state on every release):

  * cio_opportunity_assessments.jsonl — append-only version history. A symbol gets a new version only on a
    MATERIAL change (conviction ±N, rank band, stance/type, a level moving more than N%) — config
    opportunity_conviction.yaml ``material_change``. Each line: {schema, symbol, version, written_at, assessment,
    change_reasons, provenance}.
  * cio_opportunity_projection.json — the latest full ranking (every symbol, every run) for fast reads.

Separate from cio_theses.jsonl on purpose: publishing an assessment as a thesis version would replace the research
thesis's summary and evidence lists. The AI investment brief (PR-B) is thesis content and goes to the thesis.

MBI_BEHAVIOR = 0: every payload is refused if any key matches the CIO behaviour fields
(cio_instrument_record.BEHAVIOR_FIELDS — stop, limit, shares, qty, order, …), at any depth.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
EVENT_PATH = PROJECT_ROOT / "data" / "cio" / "cio_opportunity_assessments.jsonl"
PROJECTION_PATH = PROJECT_ROOT / "data" / "cio" / "cio_opportunity_projection.json"
SCHEMA = "OpportunityAssessmentVersion@v1"


class BehaviorFieldRefused(ValueError):
    pass


def _blocked() -> tuple[str, ...]:
    try:
        from scripts.lib.cio_instrument_record import BEHAVIOR_FIELDS
    except ImportError:  # pragma: no cover - flat import layout
        from lib.cio_instrument_record import BEHAVIOR_FIELDS  # type: ignore
    return tuple(BEHAVIOR_FIELDS)


def assert_no_behavior(obj: Any, path: str = "") -> None:
    """Refuse (never filter) any behaviour key anywhere in the payload."""
    blocked = set(_blocked())
    if isinstance(obj, dict):
        for k, v in obj.items():
            if str(k).lower() in blocked:
                raise BehaviorFieldRefused(f"behaviour field '{k}' at {path or '/'} refused (MBI_BEHAVIOR=0)")
            assert_no_behavior(v, f"{path}/{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            assert_no_behavior(v, f"{path}[{i}]")


def _f(v: Any) -> Optional[float]:
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def material_changes(prev: Optional[dict[str, Any]], new: dict[str, Any], cfg: dict[str, Any]) -> list[str]:
    """Reasons a new version is warranted (empty → not material). Pure."""
    if not prev:
        return ["first_assessment"]
    out = []
    dc = float(cfg.get("conviction_delta") or 5)
    if prev.get("conviction") is None or new.get("conviction") is None:
        if prev.get("conviction") != new.get("conviction"):
            out.append("conviction_availability")
    elif abs(new["conviction"] - prev["conviction"]) >= dc:
        out.append(f"conviction {prev['conviction']:.0f}→{new['conviction']:.0f}")
    band = int(cfg.get("rank_band_size") or 25)
    pb = (prev.get("rank") - 1) // band if prev.get("rank") else None
    nb = (new.get("rank") - 1) // band if new.get("rank") else None
    if pb != nb:
        out.append(f"rank band {prev.get('rank')}→{new.get('rank')}")
    for k in ("stance", "type", "technical_condition"):
        if prev.get(k) != new.get(k):
            out.append(f"{k} {prev.get(k)}→{new.get(k)}")
    lp = float(cfg.get("level_delta_pct") or 2.0)
    pr, nr = prev.get("risk_reward") or {}, new.get("risk_reward") or {}
    pt = ((pr.get("targets") or [{}])[0]).get("px")
    nt = ((nr.get("targets") or [{}])[0]).get("px")
    for name, a, b in (("entry", pr.get("entry_ref"), nr.get("entry_ref")),
                       ("invalidation", pr.get("invalidation_level"), nr.get("invalidation_level")),
                       ("target", pt, nt)):
        a, b = _f(a), _f(b)
        if (a is None) != (b is None) or (a and b and abs(b - a) / a * 100 > lp):
            out.append(f"{name} level moved")
    return out


class CIOOpportunityStore:
    def __init__(self, event_path: Path | None = None, projection_path: Path | None = None):
        self.event_path = Path(event_path or EVENT_PATH)
        self.projection_path = Path(projection_path or PROJECTION_PATH)

    def heads(self) -> dict[str, dict[str, Any]]:
        """{symbol: latest version line} from the append-only history."""
        out: dict[str, dict[str, Any]] = {}
        if not self.event_path.exists():
            return out
        with self.event_path.open(encoding="utf-8") as fh:
            for line in fh:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                s = row.get("symbol")
                if s and int(row.get("version") or 0) >= int((out.get(s) or {}).get("version") or 0):
                    out[s] = row
        return out

    def plan(self, assessments: list[dict[str, Any]], cfg: dict[str, Any]) -> list[dict[str, Any]]:
        """Version lines that WOULD be appended (material changes only). Pure w.r.t. the files."""
        heads = self.heads()
        now = datetime.now(timezone.utc).isoformat()
        lines = []
        for a in assessments:
            assert_no_behavior(a)
            prev = heads.get(a["symbol"])
            reasons = material_changes((prev or {}).get("assessment"), a, cfg)
            if reasons:
                lines.append({"schema": SCHEMA, "symbol": a["symbol"],
                              "version": int((prev or {}).get("version") or 0) + 1, "written_at": now,
                              "assessment": a, "change_reasons": reasons})
        return lines

    def append(self, lines: list[dict[str, Any]], provenance: dict[str, Any]) -> int:
        if not lines:
            return 0
        self.event_path.parent.mkdir(parents=True, exist_ok=True)
        with self.event_path.open("a", encoding="utf-8") as fh:
            for ln in lines:
                assert_no_behavior(ln)
                fh.write(json.dumps({**ln, "provenance": provenance}, default=str) + "\n")
        return len(lines)

    def write_projection(self, assessments: list[dict[str, Any]], meta: dict[str, Any]) -> None:
        from lib.data_broker.atomic_json import atomic_write_json

        body = {"schema": "OpportunityProjection@v1", **meta, "count": len(assessments),
                "items": {a["symbol"]: a for a in assessments}}
        assert_no_behavior(body)
        self.projection_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(self.projection_path, body)

    def read_projection(self) -> dict[str, Any]:
        try:
            return json.loads(self.projection_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def history(self, symbol: str, limit: int = 20) -> list[dict[str, Any]]:
        out = []
        if not self.event_path.exists():
            return out
        s = symbol.upper()
        with self.event_path.open(encoding="utf-8") as fh:
            for line in fh:
                if f'"symbol": "{s}"' not in line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if row.get("symbol") == s:
                    out.append({"version": row.get("version"), "written_at": row.get("written_at"),
                                "change_reasons": row.get("change_reasons"),
                                "conviction": (row.get("assessment") or {}).get("conviction"),
                                "rank": (row.get("assessment") or {}).get("rank"),
                                "stance": (row.get("assessment") or {}).get("stance")})
        return out[-limit:]
