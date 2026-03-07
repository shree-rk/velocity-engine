"""
Watchlist Configuration
Defines stock watchlists and their categories for the Velocity strategy.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional


class StockCategory(Enum):
    """Stock volatility categories for position sizing."""
    HIGH_BETA = "high_beta"      # Volatile tech stocks - tighter stops
    MODERATE = "moderate"         # Blue chip tech - standard stops
    ETF = "etf"                   # ETFs - wider stops, more stable


@dataclass
class StockConfig:
    """Configuration for a single stock in the watchlist."""
    symbol: str
    category: StockCategory
    enabled: bool = True
    notes: str = ""


# =============================================================================
# Velocity Mean Reversion Watchlist
# 11 symbols across 3 categories
# =============================================================================

VELOCITY_MR_WATCHLIST: Dict[StockCategory, List[StockConfig]] = {
    StockCategory.HIGH_BETA: [
        StockConfig("NVDA", StockCategory.HIGH_BETA, notes="AI leader, high vol"),
        StockConfig("AMD", StockCategory.HIGH_BETA, notes="Semiconductor"),
        StockConfig("TSLA", StockCategory.HIGH_BETA, notes="EV leader, very volatile"),
    ],
    StockCategory.MODERATE: [
        StockConfig("AAPL", StockCategory.MODERATE, notes="Mega cap tech"),
        StockConfig("MSFT", StockCategory.MODERATE, notes="Mega cap tech"),
        StockConfig("GOOGL", StockCategory.MODERATE, notes="Mega cap tech"),
    ],
    StockCategory.ETF: [
        StockConfig("QQQ", StockCategory.ETF, notes="Nasdaq 100"),
        StockConfig("SMH", StockCategory.ETF, notes="Semiconductor ETF"),
        StockConfig("XBI", StockCategory.ETF, notes="Biotech ETF"),
        StockConfig("IWM", StockCategory.ETF, notes="Russell 2000"),
        StockConfig("SPY", StockCategory.ETF, notes="S&P 500"),
    ],
}


def get_all_symbols(watchlist: Dict[StockCategory, List[StockConfig]] = None) -> List[str]:
    """
    Get all enabled symbols from a watchlist.
    
    Args:
        watchlist: Watchlist dict (defaults to VELOCITY_MR_WATCHLIST)
        
    Returns:
        List of symbol strings.
    """
    if watchlist is None:
        watchlist = VELOCITY_MR_WATCHLIST
    
    symbols = []
    for category_stocks in watchlist.values():
        for config in category_stocks:
            if config.enabled:
                symbols.append(config.symbol)
    
    return symbols


def get_stock_config(
    symbol: str,
    watchlist: Dict[StockCategory, List[StockConfig]] = None
) -> Optional[StockConfig]:
    """
    Get configuration for a specific symbol.
    
    Args:
        symbol: Stock ticker symbol.
        watchlist: Watchlist dict (defaults to VELOCITY_MR_WATCHLIST)
        
    Returns:
        StockConfig or None if not found.
    """
    if watchlist is None:
        watchlist = VELOCITY_MR_WATCHLIST
    
    for category_stocks in watchlist.values():
        for config in category_stocks:
            if config.symbol == symbol:
                return config
    
    return None


def get_category(
    symbol: str,
    watchlist: Dict[StockCategory, List[StockConfig]] = None
) -> Optional[StockCategory]:
    """
    Get category for a symbol.
    
    Args:
        symbol: Stock ticker symbol.
        watchlist: Watchlist dict (defaults to VELOCITY_MR_WATCHLIST)
        
    Returns:
        StockCategory or None if not found.
    """
    config = get_stock_config(symbol, watchlist)
    return config.category if config else None


def get_symbols_by_category(
    category: StockCategory,
    watchlist: Dict[StockCategory, List[StockConfig]] = None
) -> List[str]:
    """
    Get all symbols in a specific category.
    
    Args:
        category: StockCategory to filter by.
        watchlist: Watchlist dict (defaults to VELOCITY_MR_WATCHLIST)
        
    Returns:
        List of symbol strings.
    """
    if watchlist is None:
        watchlist = VELOCITY_MR_WATCHLIST
    
    if category not in watchlist:
        return []
    
    return [
        config.symbol
        for config in watchlist[category]
        if config.enabled
    ]


def enable_symbol(
    symbol: str,
    watchlist: Dict[StockCategory, List[StockConfig]] = None
) -> bool:
    """
    Enable a symbol in the watchlist.
    
    Args:
        symbol: Stock ticker symbol.
        watchlist: Watchlist dict (defaults to VELOCITY_MR_WATCHLIST)
        
    Returns:
        True if symbol was found and enabled.
    """
    config = get_stock_config(symbol, watchlist)
    if config:
        config.enabled = True
        return True
    return False


def disable_symbol(
    symbol: str,
    watchlist: Dict[StockCategory, List[StockConfig]] = None
) -> bool:
    """
    Disable a symbol in the watchlist.
    
    Args:
        symbol: Stock ticker symbol.
        watchlist: Watchlist dict (defaults to VELOCITY_MR_WATCHLIST)
        
    Returns:
        True if symbol was found and disabled.
    """
    config = get_stock_config(symbol, watchlist)
    if config:
        config.enabled = False
        return True
    return False


def get_watchlist_summary(
    watchlist: Dict[StockCategory, List[StockConfig]] = None
) -> Dict[str, any]:
    """
    Get summary of watchlist.
    
    Args:
        watchlist: Watchlist dict (defaults to VELOCITY_MR_WATCHLIST)
        
    Returns:
        Dictionary with summary stats.
    """
    if watchlist is None:
        watchlist = VELOCITY_MR_WATCHLIST
    
    total = 0
    enabled = 0
    by_category = {}
    
    for category, stocks in watchlist.items():
        category_enabled = sum(1 for s in stocks if s.enabled)
        by_category[category.value] = {
            "total": len(stocks),
            "enabled": category_enabled,
            "symbols": [s.symbol for s in stocks if s.enabled]
        }
        total += len(stocks)
        enabled += category_enabled
    
    return {
        "total_symbols": total,
        "enabled_symbols": enabled,
        "categories": by_category
    }