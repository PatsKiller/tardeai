"""Read-only conflict evaluation; persistence and execution are separate."""
from .engine import Finding, Input, Subject, evaluate, headline

__all__ = ["Finding", "Input", "Subject", "evaluate", "headline"]
