"""Stable pipeline facade: classify, route, render, and audit in one place."""
try:
    from .message_contract import (  # type: ignore
        MessageEnvelope,
        RenderedMessage,
        audit_unknown,
        classify_message,
        record_shadow_proposal,
        render_message,
        route_envelope,
    )
except ImportError:
    from message_contract import (
    MessageEnvelope,
    RenderedMessage,
    audit_unknown,
    classify_message,
    record_shadow_proposal,
    render_message,
    route_envelope,
    )


def process_message(value, *, producer: str = "legacy"):
    envelope = classify_message(value, producer=producer)
    audit_unknown(envelope)
    return envelope, route_envelope(envelope), render_message(envelope)
