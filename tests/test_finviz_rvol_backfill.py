#!/usr/bin/env python3
"""Finviz RVOL backfill — pre-market Rel Volume=0 must not trip false data-quality alerts."""
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from finviz_ingestion import normalize_finviz_columns  # noqa: E402


def test_backfills_relative_volume_from_volume_avg():
    df = pd.DataFrame({
        "Ticker": ["AP"],
        "Volume": ["5,000,000"],
        "Avg Volume": ["1,000,000"],
        "Rel Volume": ["0"],
        "Gap": ["2.5%"],
        "Float": ["10M"],
        "Industry": ["Software"],
    })
    out = normalize_finviz_columns(df)
    assert out["relative_volume"].iloc[0] == 5.0


def test_empty_frame_skips_quality_gate():
    df = pd.DataFrame(columns=["Ticker", "Volume"])
    out = normalize_finviz_columns(df)
    assert len(out) == 0