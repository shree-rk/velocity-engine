"""
Tests for Batch 3: Strategy, Risk Manager, Engine, Scheduler
Run with: pytest tests/test_batch3.py -v
"""

import pytest
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import Mock, patch, MagicMock


# ============================================================================
# Base Strategy Tests
# ============================================================================

class TestBaseStrategy:
    """Tests for base strategy class."""
    
    def test_trade_signal_creation(self):
        """TradeSignal can be created with required fields."""
        from strategies.base import TradeSignal, SignalDirection
        
        signal = TradeSignal(
            symbol="AAPL",
            direction=SignalDirection.LONG,
            strategy_name="test",
            entry_price=150.0,
            stop_loss=145.0
        )
        
        assert signal.symbol == "AAPL"
        assert signal.direction == SignalDirection.LONG
        assert signal.entry_price == 150.0
        assert signal.stop_loss == 145.0
    
    def test_trade_signal_is_entry(self):
        """TradeSignal correctly identifies entry signals."""
        from strategies.base import TradeSignal, SignalDirection
        
        entry = TradeSignal(
            symbol="AAPL",
            direction=SignalDirection.LONG,
            strategy_name="test",
            entry_price=150.0,
            stop_loss=145.0
        )
        
        exit = TradeSignal(
            symbol="AAPL",
            direction=SignalDirection.FLAT,
            strategy_name="test",
            entry_price=155.0,
            stop_loss=0
        )
        
        assert entry.is_entry is True
        assert entry.is_exit is False
        assert exit.is_entry is False
        assert exit.is_exit is True
    
    def test_trade_signal_to_dict(self):
        """TradeSignal converts to dictionary."""
        from strategies.base import TradeSignal, SignalDirection
        
        signal = TradeSignal(
            symbol="NVDA",
            direction=SignalDirection.LONG,
            strategy_name="velocity_mr",
            entry_price=850.0,
            stop_loss=830.0,
            conditions_met=4
        )
        
        data = signal.to_dict()
        
        assert data["symbol"] == "NVDA"
        assert data["direction"] == "long"
        assert data["strategy"] == "velocity_mr"
        assert data["conditions_met"] == 4


# ============================================================================
# Velocity MR Strategy Tests
# ============================================================================

class TestVelocityMRStrategy:
    """Tests for Velocity Mean Reversion strategy."""
    
    def test_strategy_initialization(self):
        """Strategy initializes with default watchlist."""
        from strategies.velocity_mr import VelocityMRStrategy
        
        strategy = VelocityMRStrategy()
        
        assert strategy.name == "velocity_mr"
        assert len(strategy.symbols) == 11  # Default watchlist
        assert strategy.enabled is True
    
    def test_strategy_parameters(self):
        """Strategy has correct parameters."""
        from strategies.velocity_mr import VelocityMRStrategy
        
        assert VelocityMRStrategy.RSI_OVERSOLD == 30
        assert VelocityMRStrategy.RSI_OVERBOUGHT == 70
        assert VelocityMRStrategy.ADX_MIN == 20
        assert VelocityMRStrategy.VOLUME_RATIO_MIN == 1.5
    
    def test_bb_position_calculation(self):
        """Bollinger Band position is calculated correctly."""
        from strategies.velocity_mr import VelocityMRStrategy
        
        strategy = VelocityMRStrategy()
        
        # Price at lower band = 0.0
        pos = strategy._calculate_bb_position(100, 110, 100)
        assert pos == 0.0
        
        # Price at upper band = 1.0
        pos = strategy._calculate_bb_position(110, 110, 100)
        assert pos == 1.0
        
        # Price at middle = 0.5
        pos = strategy._calculate_bb_position(105, 110, 100)
        assert pos == 0.5
    
    def test_atr_multipliers_by_category(self):
        """ATR multipliers vary by stock category."""
        from strategies.velocity_mr import VelocityMRStrategy
        
        strategy = VelocityMRStrategy()
        
        # High beta = 1.5x
        mult = strategy._get_atr_multiplier("NVDA")
        assert mult == 1.5
        
        # ETF = 2.0x
        mult = strategy._get_atr_multiplier("SPY")
        assert mult == 2.0
        
        # Unknown = 2.0x (default)
        mult = strategy._get_atr_multiplier("UNKNOWN")
        assert mult == 2.0
    
    def test_strategy_enable_disable(self):
        """Strategy can be enabled and disabled."""
        from strategies.velocity_mr import VelocityMRStrategy
        
        strategy = VelocityMRStrategy()
        
        assert strategy.enabled is True
        
        strategy.disable()
        assert strategy.enabled is False
        
        # Scan should return empty when disabled
        signals = strategy.scan()
        assert signals == []
        
        strategy.enable()
        assert strategy.enabled is True


