"""
Trading Hours Filter
Enforces market hours constraints for the Velocity strategy.
Only allows trading during regular market hours: 9:30 AM - 4:00 PM ET.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, date, time, timedelta, timezone
from typing import Optional, Tuple
from enum import Enum

logger = logging.getLogger(__name__)


class MarketSession(Enum):
    """Market session states."""
    PRE_MARKET = "pre_market"       # 4:00 AM - 9:30 AM ET
    REGULAR = "regular"              # 9:30 AM - 4:00 PM ET
    AFTER_HOURS = "after_hours"      # 4:00 PM - 8:00 PM ET
    CLOSED = "closed"                # Outside all sessions
    WEEKEND = "weekend"              # Saturday/Sunday
    HOLIDAY = "holiday"              # Market holiday


@dataclass
class TradingHoursStatus:
    """Current trading hours status."""
    session: MarketSession
    is_trading_allowed: bool
    current_time_et: datetime
    market_open_time: Optional[datetime] = None
    market_close_time: Optional[datetime] = None
    minutes_until_open: Optional[int] = None
    minutes_until_close: Optional[int] = None
    message: str = ""


# Market hours (Eastern Time)
MARKET_OPEN = time(9, 30)
MARKET_CLOSE = time(16, 0)
PRE_MARKET_OPEN = time(4, 0)
AFTER_HOURS_CLOSE = time(20, 0)

# US Market Holidays 2025-2026
# Markets closed entirely on these dates
MARKET_HOLIDAYS = {
    # 2025
    date(2025, 1, 1),    # New Year's Day
    date(2025, 1, 20),   # MLK Day
    date(2025, 2, 17),   # Presidents Day
    date(2025, 4, 18),   # Good Friday
    date(2025, 5, 26),   # Memorial Day
    date(2025, 6, 19),   # Juneteenth
    date(2025, 7, 4),    # Independence Day
    date(2025, 9, 1),    # Labor Day
    date(2025, 11, 27),  # Thanksgiving
    date(2025, 12, 25),  # Christmas
    
    # 2026
    date(2026, 1, 1),    # New Year's Day
    date(2026, 1, 19),   # MLK Day
    date(2026, 2, 16),   # Presidents Day
    date(2026, 4, 3),    # Good Friday
    date(2026, 5, 25),   # Memorial Day
    date(2026, 6, 19),   # Juneteenth
    date(2026, 7, 3),    # Independence Day (observed)
    date(2026, 9, 7),    # Labor Day
    date(2026, 11, 26),  # Thanksgiving
    date(2026, 12, 25),  # Christmas
}

# Early close days (1:00 PM ET close)
EARLY_CLOSE_DAYS = {
    # 2025
    date(2025, 7, 3),    # Day before Independence Day
    date(2025, 11, 28),  # Day after Thanksgiving
    date(2025, 12, 24),  # Christmas Eve
    
    # 2026
    date(2026, 11, 27),  # Day after Thanksgiving
    date(2026, 12, 24),  # Christmas Eve
}


def _utc_to_et(utc_time: datetime) -> datetime:
    """
    Convert UTC time to Eastern Time.
    
    Note: This is a simplified conversion assuming EST (UTC-5).
    Production should use pytz or zoneinfo for proper DST handling.
    """
    # Simple offset - production code should handle DST
    # EST = UTC-5, EDT = UTC-4
    # For simplicity, using UTC-5 (adjust for DST in production)
    
    # Check if we're in DST (roughly March-November)
    month = utc_time.month
    if 3 <= month <= 11:
        # EDT: UTC-4
        offset = timedelta(hours=-4)
    else:
        # EST: UTC-5
        offset = timedelta(hours=-5)
    
    return utc_time + offset


def _et_to_utc(et_time: datetime) -> datetime:
    """Convert Eastern Time to UTC."""
    month = et_time.month
    if 3 <= month <= 11:
        offset = timedelta(hours=4)
    else:
        offset = timedelta(hours=5)
    
    return et_time + offset


def is_market_holiday(check_date: date) -> bool:
    """Check if date is a market holiday."""
    return check_date in MARKET_HOLIDAYS


def is_early_close(check_date: date) -> bool:
    """Check if date is an early close day."""
    return check_date in EARLY_CLOSE_DAYS


def get_market_close_time(check_date: date) -> time:
    """Get market close time for a specific date."""
    if is_early_close(check_date):
        return time(13, 0)  # 1:00 PM ET
    return MARKET_CLOSE


def get_market_session(
    check_time: Optional[datetime] = None
) -> MarketSession:
    """
    Determine current market session.
    
    Args:
        check_time: UTC time to check (defaults to now).
        
    Returns:
        MarketSession enum value.
    """
    if check_time is None:
        check_time = datetime.now(timezone.utc)
    
    # Convert to Eastern Time
    et_time = _utc_to_et(check_time)
    current_date = et_time.date()
    current_time = et_time.time()
    
    # Check weekend
    if current_date.weekday() >= 5:  # Saturday = 5, Sunday = 6
        return MarketSession.WEEKEND
    
    # Check holiday
    if is_market_holiday(current_date):
        return MarketSession.HOLIDAY
    
    # Get close time (might be early close)
    close_time = get_market_close_time(current_date)
    
    # Determine session
    if current_time < PRE_MARKET_OPEN:
        return MarketSession.CLOSED
    elif current_time < MARKET_OPEN:
        return MarketSession.PRE_MARKET
    elif current_time < close_time:
        return MarketSession.REGULAR
    elif current_time < AFTER_HOURS_CLOSE:
        return MarketSession.AFTER_HOURS
    else:
        return MarketSession.CLOSED


def check_trading_hours(
    check_time: Optional[datetime] = None,
    allow_extended: bool = False
) -> TradingHoursStatus:
    """
    Check if trading is allowed at the given time.
    
    Args:
        check_time: UTC time to check (defaults to now).
        allow_extended: If True, allow pre-market and after-hours trading.
        
    Returns:
        TradingHoursStatus with full details.
    """
    if check_time is None:
        check_time = datetime.now(timezone.utc)
    
    # Convert to Eastern Time
    et_time = _utc_to_et(check_time)
    current_date = et_time.date()
    current_time = et_time.time()
    
    session = get_market_session(check_time)
    
    # Determine if trading allowed
    if allow_extended:
        allowed_sessions = {
            MarketSession.PRE_MARKET,
            MarketSession.REGULAR,
            MarketSession.AFTER_HOURS
        }
    else:
        allowed_sessions = {MarketSession.REGULAR}
    
    is_allowed = session in allowed_sessions
    
    # Calculate market times for today
    close_time = get_market_close_time(current_date)
    
    market_open_dt = datetime.combine(current_date, MARKET_OPEN)
    market_close_dt = datetime.combine(current_date, close_time)
    
    # Calculate minutes until open/close
    current_dt = datetime.combine(current_date, current_time)
    
    if session in {MarketSession.CLOSED, MarketSession.PRE_MARKET}:
        minutes_until_open = int((market_open_dt - current_dt).total_seconds() / 60)
        if minutes_until_open < 0:
            # Next trading day
            minutes_until_open = None
    else:
        minutes_until_open = None
    
    if session == MarketSession.REGULAR:
        minutes_until_close = int((market_close_dt - current_dt).total_seconds() / 60)
    else:
        minutes_until_close = None
    
    # Build status message
    if session == MarketSession.REGULAR:
        message = f"Market OPEN - {minutes_until_close} min until close"
    elif session == MarketSession.PRE_MARKET:
        message = f"Pre-market - {minutes_until_open} min until regular session"
    elif session == MarketSession.AFTER_HOURS:
        message = "After hours - trading outside regular session"
    elif session == MarketSession.WEEKEND:
        message = "Market closed - Weekend"
    elif session == MarketSession.HOLIDAY:
        message = "Market closed - Holiday"
    else:
        if minutes_until_open:
            message = f"Market closed - Opens in {minutes_until_open} min"
        else:
            message = "Market closed"
    
    if not is_allowed:
        logger.debug(f"Trading not allowed: {message}")
    
    return TradingHoursStatus(
        session=session,
        is_trading_allowed=is_allowed,
        current_time_et=et_time,
        market_open_time=market_open_dt,
        market_close_time=market_close_dt,
        minutes_until_open=minutes_until_open,
        minutes_until_close=minutes_until_close,
        message=message
    )


def is_regular_hours(check_time: Optional[datetime] = None) -> bool:
    """Quick check if we're in regular trading hours."""
    session = get_market_session(check_time)
    return session == MarketSession.REGULAR


