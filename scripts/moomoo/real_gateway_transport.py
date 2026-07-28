"""Compatibility name for the dedicated service's one Futu streaming transport.

Constructing this class opens no trade context and exposes no order path. Production code
must instantiate it only inside ``gateway_service.py`` after acquiring the owner lock.
"""
from __future__ import annotations

try:
    from .futu_streaming_transport import FutuStreamingTransport
except ImportError:  # pragma: no cover
    from futu_streaming_transport import FutuStreamingTransport  # type: ignore


class RealGatewayTransport(FutuStreamingTransport):
    pass
