#!/usr/bin/env python3
"""Guard: /v3 must never enter an infinite reload loop again.

2026-07-28 outage. Two stale-bundle checks compare a version against
sessionStorage['cc_v3_build'] and reload when it differs:
  1. an inline <script> the server injects into index.html
  2. /v3/cc-boot.js

They hardcoded DIFFERENT fallbacks ('1.5' inline, '1.6' in cc-boot). That is inert
while dist/build-meta.json carries a ui_version — but a rebuild emitted one without
that key, both paths fell back to their own literal, and the two disagreed forever:

    inline : sessionStorage != '1.5' -> set '1.5', reload
    cc-boot: sessionStorage != '1.6' -> set '1.6', reload   ...forever

/v3 became a blank page with a _cc_reload timestamp spinning in the URL. The code
comment claimed sessionStorage prevented a loop; it only does when both readers agree.

These tests fail if the two versions can ever diverge again — including the exact
trigger, a build-meta.json with no ui_version.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

SERVER = ROOT / "scripts" / "portfolio_server.py"

passed = 0


def check(label: str, ok: bool, detail: str = ""):
    global passed
    print(f"{'PASS' if ok else 'FAIL'}: {label}{(' — ' + detail) if detail and not ok else ''}")
    if not ok:
        raise SystemExit(1)
    passed += 1


def main() -> int:
    src = SERVER.read_text(encoding="utf-8")

    # 1. Neither boot path may carry its own version literal.
    inline_literals = re.findall(r"_build_ver\s*=\s*[\"']([0-9.]+)[\"']", src)
    check("no hardcoded per-path version literals remain", not inline_literals,
          f"found {inline_literals} — both paths must use the shared fallback")

    # 2. There is exactly ONE fallback constant, and both paths go through the helper.
    check("single shared fallback constant exists",
          "CC_V3_UI_VERSION_FALLBACK" in src)
    helper_uses = len(re.findall(r"_cc_v3_ui_version\(\)", src))
    check("both boot paths resolve via the shared helper", helper_uses >= 2,
          f"only {helper_uses} call site(s); inline injection and cc-boot.js both need it")

    # 3. The whole point: the two must agree even with a ui_version-less build-meta —
    #    the exact condition that caused the outage.
    import importlib
    ps = importlib.import_module("portfolio_server")
    meta = ROOT / "apps" / "command-center-v3" / "dist" / "build-meta.json"
    original = meta.read_text(encoding="utf-8") if meta.exists() else None
    try:
        if original is not None:
            stripped = {k: v for k, v in json.loads(original).items() if k != "ui_version"}
            meta.write_text(json.dumps(stripped), encoding="utf-8")
        v1 = ps._cc_v3_ui_version()
        v2 = ps._cc_v3_ui_version()
        check("version resolves identically with NO ui_version in build-meta", v1 == v2)
        check("fallback is the shared constant", v1 == ps.CC_V3_UI_VERSION_FALLBACK,
              f"{v1!r} != {ps.CC_V3_UI_VERSION_FALLBACK!r}")

        # and with a ui_version present, both still agree
        if original is not None:
            meta.write_text(json.dumps({**stripped, "ui_version": "9.9"}), encoding="utf-8")
            check("ui_version from build-meta is honoured", ps._cc_v3_ui_version() == "9.9")
    finally:
        if original is not None:
            meta.write_text(original, encoding="utf-8")

    # 4. Both emitted scripts must key off the same sessionStorage name — divergent
    #    keys would mean neither can ever settle.
    keys = set(re.findall(r"k\s*=\s*'([a-z0-9_]+)'", src))
    check("both scripts use one sessionStorage key", len(keys) <= 1, f"keys={keys}")

    # 8. ORDERING. The reload decision must be made BEFORE the module script,
    #    not appended at </head>.
    #
    #    Appended at </head> the inline check landed after <script type="module">,
    #    so Chrome's preload scanner had already started the 4.4 MB bundle when the
    #    check ran and called location.replace() — cancelling it. Every route
    #    showed net::ERR_ABORTED on a URL that serves 200 directly: one wasted
    #    navigation and re-parse per browser session. Not a loop, so the guards
    #    above never saw it, but the same family of defect.
    inject_before_module = '_body.find(b\'<script type="module"\')' in src
    check("the reload check is injected before the module script, not at </head>",
          inject_before_module,
          "appending at </head> puts it after the bundle tag and aborts the in-flight fetch")
    # and the </head> path must remain as the fallback for markup with no module tag
    check("a </head> fallback remains for markup with no module script",
          'elif b"</head>" in _body:' in src)

    # 10. NEITHER path may reload on a first visit.
    #
    #     Both compared `getItem(k) !== v`, and on the first load of any session
    #     getItem is null — so both always reloaded, cancelling the in-flight
    #     bundle for one wasted navigation per session. A first visit has nothing
    #     to bust: bundle filenames are content-hashed, so a new build is a new
    #     URL the cache cannot answer with stale JS. Record the version, and
    #     reload only when a PREVIOUS one existed and differed.
    #
    #     Note the earlier attempt at this — moving the inline script ahead of
    #     the module tag — did NOT work: Chrome's preload scanner reads ahead of
    #     the parser and had already started the fetch. Ordering is necessary
    #     hygiene, not the fix.
    first_load_guards = src.count("if(p!==null&&p!==v)")
    check("neither boot path reloads on a first visit", first_load_guards >= 2,
          f"found {first_load_guards} of 2 (inline injection + cc-boot.js)")
    check("no bare getItem!==v comparison remains",
          "sessionStorage.getItem(k)!==v" not in src,
          "that form reloads whenever the key is unset, i.e. every first load")

    print(f"\nAll {passed} cc-v3 boot-loop guards passed.")
    return 0


def test_cc_v3_boot_has_no_reload_loop():
    """pytest entry point for the guards above.

    This file sits in `tests/`, is named `test_*.py`, and until now defined no
    function starting with `test_` — so `pytest tests/` collected **zero** from
    it and `run_cio_hardening_ci.py` did not list it at all. Eleven assertions
    guarding the 2026-07-28 blank-page outage ran only when a human typed the
    path by hand.

    That is the worst version of the problem this whole campaign is about: not a
    missing guard, but a guard that is present, passing, counted by eye, and
    executing nothing. A file named like a test and living among tests is read
    as covered by everyone who looks at the directory.
    """
    assert main() == 0


if __name__ == "__main__":
    raise SystemExit(main())
