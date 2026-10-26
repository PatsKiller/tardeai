"""Ticker Prospectus → CIO memory (operator 2026-10-26: "I need to ensure that this is also in the CIO memory.
Very important.").

Every finished prospectus version (``ready`` or ``partial``) becomes one ``ProspectusMemory@v1`` record in the
CIO-owned **SecurityResearchSpine** — the shared research memory every silo, Ask the CIO and the CIO desk read
(AGENTS.md "Shared security research — NO SILOS", §26). It goes through the existing governed write call
(``security_research_spine.upsert_research_memory``: registry GUID required, ``silo="cio"``, tagged contribution,
``thesis_patch=None`` so model prose never replaces the house thesis tip), and the same payload is handed to
``research_write_path.submit`` as lane ``prospectus-writer``, which records a ``WritePathReceipt@v1`` (SHADOW
unless the operator flips the lane in ``config/memory_influence_policy.json``). No new store, no DB write.

Idempotent by (symbol, version): a version already on the spine is skipped. A newer version supersedes the tip
record; every version keeps a compact row in ``prospectus_history``.

READ_ONLY_ADVISORY (MBI_BEHAVIOR=0): the record carries text, scores, analyst-anchored scenario prices and the
house stop policy's advisory level as a fact — never a quantity, exposure dollars, an order or a stop instruction,
and no key in ``cio_instrument_record.BEHAVIOR_FIELDS``.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Iterable

SCHEMA = "ProspectusMemory@v1"
LANE_ID = "prospectus-writer"
KIND = "prospectus_version"
TAGS = ("prospectus", "llm_research", "lifecycle")
LINK_PREFIX = "/v3/prospectus/"
FINISHED = ("ready", "partial")
ADVISORY = "READ_ONLY_ADVISORY: research memory only; no AI places, sizes or stops orders."

_CITE_RE = re.compile(r"\s*\[(?:F|W)?\d+(?:\s*,\s*(?:F|W)?\d+)*\]")
_BULLET_RE = re.compile(r"^\s*(?:[-*•]|\d{1,2}[.)])\s+(.*\S)")
_STANCE_RE = re.compile(r"^([A-Z][A-Z -]{1,16}?)\s*(?:[—:–-]|$)")


def _clean(text: Any, n: int) -> str:
    s = _CITE_RE.sub("", str(text or ""))
    s = re.sub(r"[*_`#>]+", "", s)
    s = " ".join(s.split())
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def model_label(model: Any) -> str:
    m = str(model or "").lower()
    if "fable" in m:
        return "Fable"
    if "opus" in m:
        return "Opus"
    if "sonnet" in m:
        return "Sonnet"
    return str(model or "unknown")


def _num(v: Any) -> float | None:
    try:
        return None if v is None or isinstance(v, bool) else float(v)
    except (TypeError, ValueError):
        return None


def _fact(doc: dict, pattern: str) -> dict | None:
    rx = re.compile(pattern, re.I)
    for f in doc.get("facts") or []:
        if isinstance(f, dict) and rx.search(str(f.get("label") or "")):
            return f
    return None


def _section(doc: dict, sid: str) -> str:
    for s in doc.get("sections") or []:
        if isinstance(s, dict) and s.get("id") == sid:
            return str(s.get("body_md") or "")
    return ""


def bullets(text: str, *, limit: int = 8, n: int = 220) -> list[str]:
    """Bullet items of a markdown section; falls back to sentences when the writer used prose."""
    out = [_clean(m.group(1), n) for m in (_BULLET_RE.match(line) for line in str(text or "").splitlines()) if m]
    if not out:
        out = [_clean(s, n) for s in re.split(r"(?<=[.!?])\s+", _clean(text, 4000)) if len(s.strip()) > 20]
    return [b for b in out if b and not b.startswith("No statement in this section survived")][:limit]


def verdict_of(doc: dict) -> str | None:
    digest = doc.get("inputs_digest") or {}
    stance = digest.get("cio_stance")
    if isinstance(stance, dict):
        stance = stance.get("stance")
    if stance:
        return str(stance).strip().upper().replace("_", " ")
    m = _STANCE_RE.match(str(doc.get("verdict_line") or ""))
    return m.group(1).strip() if m else None


def conviction_of(doc: dict) -> dict:
    """The canonical CIO conviction the prospectus carried (CIO prospect record fact)."""
    f = _fact(doc, r"^CIO conviction")
    return {"value": _num((f or {}).get("value")), "source": (f or {}).get("source"), "as_of": (f or {}).get("as_of")}


def _stop_plan(doc: dict) -> dict | None:
    """The house stop policy's advisory level (blocks.stop_plan) — level and state only, never dollars at risk."""
    sp = (doc.get("blocks") or {}).get("stop_plan")
    if not isinstance(sp, dict) or sp.get("not_applicable"):
        return None
    rec = sp.get("recommended") if isinstance(sp.get("recommended"), dict) else {}
    brk = sp.get("broker") if isinstance(sp.get("broker"), dict) else {}
    out = {"recommended_level": _num(rec.get("level")), "method": rec.get("method"),
           "distance_pct": _num(rec.get("distance_pct")), "policy": rec.get("policy"),
           "broker_level": _num(brk.get("level")), "broker_state": brk.get("state"),
           "comparison": _clean(sp.get("comparison"), 240) or None,
           "advisory": sp.get("advisory") or "advisory — no AI places, sizes or stops orders"}
    return out if any(v is not None for k, v in out.items() if k != "advisory") else None


