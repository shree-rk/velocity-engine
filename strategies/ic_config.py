"""
Iron Condor Strategy Configuration
"""

from dataclasses import dataclass
from enum import Enum
from typing import List, Optional


class ICUnderlying(Enum):
    """Supported underlyings for Iron Condors."""
    SPY = "SPY"
    SPX = "SPX"
    QQQ = "QQQ"


@dataclass
class ICConfig:
    """Iron Condor strategy configuration."""
    
    # Underlyings
    underlyings: List[ICUnderlying] = None
    
    # Expiration
    target_dte: int = 7  # Days to expiration
    min_dte: int = 5
    max_dte: int = 10
    
    # Strike Selection
    short_put_delta: float = 0.10  # 10 delta
    short_call_delta: float = 0.10
    delta_range: tuple = (0.08, 0.16)  # Acceptable range
    
    # Spread Width
    spy_width: int = 5  # $5 wide spreads for SPY
    spx_width: int = 50  # $50 wide spreads for SPX
    qqq_width: int = 5  # $5 wide spreads for QQQ
    
    # Risk Management
    risk_per_trade_pct: float = 0.02  # 2% of account
    max_concurrent_per_underlying: int = 3
    max_total_positions: int = 6
    
    # Profit/Loss Targets
    profit_target_pct: float = 0.50  # Close at 50% profit
    stop_loss_multiplier: float = 2.0  # Stop at 2x credit received
    
    # Time-based Exits
    close_at_dte: int = 2  # Close if DTE <= 2 (gamma risk)
    
    # VIX Filters
    min_vix: float = 15.0  # Don't enter below 15 VIX
    max_vix: float = 35.0  # Don't enter above 35 VIX
    optimal_vix_range: tuple = (18.0, 30.0)  # Sweet spot
    
    # Premium Requirements
    min_credit_pct: float = 0.25  # Min 25% of width as credit
    target_credit_pct: float = 0.33  # Target 33% of width
    
    # Event Blocking
    block_days_before_event: int = 2  # No new ICs 2 days before FOMC/CPI
    
    def __post_init__(self):
        if self.underlyings is None:
            self.underlyings = [ICUnderlying.SPY, ICUnderlying.SPX]
    
    def get_spread_width(self, underlying: ICUnderlying) -> int:
        """Get spread width for underlying."""
        widths = {
            ICUnderlying.SPY: self.spy_width,
            ICUnderlying.SPX: self.spx_width,
            ICUnderlying.QQQ: self.qqq_width,
        }
        return widths.get(underlying, 5)
    
    def get_contract_multiplier(self, underlying: ICUnderlying) -> int:
        """Get contract multiplier (100 for most, 100 for SPX)."""
        return 100  # All are 100 multiplier


# Default configuration
IC_DEFAULT_CONFIG = ICConfig()
