#!/usr/bin/env python3
"""P4: cloud-OAuth usage monitor — both lanes, paid-fallback detection (critical), structure + safety."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import cloud_oauth_usage_monitor as oauth  # noqa: E402

PASS, FAIL = [], []


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")


def main():
    r = oauth.build()
    check("both lanes present (grok + chatgpt)", set(r["lanes"].keys()) == {"grok", "chatgpt"})
    check("grok lane on :8645", r["lanes"]["grok"]["port"] == 8645)
    check("chatgpt lane on :8646", r["lanes"]["chatgpt"]["port"] == 8646)
    check("each lane reports calls_today + auth_failures + paid_fallbacks",
          all(k in r["lanes"]["grok"] for k in ("calls_today", "auth_failures", "paid_fallbacks")))
    check("findings is a list", isinstance(r["findings"], list))

    # paid-fallback detection regex (the hard-fail signal)
    check("paid-fallback regex catches 'fell back to paid'", oauth._PAID_FALLBACK.search("fell back to paid key") is not None)
    check("paid-fallback regex catches OPENAI_API_KEY", oauth._PAID_FALLBACK.search("using OPENAI_API_KEY") is not None)
    check("auth-fail regex catches 401/unauthorized", oauth._AUTH_FAIL.search("HTTP 401 unauthorized") is not None)

    # safety + markdown
    check("never routes free-only to paid (note)", "never routes" in r["safety_note"].lower())
    check("no broker writes", "No broker writes" in r["safety_note"])
    check("markdown renders", "Cloud-OAuth Lane Usage" in oauth.to_markdown(r))
    check("soft cap defined", isinstance(oauth.DAILY_SOFT_CAP, int) and oauth.DAILY_SOFT_CAP > 0)

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
