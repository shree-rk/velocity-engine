"""
Tests for Iron Condor Strategy
"""

import pytest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from strategies.ic_config import ICConfig, ICUnderlying
from strategies.ic_models import (
    IronCondor, ICSignal, ICStatus, ICCloseReason,
    OptionContract, VerticalSpread, OptionType
)
from strategies.iron_condor import IronCondorStrategy, ICStrategyStatus


class TestICConfig:
    """Tests for IC configuration."""
    
    def test_default_config(self):
        config = ICConfig()
        
        assert config.target_dte == 7
        assert config.short_put_delta == 0.10
        assert config.risk_per_trade_pct == 0.02
        assert config.profit_target_pct == 0.50
        assert ICUnderlying.SPY in config.underlyings
        assert ICUnderlying.SPX in config.underlyings
    
    def test_spread_width(self):
        config = ICConfig()
        
        assert config.get_spread_width(ICUnderlying.SPY) == 5
        assert config.get_spread_width(ICUnderlying.SPX) == 50
        assert config.get_spread_width(ICUnderlying.QQQ) == 5


class TestOptionContract:
    """Tests for OptionContract."""
    
    def test_option_creation(self):
        opt = OptionContract(
            symbol="SPY",
            expiration=date(2026, 3, 14),
            strike=500.0,
            option_type=OptionType.PUT,
            delta=-0.10,
            bid=1.50,
            ask=1.60,
            mid=1.55
        )
        
        assert opt.symbol == "SPY"
        assert opt.strike == 500.0
        assert opt.option_type == OptionType.PUT
        assert opt.delta == -0.10
    
    def test_dte_calculation(self):
        # Create option expiring in 7 days
        future = date.today() + timedelta(days=7)
        opt = OptionContract(
            symbol="SPY",
            expiration=future,
            strike=500.0,
            option_type=OptionType.PUT
        )
        
        assert opt.dte == 7


class TestVerticalSpread:
    """Tests for VerticalSpread."""
    
    def test_put_spread(self):
        short_put = OptionContract(
            symbol="SPY",
            expiration=date(2026, 3, 14),
            strike=500.0,
            option_type=OptionType.PUT,
            mid=2.00
        )
        long_put = OptionContract(
            symbol="SPY",
            expiration=date(2026, 3, 14),
            strike=495.0,
            option_type=OptionType.PUT,
            mid=1.00
        )
        
        spread = VerticalSpread(short_leg=short_put, long_leg=long_put)
        
        assert spread.width == 5.0
        assert spread.is_put_spread is True
        assert spread.is_call_spread is False
        assert spread.credit == 1.00  # 2.00 - 1.00
    
    def test_call_spread(self):
        short_call = OptionContract(
            symbol="SPY",
            expiration=date(2026, 3, 14),
            strike=520.0,
            option_type=OptionType.CALL,
            mid=2.00
        )
        long_call = OptionContract(
            symbol="SPY",
            expiration=date(2026, 3, 14),
            strike=525.0,
            option_type=OptionType.CALL,
            mid=1.00
        )
        
        spread = VerticalSpread(short_leg=short_call, long_leg=long_call)
        
        assert spread.width == 5.0
        assert spread.is_call_spread is True
        assert spread.credit == 1.00


class TestIronCondor:
    """Tests for IronCondor."""
    
    def create_test_ic(self) -> IronCondor:
        """Create a test Iron Condor."""
        exp = date.today() + timedelta(days=7)
        
        # Put spread
        short_put = OptionContract("SPY", exp, 500.0, OptionType.PUT, mid=2.00)
        long_put = OptionContract("SPY", exp, 495.0, OptionType.PUT, mid=1.00)
        put_spread = VerticalSpread(short_put, long_put)
        
        # Call spread
        short_call = OptionContract("SPY", exp, 520.0, OptionType.CALL, mid=2.00)
        long_call = OptionContract("SPY", exp, 525.0, OptionType.CALL, mid=1.00)
        call_spread = VerticalSpread(short_call, long_call)
        
        return IronCondor(
            underlying="SPY",
            expiration=exp,
            put_spread=put_spread,
            call_spread=call_spread,
            contracts=2,
            entry_credit=2.00,  # Total credit $2.00
            status=ICStatus.OPEN
        )
    
    def test_ic_strikes(self):
        ic = self.create_test_ic()
        
        assert ic.short_put_strike == 500.0
        assert ic.long_put_strike == 495.0
        assert ic.short_call_strike == 520.0
        assert ic.long_call_strike == 525.0
    
    def test_ic_credit(self):
        ic = self.create_test_ic()
        
        # Total credit = $2.00 per contract x 2 contracts x 100 multiplier
        assert ic.total_credit == 400.0
    
    def test_ic_max_loss(self):
        ic = self.create_test_ic()
        
        # Max loss = (width - credit) x contracts x 100
        # = (5 - 2) x 2 x 100 = $600
        assert ic.max_loss == 600.0
    
    def test_ic_breakevens(self):
        ic = self.create_test_ic()
        
        # Lower BE = short put - credit = 500 - 2 = 498
        assert ic.breakeven_low == 498.0
        
        # Upper BE = short call + credit = 520 + 2 = 522
        assert ic.breakeven_high == 522.0
    
    def test_profit_target(self):
        ic = self.create_test_ic()
        
        # 50% of credit = $1.00 to close
        assert ic.profit_target_price == 1.00
    
    def test_stop_loss(self):
        ic = self.create_test_ic()
        
        # 2x credit = $4.00 stop
        assert ic.stop_loss_price == 4.00
    
    def test_to_dict(self):
        ic = self.create_test_ic()
        d = ic.to_dict()
        
        assert d["underlying"] == "SPY"
        assert d["short_put"] == 500.0
        assert d["short_call"] == 520.0
        assert d["entry_credit"] == 2.00


