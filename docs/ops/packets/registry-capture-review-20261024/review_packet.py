"""Offline review previews only: bytes in/bytes out; no host, scheduler, DB or write API."""
from __future__ import annotations

import gzip
import hashlib
import json
import re
from pathlib import Path

BASE_SHA256 = "f5af4203e3329053194a6113117d2992c31be0ded9c86963e8d1238e5d8db6e1"
CAPTURE_SHA256 = "b2097df25a62e6824b6e7046d55a3f279b9b058e76b1bcd09c2da89b5a748626"
PACKET = Path(__file__).resolve().parent
PATCH_FILES = {
    "restriction": "restriction-only.PROPOSED.patch",
    "provenance": "provenance-only.HELD.patch",
    "mechanical": "mechanical.REJECTED.patch",
}
LANES = frozenset({"catalyst-momentum-engine-market", "catalyst-momentum-engine-premarket"})
MISSING = object()


class ReviewError(ValueError):
    pass


def verify_bytes(data: bytes, expected: str, label: str) -> bytes:
    if hashlib.sha256(data).hexdigest() != expected:
        raise ReviewError(f"{label}: SHA256 mismatch")
    return data


def read_bundle(directory: Path = PACKET) -> tuple[dict, bytes]:
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schema") != "RegistryCaptureReview@v1":
        raise ReviewError("wrong packet schema")
    if manifest.get("source_base_registry_sha256") != BASE_SHA256:
        raise ReviewError("wrong frozen registry binding")
    if manifest.get("operator_capture", {}).get("sha256") != CAPTURE_SHA256:
        raise ReviewError("wrong operator capture binding")
    for name in ["base-registry-0764.json.gz", *PATCH_FILES.values(), "semantic-fields.json", "semantic-fields.csv"]:
        expected = manifest.get("files", {}).get(name)
        if not isinstance(expected, str):
            raise ReviewError(f"missing file binding:{name}")
        verify_bytes((directory / name).read_bytes(), expected, name)
    try:
        base = gzip.decompress((directory / "base-registry-0764.json.gz").read_bytes())
    except (OSError, EOFError) as exc:
        raise ReviewError("invalid frozen fixture") from exc
    verify_bytes(base, BASE_SHA256, "frozen fixture")
    return manifest, base


def apply_unified_bytes(base: bytes, patch: str) -> bytes:
    """Strict single-file unified diff interpreter, solely for fixture review.

    Exact context, old/new counts and positions must match. It never opens the
    patch's target path, executes a process or writes an output file.
    """
    lines = patch.splitlines(keepends=True)
    if lines[:2] != ["--- a/config/lane_registry.json\n", "+++ b/config/lane_registry.json\n"]:
        raise ReviewError("unexpected patch target")
    original = base.decode("utf-8").splitlines(keepends=True)
    result: list[str] = []
    cursor = 0
    at = 2
    hunks = 0
    while at < len(lines):
        match = re.fullmatch(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@[^\n]*\n", lines[at])
        if not match:
            raise ReviewError("invalid hunk header")
        start, old_count, new_start, new_count = [int(x) for x in (match[1], match[2] or "1", match[3], match[4] or "1")]
        position = start - 1 if old_count else start
        if position < cursor or position > len(original):
            raise ReviewError("overlapping or out-of-range hunk")
        result.extend(original[cursor:position])
        cursor = position
        if len(result) != (new_start - 1 if new_count else new_start):
            raise ReviewError("new hunk position mismatch")
        consumed = produced = 0
        at += 1
        while at < len(lines) and not lines[at].startswith("@@ "):
            line = lines[at]
            if not line or line[0] not in " +-":
                raise ReviewError("invalid hunk body")
            prefix, body = line[0], line[1:]
            if prefix in " -":
                if cursor >= len(original) or original[cursor] != body:
                    raise ReviewError("patch context mismatch")
                cursor += 1
                consumed += 1
            if prefix in " +":
                result.append(body)
                produced += 1
            at += 1
        if (consumed, produced) != (old_count, new_count):
            raise ReviewError("hunk count mismatch")
        hunks += 1
    if not hunks:
        raise ReviewError("empty patch")
    result.extend(original[cursor:])
    return "".join(result).encode("utf-8")


def flatten(value: object, prefix: str = "") -> dict[str, object]:
    if isinstance(value, dict):
        if not value:
            return {prefix: {}} if prefix else {}
        out: dict[str, object] = {}
        for key, child in value.items():
            escaped = str(key).replace("~", "~0").replace("/", "~1")
            out.update(flatten(child, prefix + "/" + escaped))
        return out
    return {prefix: value}


def semantic_changes(before: dict, after: dict) -> dict[tuple[str, str], tuple[object, object]]:
    left = {row["lane_id"]: row for row in before["lanes"]}
    right = {row["lane_id"]: row for row in after["lanes"]}
    out = {}
    for lane in left.keys() | right.keys():
        a, b = flatten(left.get(lane, {})), flatten(right.get(lane, {}))
        for key in a.keys() | b.keys():
            old, new = a.get(key, MISSING), b.get(key, MISSING)
            if old != new:
                out[lane, key] = old, new
    return out


def validate_review_scope(before: dict, after: dict, kind: str) -> None:
    if kind not in {"restriction", "provenance"}:
        raise ReviewError("mechanical diff is rejected; no review preview")
    if {k: v for k, v in before.items() if k != "lanes"} != {k: v for k, v in after.items() if k != "lanes"}:
        raise ReviewError("top-level registry changed")
    a, b = before["lanes"], after["lanes"]
    if [r["lane_id"] for r in a] != [r["lane_id"] for r in b]:
        raise ReviewError("lane identity/order changed")
    changes = semantic_changes(before, after)
    if kind == "provenance":
        expected = {("market-regime-collector", "/rationalization/f_id"): ("L199", "L213")}
    else:
        expected = {}
        for lane in LANES:
            expected[lane, "/recommendation"] = "PIPELINE:P07", "KEEP_ON_CRON"
            for key, value in {"class": "broker_order", "token": "alpaca", "source": "config/lane_stay_on_cron_tokens.json"}.items():
                expected[lane, "/stay_on_cron/" + key] = MISSING, value
    if changes != expected:
        raise ReviewError("change exceeds reviewed metadata-only scope")


def preview(kind: str, directory: Path = PACKET) -> bytes:
    if kind not in {"restriction", "provenance"}:
        raise ReviewError("mechanical diff is rejected; no review preview")
    manifest, base = read_bundle(directory)
    case = manifest["cases"][kind]
    if case["file"] != PATCH_FILES[kind]:
        raise ReviewError("wrong patch identity")
    after = apply_unified_bytes(base, (directory / PATCH_FILES[kind]).read_text(encoding="utf-8"))
    verify_bytes(after, case["candidate_sha256"], "candidate")
    validate_review_scope(json.loads(base), json.loads(after), kind)
    return after