def memory_record(doc: dict) -> dict:
    """One ProspectusMemory@v1 record for one prospectus version."""
    sym = str(doc.get("symbol") or "").upper()
    version = str(doc.get("version") or "")
    verdict = verdict_of(doc)
    conv = conviction_of(doc)
    verdict_line = _clean(doc.get("verdict_line"), 300)
    scen = (doc.get("blocks") or {}).get("scenarios") or {}
    cases = [{"case": c.get("case"), "price": _num(c.get("price")), "probability_pct": _num(c.get("probability_pct")),
              "narrative": _clean(c.get("narrative"), 240) or None}
             for c in scen.get("cases") or [] if isinstance(c, dict) and c.get("case") in ("bear", "base", "bull")]
    cov = doc.get("source_coverage") or {}
    gaps: list[str] = []
    for g in [*(doc.get("partial_gaps") or []), *(cov.get("key_gaps") or []), *(doc.get("gaps") or [])]:
        g = _clean(g, 160)
        if g and g not in gaps:
            gaps.append(g)
    link = f"{LINK_PREFIX}{sym}"
    lead = verdict_line
    if verdict and lead.upper().startswith(verdict):
        lead = lead[len(verdict):].lstrip(" —:–-")
    rec = {
        "schema": SCHEMA, "symbol": sym, "name": doc.get("name"), "scope": doc.get("scope"), "version": version,
        "written_at": doc.get("generated_at"), "mode": doc.get("mode"), "status": doc.get("status") or "ready",
        "model": doc.get("model"), "model_label": model_label(doc.get("model")),
        "verdict": verdict, "verdict_line": verdict_line or None,
        "cio_conviction": conv["value"], "cio_conviction_source": conv["source"], "cio_conviction_as_of": conv["as_of"],
        "one_line": _clean(f"{verdict + ' — ' if verdict else ''}{lead}", 220) or None,
        "summary": _clean(_section(doc, "summary_verdict"), 1200) or None,
        "scenarios": cases,
        "scenario_basis": scen.get("probability_basis"),
        "thesis_breakers": bullets(_section(doc, "thesis_breakers")),
        "key_risks": bullets(_section(doc, "risks"), limit=6),
        "data_gaps": gaps[:12],
        "source_coverage": {**{k: int(v) for k, v in (cov.get("counts") or {}).items() if isinstance(v, (int, float))},
                            "web_searches": len(cov.get("web_searches") or []),
                            "web_results": sum(int(s.get("results") or 0) for s in cov.get("web_searches") or []
                                               if isinstance(s, dict))},
        "section_excerpts": {str(s.get("id")): _clean(s.get("body_md"), 420)
                             for s in doc.get("sections") or [] if isinstance(s, dict) and s.get("id")},
        "house_stop_plan": _stop_plan(doc),
        "link": link, "version_link": f"{link}?version={version}",
        "store_ref": f"data/prospectus/{sym}/{version}/prospectus.json",
        "authority": "READ_ONLY_ADVISORY", "advisory": ADVISORY,
    }
    return rec