class TestICSignal:
    """Tests for IC Signal."""
    
    def test_signal_creation(self):
        signal = ICSignal(
            underlying="SPY",
            expiration=date(2026, 3, 14),
            short_put_strike=500.0,
            long_put_strike=495.0,
            short_call_strike=520.0,
            long_call_strike=525.0,
            expected_credit=2.00,
            expected_max_loss=300.0,
            short_put_delta=-0.10,
            short_call_delta=0.10,
            underlying_price=510.0,
            vix_at_signal=25.0,
            recommended_contracts=2
        )
        
        assert signal.underlying == "SPY"
        assert signal.expected_credit == 2.00
        assert signal.recommended_contracts == 2
    
    def test_credit_percentage(self):
        signal = ICSignal(
            underlying="SPY",
            expiration=date(2026, 3, 14),
            short_put_strike=500.0,
            long_put_strike=495.0,
            short_call_strike=520.0,
            long_call_strike=525.0,
            expected_credit=1.50,  # $1.50 credit on $5 width = 30%
            expected_max_loss=350.0,
            short_put_delta=-0.10,
            short_call_delta=0.10,
            underlying_price=510.0,
            vix_at_signal=25.0,
            recommended_contracts=2
        )
        
        assert signal.credit_pct_of_width == 0.30


