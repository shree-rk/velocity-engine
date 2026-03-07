"""
Tests for Batch 2: Broker, Filters, and Database Models
Run with: pytest tests/test_batch2.py -v
"""

import pytest
from datetime import datetime, date, time, timedelta, timezone
from decimal import Decimal
from unittest.mock import Mock, patch, MagicMock

# ============================================================================
# VIX Filter Tests
# ============================================================================

class TestVixFilter:
    """Tests for VIX filter and regime classification."""
    
    def test_classify_vix_normal(self):
        """VIX below 20 is NORMAL regime."""
        from filters.vix_filter import classify_vix_regime, VixRegime
        
        assert classify_vix_regime(15.0) == VixRegime.NORMAL
        assert classify_vix_regime(19.9) == VixRegime.NORMAL
        assert classify_vix_regime(10.0) == VixRegime.NORMAL
    
    def test_classify_vix_elevated(self):
        """VIX 20-25 is ELEVATED regime."""
        from filters.vix_filter import classify_vix_regime, VixRegime
        
        assert classify_vix_regime(20.0) == VixRegime.ELEVATED
        assert classify_vix_regime(22.5) == VixRegime.ELEVATED
        assert classify_vix_regime(24.9) == VixRegime.ELEVATED
    
    def test_classify_vix_high(self):
        """VIX 25-35 is HIGH regime."""
        from filters.vix_filter import classify_vix_regime, VixRegime
        
        assert classify_vix_regime(25.0) == VixRegime.HIGH
        assert classify_vix_regime(30.0) == VixRegime.HIGH
        assert classify_vix_regime(34.9) == VixRegime.HIGH
    
    def test_classify_vix_extreme(self):
        """VIX >= 35 is EXTREME regime."""
        from filters.vix_filter import classify_vix_regime, VixRegime
        
        assert classify_vix_regime(35.0) == VixRegime.EXTREME
        assert classify_vix_regime(50.0) == VixRegime.EXTREME
        assert classify_vix_regime(80.0) == VixRegime.EXTREME
    
    def test_position_multipliers(self):
        """Position size multipliers match regime."""
        from filters.vix_filter import REGIME_POSITION_MULTIPLIERS, VixRegime
        
        assert REGIME_POSITION_MULTIPLIERS[VixRegime.NORMAL] == 1.0
        assert REGIME_POSITION_MULTIPLIERS[VixRegime.ELEVATED] == 0.75
        assert REGIME_POSITION_MULTIPLIERS[VixRegime.HIGH] == 0.5
        assert REGIME_POSITION_MULTIPLIERS[VixRegime.EXTREME] == 0.0
    
    def test_vix_filter_cache(self):
        """VixFilter uses cache to avoid repeated API calls."""
        from filters.vix_filter import VixFilter, VixReading, VixRegime
        
        vix_filter = VixFilter(cache_seconds=60)
        
        # Mock the check_vix function
        with patch('filters.vix_filter.check_vix') as mock_check:
            mock_reading = VixReading(
                value=18.5,
                regime=VixRegime.NORMAL,
                timestamp=datetime.now(timezone.utc),
                trading_allowed=True,
                position_size_multiplier=1.0,
                message="Test"
            )
            mock_check.return_value = mock_reading
            
            # First call should fetch
            reading1 = vix_filter.get_reading()
            assert mock_check.call_count == 1
            
            # Second call should use cache
            reading2 = vix_filter.get_reading()
            assert mock_check.call_count == 1  # Still 1
            
            # Force refresh should fetch again
            reading3 = vix_filter.get_reading(force_refresh=True)
            assert mock_check.call_count == 2


# ============================================================================
# Event Calendar Tests
# ============================================================================