# ============================================================================
# Risk Manager Tests
# ============================================================================

class TestRiskManager:
    """Tests for risk manager."""
    
    def test_initialization(self):
        """RiskManager initializes with config values."""
        from core.risk_manager import RiskManager
        
        rm = RiskManager(
            base_capital=100000,
            risk_per_trade=0.02,
            max_position_pct=0.25,
            max_positions=4,
            drawdown_limit=0.15
        )
        
        assert rm.base_capital == 100000
        assert rm.risk_per_trade == 0.02
        assert rm.max_position_pct == 0.25
        assert rm.max_positions == 4
        assert rm.drawdown_limit == 0.15
    
    def test_drawdown_calculation(self):
        """Drawdown is calculated correctly."""
        from core.risk_manager import RiskManager
        
        rm = RiskManager(base_capital=100000)
        
        # No drawdown initially
        dd_abs, dd_pct = rm.get_drawdown()
        assert dd_abs == 0.0
        assert dd_pct == 0.0
        
        # Update to new high
        rm.update_equity(110000)
        dd_abs, dd_pct = rm.get_drawdown()
        assert dd_abs == 0.0
        
        # Now drop
        rm.update_equity(99000)
        dd_abs, dd_pct = rm.get_drawdown()
        assert dd_abs == 11000  # 110000 - 99000
        assert dd_pct == 0.1  # 10%
    
    def test_alpha_shield_trigger(self):
        """Alpha Shield triggers at drawdown limit."""
        from core.risk_manager import RiskManager
        
        rm = RiskManager(
            base_capital=100000,
            drawdown_limit=0.15
        )
        
        assert rm.is_alpha_shield_triggered() is False
        
        # 15% drawdown should trigger
        rm.update_equity(100000)
        rm.update_equity(85000)  # 15% drawdown
        
        assert rm.is_alpha_shield_triggered() is True
    
    def test_alpha_shield_reset(self):
        """Alpha Shield can be reset."""
        from core.risk_manager import RiskManager
        
        rm = RiskManager(base_capital=100000, drawdown_limit=0.15)
        
        # Trigger it
        rm.update_equity(85000)
        assert rm.is_alpha_shield_triggered() is True
        
        # Reset
        rm.reset_alpha_shield()
        assert rm.is_alpha_shield_triggered() is False
    
    def test_position_size_calculation(self):
        """Position size is calculated correctly."""
        from core.risk_manager import RiskManager
        
        # Mock VIX filter to return normal
        with patch('core.risk_manager.VixFilter') as MockVix:
            mock_vix = MockVix.return_value
            mock_vix.get_position_multiplier.return_value = 1.0
            
            rm = RiskManager(
                base_capital=100000,
                risk_per_trade=0.02,
                max_position_pct=0.25,
                vix_filter=mock_vix
            )
            rm.update_equity(100000)
            
            result = rm.calculate_position_size(
                symbol="AAPL",
                entry_price=150.0,
                stop_loss=145.0,  # $5 risk per share
                apply_vix_adjustment=True
            )
            
            assert result.is_valid is True
            # $100k * 2% = $2000 risk, $2000 / $5 = 400 shares
            # BUT max position = $100k * 25% = $25k, $25k / $150 = 166 shares
            # So shares get capped to 166
            assert result.original_shares == 400
            assert result.size_capped is True
            assert result.shares == 166
            assert result.risk_amount == 2000
    
    def test_position_size_max_cap(self):
        """Position size is capped at max percentage."""
        from core.risk_manager import RiskManager
        
        with patch('core.risk_manager.VixFilter') as MockVix:
            mock_vix = MockVix.return_value
            mock_vix.get_position_multiplier.return_value = 1.0
            
            rm = RiskManager(
                base_capital=100000,
                risk_per_trade=0.10,  # 10% risk would be huge
                max_position_pct=0.25,  # But capped at 25%
                vix_filter=mock_vix
            )
            rm.update_equity(100000)
            
            result = rm.calculate_position_size(
                symbol="AAPL",
                entry_price=100.0,
                stop_loss=99.0
            )
            
            # Max position = $100k * 25% = $25k
            # At $100/share = 250 shares max
            assert result.shares <= 250
            assert result.size_capped is True
    
    def test_position_blocked_alpha_shield(self):
        """Position sizing blocked when Alpha Shield triggered."""
        from core.risk_manager import RiskManager
        
        rm = RiskManager(base_capital=100000, drawdown_limit=0.15)
        rm.update_equity(85000)  # Trigger Alpha Shield
        
        result = rm.calculate_position_size(
            symbol="AAPL",
            entry_price=150.0,
            stop_loss=145.0
        )
        
        assert result.is_valid is False
        assert "Alpha Shield" in result.rejection_reason
    
    def test_allows_new_trade(self):
        """allows_new_trade returns correct status."""
        from core.risk_manager import RiskManager
        
        with patch('core.risk_manager.VixFilter') as MockVix:
            mock_vix = MockVix.return_value
            mock_vix.get_position_multiplier.return_value = 1.0
            
            rm = RiskManager(
                base_capital=100000,
                max_positions=4,
                vix_filter=mock_vix
            )
            
            allowed, reason = rm.allows_new_trade()
            assert allowed is True
            
            # Add max positions
            rm.set_positions([
                {"symbol": "A", "value": 10000},
                {"symbol": "B", "value": 10000},
                {"symbol": "C", "value": 10000},
                {"symbol": "D", "value": 10000},
            ])
            
            allowed, reason = rm.allows_new_trade()
            assert allowed is False
            assert "positions" in reason.lower()