def contribution_summary(rec: dict) -> str:
    """The ≤800-char contribution line every spine reader sees."""
    day = str(rec.get("written_at") or "")[:10]
    head = f"Prospectus {rec['symbol']} ({rec.get('model_label')}, {day}, v{rec.get('version')}"
    head += f", {rec.get('status')})" if rec.get("status") != "ready" else ")"
    parts = [head + ": " + (rec.get("one_line") or "no verdict line")]
    if rec.get("cio_conviction") is not None:
        parts.append(f"CIO conviction {rec['cio_conviction']:.0f}/100 at writing")
    if rec.get("thesis_breakers"):
        parts.append("thesis breakers: " + "; ".join(_clean(b, 90) for b in rec["thesis_breakers"][:3]))
    parts.append(rec.get("link") or "")
    return _clean(" · ".join(p for p in parts if p), 800)


def _spine():
    from scripts.lib.cross_asset import security_research_spine as sp  # noqa: PLC0415
    return sp


def record_version(doc: dict, *, root: Path | str, apply: bool = True, spine_path: Path | None = None,
                   env: dict | None = None, write_receipt: bool = True) -> dict:
    """Land one prospectus version in CIO memory. Never raises; returns the outcome row."""
    sym = str((doc or {}).get("symbol") or "").upper()
    version = str((doc or {}).get("version") or "")
    out: dict[str, Any] = {"symbol": sym, "version": version, "outcome": None}
    try:
        if not sym or not version:
            return {**out, "outcome": "refused", "reason": "symbol_and_version_required"}
        status = str(doc.get("status") or "ready")
        if status not in FINISHED:
            return {**out, "outcome": "skipped", "reason": f"status {status} is not a finished prospectus"}
        from scripts.lib.cross_asset.events import spine_write_enabled  # noqa: PLC0415
        if not spine_write_enabled():
            return {**out, "outcome": "skipped", "reason": "CROSS_ASSET_SPINE_off"}
        sp = _spine()
        root_p = Path(root)
        if sp.has_prospectus_version(sp.load_latest(sym, path=spine_path, root=root_p), version):
            return {**out, "outcome": "exists"}
        from scripts.lib import identity_carriage as ic  # noqa: PLC0415
        if not ic.is_registry_guid(ic.resolve_security_identity(sym, root=root_p).get("subject_guid")):
            # §26.1: a security without a CONFIRMED registry GUID gets no memory record (the spine refuses it too).
            return {**out, "outcome": "refused", "reason": "subject_guid_required_registry_uuid (identity unresolved)"}
        rec = memory_record(doc)
        summary = contribution_summary(rec)
        if not apply:
            return {**out, "outcome": "would_write", "summary": summary}
        res = sp.upsert_research_memory(
            sym, silo="cio", kind=KIND, summary=summary, artifact_id=f"prospectus:{sym}:{version}",
            refs=[rec["version_link"], rec["store_ref"]], tags=list(TAGS), thesis_patch=None,
            llm={"source": "prospectus_writer", "model": rec.get("model"), "kind": KIND,
                 "as_of": rec.get("written_at"), "note": "prospectus_research_memory_not_tip_thesis"},
            root=root_p, path=spine_path, prospectus=rec)
        if not res.get("ok"):
            return {**out, "outcome": "refused", "reason": res.get("error") or (res.get("write") or {}).get("error")}
        out.update(outcome="written", summary=summary)
        if write_receipt:
            out["receipt"] = _receipt(rec, summary, root_p, env)
        return out
    except Exception as exc:  # noqa: BLE001 - memory never takes the prospectus run down
        return {**out, "outcome": "error", "reason": f"{type(exc).__name__}: {str(exc)[:200]}"}


def _receipt(rec: dict, summary: str, root: Path, env: dict | None) -> dict:
    """The research write path's receipt for the same payload (SHADOW by default; thesis untouched)."""
    try:
        from scripts.lib import research_write_path as rwp  # noqa: PLC0415
        payload = {"summary": summary, "recommendation": rec.get("verdict"), "model": rec.get("model"),
                   "provider": "prospectus_writer", "source_refs": [rec["version_link"], rec["store_ref"]],
                   "evidence": [f"thesis breaker: {b}" for b in rec.get("thesis_breakers") or []][:8]}
        res = rwp.submit(LANE_ID, rec["symbol"], payload, research_id=f"prospectus:{rec['symbol']}:{rec['version']}",
                         root=root, env=env if env is not None else dict(os.environ), trigger="prospectus_version")
        return {k: res.get(k) for k in ("ok", "mode", "accepted", "receipt_id")}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {str(exc)[:160]}"}


