"""
VIX Filter
Monitors VIX levels and determines market volatility regime.
Blocks trading during extreme volatility conditions.
"""

import logging
from enum import Enum
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Tuple

import yfinance as yf

logger = logging.getLogger(__name__)


class VixRegime(Enum):
    """
    VIX volatility regimes based on Velocity 2.0 thresholds.
    
    - NORMAL: VIX < 20 - Full trading allowed
    - ELEVATED: 20 <= VIX < 25 - Trading allowed with caution
    - HIGH: 25 <= VIX < 35 - Reduced position sizes
    - EXTREME: VIX >= 35 - Trading blocked
    """
    NORMAL = "normal"
    ELEVATED = "elevated"
    HIGH = "high"
    EXTREME = "extreme"
    UNKNOWN = "unknown"


@dataclass
class VixReading:
    """Current VIX data and regime classification."""
    value: float
    regime: VixRegime
    timestamp: datetime
    trading_allowed: bool
    position_size_multiplier: float
    message: str


# Threshold configuration (matching Velocity 2.0)
VIX_THRESHOLDS = {
    "normal_max": 20.0,
    "elevated_max": 25.0,
    "high_max": 35.0
}

# Position size adjustments by regime
REGIME_POSITION_MULTIPLIERS = {
    VixRegime.NORMAL: 1.0,      # Full size
    VixRegime.ELEVATED: 0.75,    # 75% size
    VixRegime.HIGH: 0.5,         # 50% size
    VixRegime.EXTREME: 0.0,      # No trading
    VixRegime.UNKNOWN: 0.0       # Safe default
}


def classify_vix_regime(vix_value: float) -> VixRegime:
    """
    Classify VIX value into regime.
    
    Args:
        vix_value: Current VIX level.
        
    Returns:
        VixRegime enum value.
    """
    if vix_value < VIX_THRESHOLDS["normal_max"]:
        return VixRegime.NORMAL
    elif vix_value < VIX_THRESHOLDS["elevated_max"]:
        return VixRegime.ELEVATED
    elif vix_value < VIX_THRESHOLDS["high_max"]:
        return VixRegime.HIGH
    else:
        return VixRegime.EXTREME


def get_vix_current() -> Optional[float]:
    """
    Fetch current VIX value from Yahoo Finance.
    
    Returns:
        Current VIX value or None if fetch fails.
    """
    try:
        vix = yf.Ticker("^VIX")
        
        # Get intraday data (1-minute, last day)
        hist = vix.history(period="1d", interval="1m")
        
        if hist.empty:
            # Fallback to daily data
            hist = vix.history(period="5d")
            
        if hist.empty:
            logger.warning("No VIX data available from Yahoo Finance")
            return None
        
        current_vix = float(hist['Close'].iloc[-1])
        logger.debug(f"VIX fetched: {current_vix:.2f}")
        
        return current_vix
        
    except Exception as e:
        logger.error(f"Failed to fetch VIX: {e}")
        return None


def check_vix() -> VixReading:
    """
    Get current VIX reading with regime classification.
    
    Returns:
        VixReading with current status and trading guidance.
    """
    vix_value = get_vix_current()
    timestamp = datetime.now(timezone.utc)
    
    if vix_value is None:
        return VixReading(
            value=0.0,
            regime=VixRegime.UNKNOWN,
            timestamp=timestamp,
            trading_allowed=False,
            position_size_multiplier=0.0,
            message="VIX data unavailable - trading blocked for safety"
        )
    
    regime = classify_vix_regime(vix_value)
    multiplier = REGIME_POSITION_MULTIPLIERS[regime]
    trading_allowed = regime not in (VixRegime.EXTREME, VixRegime.UNKNOWN)
    
    # Build status message
    if regime == VixRegime.NORMAL:
        message = f"VIX {vix_value:.2f} - Normal conditions, full trading"
    elif regime == VixRegime.ELEVATED:
        message = f"VIX {vix_value:.2f} - Elevated volatility, reduced size ({multiplier:.0%})"
    elif regime == VixRegime.HIGH:
        message = f"VIX {vix_value:.2f} - High volatility, minimal positions ({multiplier:.0%})"
    else:
        message = f"VIX {vix_value:.2f} - EXTREME volatility, trading BLOCKED"
    
    logger.info(message)
    
    return VixReading(
        value=vix_value,
        regime=regime,
        timestamp=timestamp,
        trading_allowed=trading_allowed,
        position_size_multiplier=multiplier,
        message=message
    )


def is_vix_safe(max_regime: VixRegime = VixRegime.HIGH) -> Tuple[bool, VixReading]:
    """
    Quick check if VIX allows trading.
    
    Args:
        max_regime: Maximum acceptable regime for trading.
        
    Returns:
        Tuple of (is_safe, VixReading).
    """
    reading = check_vix()
    
    regime_order = [
        VixRegime.NORMAL,
        VixRegime.ELEVATED,
        VixRegime.HIGH,
        VixRegime.EXTREME
    ]
    
    try:
        current_idx = regime_order.index(reading.regime)
        max_idx = regime_order.index(max_regime)
        is_safe = current_idx <= max_idx
    except ValueError:
        # UNKNOWN regime
        is_safe = False
    
    return is_safe, reading


class VixFilter:
    """
    VIX filter class for integration with strategy engine.
    
    Caches VIX readings to avoid excessive API calls.
    """
    
    def __init__(self, cache_seconds: int = 60):
        """
        Initialize VIX filter.
        
        Args:
            cache_seconds: How long to cache VIX readings.
        """
        self.cache_seconds = cache_seconds
        self._cached_reading: Optional[VixReading] = None
        self._cache_time: Optional[datetime] = None
    
    def get_reading(self, force_refresh: bool = False) -> VixReading:
        """
        Get VIX reading, using cache if available.
        
        Args:
            force_refresh: Force fresh fetch ignoring cache.
            
        Returns:
            VixReading with current status.
        """
        now = datetime.now(timezone.utc)
        
        # Check cache validity
        if (
            not force_refresh
            and self._cached_reading is not None
            and self._cache_time is not None
        ):
            cache_age = (now - self._cache_time).total_seconds()
            if cache_age < self.cache_seconds:
                logger.debug(f"Using cached VIX reading (age: {cache_age:.0f}s)")
                return self._cached_reading
        
        # Fetch fresh reading
        reading = check_vix()
        self._cached_reading = reading
        self._cache_time = now
        
        return reading
    
    def allows_trading(self, max_regime: VixRegime = VixRegime.HIGH) -> bool:
        """
        Check if current VIX allows trading.
        
        Args:
            max_regime: Maximum acceptable regime.
            
        Returns:
            True if trading allowed.
        """
        reading = self.get_reading()
        
        if reading.regime == VixRegime.UNKNOWN:
            return False
        
        regime_order = [
            VixRegime.NORMAL,
            VixRegime.ELEVATED,
            VixRegime.HIGH,
            VixRegime.EXTREME
        ]
        
        try:
            current_idx = regime_order.index(reading.regime)
            max_idx = regime_order.index(max_regime)
            return current_idx <= max_idx
        except ValueError:
            return False
    
    def get_position_multiplier(self) -> float:
        """
        Get position size multiplier for current VIX regime.
        
        Returns:
            Multiplier between 0.0 and 1.0.
        """
        reading = self.get_reading()
        return reading.position_size_multiplier
    
    def clear_cache(self) -> None:
        """Clear cached VIX reading."""
        self._cached_reading = None
        self._cache_time = None
        logger.debug("VIX cache cleared")
