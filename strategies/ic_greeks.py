"""
Iron Condor Greeks Pipeline — Ported from Loveable
Fetches and tracks Greeks from IBKR for entry validation and exit monitoring.
"""

import logging
from datetime import datetime, date, timezone
from typing import Optional, Dict, List, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class OptionGreeks:
    """Greeks for a single option."""
    delta: float
    gamma: float
    theta: float
    vega: float
    iv: float  # Implied volatility
    
    def __post_init__(self):
        """Ensure all values are floats."""
        self.delta = float(self.delta) if self.delta else 0.0
        self.gamma = float(self.gamma) if self.gamma else 0.0
        self.theta = float(self.theta) if self.theta else 0.0
        self.vega = float(self.vega) if self.vega else 0.0
        self.iv = float(self.iv) if self.iv else 0.0


@dataclass
class ICGreeks:
    """Aggregated Greeks for an Iron Condor position."""
    # Net position Greeks (short adds, long subtracts for IC)
    net_delta: float
    net_gamma: float
    net_theta: float
    net_vega: float
    
    # Individual leg Greeks
    short_put_delta: float
    long_put_delta: float
    short_call_delta: float
    long_call_delta: float
    
    short_put_gamma: float
    short_call_gamma: float
    
    # IV at position level
    avg_iv: float
    
    # Timestamp
    updated_at: datetime
    
    def to_dict(self) -> dict:
        """Convert to dictionary for storage."""
        return {
            "net_delta": self.net_delta,
            "net_gamma": self.net_gamma,
            "net_theta": self.net_theta,
            "net_vega": self.net_vega,
            "short_put_delta": self.short_put_delta,
            "long_put_delta": self.long_put_delta,
            "short_call_delta": self.short_call_delta,
            "long_call_delta": self.long_call_delta,
            "short_put_gamma": self.short_put_gamma,
            "short_call_gamma": self.short_call_gamma,
            "avg_iv": self.avg_iv,
            "updated_at": self.updated_at.isoformat(),
        }


