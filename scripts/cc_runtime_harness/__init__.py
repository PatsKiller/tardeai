"""Hermetic Command Center runtime validation harness (grok-runtime lane).

Modes:
  - hermetic: ephemeral local fixture server + synthetic timestamps
  - candidate-preview: base URLs from env (never production by default)

Does not mutate production application behavior.
"""

__version__ = "1.0.0"
SCHEMA = "CcRuntimeHarness@v1"
