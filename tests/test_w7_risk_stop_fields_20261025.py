"""w7 Risk page keeps the #2141 stop-category fields (synthetic data)."""
import inspect

from scripts.lib import w7_pages


def test_display_keys_keep_stop_category_fields():
    src = inspect.getsource(w7_pages)
    for key in ("counted", "stop_category", "resting_stop_distance_pct", "loss_at_resting_stop_usd",
                "planned_stop_distance_pct"):
        assert f'"{key}"' in src, key