class ICGreeksFetcher:
    """
    Fetches Greeks from IBKR for Iron Condor positions.
    
    Used for:
    1. Entry validation (delta < 0.18)
    2. Exit monitoring (delta >= 0.25, gamma > 0.05)
    3. IV expansion tracking
    """
    
    def __init__(self, ib_connection):
        """
        Initialize with IBKR connection.
        
        Args:
            ib_connection: Connected ib_insync.IB instance
        """
        self.ib = ib_connection
    
    def fetch_option_greeks(
        self,
        symbol: str,
        expiration: date,
        strike: float,
        right: str  # 'C' or 'P'
    ) -> Optional[OptionGreeks]:
        """
        Fetch Greeks for a single option from IBKR.
        
        Args:
            symbol: Underlying symbol (SPY, SPX, etc.)
            expiration: Option expiration date
            strike: Strike price
            right: 'C' for call, 'P' for put
            
        Returns:
            OptionGreeks or None if failed
        """
        try:
            from ib_insync import Option
            
            exp_str = expiration.strftime("%Y%m%d")
            
            # Create option contract
            opt = Option(symbol, exp_str, strike, right, "SMART")
            self.ib.qualifyContracts(opt)
            
            # Request market data with Greeks
            ticker = self.ib.reqMktData(opt, "", False, False)
            self.ib.sleep(0.5)  # Wait for data
            
            # Extract Greeks from model
            if ticker.modelGreeks:
                greeks = OptionGreeks(
                    delta=ticker.modelGreeks.delta or 0.0,
                    gamma=ticker.modelGreeks.gamma or 0.0,
                    theta=ticker.modelGreeks.theta or 0.0,
                    vega=ticker.modelGreeks.vega or 0.0,
                    iv=ticker.modelGreeks.impliedVol or 0.0
                )
            else:
                # Fallback: try to get from last greeks
                greeks = OptionGreeks(
                    delta=getattr(ticker, 'delta', 0.0) or 0.0,
                    gamma=getattr(ticker, 'gamma', 0.0) or 0.0,
                    theta=getattr(ticker, 'theta', 0.0) or 0.0,
                    vega=getattr(ticker, 'vega', 0.0) or 0.0,
                    iv=getattr(ticker, 'impliedVolatility', 0.0) or 0.0
                )
            
            # Cancel market data
            self.ib.cancelMktData(opt)
            
            logger.debug(
                f"Greeks for {symbol} {expiration} {strike}{right}: "
                f"Δ={greeks.delta:.4f} Γ={greeks.gamma:.4f}"
            )
            
            return greeks
            
        except Exception as e:
            logger.error(f"Failed to fetch Greeks for {symbol} {strike}{right}: {e}")
            return None
    
    def fetch_ic_greeks(
        self,
        symbol: str,
        expiration: date,
        short_put_strike: float,
        long_put_strike: float,
        short_call_strike: float,
        long_call_strike: float
    ) -> Optional[ICGreeks]:
        """
        Fetch aggregated Greeks for full Iron Condor.
        
        Args:
            symbol: Underlying symbol
            expiration: Option expiration
            short_put_strike: Short put strike
            long_put_strike: Long put strike
            short_call_strike: Short call strike
            long_call_strike: Long call strike
            
        Returns:
            ICGreeks with aggregated position Greeks
        """
        try:
            # Fetch Greeks for all 4 legs
            short_put = self.fetch_option_greeks(symbol, expiration, short_put_strike, "P")
            long_put = self.fetch_option_greeks(symbol, expiration, long_put_strike, "P")
            short_call = self.fetch_option_greeks(symbol, expiration, short_call_strike, "C")
            long_call = self.fetch_option_greeks(symbol, expiration, long_call_strike, "C")
            
            if not all([short_put, long_put, short_call, long_call]):
                logger.error("Failed to fetch Greeks for all legs")
                return None
            
            # Calculate net Greeks
            # For Iron Condor: short positions subtract, long positions add
            # But since we're short the IC, we flip: shorts add, longs subtract
            net_delta = (
                -short_put.delta  # Short put (positive delta, we're short)
                + long_put.delta   # Long put (negative delta hedge)
                - short_call.delta # Short call (negative delta, we're short)
                + long_call.delta  # Long call (positive delta hedge)
            )
            
            net_gamma = (
                -short_put.gamma
                + long_put.gamma
                - short_call.gamma
                + long_call.gamma
            )
            
            net_theta = (
                short_put.theta   # We collect theta on shorts
                - long_put.theta
                + short_call.theta
                - long_call.theta
            )
            
            net_vega = (
                -short_put.vega   # We're short vega
                + long_put.vega
                - short_call.vega
                + long_call.vega
            )
            
            # Average IV across short strikes
            avg_iv = (short_put.iv + short_call.iv) / 2
            
            ic_greeks = ICGreeks(
                net_delta=net_delta,
                net_gamma=net_gamma,
                net_theta=net_theta,
                net_vega=net_vega,
                short_put_delta=abs(short_put.delta),  # Store absolute
                long_put_delta=abs(long_put.delta),
                short_call_delta=abs(short_call.delta),
                long_call_delta=abs(long_call.delta),
                short_put_gamma=short_put.gamma,
                short_call_gamma=short_call.gamma,
                avg_iv=avg_iv,
                updated_at=datetime.now(timezone.utc)
            )
            
            logger.info(
                f"IC Greeks: Net Δ={net_delta:.4f}, "
                f"Short Put Δ={ic_greeks.short_put_delta:.4f}, "
                f"Short Call Δ={ic_greeks.short_call_delta:.4f}"
            )
            
            return ic_greeks
            
        except Exception as e:
            logger.error(f"Failed to fetch IC Greeks: {e}")
            return None
    
    def validate_entry_delta(
        self,
        symbol: str,
        expiration: date,
        short_put_strike: float,
        short_call_strike: float,
        max_delta: float = 0.18,
        min_valid_delta: float = 0.01
    ) -> Tuple[bool, float, float]:
        """
        Validate that short strikes have acceptable delta for entry.
        
        Args:
            symbol: Underlying symbol
            expiration: Option expiration
            short_put_strike: Short put strike
            short_call_strike: Short call strike
            max_delta: Maximum acceptable delta (default 0.18)
            min_valid_delta: Minimum valid delta (below = API failure)
            
        Returns:
            Tuple of (is_valid, short_put_delta, short_call_delta)
        """
        short_put_greeks = self.fetch_option_greeks(symbol, expiration, short_put_strike, "P")
        short_call_greeks = self.fetch_option_greeks(symbol, expiration, short_call_strike, "C")
        
        if not short_put_greeks or not short_call_greeks:
            logger.error("Failed to fetch Greeks for delta validation")
            return False, 0.0, 0.0
        
        put_delta = abs(short_put_greeks.delta)
        call_delta = abs(short_call_greeks.delta)
        
        # Check for API failure (delta too small)
        if put_delta < min_valid_delta or call_delta < min_valid_delta:
            logger.warning(f"Delta too small - possible API failure: P={put_delta}, C={call_delta}")
            return False, put_delta, call_delta
        
        # Check against max entry delta
        if put_delta > max_delta or call_delta > max_delta:
            logger.info(f"Delta exceeds max: P={put_delta:.4f}, C={call_delta:.4f} > {max_delta}")
            return False, put_delta, call_delta
        
        logger.info(f"Delta validation passed: P={put_delta:.4f}, C={call_delta:.4f}")
        return True, put_delta, call_delta
    
    def check_exit_conditions(
        self,
        symbol: str,
        expiration: date,
        short_put_strike: float,
        short_call_strike: float,
        exit_delta: float = 0.25,
        gamma_threshold: float = 0.05,
        dte: int = 7
    ) -> Dict[str, any]:
        """
        Check Greeks-based exit conditions.
        
        Returns dict with:
        - should_exit: bool
        - exit_reason: str or None
        - warning: str or None
        - greeks: current Greeks values
        """
        result = {
            "should_exit": False,
            "exit_reason": None,
            "warning": None,
            "greeks": {}
        }
        
        short_put_greeks = self.fetch_option_greeks(symbol, expiration, short_put_strike, "P")
        short_call_greeks = self.fetch_option_greeks(symbol, expiration, short_call_strike, "C")
        
        if not short_put_greeks or not short_call_greeks:
            result["warning"] = "Failed to fetch Greeks"
            return result
        
        put_delta = abs(short_put_greeks.delta)
        call_delta = abs(short_call_greeks.delta)
        
        result["greeks"] = {
            "short_put_delta": put_delta,
            "short_call_delta": call_delta,
            "short_put_gamma": short_put_greeks.gamma,
            "short_call_gamma": short_call_greeks.gamma,
        }
        
        # Check delta exit (0.25)
        if put_delta >= exit_delta:
            result["should_exit"] = True
            result["exit_reason"] = "delta_exit_put"
            return result
        
        if call_delta >= exit_delta:
            result["should_exit"] = True
            result["exit_reason"] = "delta_exit_call"
            return result
        
        # Check gamma exit (only when DTE <= 5)
        if dte <= 5:
            if short_put_greeks.gamma > gamma_threshold:
                result["should_exit"] = True
                result["exit_reason"] = "gamma_exit_put"
                return result
            
            if short_call_greeks.gamma > gamma_threshold:
                result["should_exit"] = True
                result["exit_reason"] = "gamma_exit_call"
                return result
        
        # Check delta warning (0.22)
        if put_delta >= 0.22 or call_delta >= 0.22:
            result["warning"] = f"Delta warning: P={put_delta:.3f}, C={call_delta:.3f}"
        
        return result


def calculate_iv_rank(current_iv: float, high_52w: float, low_52w: float) -> float:
    """
    Calculate IV Rank from 52-week high/low.
    
    Formula: (current - low) / (high - low) * 100
    
    Returns:
        IV Rank as percentage (0-100)
    """
    if high_52w == low_52w:
        return 50.0  # Default to middle if no range
    
    iv_rank = (current_iv - low_52w) / (high_52w - low_52w) * 100
    return max(0.0, min(100.0, iv_rank))


def calculate_iv_percentile(current_iv: float, historical_ivs: List[float]) -> float:
    """
    Calculate IV Percentile from historical data.
    
    Returns:
        IV Percentile (0-100)
    """
    if not historical_ivs:
        return 50.0
    
    below_count = sum(1 for iv in historical_ivs if iv < current_iv)
    return (below_count / len(historical_ivs)) * 100
