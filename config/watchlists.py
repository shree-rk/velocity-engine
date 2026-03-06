"""
Velocity Engine - Watchlist Definitions
Symbol categories, ATR multipliers, and watchlist configs for each strategy.
"""

from dataclasses import dataclass
from typing import Dict, List


@dataclass
class SymbolConfig:
    """Configuration for a single tradeable symbol."""
    symbol: str
    category: str
    atr_multiplier: float
    display_name: str = ""

    def __post_init__(self):
        if not self.display_name:
            self.display_name = self.symbol


# ============================================================
# Velocity 2.0 Mean Reversion Watchlist (11 Symbols, FIXED)
# ============================================================

VELOCITY_MR_WATCHLIST: List[SymbolConfig] = [
    # HIGH_BETA - Tighter stops (1.5x ATR)
    SymbolConfig("NVDA",  "HIGH_BETA", 1.5, "NVIDIA"),
    SymbolConfig("AMD",   "HIGH_BETA", 1.5, "AMD"),
    SymbolConfig("TSLA",  "HIGH_BETA", 1.5, "Tesla"),

    # MODERATE - Normal stops (2x ATR)
    SymbolConfig("AAPL",  "MODERATE",  2.0, "Apple"),
    SymbolConfig("MSFT",  "MODERATE",  2.0, "Microsoft"),
    SymbolConfig("GOOGL", "MODERATE",  2.0, "Alphabet"),

    # ETF - Normal stops (2x ATR)
    SymbolConfig("QQQ",   "ETF",       2.0, "Nasdaq 100 ETF"),
    SymbolConfig("SMH",   "ETF",       2.0, "Semiconductor ETF"),
    SymbolConfig("XBI",   "ETF",       2.0, "Biotech ETF"),
    SymbolConfig("IWM",   "ETF",       2.0, "Russell 2000 ETF"),
    SymbolConfig("SPY",   "ETF",       2.0, "S&P 500 ETF"),
]


# ============================================================
# Geopolitical Hedge Watchlist (12 Symbols, FUTURE Module 2)
# ============================================================

GEO_HEDGE_WATCHLIST: List[SymbolConfig] = [
    # DEFENSE
    SymbolConfig("LMT",   "DEFENSE",    2.0, "Lockheed Martin"),
    SymbolConfig("NOC",   "DEFENSE",    2.0, "Northrop Grumman"),
    SymbolConfig("RTX",   "DEFENSE",    2.0, "RTX Corp"),
    SymbolConfig("AVAV",  "DEFENSE_HB", 1.5, "AeroVironment"),
    SymbolConfig("LHX",   "DEFENSE",    2.0, "L3Harris"),

    # OIL
    SymbolConfig("XOM",   "OIL",        2.0, "Exxon Mobil"),
    SymbolConfig("COP",   "OIL",        2.0, "ConocoPhillips"),

    # ETFs
    SymbolConfig("XLE",   "OIL_ETF",    2.0, "Energy Select ETF"),
    SymbolConfig("ITA",   "DEF_ETF",    2.0, "iShares US A&D"),

    # SAFE HAVEN
    SymbolConfig("GLD",   "SAFE_HAVEN", 2.5, "SPDR Gold"),
    SymbolConfig("GDX",   "SAFE_HAVEN", 2.0, "Gold Miners ETF"),

    # SHIPPING
    SymbolConfig("STNG",  "SHIPPING",   1.5, "Scorpio Tankers"),
]


# ============================================================
# Helper Functions
# ============================================================

def get_watchlist_by_name(name: str) -> List[SymbolConfig]:
    """Get a watchlist by strategy name."""
    watchlists = {
        "velocity_mr": VELOCITY_MR_WATCHLIST,
        "geo_hedge": GEO_HEDGE_WATCHLIST,
    }
    return watchlists.get(name, [])


def get_symbol_config(symbol: str, watchlist: List[SymbolConfig]) -> SymbolConfig | None:
    """Find a symbol's config in a watchlist."""
    for sc in watchlist:
        if sc.symbol == symbol:
            return sc
    return None


def get_all_symbols(watchlist: List[SymbolConfig]) -> List[str]:
    """Get just the ticker symbols from a watchlist."""
    return [sc.symbol for sc in watchlist]


def get_category_symbols(watchlist: List[SymbolConfig], category: str) -> List[SymbolConfig]:
    """Get all symbols in a specific category."""
    return [sc for sc in watchlist if sc.category == category]
