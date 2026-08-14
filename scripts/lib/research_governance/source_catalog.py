"""Research governance — canonical source catalog seed (PR-R1).

Machine-readable registry of the sources the research subsystem intends to
govern. `full_text_status` records honestly whether a lawful full text is in the
file library; a source whose full text is missing must never be treated as if it
had been read. The original ten books are listed first, then the recommended
additions, then the primary-research layer.
"""
from __future__ import annotations

from typing import Any, Dict, List

SOURCES: List[Dict[str, Any]] = [
    # --- original ten ---
    {"source_id": "malkiel_random_walk", "source_type": "book",
     "title": "A Random Walk Down Wall Street",
     "authors": ["Burton G. Malkiel"], "license_class": "COPYRIGHT",
     "full_text_status": "NOT_FOUND_IN_FILE_LIBRARY"},
    {"source_id": "graham_zweig_intelligent_investor", "source_type": "book",
     "title": "The Intelligent Investor", "authors": ["Benjamin Graham", "Jason Zweig"],
     "license_class": "COPYRIGHT", "full_text_status": "NOT_FOUND_IN_FILE_LIBRARY"},
    {"source_id": "housel_psychology_of_money", "source_type": "book",
     "title": "The Psychology of Money", "authors": ["Morgan Housel"],
     "license_class": "COPYRIGHT", "full_text_status": "NOT_FOUND_IN_FILE_LIBRARY"},
    {"source_id": "bogle_common_sense", "source_type": "book",
     "title": "The Little Book of Common Sense Investing", "authors": ["John C. Bogle"],
     "license_class": "COPYRIGHT", "full_text_status": "NOT_FOUND_IN_FILE_LIBRARY"},
    {"source_id": "ferri_etf_book", "source_type": "book",
     "title": "The ETF Book", "authors": ["Richard A. Ferri"],
     "license_class": "COPYRIGHT", "full_text_status": "NOT_FOUND_IN_FILE_LIBRARY"},
    {"source_id": "thau_bond_book", "source_type": "book",
     "title": "The Bond Book", "authors": ["Annette Thau"],
     "license_class": "COPYRIGHT", "full_text_status": "NOT_FOUND_IN_FILE_LIBRARY"},
    {"source_id": "harris_trading_exchanges", "source_type": "book",
     "title": "Trading and Exchanges", "authors": ["Larry Harris"],
     "license_class": "COPYRIGHT", "full_text_status": "NOT_FOUND_IN_FILE_LIBRARY"},
    {"source_id": "mcmillan_options", "source_type": "book",
     "title": "Options as a Strategic Investment", "authors": ["Lawrence G. McMillan"],
     "license_class": "COPYRIGHT", "full_text_status": "NOT_FOUND_IN_FILE_LIBRARY"},
    {"source_id": "natenberg_option_volatility", "source_type": "book",
     "title": "Option Volatility and Pricing", "authors": ["Sheldon Natenberg"],
     "license_class": "COPYRIGHT", "full_text_status": "NOT_FOUND_IN_FILE_LIBRARY"},
    {"source_id": "aronson_evidence_based_ta", "source_type": "book",
     "title": "Evidence-Based Technical Analysis", "authors": ["David Aronson"],
     "license_class": "COPYRIGHT", "full_text_status": "NOT_FOUND_IN_FILE_LIBRARY"},
    # --- additions ---
    {"source_id": "lopez_de_prado_afml", "source_type": "book",
     "title": "Advances in Financial Machine Learning", "authors": ["Marcos López de Prado"],
     "license_class": "COPYRIGHT", "full_text_status": "NOT_FOUND_IN_FILE_LIBRARY"},
    {"source_id": "ilmanen_expected_returns", "source_type": "book",
     "title": "Expected Returns", "authors": ["Antti Ilmanen"],
     "license_class": "COPYRIGHT", "full_text_status": "NOT_FOUND_IN_FILE_LIBRARY"},
    {"source_id": "grinold_kahn_active_pm", "source_type": "book",
     "title": "Active Portfolio Management", "authors": ["Richard C. Grinold", "Ronald N. Kahn"],
     "license_class": "COPYRIGHT", "full_text_status": "NOT_FOUND_IN_FILE_LIBRARY"},
    {"source_id": "damodaran_on_valuation", "source_type": "book",
     "title": "Damodaran on Valuation", "authors": ["Aswath Damodaran"],
     "license_class": "COPYRIGHT", "full_text_status": "NOT_FOUND_IN_FILE_LIBRARY"},
    {"source_id": "marks_most_important_thing", "source_type": "book",
     "title": "The Most Important Thing", "authors": ["Howard Marks"],
     "license_class": "COPYRIGHT", "full_text_status": "NOT_FOUND_IN_FILE_LIBRARY"},
    {"source_id": "stock_traders_almanac", "source_type": "book",
     "title": "Stock Trader's Almanac", "authors": ["Jeffrey A. Hirsch"],
     "license_class": "COPYRIGHT", "full_text_status": "NOT_FOUND_IN_FILE_LIBRARY"},
    # --- primary research layer ---
    {"source_id": "white_reality_check_2000", "source_type": "paper",
     "title": "A Reality Check for Data Snooping",
     "authors": ["Halbert White"],
     "publisher_or_journal": "Econometrica", "license_class": "COPYRIGHT",
     "full_text_status": "NOT_FOUND_IN_FILE_LIBRARY"},
    {"source_id": "sullivan_timmermann_white_1999", "source_type": "paper",
     "title": "Data-Snooping, Technical Trading Rule Performance, and the Bootstrap",
     "authors": ["Ryan Sullivan", "Allan Timmermann", "Halbert White"],
     "publisher_or_journal": "Journal of Finance", "license_class": "COPYRIGHT",
     "full_text_status": "NOT_FOUND_IN_FILE_LIBRARY"},
    {"source_id": "bailey_lopez_de_prado_2014", "source_type": "paper",
     "title": "The Deflated Sharpe Ratio: Correcting for Selection Bias, Backtest Overfitting and Non-Normality",
     "authors": ["David H. Bailey", "Marcos López de Prado"],
     "license_class": "COPYRIGHT", "full_text_status": "NOT_FOUND_IN_FILE_LIBRARY"},
    {"source_id": "bailey_borwein_lopez_de_prado_zhu_2017", "source_type": "paper",
     "title": "The Probability of Backtest Overfitting",
     "authors": ["David H. Bailey", "Jonathan Borwein", "Marcos López de Prado", "Qiji Jim Zhu"],
     "license_class": "COPYRIGHT", "full_text_status": "NOT_FOUND_IN_FILE_LIBRARY"},
    {"source_id": "harvey_liu_zhu_2016", "source_type": "paper",
     "title": "... and the Cross-Section of Expected Returns",
     "authors": ["Campbell R. Harvey", "Yan Liu", "Heqing Zhu"],
     "publisher_or_journal": "Review of Financial Studies", "license_class": "COPYRIGHT",
     "full_text_status": "NOT_FOUND_IN_FILE_LIBRARY"},
]