def minutes_until_market_open(check_time: Optional[datetime] = None) -> Optional[int]:
    """Get minutes until market opens. Returns None if market is open."""
    status = check_trading_hours(check_time)
    return status.minutes_until_open


def minutes_until_market_close(check_time: Optional[datetime] = None) -> Optional[int]:
    """Get minutes until market closes. Returns None if market is closed."""
    status = check_trading_hours(check_time)
    return status.minutes_until_close


class TradingHoursFilter:
    """
    Trading hours filter for integration with strategy engine.
    
    Enforces market hours constraints and provides convenience methods.
    """
    
    def __init__(
        self,
        allow_extended: bool = False,
        buffer_minutes_open: int = 5,
        buffer_minutes_close: int = 15
    ):
        """
        Initialize trading hours filter.
        
        Args:
            allow_extended: Allow pre/after market trading.
            buffer_minutes_open: Minutes after open before trading.
            buffer_minutes_close: Minutes before close to stop new entries.
        """
        self.allow_extended = allow_extended
        self.buffer_minutes_open = buffer_minutes_open
        self.buffer_minutes_close = buffer_minutes_close
        
        self._last_status: Optional[TradingHoursStatus] = None
    
    def allows_trading(self, check_time: Optional[datetime] = None) -> bool:
        """
        Check if trading is currently allowed.
        
        Applies buffers around market open/close.
        
        Args:
            check_time: UTC time to check (defaults to now).
            
        Returns:
            True if trading is allowed.
        """
        status = check_trading_hours(check_time, self.allow_extended)
        self._last_status = status
        
        if not status.is_trading_allowed:
            return False
        
        # Apply buffers for regular session
        if status.session == MarketSession.REGULAR:
            # Check open buffer
            if status.minutes_until_close is not None:
                # Calculate minutes since open
                # Close in X minutes means we've been open for (total_session - X) minutes
                total_session = 390  # 6.5 hours in minutes
                minutes_since_open = total_session - status.minutes_until_close
                
                if minutes_since_open < self.buffer_minutes_open:
                    logger.debug(
                        f"Within open buffer ({minutes_since_open} min since open)"
                    )
                    return False
            
            # Check close buffer
            if status.minutes_until_close is not None:
                if status.minutes_until_close < self.buffer_minutes_close:
                    logger.debug(
                        f"Within close buffer ({status.minutes_until_close} min to close)"
                    )
                    return False
        
        return True
    
    def allows_new_entries(self, check_time: Optional[datetime] = None) -> bool:
        """
        Check if new position entries are allowed.
        
        More restrictive than allows_trading - adds extra buffer before close.
        """
        if not self.allows_trading(check_time):
            return False
        
        status = self._last_status
        
        if status and status.minutes_until_close is not None:
            # Don't enter new positions in last 30 minutes
            if status.minutes_until_close < 30:
                logger.debug("New entries blocked - too close to market close")
                return False
        
        return True
    
    def allows_exits(self, check_time: Optional[datetime] = None) -> bool:
        """
        Check if position exits are allowed.
        
        Less restrictive - allows exits until market close.
        """
        status = check_trading_hours(check_time, self.allow_extended)
        self._last_status = status
        return status.is_trading_allowed
    
    def get_status(self, check_time: Optional[datetime] = None) -> TradingHoursStatus:
        """Get full trading hours status."""
        status = check_trading_hours(check_time, self.allow_extended)
        self._last_status = status
        return status
    
    def is_holiday(self, check_date: Optional[date] = None) -> bool:
        """Check if date is a market holiday."""
        if check_date is None:
            check_date = date.today()
        return is_market_holiday(check_date)
    
    def is_early_close(self, check_date: Optional[date] = None) -> bool:
        """Check if date is an early close day."""
        if check_date is None:
            check_date = date.today()
        return is_early_close(check_date)
    
    def get_session(self, check_time: Optional[datetime] = None) -> MarketSession:
        """Get current market session."""
        return get_market_session(check_time)
