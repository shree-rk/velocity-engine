"""
Tests for Iron Condor Strategy - Ported from Loveable
"""

import pytest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from strategies.ic_config import (
    ICConfig, IC_CONFIG, VIXRegime, ICPositionStatus, ICCloseReason,
    UNDERLYING_CONFIGS, get_underlying_config, is_event_blocked, get_event_warning,
    VIXConfig, EntryConfig, ExitConfig, PositionConfig
)
from strategies.ic_models import (
    IronCondor, ICEntrySignal, ICExitSignal,
    OptionContract, VerticalSpread, OptionType, GreeksSnapshot
)
from strategies.iron_condor import IronCondorStrategy, GateResult


# =============================================================================
# CONFIG TESTS
# =============================================================================

class TestICConfig:
    """Tests for IC configuration."""
    
    def test_default_config_values(self):
        """Test default configuration values match Loveable spec."""
        config = ICConfig()
        
        # VIX thresholds (3-tier)
        assert config.vix.normal_threshold == 20.0
        assert config.vix.elevated_threshold == 23.0
        assert config.vix.critical_threshold == 25.0
        
        # Entry config
        assert config.entry.max_entry_delta == 0.18
        assert config.entry.max_iv_rank == 25.0
        assert config.entry.max_widen_attempts == 5
        
        # Exit config (dual profit targets)
        assert config.exit.profit_target_max_pct == 50.0
        assert config.exit.profit_target_premium_pct == 70.0
        assert config.exit.stop_loss_multiplier == 1.5  # Tighter than 2x
        assert config.exit.delta_exit == 0.25
        assert config.exit.dte_safety_exit == 2
        
        # Position limits
        assert config.position.max_condors_per_100k == 6
        
    def test_vix_regime_classification(self):
        """Test VIX regime is correctly classified."""
        vix_config = VIXConfig()
        
        assert vix_config.get_regime(15.0) == VIXRegime.NORMAL
        assert vix_config.get_regime(19.9) == VIXRegime.NORMAL
        assert vix_config.get_regime(20.0) == VIXRegime.ELEVATED
        assert vix_config.get_regime(22.9) == VIXRegime.ELEVATED
        assert vix_config.get_regime(23.0) == VIXRegime.HIGH
        assert vix_config.get_regime(24.9) == VIXRegime.HIGH
        assert vix_config.get_regime(25.0) == VIXRegime.CRITICAL
        assert vix_config.get_regime(35.0) == VIXRegime.CRITICAL
        
    def test_vix_entry_blocking(self):
        """Test VIX blocks entry at critical level."""
        vix_config = VIXConfig()
        
        # Should allow entry
        can_enter, _ = vix_config.can_enter(15.0)
        assert can_enter is True
        
        can_enter, _ = vix_config.can_enter(22.0)
        assert can_enter is True
        
        # Should block entry at HIGH (>= 23)
        can_enter, msg = vix_config.can_enter(23.0)
        assert can_enter is False
        assert "NO ENTRY" in msg
        
        # Should block entry at CRITICAL
        can_enter, msg = vix_config.can_enter(30.0)
        assert can_enter is False
        
    def test_vix_position_multiplier(self):
        """Test VIX-based position sizing multipliers."""
        vix_config = VIXConfig()
        
        # Normal: full size
        assert vix_config.get_multiplier(15.0) == 1.0
        
        # Elevated: 50%
        assert vix_config.get_multiplier(21.0) == 0.5
        
        # Critical: no new positions
        assert vix_config.get_multiplier(25.0) == 0.0
        
    def test_underlying_configs(self):
        """Test underlying configurations."""
        spy_config = get_underlying_config("SPY")
        assert spy_config is not None
        assert spy_config.symbol == "SPY"
        assert spy_config.option_symbol == "SPY"
        assert spy_config.min_strike_width == 5
        assert spy_config.max_condors == 3
        
        spx_config = get_underlying_config("SPX")
        assert spx_config is not None
        assert spx_config.option_symbol == "SPXW"  # Weekly options
        assert spx_config.min_strike_width == 25
        assert spx_config.cash_settled is True
        assert spx_config.tax_advantaged is True
        
        qqq_config = get_underlying_config("QQQ")
        assert qqq_config is not None
        assert qqq_config.iv_index == "VXN"
        
    def test_max_condors_scaling(self):
        """Test max condors scales with account size."""
        config = ICConfig()
        
        assert config.get_max_condors(50000) == 3   # $50K = 3 condors
        assert config.get_max_condors(100000) == 6  # $100K = 6 condors
        assert config.get_max_condors(200000) == 12 # $200K = 12 condors
        assert config.get_max_condors(1000000) == 60 # $1M = 60 condors


