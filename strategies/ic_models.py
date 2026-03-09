"""
Iron Condor Data Models - Ported from Loveable
Data structures for Iron Condor positions, signals, and Greeks.
"""

from dataclasses import dataclass, field
from datetime import datetime, date, timezone
from typing import Optional, List, Dict, Any
from enum import Enum

from strategies.ic_config import ICPositionStatus, ICCloseReason


# =============================================================================
# OPTION CONTRACT
# =============================================================================

class OptionType(Enum):
    """Option type."""
    CALL = "C"
    PUT = "P"


@dataclass
class OptionContract:
    """Single option contract."""
    symbol: str  # Underlying e.g., "SPY"
    expiration: date
    strike: float
    option_type: OptionType
    
    # OCC symbol (e.g., "SPY260313P00638000")
    occ_symbol: Optional[str] = None
    
    # Greeks (from broker)
    delta: Optional[float] = None
    gamma: Optional[float] = None
    theta: Optional[float] = None
    vega: Optional[float] = None
    iv: Optional[float] = None
    
    # Pricing
    bid: Optional[float] = None
    ask: Optional[float] = None
    mid: Optional[float] = None
    last: Optional[float] = None
    
    @property
    def dte(self) -> int:
        """Days to expiration."""
        return (self.expiration - date.today()).days
    
    def build_occ_symbol(self, option_ticker: str = None) -> str:
        """
        Build OCC option symbol.
        Format: SPY260313P00638000 (Symbol + YYMMDD + P/C + Strike*1000 padded to 8)
        """
        ticker = option_ticker or self.symbol
        exp_str = self.expiration.strftime("%y%m%d")
        opt_type = self.option_type.value
        strike_str = f"{int(self.strike * 1000):08d}"
        return f"{ticker}{exp_str}{opt_type}{strike_str}"


# =============================================================================
# VERTICAL SPREAD
# =============================================================================

@dataclass
class VerticalSpread:
    """Vertical spread (one side of Iron Condor)."""
    short_leg: OptionContract
    long_leg: OptionContract
    
    @property
    def width(self) -> float:
        """Spread width."""
        return abs(self.short_leg.strike - self.long_leg.strike)
    
    @property
    def is_put_spread(self) -> bool:
        """Is this a put spread (bull put spread)."""
        return self.short_leg.option_type == OptionType.PUT
    
    @property
    def is_call_spread(self) -> bool:
        """Is this a call spread (bear call spread)."""
        return self.short_leg.option_type == OptionType.CALL
    
    @property
    def credit(self) -> Optional[float]:
        """Credit received (short premium - long premium)."""
        if self.short_leg.mid is None or self.long_leg.mid is None:
            return None
        return self.short_leg.mid - self.long_leg.mid
    
    @property
    def max_loss(self) -> float:
        """Maximum loss per contract."""
        credit = self.credit or 0
        return (self.width - credit) * 100  # Per contract
    
    @property
    def short_delta(self) -> Optional[float]:
        """Delta of short leg (absolute value)."""
        if self.short_leg.delta is None:
            return None
        return abs(self.short_leg.delta)


# =============================================================================
# IRON CONDOR POSITION
# =============================================================================