# ── backfill ──────────────────────────────────────────────────────────────────────────────────────────────────
def iter_versions(base: Path, symbols: Iterable[str] | None = None, *, latest_only: bool = False):
    """(symbol, version, doc) for every stored version, oldest first per symbol, so history builds in order."""
    from . import store  # noqa: PLC0415
    wanted = {store.norm_symbol(s) for s in symbols or []} - {None}
    for sdir in sorted(p for p in Path(base).iterdir() if p.is_dir()) if Path(base).is_dir() else []:
        sym = store.norm_symbol(sdir.name)
        if not sym or (wanted and sym not in wanted):
            continue
        rows = store.versions(base, sym)
        if latest_only:
            rows = rows[:1]
        for row in reversed(rows):
            doc = store.read_prospectus(base, sym, row["version"])
            if isinstance(doc, dict):
                yield sym, row["version"], doc


def backfill(base: Path, *, root: Path | str, apply: bool = False, symbols: Iterable[str] | None = None,
             latest_only: bool = False, spine_path: Path | None = None, env: dict | None = None) -> dict:
    rows = [record_version(doc, root=root, apply=apply, spine_path=spine_path, env=env)
            for _sym, _ver, doc in iter_versions(base, symbols, latest_only=latest_only)]
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["outcome"]] = counts.get(r["outcome"], 0) + 1
    return {"mode": "apply" if apply else "dry_run", "versions": len(rows),
            "symbols": len({r["symbol"] for r in rows}), "counts": counts, "rows": rows}


# ── read side (Ask the CIO, the CIO desk, the subject dossier) ───────────────────────────────────────────────
def latest_for(symbol: str, *, root: Path | str | None = None, spine_path: Path | None = None,
               security_guid: str | None = None) -> dict | None:
    """The latest ProspectusMemory@v1 for a security from the spine, or None. Never raises."""
    try:
        sp = _spine()
        tip = sp.load_latest(symbol, path=spine_path, root=Path(root) if root is not None else None) or {}
        if security_guid and tip.get("subject_guid") and tip["subject_guid"] != security_guid:
            return None  # same ticker, different security: never recall across identities
        rec = tip.get("latest_prospectus")
        if not isinstance(rec, dict):
            return None
        return {**rec, "history": list(tip.get("prospectus_history") or [])}
    except Exception:  # noqa: BLE001
        return None


def headline(rec: dict) -> str:
    """'Latest prospectus (Fable, Oct 26): ADD — … · CIO conviction 62/100 at writing'."""
    from datetime import datetime  # noqa: PLC0415
    when = str(rec.get("written_at") or "")[:10]
    try:
        when = datetime.fromisoformat(when).strftime("%b %d").replace(" 0", " ")
    except ValueError:
        pass
    text = f"Latest prospectus ({rec.get('model_label')}, {when}"
    text += f", {rec.get('status')}" if rec.get("status") and rec.get("status") != "ready" else ""
    text += "): "
    line = str(rec.get("verdict_line") or "no verdict line")
    verdict = str(rec.get("verdict") or "")
    if verdict and line.upper().startswith(verdict):
        line = line[len(verdict):].lstrip(" —:–-")
    text += (f"{verdict} — " if verdict else "") + line
    if rec.get("cio_conviction") is not None:
        text += f" · CIO conviction {float(rec['cio_conviction']):.0f}/100 at writing"
    return text


