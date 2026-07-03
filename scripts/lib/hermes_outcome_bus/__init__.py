"""Thin outcome_bus coordination layer — versioned JSON read model for Hermes agents."""
from .bus import (
    OUTCOME_BUS_PATH,
    OUTCOME_BUS_VERSION,
    load_outcome_bus,
    load_outcome_bus_trend,
    read_outcome_bus,
    write_outcome_bus,
)

__all__ = [
    "OUTCOME_BUS_PATH",
    "OUTCOME_BUS_VERSION",
    "load_outcome_bus",
    "load_outcome_bus_trend",
    "read_outcome_bus",
    "write_outcome_bus",
]