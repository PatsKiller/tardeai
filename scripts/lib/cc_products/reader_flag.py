"""Per-product reader migration flag: ``legacy`` | ``stored`` (operator 13 Nov 2026, home-products rework item 6).

There is NO automatic cache-miss fallback. Each product's GET routes serve exactly one path, chosen by this flag:

* ``legacy`` (the default for every product): the route serves the path it served before the stored products existed
  (on the mem-contain fold: the containment/SWR path). Builders may run in shadow and seed rows independently; the
  reader does not look at them.
* ``stored``: the route serves the compatible stored product ONLY. A missing, expired or schema-incompatible product
  answers the defined UNKNOWN/unavailable response (or the last good, greyed, with its age, where the product's
  contract allows). It never imports or calls the legacy compute and never falls back to legacy.

Configuration is one environment variable, read ONCE when this module is imported (process start), so a flip needs a
restart or reload of portfolio-server; a request never sees a half-applied flag::

    TRADEAI_CC_PRODUCT_READERS="market_risk.latest=stored,risk=stored"

Unlisted products are ``legacy``. A malformed value (unknown product, unknown mode, bad token) makes EVERY product
``legacy`` and is reported in ``status()``: a typo must never half-cut a product over.

Rollback: set the product back to ``legacy`` (or remove it from the variable) and restart portfolio-server. The legacy
code path is kept in the tree for exactly this.
"""
from __future__ import annotations

import logging
import os

ENV_NAME = "TRADEAI_CC_PRODUCT_READERS"
LEGACY, STORED = "legacy", "stored"
MODES = (LEGACY, STORED)

#: Products a reader flag exists for. ``market_risk.latest`` covers /api/v2/market-risk/latest AND
#: /api/v2/home/cio-card (one record, two routes); ``home`` covers the six /api/v2/home/* slice routes.
PRODUCTS = ("market_risk.latest", "risk", "reports.analyst_links", "home", "cio.pages")

log = logging.getLogger("cc_products.reader_flag")


def parse(value: str | None) -> tuple[dict[str, str], str | None]:
    """(modes, error). On any error every product is legacy."""
    modes = {p: LEGACY for p in PRODUCTS}
    if not value or not value.strip():
        return modes, None
    out = dict(modes)
    for token in value.split(","):
        token = token.strip()
        if not token:
            continue
        pid, sep, mode = token.partition("=")
        pid, mode = pid.strip(), mode.strip().lower()
        if not sep or pid not in PRODUCTS or mode not in MODES:
            return modes, f"{ENV_NAME}: bad entry {token!r} (products {', '.join(PRODUCTS)}; modes legacy|stored)"
        out[pid] = mode
    return out, None


_MODES, _ERROR = parse(os.environ.get(ENV_NAME))
if _ERROR:
    log.error("cc_product_reader_flag error=%s all_products=legacy", _ERROR)


def mode(product_id: str) -> str:
    """``legacy`` or ``stored`` for ``product_id`` (unknown products are legacy)."""
    return _MODES.get(product_id, LEGACY)


def is_stored(product_id: str) -> bool:
    return mode(product_id) == STORED


def status() -> dict:
    return {"env": ENV_NAME, "modes": dict(_MODES), "error": _ERROR}


def reload(value: str | None = None) -> dict:
    """Re-read the flag (tests; or an explicit reload hook). ``value`` None re-reads the environment."""
    global _MODES, _ERROR
    _MODES, _ERROR = parse(os.environ.get(ENV_NAME) if value is None else value)
    if _ERROR:
        log.error("cc_product_reader_flag error=%s all_products=legacy", _ERROR)
    return status()