def ask_facts(ent: Any, ctx: Any) -> list:
    """Ask the CIO source ``internal.prospectus``: the latest prospectus from the CIO memory as cited facts.

    Gives the panel and the answer the verdict, the CIO conviction at writing, the summary, every section excerpt
    (so "what does the prospectus say about X" is answerable), scenarios, thesis breakers and key risks (``risk``
    facts, which the answer lists), data gaps and the house stop plan (``local_only``: never leaves the box).
    """
    try:
        from scripts.lib import cio_ask_research as ask  # noqa: PLC0415
    except ImportError:  # pragma: no cover - hub import path
        from lib import cio_ask_research as ask  # type: ignore  # noqa: PLC0415
    rec = latest_for(ent.symbol or "", root=getattr(ctx, "state_root", None),
                     security_guid=getattr(ent, "security_guid", None))
    if not rec:
        return []
    as_of = rec.get("written_at") or rec.get("recorded_at")
    cit = {"store": "security_research_spine", "field": "latest_prospectus", "version": rec.get("version"),
           "model": rec.get("model"), "url": rec.get("version_link") or rec.get("link"),
           "security_guid": getattr(ent, "security_guid", None)}

    def fact(kind: str, claim: str, **kw: Any):
        return ask.make_fact(source="internal.prospectus", family="internal", kind=kind, subject_key=ent.subject_key,
                             symbol=ent.symbol, claim=claim, as_of=as_of, citation=cit, **kw)

    out = [fact("prospectus", headline(rec) + f" · {rec.get('link')}", field="cio_conviction_at_writing",
                value=rec.get("cio_conviction"), unit="score_0_100")]
    if rec.get("summary"):
        out.append(fact("prospectus", "Prospectus summary: " + str(rec["summary"])))
    titles = {"summary_verdict": None, "thesis_breakers": None, "risks": None}
    for sid, text in (rec.get("section_excerpts") or {}).items():
        if text and sid not in titles:
            out.append(fact("prospectus", f"Prospectus — {sid.replace('_', ' ')}: {text}", field=f"section.{sid}"))
    for c in rec.get("scenarios") or []:
        if c.get("price") is None:
            continue
        prob = f", {c['probability_pct']:.0f}% writer judgment" if c.get("probability_pct") is not None else ""
        out.append(fact("prospectus", f"Prospectus {c['case']} case: ${c['price']:,.2f} (analyst-target anchor{prob})"
                        + (f" — {c['narrative']}" if c.get("narrative") else ""),
                        field=f"scenario_{c['case']}_price", value=c["price"], unit="usd"))
    for b in rec.get("thesis_breakers") or []:
        out.append(fact("risk", f"Prospectus thesis breaker: {b}"))
    for r in rec.get("key_risks") or []:
        out.append(fact("risk", f"Prospectus key risk: {r}"))
    if rec.get("data_gaps"):
        out.append(fact("prospectus", "Prospectus data gaps: " + "; ".join(rec["data_gaps"][:8])))
    sp = rec.get("house_stop_plan") or {}
    if sp:
        out.append(fact("prospectus", stop_plan_line(sp), egress="local_only"))
    return out


def stop_plan_line(sp: dict) -> str:
    bits = []
    if sp.get("recommended_level") is not None:
        bits.append(f"house stop policy level ${sp['recommended_level']:,.2f}"
                    + (f" ({sp['method']})" if sp.get("method") else "")
                    + (f", {abs(sp['distance_pct']):.1f}% from last close" if sp.get("distance_pct") is not None else ""))
    if sp.get("broker_state"):
        bits.append(f"broker stop {sp['broker_state']}"
                    + (f" at ${sp['broker_level']:,.2f}" if sp.get("broker_level") is not None else ""))
    if sp.get("comparison"):
        bits.append(str(sp["comparison"]))
    return "Prospectus stop plan at writing: " + "; ".join(bits or ["not reported"]) + \
        f" ({sp.get('advisory') or 'advisory — no AI places, sizes or stops orders'})"


def recall_item(rec: dict) -> dict:
    """The Ask memory recall row for the latest prospectus (rendered first under 'Earlier on X')."""
    text = headline(rec)
    if rec.get("thesis_breakers"):
        text += " · thesis breakers: " + "; ".join(_clean(b, 80) for b in rec["thesis_breakers"][:3])
    return {"at": rec.get("written_at"), "kind": "prospectus.latest", "summary": f"{text} · {rec.get('link')}",
            "ref": f"prospectus:{rec.get('symbol')}:{rec.get('version')}", "source": "security_research_spine"}


def dossier_line(rec: dict, pill: str) -> str:
    """The subject-dossier line (pill-tagged, store named) for the CIO desk."""
    text = f"{pill} · {headline(rec)} (CIO memory: security_research_spine, v{rec.get('version')})"
    if rec.get("thesis_breakers"):
        text += " · thesis breakers: " + "; ".join(_clean(b, 70) for b in rec["thesis_breakers"][:3])
    sc = [f"{c['case']} ${c['price']:,.0f}" + (f" {c['probability_pct']:.0f}%" if c.get("probability_pct") is not None else "")
          for c in rec.get("scenarios") or [] if c.get("price") is not None]
    if sc:
        text += " · scenarios " + " / ".join(sc)
    return text + f" · {rec.get('link')}"


__all__ = ["SCHEMA", "LANE_ID", "memory_record", "contribution_summary", "record_version", "backfill",
           "iter_versions", "latest_for", "headline", "model_label", "bullets", "ask_facts", "recall_item",
           "dossier_line", "stop_plan_line"]
