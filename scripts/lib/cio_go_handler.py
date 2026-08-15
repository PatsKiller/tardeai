"""Server-side /v3/go/cio signed-action pages.

GET: verify token, show confirmation (no mutation).
POST: apply governed disposition.

Authority: READ_ONLY_ADVISORY.
"""
from __future__ import annotations

import html
from typing import Any
from urllib.parse import parse_qs

from scripts.lib.cio_action_links import (
    AUTHORITY,
    MUTATING,
    apply_signed_disposition,
    verify_action_token,
)


def _page(title: str, body: str, status: int = 200) -> tuple[int, str, bytes]:
    doc = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>{html.escape(title)}</title>
<style>
body{{font-family:ui-sans-serif,system-ui,sans-serif;max-width:36rem;margin:2rem auto;padding:0 1rem;background:#0f1419;color:#e7ecf1}}
card{{display:block;border:1px solid #2a3340;border-radius:12px;padding:1.25rem}}
button,a.btn{{background:#3d8bfd;color:#fff;border:0;border-radius:8px;padding:.6rem 1rem;text-decoration:none;display:inline-block}}
.muted{{color:#93a0ad;font-size:.9rem}}
</style></head><body><card>{body}</card>
<p class="muted">READ_ONLY_ADVISORY · no broker/order/stop</p></body></html>"""
    return status, "text/html; charset=utf-8", doc.encode("utf-8")


def handle_cio_go(method: str, path: str, query: dict[str, list[str]], body: dict[str, Any] | None = None) -> tuple[int, str, bytes]:
    parts = [p for p in path.split("/") if p]
    # v3 go cio decision {id} action {action}
    try:
        i = parts.index("decision")
        did = parts[i + 1]
        action = parts[i + 3]
    except Exception:
        return _page("Bad link", "<h1>Malformed CIO action link</h1>", 400)
    token = (query.get("t") or [""])[0]
    vr = verify_action_token(token, expected_action=action, expected_decision_id=did)
    if not vr.get("ok"):
        return _page("Link invalid", f"<h1>Link {html.escape(str(vr.get('error')))}</h1><p>This signed action is expired, mismatched, or forged. Nothing was recorded.</p>", 400)
    payload = vr["payload"]
    if method.upper() == "GET":
        if action not in MUTATING:
            return _page("Open CIO", f"<h1>{html.escape(action.upper())}</h1><p>Non-mutating view. Open the CIO desk to continue.</p>")
        extra = ""
        if action == "rate":
            extra = "".join(f'<button name="rating" value="{n}">{n}</button> ' for n in range(1, 6))
        form = f"""
        <h1>Confirm {html.escape(action.upper())}</h1>
        <p>Decision <code>{html.escape(did)}</code></p>
        <p class="muted">Unsigned GET did not change anything.</p>
        <form method="post">
          <input type="hidden" name="t" value="{html.escape(token)}"/>
          {extra}
          <p><button type="submit">Confirm {html.escape(action.upper())}</button></p>
        </form>
        """
        return _page("Confirm CIO action", form)
    # POST
    rating = None
    note = ""
    if isinstance(body, dict):
        if body.get("rating") is not None:
            try:
                rating = int(body["rating"])
            except Exception:
                rating = None
        note = str(body.get("note") or "")
    result = apply_signed_disposition(payload, rating=rating, note=note)
    if not result.get("ok"):
        err = html.escape(str(result.get("error") or "unknown"))
        field = html.escape(str(result.get("field") or ""))
        detail = html.escape(str(result.get("detail") or ""))
        extra = f"<p class=\"muted\">{field}</p>" if field else ""
        if detail:
            extra += f"<p class=\"muted\">{detail}</p>"
        if err == "digest_mismatch":
            extra += (
                "<p>This button was minted against a different evidence hash than "
                "the live capital-plan catalog. Open CIO and retry, or wait for a "
                "refreshed card. Nothing was recorded.</p>"
            )
        return _page("Not applied", f"<h1>Disposition not applied</h1><p>{err}</p>{extra}", 409)
    return _page("Recorded", f"<h1>{html.escape(action.upper())} recorded</h1><p>Decision {html.escape(did)} · idempotent advisory write only.</p>")
