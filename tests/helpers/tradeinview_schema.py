"""Stdlib Draft 2020-12 validator for config/schemas/tradeinview_projection_v1.schema.json (test helper).

The required CI runners do not install ``jsonschema`` (only the TradeInView shards install
requirements-ci-tradeinview.txt), so — like ``scripts/lib/release_train_contracts.py`` — the TradeInView tests carry
a small validator for exactly the keyword subset the schema uses (``SUPPORTED_KEYWORDS``). It never skips: every
payload is validated by this helper on every runner, and where ``jsonschema`` IS installed it validates too and both
must agree. ``unsupported_keywords`` pins that the schema file never grows a keyword this helper would ignore.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "config/schemas/tradeinview_projection_v1.schema.json"
#: keywords that constrain a value, all implemented below
SUPPORTED_KEYWORDS = frozenset({"type", "items", "$ref", "const", "properties", "required", "additionalProperties",
                                "minimum", "maximum", "exclusiveMinimum", "enum", "oneOf", "anyOf", "pattern"})
#: annotation / structural keywords that constrain nothing by themselves
ANNOTATIONS = frozenset({"$schema", "$id", "title", "description", "$defs", "$comment", "default", "examples"})

_TYPES = {
    "null": lambda v: v is None,
    "boolean": lambda v: isinstance(v, bool),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool)
    or (isinstance(v, float) and v.is_integer()),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "string": lambda v: isinstance(v, str),
    "array": lambda v: isinstance(v, list),
    "object": lambda v: isinstance(v, Mapping),
}


@lru_cache(maxsize=1)
def load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def unsupported_keywords(schema: Any | None = None) -> set[str]:
    """Every schema keyword in the file that this helper does not implement (must stay empty)."""
    schema = load_schema() if schema is None else schema
    out: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, Mapping):
            for k, v in node.items():
                if k not in SUPPORTED_KEYWORDS and k not in ANNOTATIONS:
                    out.add(k)
                if k in ("properties", "$defs"):
                    for sub in v.values():
                        walk(sub)
                elif k in ("items", "additionalProperties") and isinstance(v, Mapping):
                    walk(v)
                elif k in ("oneOf", "anyOf"):
                    for sub in v:
                        walk(sub)
    walk(schema)
    return out


def _resolve(ref: str, root: Mapping[str, Any]) -> Mapping[str, Any]:
    if not ref.startswith("#/"):
        raise ValueError(f"only local $ref supported: {ref}")
    node: Any = root
    for part in ref[2:].split("/"):
        node = node[part]
    return node


def _check(value: Any, schema: Mapping[str, Any], root: Mapping[str, Any], where: str, errs: list[str]) -> None:
    if "$ref" in schema:
        _check(value, _resolve(schema["$ref"], root), root, where, errs)
    if "oneOf" in schema:
        passing = sum(1 for sub in schema["oneOf"] if not _errors(value, sub, root, where))
        if passing != 1:
            errs.append(f"{where}: matches {passing} of oneOf (exactly 1 required)")
    if "anyOf" in schema and not any(not _errors(value, sub, root, where) for sub in schema["anyOf"]):
        errs.append(f"{where}: matches none of anyOf")
    if "const" in schema and value != schema["const"]:
        errs.append(f"{where}: must be {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        errs.append(f"{where}: {value!r} not in {schema['enum']}")
    types = schema.get("type")
    if types is not None:
        tl = [types] if isinstance(types, str) else list(types)
        if not any(_TYPES[t](value) for t in tl):
            errs.append(f"{where}: expected {'/'.join(tl)}, got {type(value).__name__}")
            return
    if isinstance(value, str) and "pattern" in schema and not re.search(schema["pattern"], value):
        errs.append(f"{where}: does not match {schema['pattern']}")
    if _TYPES["number"](value):
        if "minimum" in schema and value < schema["minimum"]:
            errs.append(f"{where}: below {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errs.append(f"{where}: above {schema['maximum']}")
        if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
            errs.append(f"{where}: not above {schema['exclusiveMinimum']}")
    if isinstance(value, list) and "items" in schema:
        for i, v in enumerate(value):
            _check(v, schema["items"], root, f"{where}[{i}]", errs)
    if isinstance(value, Mapping):
        props = schema.get("properties") or {}
        for k in schema.get("required") or ():
            if k not in value:
                errs.append(f"{where}: missing {k}")
        extra = schema.get("additionalProperties", True)
        for k, v in value.items():
            if k in props:
                _check(v, props[k], root, f"{where}.{k}", errs)
            elif extra is False:
                errs.append(f"{where}: unknown key {k}")
            elif isinstance(extra, Mapping):
                _check(v, extra, root, f"{where}.{k}", errs)


def _errors(value: Any, schema: Mapping[str, Any], root: Mapping[str, Any], where: str = "$") -> list[str]:
    errs: list[str] = []
    _check(value, schema, root, where, errs)
    return errs


def schema_errors(payload: Any, schema: Mapping[str, Any] | None = None) -> list[str]:
    """Schema defects of ``payload``; [] when valid."""
    schema = load_schema() if schema is None else schema
    return _errors(payload, schema, schema)


def validate(payload: Any, schema: Mapping[str, Any] | None = None) -> None:
    """Raise AssertionError on any defect. Also runs ``jsonschema`` when installed, and requires agreement."""
    schema = load_schema() if schema is None else schema
    errs = schema_errors(payload, schema)
    try:
        from jsonschema import Draft202012Validator  # type: ignore
    except ImportError:
        Draft202012Validator = None  # noqa: N806 — the stdlib result above is the evidence on this runner
    if Draft202012Validator is not None:
        lib_errs = list(Draft202012Validator(schema).iter_errors(payload))
        assert bool(lib_errs) == bool(errs), f"validators disagree: stdlib={errs[:5]} jsonschema={[e.message for e in lib_errs[:5]]}"
    assert not errs, errs[:20]