# =============================================================================
# EVENT CALENDAR TESTS
# =============================================================================

class TestEventCalendar:
    """Tests for economic event calendar."""
    
    def test_fomc_blocks_entry(self):
        """Test FOMC days block entry."""
        blocked, event = is_event_blocked(date(2025, 3, 19))
        assert blocked is True
        assert "FOMC" in event
        
    def test_cpi_blocks_entry(self):
        """Test CPI release days block entry."""
        blocked, event = is_event_blocked(date(2025, 3, 12))
        assert blocked is True
        assert "CPI" in event
        
    def test_nfp_blocks_entry(self):
        """Test NFP (jobs) days block entry."""
        blocked, event = is_event_blocked(date(2025, 3, 7))
        assert blocked is True
        assert "NFP" in event or "Jobs" in event
        
    def test_quad_witch_blocks_entry(self):
        """Test quad witching blocks entry."""
        blocked, event = is_event_blocked(date(2025, 3, 21))
        assert blocked is True
        assert "Quad" in event or "Witch" in event
        
    def test_normal_day_allows_entry(self):
        """Test normal days allow entry."""
        blocked, _ = is_event_blocked(date(2025, 3, 10))  # Monday, no events
        assert blocked is False
        
    def test_event_warning_day_before(self):
        """Test warning is generated day before event."""
        warning = get_event_warning(date(2025, 3, 18))  # Day before FOMC
        assert warning is not None
        assert "FOMC" in warning


# =============================================================================
# OPTION CONTRACT TESTS
# =============================================================================

class TestOptionContract:
    """Tests for OptionContract model."""
    
    def test_option_creation(self):
        """Test creating an option contract."""
        opt = OptionContract(
            symbol="SPY",
            expiration=date(2026, 3, 20),
            strike=600.0,
            option_type=OptionType.PUT,
            delta=-0.10,
            gamma=0.02,
            bid=2.50,
            ask=2.60,
        )
        
        assert opt.symbol == "SPY"
        assert opt.strike == 600.0
        assert opt.option_type == OptionType.PUT
        assert opt.delta == -0.10
        
    def test_dte_calculation(self):
        """Test DTE calculation."""
        future = date.today() + timedelta(days=7)
        opt = OptionContract(
            symbol="SPY",
            expiration=future,
            strike=600.0,
            option_type=OptionType.PUT
        )
        
        assert opt.dte == 7
        
    def test_occ_symbol_building(self):
        """Test OCC symbol construction."""
        opt = OptionContract(
            symbol="SPY",
            expiration=date(2026, 3, 13),
            strike=638.0,
            option_type=OptionType.PUT
        )
        
        occ = opt.build_occ_symbol()
        # SPY260313P00638000
        assert occ.startswith("SPY")
        assert "260313" in occ
        assert "P" in occ
        assert "00638000" in occ


# =============================================================================
# VERTICAL SPREAD TESTS
# =============================================================================

class TestVerticalSpread:
    """Tests for VerticalSpread model."""
    
    def test_put_spread(self):
        """Test put spread (bull put spread)."""
        short_put = OptionContract(
            symbol="SPY", expiration=date(2026, 3, 20),
            strike=595.0, option_type=OptionType.PUT,
            mid=1.50
        )
        long_put = OptionContract(
            symbol="SPY", expiration=date(2026, 3, 20),
            strike=590.0, option_type=OptionType.PUT,
            mid=0.80
        )
        
        spread = VerticalSpread(short_leg=short_put, long_leg=long_put)
        
        assert spread.is_put_spread is True
        assert spread.is_call_spread is False
        assert spread.width == 5.0
        assert spread.credit == 0.70  # 1.50 - 0.80
        
    def test_call_spread(self):
        """Test call spread (bear call spread)."""
        short_call = OptionContract(
            symbol="SPY", expiration=date(2026, 3, 20),
            strike=605.0, option_type=OptionType.CALL,
            mid=1.40
        )
        long_call = OptionContract(
            symbol="SPY", expiration=date(2026, 3, 20),
            strike=610.0, option_type=OptionType.CALL,
            mid=0.75
        )
        
        spread = VerticalSpread(short_leg=short_call, long_leg=long_call)
        
        assert spread.is_call_spread is True
        assert spread.is_put_spread is False
        assert spread.width == 5.0
        assert abs(spread.credit - 0.65) < 0.001  # Float comparison


# =============================================================================
# IRON CONDOR TESTS
# =============================================================================