# ============================================================================
# Engine Tests
# ============================================================================

class TestVelocityEngine:
    """Tests for main engine (mocked broker)."""
    
    def test_engine_initialization(self):
        """Engine initializes with components."""
        from core.engine import VelocityEngine, EngineState
        
        engine = VelocityEngine(auto_connect=False)
        
        assert engine.state == EngineState.STOPPED
        assert engine.strategy is not None
        assert engine.risk_manager is not None
        assert engine.vix_filter is not None
    
    def test_engine_state_transitions(self):
        """Engine state transitions work correctly."""
        from core.engine import VelocityEngine, EngineState
        
        engine = VelocityEngine(auto_connect=False)
        
        assert engine.state == EngineState.STOPPED
        
        # Can't start without broker
        result = engine.start()
        # Will fail because no broker
        
        # Test pause/resume
        engine.state = EngineState.RUNNING  # Force state
        
        engine.pause()
        assert engine.state == EngineState.PAUSED
        
        engine.resume()
        assert engine.state == EngineState.RUNNING
        
        engine.stop()
        assert engine.state == EngineState.STOPPED
    
    def test_engine_get_status(self):
        """Engine returns status correctly."""
        from core.engine import VelocityEngine, EngineState
        
        engine = VelocityEngine(auto_connect=False)
        
        status = engine.get_status()
        
        assert status.state == EngineState.STOPPED
        assert status.mode in ["PAPER", "LIVE"]
        assert status.broker_connected is False
        assert isinstance(status.vix_value, float)


# ============================================================================
# Scheduler Tests
# ============================================================================

