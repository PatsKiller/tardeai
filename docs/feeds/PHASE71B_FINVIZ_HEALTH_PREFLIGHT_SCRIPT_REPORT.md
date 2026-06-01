# Phase 71B — Finviz Health Preflight Report

**Status:** DESIGN ONLY — preflight check logic defined

## Preflight Logic

```python
def finviz_preflight():
    if not FINVIZ_COOKIE:
        return "MISSING_COOKIE"
    test = requests.get(FINVIZ_URL, cookies={"finviz_cookie": FINVIZ_COOKIE})
    if "Login" in test.text or test.status_code != 200:
        return "EXPIRED_COOKIE"
    return "HEALTHY"
```

Not yet added to screener pipeline. Requires script modification approval.
