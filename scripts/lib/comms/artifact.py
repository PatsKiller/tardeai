"""MessageArtifact@v1 — the governed, curated message (Wave F).

A ``MessageArtifact`` is the single unit of curated operator-facing output: a
dataclass, not a persisted store. It carries the meaning-bearing fields
(headline, why_now, protected facts, requested action, urgency, ranked
authoritative links, command-center URL, external links), a lifecycle field
(retention class), and a production field (curation mode).

Two identity hashes are computed:

* ``protected_facts_hash`` — hash of ``protected_facts`` alone (reused from
  ``scripts.lib.comms.identity``).
* ``semantic_hash`` — a canonical hash over the meaning-bearing fields. It is
  order-insensitive: reordering the authoritative/external link lists does not
  change it. Rendered variants (LLM vs deterministic vs template) are recorded
  separately in ``rendered_variants`` so a semantic identity can stay stable
  while its presentation changes.

Link contract — every rendered link must point at the Tailscale command center
FQDN ``https://ms01-openclaw.tail163d14.ts.net/v3/...``. Rejected outright:
``localhost``/loopback, RFC1918/LAN/private/reserved/link-local IPs, the local
``:7777`` portfolio-server port, ``file://``/local filesystem paths, shell-command
metacharacters, the legacy ``/v2`` surface, non-HTTPS schemes, and any host other
than the allowed FQDN. Egress to arbitrary external hosts is not permitted here —
that is an operator decision under AGENTS.md §2A, not a default this module
grants.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

from scripts.lib.comms.curation import DETERMINISTIC, VALID_CURATION_MODES
from scripts.lib.comms.identity import protected_facts_hash_for

SCHEMA_VERSION = "MessageArtifact@v1"

# ---------------------------------------------------------------------------
# Link contract
# ---------------------------------------------------------------------------

TAILSCALE_FQDN = "ms01-openclaw.tail163d14.ts.net"
ALLOWED_HOST = TAILSCALE_FQDN
ALLOWED_SCHEME = "https"
ALLOWED_PATH_PREFIX = "/v3/"
LEGACY_PATH_PREFIX = "/v2"
FORBIDDEN_PORT = 7777

_FORBIDDEN_SCHEMES = frozenset({"data", "javascript", "vbscript", "about"})
_SHELL_CHARS = (";", "|", "`", "$", "<", ">", "\n", "\r", "\t", " ")


def _looks_like_shell_command(url: str) -> bool:
    if any(ch in url for ch in _SHELL_CHARS):
        return True
    return "&&" in url or "||" in url


class LinkContractError(ValueError):
    """A URL violates the governed link contract."""

    def __init__(self, *, url: str, reason: str, field: str = "link"):
        self.url = url
        self.reason = reason
        self.field = field
        super().__init__(f"link_contract:{reason}:{field}={url!r}")


def validate_link(url: str | None, *, field: str = "link") -> str:
    """Return ``url`` unchanged if it satisfies the link contract, else raise.

    Ordering matters: identity/shell/file checks run first, then host and
    port, then the legacy-surface and FQDN/path checks. Every rendered link
    (command_center_url, authoritative_links, external_links) goes through this
    one function so the policy is enforced in one place.
    """
    if url is None:
        raise LinkContractError(url="", reason="empty", field=field)
    raw = str(url).strip()
    if not raw:
        raise LinkContractError(url=raw, reason="empty", field=field)

    if _looks_like_shell_command(raw):
        raise LinkContractError(url=raw, reason="shell_command", field=field)

    parsed = urlparse(raw)
    scheme = (parsed.scheme or "").lower()

    if scheme == "file":
        raise LinkContractError(url=raw, reason="local_file", field=field)
    if scheme in _FORBIDDEN_SCHEMES:
        raise LinkContractError(url=raw, reason="forbidden_scheme", field=field)
    if scheme != ALLOWED_SCHEME:
        if scheme == "" and raw.startswith(("/", "./", "../", "~/")):
            raise LinkContractError(url=raw, reason="local_file", field=field)
        raise LinkContractError(url=raw, reason="scheme_not_https", field=field)

    host = (parsed.hostname or "").lower()
    if not host:
        raise LinkContractError(url=raw, reason="missing_host", field=field)
    if host == "localhost" or host.endswith(".localhost"):
        raise LinkContractError(url=raw, reason="localhost", field=field)

    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None and (
        ip.is_loopback
        or ip.is_link_local
        or ip.is_private
        or ip.is_reserved
        or ip.is_unspecified
        or ip.is_multicast
    ):
        raise LinkContractError(url=raw, reason="rfc1918_lan", field=field)

    try:
        port = parsed.port
    except ValueError:
        raise LinkContractError(url=raw, reason="invalid_port", field=field)
    if port == FORBIDDEN_PORT:
        raise LinkContractError(url=raw, reason="forbidden_port_7777", field=field)

    path = parsed.path or ""
    if path == LEGACY_PATH_PREFIX or path.startswith(LEGACY_PATH_PREFIX + "/"):
        raise LinkContractError(url=raw, reason="legacy_v2", field=field)

    if host != ALLOWED_HOST:
        raise LinkContractError(url=raw, reason="host_not_allowed", field=field)
    if not path.startswith(ALLOWED_PATH_PREFIX):
        raise LinkContractError(url=raw, reason="path_not_v3", field=field)

    return raw


# ---------------------------------------------------------------------------
# Urgency vocabulary (deterministic, closed set)
# ---------------------------------------------------------------------------

URGENCY_IMMEDIATE = "IMMEDIATE"
URGENCY_HIGH = "HIGH"
URGENCY_NORMAL = "NORMAL"
URGENCY_LOW = "LOW"
VALID_URGENCY = frozenset({URGENCY_IMMEDIATE, URGENCY_HIGH, URGENCY_NORMAL, URGENCY_LOW})

# ---------------------------------------------------------------------------
# Attachment vocabulary
# ---------------------------------------------------------------------------

SCAN_RESULT_CLEAN = "clean"
SCAN_RESULT_UNSCANNED = "unscanned"
SCAN_RESULT_BLOCKED = "blocked"
VALID_SCAN_RESULTS = frozenset(
    {SCAN_RESULT_CLEAN, SCAN_RESULT_UNSCANNED, SCAN_RESULT_BLOCKED}
)

CAPABILITY_INLINE = "inline"
CAPABILITY_LINK = "link"
CAPABILITY_BLOCKED = "blocked"
VALID_CAPABILITIES = frozenset({CAPABILITY_INLINE, CAPABILITY_LINK, CAPABILITY_BLOCKED})


def _stable_dumps(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Sub-structures
# ---------------------------------------------------------------------------


@dataclass
class AuthoritativeLink:
    """A typed, ranked authoritative source link.

    ``rank`` is 0-indexed (0 = primary source). ``provenance_class`` follows the
    provenance vocabulary (D/T/M/A/S); links are normally ``D``.
    """

    url: str
    link_type: str
    rank: int
    title: str | None = None
    provenance_class: str = "D"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_semantic(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "link_type": self.link_type,
            "rank": self.rank,
        }


@dataclass
class MessageAttachment:
    """A first-class attachment with scan/retention/capability provenance."""

    mime_type: str
    size_bytes: int
    content_hash: str
    storage_locator: str
    scan_result: str
    retention_class: str
    # channel -> capability decision (inline / link / blocked).
    channel_capability: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def validate(self) -> None:
        if not (self.mime_type or "").strip():
            raise ValueError("attachment.mime_type required")
        if not isinstance(self.size_bytes, int) or self.size_bytes < 0:
            raise ValueError("attachment.size_bytes must be a non-negative int")
        if not (self.content_hash or "").strip():
            raise ValueError("attachment.content_hash required")
        if not (self.storage_locator or "").strip():
            raise ValueError("attachment.storage_locator required")
        if self.scan_result not in VALID_SCAN_RESULTS:
            raise ValueError(
                f"attachment.scan_result must be one of {sorted(VALID_SCAN_RESULTS)}"
            )
        if not (self.retention_class or "").strip():
            raise ValueError("attachment.retention_class required")
        for ch, cap in self.channel_capability.items():
            if cap not in VALID_CAPABILITIES:
                raise ValueError(
                    f"attachment.channel_capability[{ch!r}] must be one of "
                    f"{sorted(VALID_CAPABILITIES)}"
                )


# ---------------------------------------------------------------------------
# MessageArtifact@v1
# ---------------------------------------------------------------------------

# Fields that participate in the canonical semantic hash. Presentation and
# lifecycle-provenance fields (provenance_footer, expires_at, curation_mode,
# rendered_variants) are excluded: they describe how/when/for-how-long the
# artifact is produced, not what it says or cites.
_SEMANTIC_FIELDS = (
    "headline",
    "why_now",
    "protected_facts",
    "requested_action",
    "urgency",
    "authoritative_links",
    "command_center_url",
    "external_links",
    "retention_class",
)


@dataclass
class MessageArtifact:
    """The governed curated message (Wave F). Not a persisted store."""

    headline: str
    why_now: str
    protected_facts: dict[str, Any] = field(default_factory=dict)
    requested_action: str = ""
    urgency: str = URGENCY_NORMAL
    authoritative_links: list[AuthoritativeLink] = field(default_factory=list)
    command_center_url: str = ""
    external_links: list[str] = field(default_factory=list)
    provenance_footer: str = ""
    retention_class: str = "operational_30d"
    curation_mode: str = DETERMINISTIC
    expires_at: datetime | None = None
    attachments: list[MessageAttachment] = field(default_factory=list)

    # Computed identity.
    schema_version: str = SCHEMA_VERSION
    protected_facts_hash: str | None = None
    semantic_hash: str | None = None
    rendered_variants: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.authoritative_links = [
            l if isinstance(l, AuthoritativeLink) else AuthoritativeLink(**l)
            for l in (self.authoritative_links or [])
        ]
        self.attachments = [
            a if isinstance(a, MessageAttachment) else MessageAttachment(**a)
            for a in (self.attachments or [])
        ]

    # -- identity ----------------------------------------------------------

    def compute_protected_facts_hash(self) -> str:
        self.protected_facts_hash = protected_facts_hash_for(self.protected_facts)
        return self.protected_facts_hash

    def _semantic_material(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "headline": self.headline,
            "why_now": self.why_now,
            "protected_facts": self.protected_facts or {},
            "requested_action": self.requested_action,
            "urgency": self.urgency,
            "authoritative_links": sorted(
                (l.to_semantic() for l in self.authoritative_links),
                key=lambda d: (d["rank"], d["link_type"], d["url"]),
            ),
            "command_center_url": self.command_center_url,
            "external_links": sorted(self.external_links),
            "retention_class": self.retention_class,
        }

    def compute_semantic_hash(self) -> str:
        self.semantic_hash = _sha256(_stable_dumps(self._semantic_material()))
        return self.semantic_hash

    def mint(self) -> "MessageArtifact":
        """Compute identity hashes if absent. Never overwrites an existing hash."""
        if not self.protected_facts_hash:
            self.compute_protected_facts_hash()
        if not self.semantic_hash:
            self.compute_semantic_hash()
        return self

    # -- rendered variants -------------------------------------------------

    def record_rendered_variant(self, name: str, rendered_text: str) -> str:
        """Record the hash of one rendered variant (e.g. 'llm', 'deterministic')."""
        digest = _sha256(rendered_text)
        self.rendered_variants[name] = digest
        return digest

    # -- validation --------------------------------------------------------

    def validate(self) -> "MessageArtifact":
        if not (self.headline or "").strip():
            raise ValueError("MessageArtifact.headline required")
        if not (self.why_now or "").strip():
            raise ValueError("MessageArtifact.why_now required")
        if not (self.requested_action or "").strip():
            raise ValueError("MessageArtifact.requested_action required")
        if self.urgency not in VALID_URGENCY:
            raise ValueError(f"urgency must be one of {sorted(VALID_URGENCY)}")
        if self.curation_mode not in VALID_CURATION_MODES:
            raise ValueError(
                f"curation_mode must be one of {sorted(VALID_CURATION_MODES)}"
            )
        if not (self.retention_class or "").strip():
            raise ValueError("MessageArtifact.retention_class required")
        if not isinstance(self.protected_facts, dict):
            raise ValueError("protected_facts must be a dict")

        validate_link(self.command_center_url, field="command_center_url")
        for link in self.authoritative_links:
            validate_link(link.url, field="authoritative_links")
            if not (link.link_type or "").strip():
                raise ValueError("authoritative link_type required")
            if not isinstance(link.rank, int) or link.rank < 0:
                raise ValueError("authoritative rank must be a non-negative int")
        for url in self.external_links or []:
            validate_link(url, field="external_links")
        for att in self.attachments:
            att.validate()
        return self.mint()

    # -- deterministic render ---------------------------------------------

    def render(self) -> str:
        """Stable, deterministic text render (never an LLM)."""
        self.mint()
        lines = [
            f"headline: {self.headline}",
            f"why_now: {self.why_now}",
            f"protected_facts_hash: {self.protected_facts_hash}",
            f"requested_action: {self.requested_action}",
            f"urgency: {self.urgency}",
            "authoritative_links:",
        ]
        for link in sorted(self.authoritative_links, key=lambda l: (l.rank, l.url)):
            lines.append(f"  - [{link.rank}] {link.link_type}: {link.url}")
        lines.append(f"command_center_url: {self.command_center_url}")
        lines.append("external_links:")
        for url in sorted(self.external_links):
            lines.append(f"  - {url}")
        lines.append(f"provenance_footer: {self.provenance_footer}")
        lines.append(
            f"expires_at: {self.expires_at.isoformat() if self.expires_at else ''}"
        )
        lines.append(f"retention_class: {self.retention_class}")
        lines.append(f"curation_mode: {self.curation_mode}")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        self.mint()
        return {
            "schema_version": self.schema_version,
            "headline": self.headline,
            "why_now": self.why_now,
            "protected_facts": self.protected_facts,
            "protected_facts_hash": self.protected_facts_hash,
            "requested_action": self.requested_action,
            "urgency": self.urgency,
            "authoritative_links": [l.to_dict() for l in self.authoritative_links],
            "command_center_url": self.command_center_url,
            "external_links": list(self.external_links),
            "provenance_footer": self.provenance_footer,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "retention_class": self.retention_class,
            "curation_mode": self.curation_mode,
            "attachments": [a.to_dict() for a in self.attachments],
            "semantic_hash": self.semantic_hash,
            "rendered_variants": dict(self.rendered_variants),
        }