class TestVelocityScheduler:
    """Tests for scheduler."""
    
    def test_scheduler_initialization(self):
        """Scheduler initializes correctly."""
        from core.scheduler import VelocityScheduler
        
        scheduler = VelocityScheduler(
            scan_interval_minutes=3,
            market_hours_only=True
        )
        
        assert scheduler.scan_interval == 3
        assert scheduler.market_hours_only is True
        assert scheduler.is_running is False
    
    def test_scheduler_with_callbacks(self):
        """Scheduler accepts callback functions."""
        from core.scheduler import VelocityScheduler
        
        scan_called = []
        
        def mock_scan():
            scan_called.append(True)
        
        scheduler = VelocityScheduler(
            scan_callback=mock_scan,
            scan_interval_minutes=1
        )
        
        assert scheduler.scan_callback is not None
    
    def test_scheduler_stats(self):
        """Scheduler tracks statistics."""
        from core.scheduler import VelocityScheduler
        
        scheduler = VelocityScheduler()
        
        stats = scheduler.get_stats()
        
        assert "is_running" in stats
        assert "scans_executed" in stats
        assert "errors" in stats
        assert stats["scans_executed"] == 0


# ============================================================================
# Integration Tests
# ============================================================================

class TestBatch3Integration:
    """Integration tests for Batch 3 components."""
    
    def test_all_components_importable(self):
        """All Batch 3 components can be imported."""
        from strategies import VelocityMRStrategy, TradeSignal, SignalDirection
        from core import (
            VelocityEngine,
            RiskManager,
            VelocityScheduler,
            EngineState,
            RiskStatus
        )
        
        assert VelocityMRStrategy is not None
        assert VelocityEngine is not None
        assert RiskManager is not None
        assert VelocityScheduler is not None
    
    def test_strategy_produces_valid_signals(self):
        """Strategy produces valid TradeSignal objects."""
        from strategies import VelocityMRStrategy, SignalDirection
        from strategies.base import TradeSignal
        
        strategy = VelocityMRStrategy()
        
        # Create a mock signal to test validation
        signal = TradeSignal(
            symbol="NVDA",
            direction=SignalDirection.LONG,
            strategy_name="velocity_mr",
            entry_price=850.0,
            stop_loss=830.0,
            take_profit=870.0,
            conditions_met=4,
            total_conditions=4
        )
        
        assert strategy.validate_signal(signal) is True
        
        # Invalid signal (stop above entry)
        bad_signal = TradeSignal(
            symbol="NVDA",
            direction=SignalDirection.LONG,
            strategy_name="velocity_mr",
            entry_price=850.0,
            stop_loss=860.0  # Above entry!
        )
        
        assert strategy.validate_signal(bad_signal) is False
    
    def test_risk_manager_with_strategy_signal(self):
        """Risk manager can size positions from strategy signals."""
        from strategies import VelocityMRStrategy
        from core import RiskManager
        
        with patch('core.risk_manager.VixFilter') as MockVix:
            mock_vix = MockVix.return_value
            mock_vix.get_position_multiplier.return_value = 1.0
            
            rm = RiskManager(
                base_capital=100000,
                risk_per_trade=0.02,
                vix_filter=mock_vix
            )
            rm.update_equity(100000)
            
            # Size a position
            result = rm.calculate_position_size(
                symbol="NVDA",
                entry_price=850.0,
                stop_loss=830.0  # $20 risk per share
            )
            
            assert result.is_valid is True
            # $2000 risk / $20 per share = 100 shares
            # BUT max position = $100k * 25% = $25k, $25k / $850 = 29 shares
            # So shares get capped to 29
            assert result.original_shares == 100
            assert result.size_capped is True
            assert result.shares == 29
    
    def test_engine_with_mocked_broker(self):
        """Engine works with mocked broker."""
        from core.engine import VelocityEngine, EngineState
        from brokers.alpaca_broker import AlpacaBroker, AccountInfo
        from decimal import Decimal
        from datetime import datetime, timezone
        
        # Create mock broker
        mock_broker = Mock(spec=AlpacaBroker)
        mock_broker.is_connected = True
        mock_broker.get_account.return_value = AccountInfo(
            equity=Decimal("100000"),
            cash=Decimal("50000"),
            buying_power=Decimal("100000"),
            portfolio_value=Decimal("100000"),
            pattern_day_trader=False,
            trading_blocked=False,
            account_blocked=False,
            created_at=datetime.now(timezone.utc)
        )
        mock_broker.get_positions.return_value = []
        
        engine = VelocityEngine(
            broker=mock_broker,
            auto_connect=False
        )
        engine.state = EngineState.RUNNING
        
        status = engine.get_status()
        assert status.broker_connected is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])