class TestEventCalendar:
    """Tests for event calendar filter."""
    
    def test_fomc_dates_exist(self):
        """FOMC dates are populated for 2025-2026."""
        from filters.event_calendar import FOMC_DATES_2025, FOMC_DATES_2026
        
        assert len(FOMC_DATES_2025) == 8
        assert len(FOMC_DATES_2026) == 8
    
    def test_cpi_dates_exist(self):
        """CPI dates are populated for 2025-2026."""
        from filters.event_calendar import CPI_DATES_2025, CPI_DATES_2026
        
        assert len(CPI_DATES_2025) == 12
        assert len(CPI_DATES_2026) == 12
    
    def test_nfp_dates_exist(self):
        """NFP dates are populated for 2025-2026."""
        from filters.event_calendar import NFP_DATES_2025, NFP_DATES_2026
        
        assert len(NFP_DATES_2025) == 12
        assert len(NFP_DATES_2026) == 12
    
    def test_quad_witch_dates_exist(self):
        """Quad witching dates are populated."""
        from filters.event_calendar import QUAD_WITCH_DATES_2025, QUAD_WITCH_DATES_2026
        
        assert len(QUAD_WITCH_DATES_2025) == 4
        assert len(QUAD_WITCH_DATES_2026) == 4
    
    def test_get_events_for_date(self):
        """Can retrieve events for a specific date."""
        from filters.event_calendar import get_events_for_date, FOMC_DATES_2025
        
        fomc_date = FOMC_DATES_2025[0]
        events = get_events_for_date(fomc_date)
        
        assert len(events) >= 1
        assert any(e.event_date == fomc_date for e in events)
    
    def test_get_next_event(self):
        """Can get next upcoming event."""
        from filters.event_calendar import get_next_event, EventType
        
        # Get next FOMC from a known past date
        next_fomc = get_next_event(EventType.FOMC, date(2025, 1, 1))
        
        assert next_fomc is not None
        assert next_fomc.event_type == EventType.FOMC
        assert next_fomc.event_date >= date(2025, 1, 1)
    
    def test_event_check_result(self):
        """EventCheckResult dataclass works correctly."""
        from filters.event_calendar import EventCheckResult, MarketEvent, EventType, EventImpact
        
        result = EventCheckResult(
            is_blocked=False,
            message="All clear"
        )
        
        assert result.is_blocked is False
        assert result.blocking_event is None
        assert result.upcoming_events == []


# ============================================================================
# Trading Hours Tests
# ============================================================================

class TestTradingHours:
    """Tests for trading hours filter."""
    
    def test_market_holidays_exist(self):
        """Market holidays are populated for 2025-2026."""
        from filters.trading_hours import MARKET_HOLIDAYS
        
        # Should have holidays for both years
        holidays_2025 = [h for h in MARKET_HOLIDAYS if h.year == 2025]
        holidays_2026 = [h for h in MARKET_HOLIDAYS if h.year == 2026]
        
        assert len(holidays_2025) >= 9
        assert len(holidays_2026) >= 9
    
    def test_is_market_holiday(self):
        """Correctly identifies market holidays."""
        from filters.trading_hours import is_market_holiday
        
        # Christmas 2025 is a holiday
        assert is_market_holiday(date(2025, 12, 25)) is True
        
        # Random weekday is not a holiday
        assert is_market_holiday(date(2025, 6, 10)) is False
    
    def test_market_session_weekend(self):
        """Weekend is correctly identified."""
        from filters.trading_hours import get_market_session, MarketSession
        
        # Saturday
        saturday = datetime(2025, 3, 8, 12, 0, 0, tzinfo=timezone.utc)
        assert get_market_session(saturday) == MarketSession.WEEKEND
        
        # Sunday
        sunday = datetime(2025, 3, 9, 12, 0, 0, tzinfo=timezone.utc)
        assert get_market_session(sunday) == MarketSession.WEEKEND
    
    def test_market_session_holiday(self):
        """Holiday is correctly identified."""
        from filters.trading_hours import get_market_session, MarketSession
        
        # Christmas 2025 (Thursday) at noon
        christmas = datetime(2025, 12, 25, 17, 0, 0, tzinfo=timezone.utc)  # Noon ET
        assert get_market_session(christmas) == MarketSession.HOLIDAY
    
    def test_early_close_days(self):
        """Early close days return correct close time."""
        from filters.trading_hours import get_market_close_time, is_early_close
        
        # Day before July 4th, 2025
        early_close_day = date(2025, 7, 3)
        
        assert is_early_close(early_close_day) is True
        assert get_market_close_time(early_close_day) == time(13, 0)
    
    def test_regular_day_close_time(self):
        """Regular days return standard close time."""
        from filters.trading_hours import get_market_close_time
        
        regular_day = date(2025, 6, 10)
        assert get_market_close_time(regular_day) == time(16, 0)
    
    def test_trading_hours_filter_buffers(self):
        """Trading hours filter applies open/close buffers."""
        from filters.trading_hours import TradingHoursFilter
        
        filter = TradingHoursFilter(
            buffer_minutes_open=5,
            buffer_minutes_close=15
        )
        
        assert filter.buffer_minutes_open == 5
        assert filter.buffer_minutes_close == 15


