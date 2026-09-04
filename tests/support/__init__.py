"""Test-only helpers.

Named ``support`` rather than ``lib`` on purpose: ``tests/conftest.py`` puts
``scripts/`` on ``sys.path`` so the suite can ``import lib.<module>`` from the
production tree. A ``tests/lib`` package shadows that and breaks every such
import — which is exactly what happened when this package was first added.
"""
