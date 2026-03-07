"""
Event Calendar Filter
Blocks trading during high-impact market events.
Covers FOMC, CPI, NFP, and Quad Witching dates.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, date, time, timedelta, timezone
from typing import Optional, List, Tuple
from enum import Enum

logger = logging.getLogger(__name__)


class EventType(Enum):
    """Types of market-moving events."""
    FOMC = "fomc"           # Federal Reserve meetings
    CPI = "cpi"             # Consumer Price Index
    NFP = "nfp"             # Non-Farm Payrolls
    QUAD_WITCH = "quad_witch"  # Quadruple witching
    EARNINGS = "earnings"    # Major earnings (future use)
    CUSTOM = "custom"        # User-defined events


class EventImpact(Enum):
    """Impact level of events."""
    HIGH = "high"       # Block all trading
    MEDIUM = "medium"   # Block entries, allow exits
    LOW = "low"         # Trading allowed with caution


@dataclass
class MarketEvent:
    """A market event that may affect trading."""
    event_type: EventType
    event_date: date
    description: str
    impact: EventImpact
    block_before_hours: int = 0  # Hours to block before event
    block_after_hours: int = 2   # Hours to block after event
    event_time: Optional[time] = None  # Specific time if known


@dataclass
class EventCheckResult:
    """Result of checking if trading is blocked by events."""
    is_blocked: bool
    blocking_event: Optional[MarketEvent] = None
    upcoming_events: List[MarketEvent] = None
    message: str = ""
    
    def __post_init__(self):
        if self.upcoming_events is None:
            self.upcoming_events = []


# ============================================================================
# 2025-2026 Event Calendars
# ============================================================================

# FOMC Meeting Dates (announcement typically at 2:00 PM ET)
FOMC_DATES_2025 = [
    date(2025, 1, 29),
    date(2025, 3, 19),
    date(2025, 5, 7),
    date(2025, 6, 18),
    date(2025, 7, 30),
    date(2025, 9, 17),
    date(2025, 11, 5),
    date(2025, 12, 17),
]

FOMC_DATES_2026 = [
    date(2026, 1, 28),
    date(2026, 3, 18),
    date(2026, 4, 29),
    date(2026, 6, 17),
    date(2026, 7, 29),
    date(2026, 9, 16),
    date(2026, 11, 4),
    date(2026, 12, 16),
]

# CPI Release Dates (8:30 AM ET typically)
CPI_DATES_2025 = [
    date(2025, 1, 15),
    date(2025, 2, 12),
    date(2025, 3, 12),
    date(2025, 4, 10),
    date(2025, 5, 13),
    date(2025, 6, 11),
    date(2025, 7, 11),
    date(2025, 8, 12),
    date(2025, 9, 10),
    date(2025, 10, 10),
    date(2025, 11, 13),
    date(2025, 12, 10),
]

CPI_DATES_2026 = [
    date(2026, 1, 14),
    date(2026, 2, 11),
    date(2026, 3, 11),
    date(2026, 4, 14),
    date(2026, 5, 12),
    date(2026, 6, 10),
    date(2026, 7, 14),
    date(2026, 8, 12),
    date(2026, 9, 15),
    date(2026, 10, 13),
    date(2026, 11, 12),
    date(2026, 12, 10),
]

# Non-Farm Payrolls (First Friday of month, 8:30 AM ET)
NFP_DATES_2025 = [
    date(2025, 1, 10),
    date(2025, 2, 7),
    date(2025, 3, 7),
    date(2025, 4, 4),
    date(2025, 5, 2),
    date(2025, 6, 6),
    date(2025, 7, 3),
    date(2025, 8, 1),
    date(2025, 9, 5),
    date(2025, 10, 3),
    date(2025, 11, 7),
    date(2025, 12, 5),
]

NFP_DATES_2026 = [
    date(2026, 1, 9),
    date(2026, 2, 6),
    date(2026, 3, 6),
    date(2026, 4, 3),
    date(2026, 5, 1),
    date(2026, 6, 5),
    date(2026, 7, 2),
    date(2026, 8, 7),
    date(2026, 9, 4),
    date(2026, 10, 2),
    date(2026, 11, 6),
    date(2026, 12, 4),
]

# Quad Witching (Third Friday of March, June, September, December)
QUAD_WITCH_DATES_2025 = [
    date(2025, 3, 21),
    date(2025, 6, 20),
    date(2025, 9, 19),
    date(2025, 12, 19),
]

QUAD_WITCH_DATES_2026 = [
    date(2026, 3, 20),
    date(2026, 6, 19),
    date(2026, 9, 18),
    date(2026, 12, 18),
]


def _build_event_list() -> List[MarketEvent]:
    """Build complete list of market events."""
    events = []
    
    # FOMC events - block 2 hours before, 2 hours after
    for d in FOMC_DATES_2025 + FOMC_DATES_2026:
        events.append(MarketEvent(
            event_type=EventType.FOMC,
            event_date=d,
            description=f"FOMC Meeting - {d.strftime('%b %d, %Y')}",
            impact=EventImpact.HIGH,
            block_before_hours=2,
            block_after_hours=2,
            event_time=time(14, 0)  # 2:00 PM ET
        ))
    
    # CPI events - block 1 hour before, 2 hours after
    for d in CPI_DATES_2025 + CPI_DATES_2026:
        events.append(MarketEvent(
            event_type=EventType.CPI,
            event_date=d,
            description=f"CPI Release - {d.strftime('%b %d, %Y')}",
            impact=EventImpact.HIGH,
            block_before_hours=1,
            block_after_hours=2,
            event_time=time(8, 30)  # 8:30 AM ET
        ))
    
    # NFP events - block 1 hour before, 2 hours after
    for d in NFP_DATES_2025 + NFP_DATES_2026:
        events.append(MarketEvent(
            event_type=EventType.NFP,
            event_date=d,
            description=f"Non-Farm Payrolls - {d.strftime('%b %d, %Y')}",
            impact=EventImpact.HIGH,
            block_before_hours=1,
            block_after_hours=2,
            event_time=time(8, 30)  # 8:30 AM ET
        ))
    
    # Quad Witching - block entire day
    for d in QUAD_WITCH_DATES_2025 + QUAD_WITCH_DATES_2026:
        events.append(MarketEvent(
            event_type=EventType.QUAD_WITCH,
            event_date=d,
            description=f"Quad Witching - {d.strftime('%b %d, %Y')}",
            impact=EventImpact.HIGH,
            block_before_hours=24,  # Block from previous day
            block_after_hours=0,
            event_time=None  # All day
        ))
    
    return sorted(events, key=lambda e: e.event_date)


# Pre-built event list
ALL_EVENTS = _build_event_list()


def is_event_active(
    event: MarketEvent,
    check_time: Optional[datetime] = None
) -> bool:
    """
    Check if an event is currently blocking trading.
    
    Args:
        event: The market event to check.
        check_time: Time to check (defaults to now).
        
    Returns:
        True if event is currently blocking trading.
    """
    if check_time is None:
        check_time = datetime.now(timezone.utc)
    
    # Convert to Eastern time for market events
    # Simplified: assume UTC-5 (EST) - production should use pytz
    et_offset = timedelta(hours=-5)
    check_time_et = check_time + et_offset
    
    # Build event datetime
    if event.event_time:
        event_dt = datetime.combine(event.event_date, event.event_time)
    else:
        # All-day events: use market open (9:30 AM)
        event_dt = datetime.combine(event.event_date, time(9, 30))
    
    # Calculate blocking window
    block_start = event_dt - timedelta(hours=event.block_before_hours)
    block_end = event_dt + timedelta(hours=event.block_after_hours)
    
    # Check if current time is in blocking window
    check_naive = check_time_et.replace(tzinfo=None)
    
    return block_start <= check_naive <= block_end


def check_events(
    check_time: Optional[datetime] = None,
    lookahead_hours: int = 4
) -> EventCheckResult:
    """
    Check if any events are blocking trading.
    
    Args:
        check_time: Time to check (defaults to now).
        lookahead_hours: Hours to look ahead for upcoming events.
        
    Returns:
        EventCheckResult with blocking status and details.
    """
    if check_time is None:
        check_time = datetime.now(timezone.utc)
    
    # Check for active blocking events
    for event in ALL_EVENTS:
        if is_event_active(event, check_time):
            logger.warning(f"Trading blocked: {event.description}")
            return EventCheckResult(
                is_blocked=True,
                blocking_event=event,
                message=f"Trading blocked: {event.description}"
            )
    
    # Find upcoming events within lookahead window
    check_date = check_time.date()
    lookahead_end = check_time + timedelta(hours=lookahead_hours)
    lookahead_date = lookahead_end.date()
    
    upcoming = [
        event for event in ALL_EVENTS
        if check_date <= event.event_date <= lookahead_date
        and not is_event_active(event, check_time)
    ]
    
    if upcoming:
        next_event = upcoming[0]
        message = f"Trading allowed. Upcoming: {next_event.description}"
    else:
        message = "Trading allowed. No upcoming events."
    
    logger.debug(message)
    
    return EventCheckResult(
        is_blocked=False,
        upcoming_events=upcoming,
        message=message
    )


def get_events_for_date(target_date: date) -> List[MarketEvent]:
    """
    Get all events for a specific date.
    
    Args:
        target_date: Date to check.
        
    Returns:
        List of events on that date.
    """
    return [e for e in ALL_EVENTS if e.event_date == target_date]


def get_next_event(
    event_type: Optional[EventType] = None,
    from_date: Optional[date] = None
) -> Optional[MarketEvent]:
    """
    Get the next upcoming event.
    
    Args:
        event_type: Filter by event type (optional).
        from_date: Start date for search (defaults to today).
        
    Returns:
        Next MarketEvent or None.
    """
    if from_date is None:
        from_date = date.today()
    
    for event in ALL_EVENTS:
        if event.event_date < from_date:
            continue
        if event_type and event.event_type != event_type:
            continue
        return event
    
    return None


class EventCalendarFilter:
    """
    Event calendar filter for integration with strategy engine.
    
    Provides caching and convenient interface for event checks.
    """
    
    def __init__(self, custom_events: Optional[List[MarketEvent]] = None):
        """
        Initialize event calendar filter.
        
        Args:
            custom_events: Additional custom events to track.
        """
        self.events = ALL_EVENTS.copy()
        
        if custom_events:
            self.events.extend(custom_events)
            self.events.sort(key=lambda e: e.event_date)
        
        self._last_check: Optional[EventCheckResult] = None
    
    def allows_trading(self, check_time: Optional[datetime] = None) -> bool:
        """
        Check if trading is currently allowed.
        
        Args:
            check_time: Time to check (defaults to now).
            
        Returns:
            True if no events are blocking trading.
        """
        result = check_events(check_time)
        self._last_check = result
        return not result.is_blocked
    
    def get_blocking_event(self) -> Optional[MarketEvent]:
        """Get the event currently blocking trading, if any."""
        if self._last_check and self._last_check.is_blocked:
            return self._last_check.blocking_event
        return None
    
    def get_status(self, check_time: Optional[datetime] = None) -> EventCheckResult:
        """
        Get full event status.
        
        Args:
            check_time: Time to check (defaults to now).
            
        Returns:
            EventCheckResult with all details.
        """
        result = check_events(check_time)
        self._last_check = result
        return result
    
    def get_today_events(self) -> List[MarketEvent]:
        """Get all events for today."""
        return get_events_for_date(date.today())
    
    def add_custom_event(
        self,
        event_date: date,
        description: str,
        block_before_hours: int = 1,
        block_after_hours: int = 2
    ) -> None:
        """
        Add a custom event to track.
        
        Args:
            event_date: Date of the event.
            description: Description of the event.
            block_before_hours: Hours to block before.
            block_after_hours: Hours to block after.
        """
        event = MarketEvent(
            event_type=EventType.CUSTOM,
            event_date=event_date,
            description=description,
            impact=EventImpact.HIGH,
            block_before_hours=block_before_hours,
            block_after_hours=block_after_hours
        )
        self.events.append(event)
        self.events.sort(key=lambda e: e.event_date)
        logger.info(f"Added custom event: {description}")