# ============================================================================
# Alpaca Broker Tests
# ============================================================================

class TestAlpacaBroker:
    """Tests for Alpaca broker (mocked - no real API calls)."""
    
    def test_broker_initialization(self):
        """Broker initializes with correct mode."""
        from brokers.alpaca_broker import AlpacaBroker
        
        broker = AlpacaBroker(paper=True)
        assert broker.paper is True
        assert broker.is_connected is False
    
    def test_order_result_dataclass(self):
        """OrderResult dataclass works correctly."""
        from brokers.alpaca_broker import OrderResult
        
        result = OrderResult(
            success=True,
            order_id="test-123",
            symbol="AAPL",
            side="buy",
            qty=100
        )
        
        assert result.success is True
        assert result.order_id == "test-123"
        assert result.error_message is None
    
    def test_position_dataclass(self):
        """Position dataclass works correctly."""
        from brokers.alpaca_broker import Position
        
        position = Position(
            symbol="NVDA",
            qty=50,
            avg_entry_price=Decimal("850.00"),
            current_price=Decimal("875.00"),
            market_value=Decimal("43750.00"),
            unrealized_pl=Decimal("1250.00"),
            unrealized_plpc=Decimal("2.94"),
            side="long"
        )
        
        assert position.symbol == "NVDA"
        assert position.qty == 50
        assert position.unrealized_pl == Decimal("1250.00")
    
    def test_account_info_dataclass(self):
        """AccountInfo dataclass works correctly."""
        from brokers.alpaca_broker import AccountInfo
        
        account = AccountInfo(
            equity=Decimal("100000.00"),
            cash=Decimal("50000.00"),
            buying_power=Decimal("100000.00"),
            portfolio_value=Decimal("100000.00"),
            pattern_day_trader=False,
            trading_blocked=False,
            account_blocked=False,
            created_at=datetime.now(timezone.utc)
        )
        
        assert account.equity == Decimal("100000.00")
        assert account.pattern_day_trader is False


# ============================================================================
# Database Model Tests
# ============================================================================

