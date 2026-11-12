# Route patch: `GET /api/v2/home/status` (LQ-20261107-2144)

`scripts/api_v2.py` is claimed by another worker (LQ-2142/2147), and the spec gives route lines to the W2-b route
owner, so this LQ ships the handler in `scripts/lib/home_trade_ready.py` (`api_handler`) and the route as this patch.
The route owner applies it. It is two hunks and adds no logic to api_v2:

```python
# near _home_since_close():
def _home_status():
    """GET /api/v2/home/status — HomeStatus@v1 (LQ-20261107-2144). Reads the latest home_snapshots kind='status' row
    written by the n8n lane home-status-verdict (the JSON mirror only when the DB is unreachable). Never computes a
    verdict on the request; a stale or missing snapshot is UNKNOWN, never YES."""
    from lib import home_trade_ready as _htr

    return _htr.api_handler(_db_query)
```

```python
# route table, next to "/api/v2/home/since-close":
    "/api/v2/home/status": lambda: _home_status(),
```

Behaviour (pinned in `tests/test_home_trade_ready_20261112.py`):

* DB readable and a row exists: the row is served, every field's `age_s` recomputed at serve time.
* Snapshot older than 300 s in session (09:00-15:59 ET weekdays) or 900 s otherwise: `verdict: "UNKNOWN"`,
  `unknown_inputs: [{"input": "verdict_snapshot", ...}]`, last verdict and blockers under `last_known`.
* DB readable, no row: UNKNOWN `no snapshot written` (an old mirror is not used).
* DB unreachable: the mirror, with `read_from: "mirror"`; no mirror: UNKNOWN.
* Wrong schema, rule version or verdict word: UNKNOWN `verdict_unreadable`.

Between 04:00 and 16:15 ET on market days, nothing here is exercised against :7777 (AGENTS.md 28.8).
