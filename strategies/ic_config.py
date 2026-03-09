"""
Iron Condor Strategy Configuration - Ported from Loveable
Complete configuration matching the production Loveable IC system.
"""

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import List, Dict, Optional, Tuple


# =============================================================================
# ENUMS
# =============================================================================

class ICUnderlying(Enum):
    """Supported underlyings for Iron Condors."""
    SPY = "SPY"
    SPX = "SPX"
    QQQ = "QQQ"
    IWM = "IWM"


class VIXRegime(Enum):
    """VIX regime classification."""
    NORMAL = "NORMAL"        # VIX < 20 - Full size
    ELEVATED = "ELEVATED"    # VIX 20-23 - 50% size
    HIGH = "HIGH"            # VIX 23-25 - 25% size  
    CRITICAL = "CRITICAL"    # VIX >= 25 - NO ENTRY


class ICPositionStatus(Enum):
    """Iron Condor position status."""
    PENDING = "PENDING"
    OPEN = "OPEN"
    CLOSING = "CLOSING"
    CLOSED = "CLOSED"
    EXPIRED = "EXPIRED"


class ICCloseReason(Enum):
    """Reason for closing an Iron Condor."""
    # Profit targets
    PROFIT_TARGET_50 = "profit_target_50%_max_profit"
    PROFIT_TARGET_70 = "profit_target_70%_premium"
    
    # Stop losses
    STOP_LOSS = "stop_loss"
    PER_SPREAD_STOP_PUT = "per_spread_stop_put"
    PER_SPREAD_STOP_CALL = "per_spread_stop_call"
    
    # Greek exits
    DELTA_EXIT_PUT = "delta_exit_put"
    DELTA_EXIT_CALL = "delta_exit_call"
    GAMMA_EXIT_PUT = "gamma_exit_put"
    GAMMA_EXIT_CALL = "gamma_exit_call"
    IV_EXPANSION = "iv_expansion_exit"
    
    # Time exits
    DTE_SAFETY = "dte_safety_exit"
    TIME_BASED = "time_based"
    EXPIRY = "expiry_approaching"
    
    # Price exits
    STRIKE_PROXIMITY_PUT = "strike_proximity_put"
    STRIKE_PROXIMITY_CALL = "strike_proximity_call"
    SUPPORT_BREAK = "support_break_put"
    RESISTANCE_BREAK = "resistance_break_call"
    
    # VIX exits
    VIX_EXPANSION = "vix_expansion"
    
    # Rolling
    AUTO_ROLL_PUT = "auto_roll_put"
    AUTO_ROLL_CALL = "auto_roll_call"
    
    # Other
    MANUAL = "manual"
    POSITION_NOT_FOUND = "position_not_found"


# =============================================================================
# UNDERLYING CONFIGURATION
# =============================================================================

@dataclass
class UnderlyingConfig:
    """Configuration for each underlying."""
    symbol: str
    name: str
    option_symbol: str  # SPXW for SPX, same as symbol for others
    multiplier: int = 100
    cash_settled: bool = False
    tax_advantaged: bool = False  # SPX has 60/40 tax treatment
    min_strike_width: int = 5
    typical_iv: float = 15.0
    correlation_to_spy: float = 1.0
    enabled: bool = True
    max_condors: int = 3
    iv_index: str = "VIX"
    
    # Underlying-specific thresholds
    min_credit: float = 0.30
    target_delta: float = 0.10


# Supported underlyings configuration (from underlyings.ts)
UNDERLYING_CONFIGS: Dict[str, UnderlyingConfig] = {
    "SPY": UnderlyingConfig(
        symbol="SPY",
        name="S&P 500 ETF",
        option_symbol="SPY",
        min_strike_width=5,
        typical_iv=15.0,
        correlation_to_spy=1.0,
        enabled=True,
        max_condors=3,
        iv_index="VIX",
        min_credit=0.30,
        target_delta=0.10,
    ),
    "SPX": UnderlyingConfig(
        symbol="SPX",
        name="S&P 500 Index",
        option_symbol="SPXW",  # Weekly options use SPXW
        min_strike_width=25,
        typical_iv=14.0,
        correlation_to_spy=0.99,
        cash_settled=True,
        tax_advantaged=True,
        enabled=True,
        max_condors=2,
        iv_index="VIX",
        min_credit=1.0,
        target_delta=0.10,
    ),
    "QQQ": UnderlyingConfig(
        symbol="QQQ",
        name="Nasdaq 100 ETF",
        option_symbol="QQQ",
        min_strike_width=5,
        typical_iv=20.0,
        correlation_to_spy=0.85,
        enabled=True,
        max_condors=2,
        iv_index="VXN",
        min_credit=0.35,
        target_delta=0.12,
    ),
    "IWM": UnderlyingConfig(
        symbol="IWM",
        name="Russell 2000 ETF",
        option_symbol="IWM",
        min_strike_width=2,
        typical_iv=22.0,
        correlation_to_spy=0.75,
        enabled=False,  # Disabled by default
        max_condors=1,
        iv_index="RVX",
        min_credit=0.30,
        target_delta=0.10,
    ),
}


