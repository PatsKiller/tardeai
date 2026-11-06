"""§6: a deep crawl opens detail views and follows links — it never presses an action.

Operator wording (SPEC_SITE_AUDIT_AUTOREMEDIATE_LOOP_20261104.md §6): "Still never press action buttons: approve,
decline, acknowledge, refresh, run now, place, stop, apply, merge. A denylist by label and role is enforced in code."

Enforced here, on the node's own text and role, before anything is clicked. Matching is word-boundary based so a
navigation label like "Approvals" is not mistaken for the button "Approve", and a card heading containing "stop" inside
a sentence is not a button at all (the role check runs first).

Two predicates, deliberately different:

  `is_forbidden_action` / `safe_to_open` answer "is this node an action CONTROL?" — role first, so prose under a
  heading is not an action. They judge planned openers and links.

  `is_forbidden_click` / `safe_to_activate` answer "may the crawler PRESS this live node?" — the fail-closed default
  the whole-head review demanded (F1): an action word in the accessible name refuses the node whatever its role
  (an `<a>`, a `<div>` and `role="none"` labelled "Approve" are all actions), and a live node whose role is absent,
  unknown or non-actionable is never pressed to find out what it does.
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


#: Roles a live node may carry and still be pressed: the action roles (a detail button) and a link (a GET that
#: navigates). Every other role — absent, "none", "presentation", "heading", anything unknown — is refused.
CLICKABLE_ROLES = ACTION_ROLES | {"link"}


def is_forbidden_click(label: str | None, role: str | None) -> bool:
    """True when the crawler must not PRESS this live node. Fails closed on every unknown.

    Rule 1 — the node's own accessible name wins over its role. A target labelled "Approve" is an action when it
    resolves as `<a>`, `<div>` or `role="none"`, not only when it is a semantic `<button>`. The role-before-label
    ordering of `is_forbidden_action` exists to keep prose under a heading from looking like a control; at the
    click boundary the question is different, so the label is checked first and regardless of role.

    Rule 2 — an absent or unknown role is not clicked. If the crawler cannot tell what the node is, it does not
    press it to find out (the whole-head finding's "unknown/absent role means do NOT click"). An unlabelled node
    is refused for the same reason: there is nothing to judge it by.
    """
    text = str(label or "").strip()
    if not text:
        return True
    if ACTION_WORDS.search(text):
        return True
    r = str(role or "").strip().lower()
    return r not in CLICKABLE_ROLES


def safe_to_activate(label: str | None, role: str | None) -> bool:
    """The positive form the click boundary calls: True only for a readable, non-action, clickable-role node."""
    return not is_forbidden_click(label, role)