@dataclass
class IronCondor:
    """Complete Iron Condor position."""
    # Identification
    id: Optional[int] = None
    underlying: str = ""
    expiration: Optional[date] = None
    
    # The spreads
    put_spread: Optional[VerticalSpread] = None
    call_spread: Optional[VerticalSpread] = None
    
    # Position info
    contracts: int = 1
    status: ICPositionStatus = ICPositionStatus.PENDING
    
    # Entry details
    entry_time: Optional[datetime] = None
    entry_credit: Optional[float] = None  # Credit per contract
    entry_vix: Optional[float] = None
    entry_iv_rank: Optional[float] = None
    entry_spot_price: Optional[float] = None
    
    # Entry Greeks (stored at fill)
    entry_delta: Optional[float] = None
    entry_gamma: Optional[float] = None
    entry_theta: Optional[float] = None
    entry_vega: Optional[float] = None
    
    # Current Greeks (updated each cycle)
    current_delta: Optional[float] = None
    current_gamma: Optional[float] = None
    current_theta: Optional[float] = None
    current_vega: Optional[float] = None
    current_spot_price: Optional[float] = None
    current_iv: Optional[float] = None
    
    # P&L tracking
    unrealized_pnl: Optional[float] = None
    unrealized_pnl_pct: Optional[float] = None
    
    # Exit details
    exit_time: Optional[datetime] = None
    exit_debit: Optional[float] = None
    exit_reason: Optional[ICCloseReason] = None
    realized_pnl: Optional[float] = None
    
    # Order tracking
    entry_order_id: Optional[str] = None
    exit_order_id: Optional[str] = None
    
    @property
    def dte(self) -> int:
        """Days to expiration."""
        if self.expiration is None:
            return 0
        return (self.expiration - date.today()).days
    
    @property
    def short_put_strike(self) -> float:
        """Short put strike."""
        return self.put_spread.short_leg.strike if self.put_spread else 0
    
    @property
    def long_put_strike(self) -> float:
        """Long put strike."""
        return self.put_spread.long_leg.strike if self.put_spread else 0
    
    @property
    def short_call_strike(self) -> float:
        """Short call strike."""
        return self.call_spread.short_leg.strike if self.call_spread else 0
    
    @property
    def long_call_strike(self) -> float:
        """Long call strike."""
        return self.call_spread.long_leg.strike if self.call_spread else 0
    
    @property
    def wing_width(self) -> float:
        """Wing width (assumes symmetric)."""
        if self.put_spread:
            return self.put_spread.width
        return 0
    
    @property
    def total_credit(self) -> Optional[float]:
        """Total credit received (all contracts)."""
        if self.entry_credit:
            return self.entry_credit * self.contracts * 100
        return None
    
    @property
    def max_profit(self) -> Optional[float]:
        """Maximum profit (credit received)."""
        return self.total_credit
    
    @property
    def max_loss(self) -> float:
        """Maximum loss."""
        credit_per = self.entry_credit or 0
        return (self.wing_width - credit_per) * self.contracts * 100
    
    @property
    def profit_target_price(self) -> Optional[float]:
        """Price to close for 50% profit."""
        if self.entry_credit is None:
            return None
        return self.entry_credit * 0.50
    
    @property
    def stop_loss_price(self) -> Optional[float]:
        """Price to close for 1.5x stop loss."""
        if self.entry_credit is None:
            return None
        return self.entry_credit * 1.5
    
    @property
    def breakeven_low(self) -> float:
        """Lower breakeven price."""
        credit = self.entry_credit or 0
        return self.short_put_strike - credit
    
    @property
    def breakeven_high(self) -> float:
        """Upper breakeven price."""
        credit = self.entry_credit or 0
        return self.short_call_strike + credit
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage/API."""
        return {
            "id": self.id,
            "underlying": self.underlying,
            "expiration": str(self.expiration) if self.expiration else None,
            "dte": self.dte,
            "contracts": self.contracts,
            "status": self.status.value,
            "short_put": self.short_put_strike,
            "long_put": self.long_put_strike,
            "short_call": self.short_call_strike,
            "long_call": self.long_call_strike,
            "wing_width": self.wing_width,
            "entry_credit": self.entry_credit,
            "total_credit": self.total_credit,
            "max_loss": self.max_loss,
            "entry_vix": self.entry_vix,
            "entry_iv_rank": self.entry_iv_rank,
            "entry_time": self.entry_time.isoformat() if self.entry_time else None,
            "entry_delta": self.entry_delta,
            "current_delta": self.current_delta,
            "current_gamma": self.current_gamma,
            "unrealized_pnl": self.unrealized_pnl,
            "unrealized_pnl_pct": self.unrealized_pnl_pct,
            "exit_time": self.exit_time.isoformat() if self.exit_time else None,
            "exit_reason": self.exit_reason.value if self.exit_reason else None,
            "realized_pnl": self.realized_pnl,
        }


# =============================================================================
# ENTRY SIGNAL
# =============================================================================

@dataclass
class ICEntrySignal:
    """Validated entry signal ready for execution."""
    underlying: str
    expiration: date
    
    # Strikes
    short_put_strike: float
    long_put_strike: float
    short_call_strike: float
    long_call_strike: float
    wing_width: float
    
    # Sizing
    quantity: int
    vix_multiplier: float
    
    # Validated Greeks
    short_put_delta: float
    short_call_delta: float
    
    # Market data at signal
    spot_price: float
    vix_value: float
    iv_rank: float
    
    # Expected values
    estimated_credit: float
    max_risk: float
    
    # Metadata
    signal_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    gate_results: List[Dict] = field(default_factory=list)
    
    @property
    def credit_pct_of_width(self) -> float:
        """Credit as percentage of spread width."""
        if self.wing_width <= 0:
            return 0
        return (self.estimated_credit / self.wing_width) * 100
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "underlying": self.underlying,
            "expiration": str(self.expiration),
            "short_put": self.short_put_strike,
            "long_put": self.long_put_strike,
            "short_call": self.short_call_strike,
            "long_call": self.long_call_strike,
            "quantity": self.quantity,
            "short_put_delta": self.short_put_delta,
            "short_call_delta": self.short_call_delta,
            "spot_price": self.spot_price,
            "vix": self.vix_value,
            "iv_rank": self.iv_rank,
            "estimated_credit": self.estimated_credit,
            "credit_pct": self.credit_pct_of_width,
        }


# =============================================================================
# EXIT SIGNAL
# =============================================================================

@dataclass
class ICExitSignal:
    """Signal to exit an Iron Condor position."""
    position_id: int
    reason: ICCloseReason
    urgency: str  # LOW, MEDIUM, HIGH, CRITICAL
    
    # Current state
    current_pnl: float
    current_pnl_pct: float
    current_delta: Optional[float] = None
    current_gamma: Optional[float] = None
    dte: int = 0
    
    # Details
    message: str = ""
    signal_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "position_id": self.position_id,
            "reason": self.reason.value,
            "urgency": self.urgency,
            "current_pnl": self.current_pnl,
            "current_pnl_pct": self.current_pnl_pct,
            "current_delta": self.current_delta,
            "dte": self.dte,
            "message": self.message,
        }


# =============================================================================
# GREEKS SNAPSHOT
# =============================================================================

@dataclass
class GreeksSnapshot:
    """Greeks for a position at a point in time."""
    timestamp: datetime
    
    # Position Greeks (net)
    delta: float
    gamma: float
    theta: float
    vega: float
    
    # Individual leg Greeks
    short_put_delta: Optional[float] = None
    short_call_delta: Optional[float] = None
    short_put_gamma: Optional[float] = None
    short_call_gamma: Optional[float] = None
    
    # IV data
    iv_value: Optional[float] = None
    iv_rank: Optional[float] = None
