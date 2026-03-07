"""
Filters Package
Trading filters for VIX, events, and market hours.
"""

from filters.vix_filter import (
    VixFilter,
    VixRegime,
    VixReading,
    check_vix,
    get_vix_current,
    is_vix_safe,
    classify_vix_regime
)

from filters.event_calendar import (
    EventCalendarFilter,
    EventType,
    EventImpact,
    MarketEvent,
    EventCheckResult,
    check_events,
    get_events_for_date,
    get_next_event
)

from filters.trading_hours import (
    TradingHoursFilter,
    MarketSession,
    TradingHoursStatus,
    check_trading_hours,
    is_regular_hours,
    is_market_holiday,
    is_early_close,
    minutes_until_market_open,
    minutes_until_market_close
)

__all__ = [
    # VIX
    "VixFilter",
    "VixRegime",
    "VixReading",
    "check_vix",
    "get_vix_current",
    "is_vix_safe",
    "classify_vix_regime",
    
    # Events
    "EventCalendarFilter",
    "EventType",
    "EventImpact",
    "MarketEvent",
    "EventCheckResult",
    "check_events",
    "get_events_for_date",
    "get_next_event",
    
    # Trading Hours
    "TradingHoursFilter",
    "MarketSession",
    "TradingHoursStatus",
    "check_trading_hours",
    "is_regular_hours",
    "is_market_holiday",
    "is_early_close",
    "minutes_until_market_open",
    "minutes_until_market_close"
]