class TestIronCondor:
    """Tests for IronCondor model."""
    
    @pytest.fixture
    def sample_ic(self):
        """Create a sample Iron Condor for testing."""
        expiration = date.today() + timedelta(days=7)
        
        put_spread = VerticalSpread(
            short_leg=OptionContract("SPY", expiration, 595.0, OptionType.PUT, mid=1.50),
            long_leg=OptionContract("SPY", expiration, 590.0, OptionType.PUT, mid=0.80)
        )
        call_spread = VerticalSpread(
            short_leg=OptionContract("SPY", expiration, 605.0, OptionType.CALL, mid=1.40),
            long_leg=OptionContract("SPY", expiration, 610.0, OptionType.CALL, mid=0.75)
        )
        
        ic = IronCondor(
            id=1,
            underlying="SPY",
            expiration=expiration,
            put_spread=put_spread,
            call_spread=call_spread,
            contracts=2,
            status=ICPositionStatus.OPEN,
            entry_credit=1.35,
            entry_vix=18.0,
        )
        
        return ic
    
    def test_ic_strikes(self, sample_ic):
        """Test IC strike properties."""
        assert sample_ic.short_put_strike == 595.0
        assert sample_ic.long_put_strike == 590.0
        assert sample_ic.short_call_strike == 605.0
        assert sample_ic.long_call_strike == 610.0
        
    def test_ic_wing_width(self, sample_ic):
        """Test wing width calculation."""
        assert sample_ic.wing_width == 5.0
        
    def test_ic_credit(self, sample_ic):
        """Test total credit calculation."""
        # entry_credit * contracts * 100
        assert sample_ic.total_credit == 1.35 * 2 * 100
        
    def test_ic_max_loss(self, sample_ic):
        """Test max loss calculation."""
        # (width - credit) * contracts * 100
        expected = (5.0 - 1.35) * 2 * 100
        assert sample_ic.max_loss == expected
        
    def test_ic_breakevens(self, sample_ic):
        """Test breakeven prices."""
        assert sample_ic.breakeven_low == 595.0 - 1.35  # short put - credit
        assert sample_ic.breakeven_high == 605.0 + 1.35  # short call + credit
        
    def test_ic_dte(self, sample_ic):
        """Test DTE calculation."""
        assert sample_ic.dte == 7
        
    def test_ic_profit_target(self, sample_ic):
        """Test 50% profit target price."""
        assert sample_ic.profit_target_price == 1.35 * 0.50
        
    def test_ic_stop_loss(self, sample_ic):
        """Test 1.5x stop loss price."""
        assert sample_ic.stop_loss_price == 1.35 * 1.5


# =============================================================================
# ENTRY SIGNAL TESTS
# =============================================================================

class TestICEntrySignal:
    """Tests for ICEntrySignal model."""
    
    def test_entry_signal_creation(self):
        """Test creating an entry signal."""
        signal = ICEntrySignal(
            underlying="SPY",
            expiration=date.today() + timedelta(days=7),
            short_put_strike=595.0,
            long_put_strike=590.0,
            short_call_strike=605.0,
            long_call_strike=610.0,
            wing_width=5.0,
            quantity=2,
            vix_multiplier=1.0,
            short_put_delta=0.10,
            short_call_delta=0.10,
            spot_price=600.0,
            vix_value=18.0,
            iv_rank=20.0,
            estimated_credit=1.35,
            max_risk=730.0,
        )
        
        assert signal.underlying == "SPY"
        assert signal.quantity == 2
        assert signal.estimated_credit == 1.35
        
    def test_credit_pct_of_width(self):
        """Test credit as percentage of width calculation."""
        signal = ICEntrySignal(
            underlying="SPY",
            expiration=date.today() + timedelta(days=7),
            short_put_strike=595.0,
            long_put_strike=590.0,
            short_call_strike=605.0,
            long_call_strike=610.0,
            wing_width=5.0,
            quantity=1,
            vix_multiplier=1.0,
            short_put_delta=0.10,
            short_call_delta=0.10,
            spot_price=600.0,
            vix_value=18.0,
            iv_rank=20.0,
            estimated_credit=1.50,  # 30% of $5 width
            max_risk=350.0,
        )
        
        assert signal.credit_pct_of_width == 30.0


# =============================================================================
# STRATEGY TESTS
# =============================================================================