def get_underlying_config(symbol: str) -> Optional[UnderlyingConfig]:
    """Get configuration for an underlying."""
    return UNDERLYING_CONFIGS.get(symbol)


def get_enabled_underlyings() -> List[UnderlyingConfig]:
    """Get list of enabled underlying configs."""
    return [c for c in UNDERLYING_CONFIGS.values() if c.enabled]


# =============================================================================
# VIX CONFIGURATION
# =============================================================================

@dataclass
class VIXConfig:
    """VIX-based position sizing thresholds (3-tier system from Loveable)."""
    normal_threshold: float = 20.0      # Full position size below this
    elevated_threshold: float = 23.0    # 50% position size
    critical_threshold: float = 25.0    # NO ENTRY at or above this
    
    # Position size multipliers
    normal_multiplier: float = 1.0
    elevated_multiplier: float = 0.5
    critical_multiplier: float = 0.0  # No new trades
    
    # VIX expansion exit threshold
    expansion_exit_pct: float = 15.0  # Exit if VIX up 15%+ from entry
    
    def get_regime(self, vix_value: float) -> VIXRegime:
        """Determine VIX regime."""
        if vix_value >= self.critical_threshold:
            return VIXRegime.CRITICAL
        elif vix_value >= self.elevated_threshold:
            return VIXRegime.HIGH
        elif vix_value >= self.normal_threshold:
            return VIXRegime.ELEVATED
        else:
            return VIXRegime.NORMAL
    
    def get_multiplier(self, vix_value: float) -> float:
        """Get position size multiplier based on VIX level."""
        if vix_value >= self.critical_threshold:
            return self.critical_multiplier
        elif vix_value >= self.normal_threshold:  # 20-25 range gets reduced size
            return self.elevated_multiplier
        else:
            return self.normal_multiplier
    
    def can_enter(self, vix_value: float) -> Tuple[bool, str]:
        """Check if VIX allows entry."""
        regime = self.get_regime(vix_value)
        
        if regime == VIXRegime.CRITICAL:
            return False, f"VIX {vix_value:.1f} >= {self.critical_threshold} (CRITICAL - NO ENTRY)"
        elif regime == VIXRegime.HIGH:
            return False, f"VIX {vix_value:.1f} >= {self.elevated_threshold} (HIGH - NO ENTRY)"
        elif regime == VIXRegime.ELEVATED:
            return True, f"VIX {vix_value:.1f} elevated - 50% position size"
        else:
            return True, f"VIX {vix_value:.1f} normal - full position size"


# =============================================================================
# ENTRY CONFIGURATION
# =============================================================================

@dataclass
class EntryConfig:
    """Entry gate configuration."""
    # Delta validation
    max_entry_delta: float = 0.18  # Max delta for short strikes at entry
    max_widen_attempts: int = 5    # Max attempts to widen strikes
    delta_widen_step: float = 1.0  # Dollars to widen per attempt
    min_sanity_delta: float = 0.01 # Below this = API failure
    
    # IV filters
    max_iv_rank: float = 25.0      # Block if IV Rank > 25%
    max_iv_percentile: float = 30.0
    
    # Credit requirements
    min_credit_dollar: float = 0.30
    min_credit_percent: float = 6.0  # % of width
    
    # Entry days (0=Mon, 4=Fri, production: Thu/Fri only)
    entry_days: List[int] = field(default_factory=lambda: [0, 1, 2, 3, 4])  # Mon-Fri for testing
    
    # Trend filter thresholds
    enable_trend_filter: bool = True
    trend_change_threshold: float = 0.5  # % change to consider trending
    trend_timeframes_required: int = 2   # Out of 3 timeframes
    
    # ATR filter
    enable_atr_filter: bool = True
    atr_expand_threshold: float = 10.0  # % increase to block
    
    # Delta drift filter  
    enable_delta_drift_filter: bool = True
    delta_drift_threshold: float = 0.3  # % 1h change to block