class TestDatabaseModels:
    """Tests for SQLAlchemy database models."""
    
    def test_position_model_creation(self):
        """Position model can be instantiated."""
        from storage.models import Position, PositionSide, PositionStatus
        
        position = Position(
            symbol="AAPL",
            strategy="velocity_mr",
            side=PositionSide.LONG,
            status=PositionStatus.OPEN,
            entry_price=150.0,
            entry_qty=100
        )
        
        assert position.symbol == "AAPL"
        assert position.side == PositionSide.LONG
        assert position.status == PositionStatus.OPEN
    
    def test_position_pnl_calculation(self):
        """Position P&L calculation works correctly."""
        from storage.models import Position, PositionSide, PositionStatus
        
        # Long position with profit
        long_position = Position(
            symbol="AAPL",
            strategy="velocity_mr",
            side=PositionSide.LONG,
            status=PositionStatus.CLOSED,
            entry_price=100.0,
            exit_price=110.0,
            entry_qty=100
        )
        
        pnl = long_position.calculate_pnl()
        assert pnl == 1000.0  # (110 - 100) * 100
        
        # Long position with loss
        loss_position = Position(
            symbol="AAPL",
            strategy="velocity_mr",
            side=PositionSide.LONG,
            status=PositionStatus.CLOSED,
            entry_price=100.0,
            exit_price=90.0,
            entry_qty=100
        )
        
        pnl = loss_position.calculate_pnl()
        assert pnl == -1000.0  # (90 - 100) * 100
    
    def test_trade_model_creation(self):
        """Trade model can be instantiated."""
        from storage.models import Trade, OrderSideEnum, OrderTypeEnum
        
        trade = Trade(
            symbol="NVDA",
            side=OrderSideEnum.BUY,
            order_type=OrderTypeEnum.MARKET,
            qty=50
        )
        
        assert trade.symbol == "NVDA"
        assert trade.side == OrderSideEnum.BUY
        assert trade.qty == 50
    
    def test_signal_model_creation(self):
        """Signal model can be instantiated."""
        from storage.models import Signal, SignalType, SignalStatus
        
        signal = Signal(
            symbol="TSLA",
            strategy="velocity_mr",
            signal_type=SignalType.ENTRY,
            status=SignalStatus.PENDING,
            price_at_signal=250.0,
            rsi_value=28.0,
            conditions_met=4
        )
        
        assert signal.symbol == "TSLA"
        assert signal.signal_type == SignalType.ENTRY
        assert signal.conditions_met == 4
    
    def test_equity_snapshot_creation(self):
        """EquitySnapshot model can be instantiated."""
        from storage.models import EquitySnapshot
        
        snapshot = EquitySnapshot(
            equity=100000.0,
            cash=50000.0,
            positions_value=50000.0,
            high_water_mark=105000.0,
            drawdown=5000.0,
            drawdown_pct=0.0476,
            open_positions=2
        )
        
        assert snapshot.equity == 100000.0
        assert snapshot.drawdown_pct == 0.0476
    
    def test_system_state_creation(self):
        """SystemState model can be instantiated."""
        from storage.models import SystemState
        
        state = SystemState(
            key="alpha_shield_triggered",
            value="false"
        )
        
        assert state.key == "alpha_shield_triggered"
        assert state.value == "false"
    
    def test_database_manager_creation(self):
        """DatabaseManager can be instantiated with in-memory SQLite."""
        from storage.models import DatabaseManager
        
        # Use in-memory SQLite for testing
        db = DatabaseManager(db_url="sqlite:///:memory:", echo=False)
        
        assert db.engine is not None
        assert db.Session is not None
        
        # Create tables
        db.create_tables()
        
        # Get a session
        session = db.get_session()
        assert session is not None
        session.close()


# ============================================================================
# Integration Tests (Mocked)
# ============================================================================

class TestBatch2Integration:
    """Integration tests for Batch 2 components."""
    
    def test_all_filters_importable(self):
        """All filter components can be imported."""
        from filters import (
            VixFilter,
            VixRegime,
            EventCalendarFilter,
            EventType,
            TradingHoursFilter,
            MarketSession
        )
        
        assert VixFilter is not None
        assert EventCalendarFilter is not None
        assert TradingHoursFilter is not None
    
    def test_broker_importable(self):
        """Broker components can be imported."""
        from brokers import (
            AlpacaBroker,
            create_broker,
            OrderResult,
            Position,
            AccountInfo
        )
        
        assert AlpacaBroker is not None
        assert create_broker is not None
    
    def test_storage_importable(self):
        """Storage components can be imported."""
        from storage import (
            Position,
            Trade,
            Signal,
            EquitySnapshot,
            DatabaseManager
        )
        
        assert Position is not None
        assert Trade is not None
        assert Signal is not None
    
    def test_filter_combination(self):
        """Multiple filters can be used together."""
        from filters import VixFilter, EventCalendarFilter, TradingHoursFilter
        
        vix = VixFilter(cache_seconds=60)
        events = EventCalendarFilter()
        hours = TradingHoursFilter()
        
        # All filters should have allows_trading method
        assert hasattr(vix, 'allows_trading')
        assert hasattr(events, 'allows_trading')
        assert hasattr(hours, 'allows_trading')


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