class TestIronCondorStrategy:
    """Tests for IronCondorStrategy."""
    
    @pytest.fixture
    def strategy(self):
        """Create strategy for testing."""
        return IronCondorStrategy(account_capital=100000.0)
    
    def test_strategy_initialization(self, strategy):
        """Test strategy initializes correctly."""
        assert strategy.account_capital == 100000.0
        assert len(strategy.open_positions) == 0
        
    def test_portfolio_limit_gate(self, strategy):
        """Test portfolio limit gate check."""
        # With no positions, should pass
        gate = strategy._check_gate_portfolio_limits()
        assert gate.passed is True
        assert "0/6" in gate.message
        
    def test_trading_enabled_gate(self, strategy):
        """Test trading enabled gate."""
        gate = strategy._check_gate_trading_enabled()
        assert gate.passed is True
        
        # Disable trading
        strategy.config.trading_enabled = False
        gate = strategy._check_gate_trading_enabled()
        assert gate.passed is False
        
    def test_vix_gate_normal(self, strategy):
        """Test VIX gate with normal VIX."""
        gate = strategy._check_gate_vix_filter(18.0)
        assert gate.passed is True
        assert gate.data["regime"] == "NORMAL"
        
    def test_vix_gate_elevated(self, strategy):
        """Test VIX gate with elevated VIX."""
        gate = strategy._check_gate_vix_filter(21.0)
        assert gate.passed is True
        assert gate.data["regime"] == "ELEVATED"
        
    def test_vix_gate_critical_blocks(self, strategy):
        """Test VIX gate blocks at critical level."""
        gate = strategy._check_gate_vix_filter(26.0)
        assert gate.passed is False
        assert "CRITICAL" in gate.message
        
    def test_iv_rank_gate(self, strategy):
        """Test IV Rank gate."""
        # Should pass with low IV Rank
        gate = strategy._check_gate_iv_rank(20.0)
        assert gate.passed is True
        
        # Should fail with high IV Rank
        gate = strategy._check_gate_iv_rank(30.0)
        assert gate.passed is False
        assert "25" in gate.message  # Shows threshold
        
    def test_underlying_limit_gate(self, strategy):
        """Test per-underlying position limit gate."""
        gate = strategy._check_gate_underlying_limit("SPY")
        assert gate.passed is True
        assert "0/3" in gate.message
        
        # Unknown underlying
        gate = strategy._check_gate_underlying_limit("FAKE")
        assert gate.passed is False
        
    def test_delta_cooldown_gate(self, strategy):
        """Test same-day delta exit cooldown gate."""
        # No cooldown
        gate = strategy._check_gate_delta_cooldown("SPY")
        assert gate.passed is True
        
        # Set cooldown for today
        from datetime import date
        strategy.delta_exit_cooldowns["SPY"] = date.today()
        
        gate = strategy._check_gate_delta_cooldown("SPY")
        assert gate.passed is False
        assert "cooldown" in gate.message.lower()


# =============================================================================
# EXIT CONDITION TESTS
# =============================================================================

class TestExitConditions:
    """Tests for exit conditions."""
    
    @pytest.fixture
    def strategy_with_position(self):
        """Create strategy with an open position."""
        strategy = IronCondorStrategy(account_capital=100000.0)
        
        expiration = date.today() + timedelta(days=7)
        
        put_spread = VerticalSpread(
            short_leg=OptionContract("SPY", expiration, 595.0, OptionType.PUT),
            long_leg=OptionContract("SPY", expiration, 590.0, OptionType.PUT)
        )
        call_spread = VerticalSpread(
            short_leg=OptionContract("SPY", expiration, 605.0, OptionType.CALL),
            long_leg=OptionContract("SPY", expiration, 610.0, OptionType.CALL)
        )
        
        position = IronCondor(
            id=1,
            underlying="SPY",
            expiration=expiration,
            put_spread=put_spread,
            call_spread=call_spread,
            contracts=2,
            status=ICPositionStatus.OPEN,
            entry_credit=1.35,
            entry_vix=18.0,
        )
        
        strategy.open_positions.append(position)
        return strategy
    
    def test_dte_safety_exit(self, strategy_with_position):
        """Test 2 DTE safety exit."""
        # Set expiration to 2 days from now
        position = strategy_with_position.open_positions[0]
        position.expiration = date.today() + timedelta(days=2)
        
        # Create mock for _fetch_spot_price
        strategy_with_position._fetch_spot_price = MagicMock(return_value=600.0)
        strategy_with_position._get_position_current_price = MagicMock(return_value=0.50)
        strategy_with_position._fetch_position_greeks = MagicMock(return_value=None)
        
        signals = strategy_with_position.check_exits()
        
        assert len(signals) == 1
        assert signals[0].reason == ICCloseReason.DTE_SAFETY
        assert signals[0].urgency == "HIGH"


# =============================================================================
# RUN TESTS
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
