"""§6: a deep crawl opens detail views and follows links — it never presses an action.

Operator wording (SPEC_SITE_AUDIT_AUTOREMEDIATE_LOOP_20261104.md §6): "Still never press action buttons: approve,
decline, acknowledge, refresh, run now, place, stop, apply, merge. A denylist by label and role is enforced in code."

Enforced here, on the node's own text and role, before anything is clicked. Matching is word-boundary based so a
navigation label like "Approvals" is not mistaken for the button "Approve", and a card heading containing "stop" inside
a sentence is not a button at all (the role check runs first).
"""

from __future__ import annotations

import re

#: Roles that can carry an action. A link (role=link) navigates; it is followed one level deep, never "pressed".
ACTION_ROLES = frozenset({"button", "menuitem", "menuitemcheckbox", "menuitemradio", "switch", "checkbox"})

#: Words that mark an action, matched as whole words. Deliberately broad: a false positive costs one unopened detail,
#: a false negative performs an operator action.
ACTION_WORDS = re.compile(
    r"\b(approve|approves|approval|decline|reject|acknowledge|ack|confirm|submit|save|delete|remove|cancel|"
    r"place|buy|sell|order|trade|refresh|retry|rerun|re-run|run now|apply|merge|install|enable|disable|arm|"
    r"stop|halt|kill|engage|resume|resume trading|execute|activate|deactivate|promote|pause|unpause|"
    r"clear|reset|purge|revoke|grant|send|post)\b",
    re.I,
)


def is_forbidden_action(label: str | None, role: str | None) -> bool:
    """True when a node must not be activated by the crawler.

    A node is forbidden when its role can act and its accessible text matches an action word. Anything with an action
    role is refused when it has no readable label at all — an unlabelled button is not something a crawler should press
    to find out.
    """
    r = str(role or "").strip().lower()
    if r not in ACTION_ROLES:
        return False
    text = str(label or "").strip()
    if not text:
        return True
    return bool(ACTION_WORDS.search(text))


def safe_to_open(label: str | None, role: str | None) -> bool:
    """The positive form the crawler calls before a click: detail openers only."""
    return not is_forbidden_action(label, role)