# =============================================================================
# EXIT CONFIGURATION
# =============================================================================

@dataclass
class ExitConfig:
    """Exit condition configuration - 15 exit conditions from Loveable."""
    # Delta exits
    delta_warning: float = 0.22     # Yellow warning level
    delta_exit: float = 0.25        # Hard exit threshold
    delta_critical: float = 0.30    # Critical level for adjustment
    
    # Gamma exit
    gamma_exit_threshold: float = 0.05
    gamma_critical_dte: int = 5     # Only apply gamma exit when DTE <= this
    
    # IV expansion exit
    iv_expansion_exit_pct: float = 20.0  # Exit if IV up 20%+
    
    # Profit targets (DUAL system - whichever comes first)
    profit_target_max_pct: float = 50.0     # 50% of max profit
    profit_target_premium_pct: float = 70.0  # 70% of premium collected
    
    # Stop loss
    stop_loss_multiplier: float = 1.5  # 1.5x credit (tighter than 2x)
    per_spread_stop_multiplier: float = 1.5  # Per-side stop
    
    # Time-based exits
    dte_safety_exit: int = 2        # Close at 2 DTE or less
    exit_days: List[int] = field(default_factory=lambda: [1, 2])  # Tue/Wed (0=Mon)
    time_exit_min_profit_pct: float = 60.0  # Need 60%+ profit for time exit
    
    # Strike proximity
    strike_proximity_pct: float = 3.0  # Warn if within 3% of short strike
    enable_sr_exit: bool = True        # Enable support/resistance break exit


# =============================================================================
# POSITION SIZING CONFIGURATION
# =============================================================================

@dataclass
class PositionConfig:
    """Position sizing and limits."""
    # Portfolio limits (from icConfig.ts)
    max_condors_per_100k: int = 6
    risk_per_condor_pct: float = 1.67  # ~10% total for 6 condors
    max_portfolio_allocation_pct: float = 60.0
    min_cash_reserve_pct: float = 20.0
    
    # Diversification
    max_same_expiry: int = 3
    min_strike_separation: float = 50.0
    max_spreads_per_trade: int = 10


# =============================================================================
# STRIKE CONFIGURATION
# =============================================================================

@dataclass
class StrikeConfig:
    """Strike selection configuration."""
    target_dte: int = 7
    min_dte: int = 5
    max_dte: int = 10
    
    # Default wing widths
    default_wing_width: int = 5
    max_wing_width: int = 25  # Widen to this if IV > 60%
    iv_widen_threshold: float = 60.0  # IV percentile to trigger wider wings


# =============================================================================
# MAIN CONFIG CLASS
# =============================================================================

@dataclass 
class ICConfig:
    """Complete Iron Condor strategy configuration."""
    vix: VIXConfig = field(default_factory=VIXConfig)
    entry: EntryConfig = field(default_factory=EntryConfig)
    exit: ExitConfig = field(default_factory=ExitConfig)
    position: PositionConfig = field(default_factory=PositionConfig)
    strikes: StrikeConfig = field(default_factory=StrikeConfig)
    
    # Feature toggles
    trading_enabled: bool = True
    auto_roll_enabled: bool = False
    
    # Enabled underlyings
    enabled_symbols: List[str] = field(default_factory=lambda: ["SPY", "SPX", "QQQ"])
    
    def get_underlying_config(self, symbol: str) -> Optional[UnderlyingConfig]:
        """Get configuration for an underlying."""
        return UNDERLYING_CONFIGS.get(symbol)
    
    def get_enabled_underlyings(self) -> List[UnderlyingConfig]:
        """Get list of enabled underlying configs."""
        return [
            UNDERLYING_CONFIGS[s] 
            for s in self.enabled_symbols 
            if s in UNDERLYING_CONFIGS and UNDERLYING_CONFIGS[s].enabled
        ]
    
    def get_max_condors(self, account_capital: float) -> int:
        """Calculate max condors for account size."""
        multiplier = account_capital / 100000
        return max(1, int(multiplier * self.position.max_condors_per_100k))
    
    def get_risk_per_condor(self, account_capital: float) -> float:
        """Calculate risk amount per condor."""
        return account_capital * (self.position.risk_per_condor_pct / 100)
    
    def get_wing_width(self, symbol: str, iv_percentile: float = 0) -> int:
        """Get wing width for underlying, possibly widened for high IV."""
        config = self.get_underlying_config(symbol)
        base_width = config.min_strike_width if config else self.strikes.default_wing_width
        
        if iv_percentile > self.strikes.iv_widen_threshold:
            return min(base_width * 2, self.strikes.max_wing_width)
        return base_width


