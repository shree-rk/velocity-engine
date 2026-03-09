"""
Iron Condor Data Models
"""

from dataclasses import dataclass, field
from datetime import datetime, date
from enum import Enum
from typing import Optional, List


class OptionType(Enum):
    """Option type."""
    CALL = "CALL"
    PUT = "PUT"


class ICStatus(Enum):
    """Iron Condor position status."""
    PENDING = "PENDING"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    EXPIRED = "EXPIRED"
    STOPPED = "STOPPED"


class ICCloseReason(Enum):
    """Reason for closing IC."""
    PROFIT_TARGET = "PROFIT_TARGET"
    STOP_LOSS = "STOP_LOSS"
    DTE_EXIT = "DTE_EXIT"
    MANUAL = "MANUAL"
    EXPIRED = "EXPIRED"
    ADJUSTMENT = "ADJUSTMENT"


@dataclass
class OptionContract:
    """Single option contract."""
    symbol: str  # e.g., "SPY"
    expiration: date
    strike: float
    option_type: OptionType
    
    # Greeks (optional, populated from broker)
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
    
    @property
    def option_symbol(self) -> str:
        """Generate OCC option symbol."""
        # Format: SPY240315C00500000 (SPY March 15 2024 $500 Call)
        exp_str = self.expiration.strftime("%y%m%d")
        opt_type = "C" if self.option_type == OptionType.CALL else "P"
        strike_str = f"{int(self.strike * 1000):08d}"
        return f"{self.symbol}{exp_str}{opt_type}{strike_str}"


@dataclass
class VerticalSpread:
    """Vertical spread (part of Iron Condor)."""
    short_leg: OptionContract
    long_leg: OptionContract
    
    @property
    def width(self) -> float:
        """Spread width."""
        return abs(self.short_leg.strike - self.long_leg.strike)
    
    @property
    def is_put_spread(self) -> bool:
        """Is this a put spread."""
        return self.short_leg.option_type == OptionType.PUT
    
    @property
    def is_call_spread(self) -> bool:
        """Is this a call spread."""
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
        """Delta of short leg."""
        return self.short_leg.delta


@dataclass
class IronCondor:
    """Complete Iron Condor position."""
    id: Optional[int] = None
    underlying: str = ""
    expiration: date = None
    
    # The spreads
    put_spread: VerticalSpread = None
    call_spread: VerticalSpread = None
    
    # Position info
    contracts: int = 1
    status: ICStatus = ICStatus.PENDING
    
    # Entry details
    entry_time: Optional[datetime] = None
    entry_credit: Optional[float] = None  # Total credit per contract
    entry_vix: Optional[float] = None
    
    # Exit details
    exit_time: Optional[datetime] = None
    exit_debit: Optional[float] = None
    close_reason: Optional[ICCloseReason] = None
    
    # P&L
    realized_pnl: Optional[float] = None
    
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
    def total_credit(self) -> Optional[float]:
        """Total credit received."""
        if self.entry_credit:
            return self.entry_credit * self.contracts * 100
        
        put_credit = self.put_spread.credit if self.put_spread else 0
        call_credit = self.call_spread.credit if self.call_spread else 0
        
        if put_credit is None or call_credit is None:
            return None
        
        return (put_credit + call_credit) * self.contracts * 100
    
    @property
    def max_profit(self) -> Optional[float]:
        """Maximum profit (credit received)."""
        return self.total_credit
    
    @property
    def max_loss(self) -> float:
        """Maximum loss."""
        put_width = self.put_spread.width if self.put_spread else 0
        call_width = self.call_spread.width if self.call_spread else 0
        max_width = max(put_width, call_width)
        
        credit_per_contract = self.entry_credit or 0
        
        return (max_width - credit_per_contract) * self.contracts * 100
    
    @property
    def profit_target_price(self) -> Optional[float]:
        """Price to close for 50% profit."""
        if self.entry_credit is None:
            return None
        return self.entry_credit * 0.50
    
    @property
    def stop_loss_price(self) -> Optional[float]:
        """Price to close for stop loss (2x credit)."""
        if self.entry_credit is None:
            return None
        return self.entry_credit * 2.0
    
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
    
    @property
    def current_pnl(self) -> Optional[float]:
        """Current unrealized P&L."""
        if self.status == ICStatus.CLOSED:
            return self.realized_pnl
        # Would need current prices to calculate
        return None
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
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
            "entry_credit": self.entry_credit,
            "total_credit": self.total_credit,
            "max_loss": self.max_loss,
            "entry_vix": self.entry_vix,
            "entry_time": self.entry_time.isoformat() if self.entry_time else None,
            "exit_time": self.exit_time.isoformat() if self.exit_time else None,
            "close_reason": self.close_reason.value if self.close_reason else None,
            "realized_pnl": self.realized_pnl,
        }


@dataclass
class ICSignal:
    """Signal to open an Iron Condor."""
    underlying: str
    expiration: date
    
    # Strikes
    short_put_strike: float
    long_put_strike: float
    short_call_strike: float
    long_call_strike: float
    
    # Expected values
    expected_credit: float
    expected_max_loss: float
    
    # Greeks at signal time
    short_put_delta: float
    short_call_delta: float
    
    # Context
    underlying_price: float
    vix_at_signal: float
    signal_time: datetime = field(default_factory=lambda: datetime.now())
    
    # Sizing
    recommended_contracts: int = 1
    
    @property
    def risk_reward_ratio(self) -> float:
        """Risk to reward ratio."""
        if self.expected_credit == 0:
            return float('inf')
        return self.expected_max_loss / (self.expected_credit * 100)
    
    @property
    def credit_pct_of_width(self) -> float:
        """Credit as percentage of spread width."""
        width = self.short_put_strike - self.long_put_strike
        return self.expected_credit / width if width > 0 else 0
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "underlying": self.underlying,
            "expiration": str(self.expiration),
            "short_put": self.short_put_strike,
            "long_put": self.long_put_strike,
            "short_call": self.short_call_strike,
            "long_call": self.long_call_strike,
            "expected_credit": self.expected_credit,
            "expected_max_loss": self.expected_max_loss,
            "short_put_delta": self.short_put_delta,
            "short_call_delta": self.short_call_delta,
            "underlying_price": self.underlying_price,
            "vix": self.vix_at_signal,
            "recommended_contracts": self.recommended_contracts,
            "credit_pct": self.credit_pct_of_width,
        }