class TestIronCondorStrategy:
    """Tests for IC Strategy."""
    
    @patch('strategies.iron_condor.check_vix')
    @patch('strategies.iron_condor.get_events_for_date')
    def test_strategy_initialization(self, mock_events, mock_vix):
        mock_vix.return_value = MagicMock(value=25.0, regime=MagicMock(value="HIGH"))
        mock_events.return_value = []
        
        strategy = IronCondorStrategy()
        
        assert strategy.name == "iron_condor"
        assert strategy.enabled is True
    
    @patch('strategies.iron_condor.check_vix')
    @patch('strategies.iron_condor.get_events_for_date')
    def test_get_status_vix_in_range(self, mock_events, mock_vix):
        mock_vix.return_value = MagicMock(value=25.0, regime=MagicMock(value="HIGH"))
        mock_events.return_value = []
        
        strategy = IronCondorStrategy()
        status = strategy.get_status()
        
        assert status.vix_value == 25.0
        assert status.vix_allows_entry is True
        assert status.can_open_new is True
    
    @patch('strategies.iron_condor.check_vix')
    @patch('strategies.iron_condor.get_events_for_date')
    def test_get_status_vix_too_low(self, mock_events, mock_vix):
        mock_vix.return_value = MagicMock(value=12.0, regime=MagicMock(value="NORMAL"))
        mock_events.return_value = []
        
        strategy = IronCondorStrategy()
        status = strategy.get_status()
        
        assert status.vix_allows_entry is False
        assert status.can_open_new is False
        assert "too low" in status.message.lower()
    
    @patch('strategies.iron_condor.check_vix')
    @patch('strategies.iron_condor.get_events_for_date')
    def test_get_status_vix_too_high(self, mock_events, mock_vix):
        mock_vix.return_value = MagicMock(value=40.0, regime=MagicMock(value="EXTREME"))
        mock_events.return_value = []
        
        strategy = IronCondorStrategy()
        status = strategy.get_status()
        
        assert status.vix_allows_entry is False
        assert status.can_open_new is False
    
    def test_position_sizing_spy(self):
        strategy = IronCondorStrategy(account_value=100000)
        
        # $300 max loss per contract, 2% risk = $2000
        # Should allow ~6 contracts
        contracts = strategy.calculate_position_size(300.0, ICUnderlying.SPY)
        
        assert contracts == 6
    
    def test_position_sizing_spx(self):
        strategy = IronCondorStrategy(account_value=100000)
        
        # $3000 max loss per SPX contract, 2% risk = $2000
        # Would allow 0, but minimum is 1, capped at 2 for SPX
        contracts = strategy.calculate_position_size(3000.0, ICUnderlying.SPX)
        
        assert contracts == 1  # Capped due to risk
    
    def test_find_expiration(self):
        strategy = IronCondorStrategy()
        
        exp = strategy.find_target_expiration(ICUnderlying.SPY)
        
        assert exp is not None
        dte = (exp - date.today()).days
        assert 5 <= dte <= 10  # Within acceptable range
        assert exp.weekday() == 4  # Friday
    
    @patch('strategies.iron_condor.check_vix')
    @patch('strategies.iron_condor.get_events_for_date')
    def test_check_exit_profit_target(self, mock_events, mock_vix):
        mock_vix.return_value = MagicMock(value=25.0, regime=MagicMock(value="HIGH"))
        mock_events.return_value = []
        
        strategy = IronCondorStrategy()
        
        # Create open position with $2 credit
        ic = IronCondor(
            underlying="SPY",
            expiration=date.today() + timedelta(days=5),
            status=ICStatus.OPEN,
            entry_credit=2.00
        )
        
        # Current price $0.90 = 55% profit
        reason = strategy.check_exit_conditions(ic, 0.90)
        
        assert reason == ICCloseReason.PROFIT_TARGET
    
    @patch('strategies.iron_condor.check_vix')
    @patch('strategies.iron_condor.get_events_for_date')
    def test_check_exit_stop_loss(self, mock_events, mock_vix):
        mock_vix.return_value = MagicMock(value=25.0, regime=MagicMock(value="HIGH"))
        mock_events.return_value = []
        
        strategy = IronCondorStrategy()
        
        ic = IronCondor(
            underlying="SPY",
            expiration=date.today() + timedelta(days=5),
            status=ICStatus.OPEN,
            entry_credit=2.00
        )
        
        # Current price $4.50 = 2.25x credit (stop loss)
        reason = strategy.check_exit_conditions(ic, 4.50)
        
        assert reason == ICCloseReason.STOP_LOSS
    
    @patch('strategies.iron_condor.check_vix')
    @patch('strategies.iron_condor.get_events_for_date')
    def test_check_exit_dte(self, mock_events, mock_vix):
        mock_vix.return_value = MagicMock(value=25.0, regime=MagicMock(value="HIGH"))
        mock_events.return_value = []
        
        strategy = IronCondorStrategy()
        
        # Position expiring in 2 days
        ic = IronCondor(
            underlying="SPY",
            expiration=date.today() + timedelta(days=2),
            status=ICStatus.OPEN,
            entry_credit=2.00
        )
        
        reason = strategy.check_exit_conditions(ic, 1.50)
        
        assert reason == ICCloseReason.DTE_EXIT


class TestICIntegration:
    """Integration tests for IC strategy."""
    
    @patch('strategies.iron_condor.check_vix')
    @patch('strategies.iron_condor.get_events_for_date')
    def test_full_trade_cycle(self, mock_events, mock_vix):
        """Test opening and closing a position."""
        mock_vix.return_value = MagicMock(value=25.0, regime=MagicMock(value="HIGH"))
        mock_events.return_value = []
        
        strategy = IronCondorStrategy(account_value=100000)
        
        # Create signal
        signal = ICSignal(
            underlying="SPY",
            expiration=date.today() + timedelta(days=7),
            short_put_strike=500.0,
            long_put_strike=495.0,
            short_call_strike=520.0,
            long_call_strike=525.0,
            expected_credit=1.50,
            expected_max_loss=350.0,
            short_put_delta=-0.10,
            short_call_delta=0.10,
            underlying_price=510.0,
            vix_at_signal=25.0,
            recommended_contracts=3
        )
        
        # Open position
        ic = strategy.create_position(signal, fill_credit=1.45)
        
        assert ic.status == ICStatus.OPEN
        assert ic.entry_credit == 1.45
        assert ic.contracts == 3
        assert len(strategy.get_open_positions()) == 1
        
        # Close position at profit
        closed_ic = strategy.close_position(ic, close_debit=0.70, reason=ICCloseReason.PROFIT_TARGET)
        
        assert closed_ic.status == ICStatus.CLOSED
        assert closed_ic.close_reason == ICCloseReason.PROFIT_TARGET
        
        # P&L = (1.45 - 0.70) x 3 x 100 = $225
        assert closed_ic.realized_pnl == 225.0
        
        # Check total P&L
        assert strategy.get_total_pnl() == 225.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