# =============================================================================
# DEFAULT INSTANCE
# =============================================================================

IC_CONFIG = ICConfig()


# =============================================================================
# BLOCKED EVENTS (from eventCalendar.ts)
# =============================================================================

# Events that BLOCK entry on that day
BLOCKING_EVENTS = {
    # FOMC 2025-2026
    "2025-01-29": "FOMC Decision",
    "2025-03-19": "FOMC Decision",
    "2025-05-07": "FOMC Decision",
    "2025-06-18": "FOMC Decision",
    "2025-07-30": "FOMC Decision",
    "2025-09-17": "FOMC Decision",
    "2025-11-05": "FOMC Decision",
    "2025-12-17": "FOMC Decision",
    "2026-01-29": "FOMC Decision",
    "2026-03-18": "FOMC Decision",
    "2026-05-06": "FOMC Decision",
    "2026-06-17": "FOMC Decision",
    
    # CPI 2025-2026
    "2025-01-15": "CPI Release",
    "2025-02-12": "CPI Release",
    "2025-03-12": "CPI Release",
    "2025-04-10": "CPI Release",
    "2025-05-13": "CPI Release",
    "2025-06-11": "CPI Release",
    "2025-07-11": "CPI Release",
    "2025-08-12": "CPI Release",
    "2025-09-10": "CPI Release",
    "2025-10-10": "CPI Release",
    "2025-11-13": "CPI Release",
    "2025-12-10": "CPI Release",
    "2026-01-14": "CPI Release",
    "2026-02-12": "CPI Release",
    "2026-03-11": "CPI Release",
    
    # NFP (Jobs Report) 2025-2026
    "2025-01-10": "Jobs Report (NFP)",
    "2025-02-07": "Jobs Report (NFP)",
    "2025-03-07": "Jobs Report (NFP)",
    "2025-04-04": "Jobs Report (NFP)",
    "2025-05-02": "Jobs Report (NFP)",
    "2025-06-06": "Jobs Report (NFP)",
    "2025-07-03": "Jobs Report (NFP)",
    "2025-08-01": "Jobs Report (NFP)",
    "2025-09-05": "Jobs Report (NFP)",
    "2025-10-03": "Jobs Report (NFP)",
    "2025-11-07": "Jobs Report (NFP)",
    "2025-12-05": "Jobs Report (NFP)",
    "2026-01-09": "Jobs Report (NFP)",
    "2026-02-06": "Jobs Report (NFP)",
    "2026-03-06": "Jobs Report (NFP)",
    
    # Quad Witching 2025-2026
    "2025-03-21": "Quad Witching",
    "2025-06-20": "Quad Witching",
    "2025-09-19": "Quad Witching",
    "2025-12-19": "Quad Witching",
    "2026-03-20": "Quad Witching",
    "2026-06-19": "Quad Witching",
}

# Events that generate WARNING (day before)
WARNING_EVENTS = BLOCKING_EVENTS.copy()


def is_event_blocked(check_date: date) -> Tuple[bool, Optional[str]]:
    """Check if entry is blocked due to economic event."""
    date_str = check_date.strftime("%Y-%m-%d")
    
    if date_str in BLOCKING_EVENTS:
        return True, BLOCKING_EVENTS[date_str]
    
    return False, None


def get_event_warning(check_date: date) -> Optional[str]:
    """Check if there's an event tomorrow (warning)."""
    from datetime import timedelta
    tomorrow = check_date + timedelta(days=1)
    tomorrow_str = tomorrow.strftime("%Y-%m-%d")
    
    return WARNING_EVENTS.get(tomorrow_str)
