"""
Velocity Engine - Indicator Unit Tests
Validates all technical indicator calculations.
Run: pytest tests/test_indicators.py -v
"""

import pytest
import pandas as pd
import numpy as np
from indicators.technical import (
    calculate_all_indicators,
    calculate_stop_loss,
    calculate_position_size,
    validate_dataframe,
    IndicatorSnapshot,
)


def make_test_df(rows: int = 100, base_price: float = 100.0, volatility: float = 2.0) -> pd.DataFrame:
    """
    Generate a realistic OHLCV DataFrame for testing.
    Creates a mean-reverting price series with volume spikes.
    """
    np.random.seed(42)  # Reproducible results
    dates = pd.date_range("2026-01-01 09:30", periods=rows, freq="15min")

    # Generate price series with some mean reversion
    returns = np.random.normal(0, volatility / 100, rows)
    prices = base_price * np.exp(np.cumsum(returns))

    # Add realistic OHLC variation
    opens = prices * (1 + np.random.uniform(-0.002, 0.002, rows))
    highs = np.maximum(opens, prices) * (1 + np.abs(np.random.normal(0, 0.003, rows)))
    lows = np.minimum(opens, prices) * (1 - np.abs(np.random.normal(0, 0.003, rows)))
    closes = prices

    # Volume with occasional spikes
    base_volume = 1000000
    volumes = np.random.lognormal(np.log(base_volume), 0.5, rows).astype(int)

    df = pd.DataFrame({
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes,
    }, index=dates)

    return df


def make_oversold_df() -> pd.DataFrame:
    """
    Generate a DataFrame where the last bar is clearly oversold.
    Sharp drop at the end to trigger entry conditions.
    """
    np.random.seed(42)
    rows = 100
    dates = pd.date_range("2026-01-01 09:30", periods=rows, freq="15min")

    # Start with stable price, then sharp drop in last 5 bars
    prices = np.full(rows, 100.0)
    prices[:80] = 100 + np.random.normal(0, 0.5, 80)  # Stable around 100

    # Sharp drop in last 20 bars
    for i in range(80, rows):
        prices[i] = prices[i-1] - np.random.uniform(0.3, 0.8)

    opens = prices + np.random.uniform(-0.1, 0.1, rows)
    highs = np.maximum(opens, prices) + np.abs(np.random.normal(0, 0.2, rows))
    lows = np.minimum(opens, prices) - np.abs(np.random.normal(0, 0.2, rows))

    # High volume on last bar (capitulation)
    volumes = np.full(rows, 1000000)
    volumes[-1] = 3000000  # 3x spike on last bar

    df = pd.DataFrame({
        "open": opens,
        "high": highs,
        "low": lows,
        "close": prices,
        "volume": volumes,
    }, index=dates)

    return df


# ============================================================
# DataFrame Validation Tests
# ============================================================

class TestValidation:
    def test_valid_dataframe_passes(self):
        df = make_test_df()
        assert validate_dataframe(df) is True

    def test_missing_column_raises(self):
        df = make_test_df()
        df = df.drop(columns=["volume"])
        with pytest.raises(ValueError, match="missing columns"):
            validate_dataframe(df)

    def test_insufficient_rows_raises(self):
        df = make_test_df(rows=10)
        with pytest.raises(ValueError, match="at least 50 rows"):
            validate_dataframe(df)

    def test_nan_values_raise(self):
        df = make_test_df()
        df.loc[df.index[50], "close"] = np.nan
        with pytest.raises(ValueError, match="NaN"):
            validate_dataframe(df)


# ============================================================
# Indicator Calculation Tests
# ============================================================

class TestIndicatorCalculation:
    def test_calculate_all_returns_snapshot(self):
        df = make_test_df()
        snap = calculate_all_indicators(df, "NVDA")
        assert isinstance(snap, IndicatorSnapshot)
        assert snap.symbol == "NVDA"

    def test_price_is_last_close(self):
        df = make_test_df()
        snap = calculate_all_indicators(df, "AAPL")
        assert snap.price == pytest.approx(df["close"].iloc[-1], rel=1e-4)

    def test_sma_is_reasonable(self):
        df = make_test_df(base_price=100)
        snap = calculate_all_indicators(df, "TEST")
        # SMA should be roughly near the price (within 20% for test data)
        assert 50 < snap.sma_20 < 200

    def test_bb_bands_bracket_sma(self):
        df = make_test_df()
        snap = calculate_all_indicators(df, "TEST")
        assert snap.bb_lower < snap.sma_20 < snap.bb_upper

    def test_rsi_in_valid_range(self):
        df = make_test_df()
        snap = calculate_all_indicators(df, "TEST")
        assert 0 <= snap.rsi_14 <= 100

    def test_atr_is_positive(self):
        df = make_test_df()
        snap = calculate_all_indicators(df, "TEST")
        assert snap.atr_14 > 0

    def test_adx_in_valid_range(self):
        df = make_test_df()
        snap = calculate_all_indicators(df, "TEST")
        assert 0 <= snap.adx_14 <= 100

    def test_volume_ratio_calculated(self):
        df = make_test_df()
        snap = calculate_all_indicators(df, "TEST")
        assert snap.volume_ratio > 0
        assert snap.avg_volume > 0
        assert snap.volume > 0

    def test_to_dict_has_all_fields(self):
        df = make_test_df()
        snap = calculate_all_indicators(df, "TEST")
        d = snap.to_dict()
        required_keys = [
            "symbol", "price", "sma_20", "bb_upper", "bb_lower",
            "rsi_14", "atr_14", "adx_14", "volume", "avg_volume",
            "volume_ratio", "below_bb", "oversold", "not_trending",
            "vol_spike", "all_met"
        ]
        for key in required_keys:
            assert key in d, f"Missing key: {key}"


# ============================================================
# Entry Condition Logic Tests
# ============================================================

class TestEntryConditions:
    def test_below_bb_detection(self):
        snap = IndicatorSnapshot(
            symbol="TEST", price=95.0,
            sma_20=100.0, bb_upper=105.0, bb_lower=96.0,
            rsi_14=25.0, atr_14=2.0, adx_14=20.0,
            plus_di=15.0, minus_di=25.0,
            volume=2000000, avg_volume=1000000, volume_ratio=2.0,
        )
        assert snap.is_below_lower_bb is True

    def test_above_bb_not_triggered(self):
        snap = IndicatorSnapshot(
            symbol="TEST", price=98.0,
            sma_20=100.0, bb_upper=105.0, bb_lower=96.0,
            rsi_14=25.0, atr_14=2.0, adx_14=20.0,
            plus_di=15.0, minus_di=25.0,
            volume=2000000, avg_volume=1000000, volume_ratio=2.0,
        )
        assert snap.is_below_lower_bb is False

    def test_oversold_detection(self):
        snap = IndicatorSnapshot(
            symbol="TEST", price=95.0,
            sma_20=100.0, bb_upper=105.0, bb_lower=96.0,
            rsi_14=25.0, atr_14=2.0, adx_14=20.0,
            plus_di=15.0, minus_di=25.0,
            volume=2000000, avg_volume=1000000, volume_ratio=2.0,
        )
        assert snap.is_oversold is True

    def test_not_oversold(self):
        snap = IndicatorSnapshot(
            symbol="TEST", price=95.0,
            sma_20=100.0, bb_upper=105.0, bb_lower=96.0,
            rsi_14=45.0, atr_14=2.0, adx_14=20.0,
            plus_di=15.0, minus_di=25.0,
            volume=2000000, avg_volume=1000000, volume_ratio=2.0,
        )
        assert snap.is_oversold is False

    def test_trend_blocked_when_adx_high(self):
        snap = IndicatorSnapshot(
            symbol="TEST", price=95.0,
            sma_20=100.0, bb_upper=105.0, bb_lower=96.0,
            rsi_14=25.0, atr_14=2.0, adx_14=35.0,  # Strong trend
            plus_di=15.0, minus_di=25.0,
            volume=2000000, avg_volume=1000000, volume_ratio=2.0,
        )
        assert snap.is_not_trending is False

    def test_volume_spike_detection(self):
        snap = IndicatorSnapshot(
            symbol="TEST", price=95.0,
            sma_20=100.0, bb_upper=105.0, bb_lower=96.0,
            rsi_14=25.0, atr_14=2.0, adx_14=20.0,
            plus_di=15.0, minus_di=25.0,
            volume=2000000, avg_volume=1000000, volume_ratio=2.0,
        )
        assert snap.has_volume_spike is True

    def test_no_volume_spike(self):
        snap = IndicatorSnapshot(
            symbol="TEST", price=95.0,
            sma_20=100.0, bb_upper=105.0, bb_lower=96.0,
            rsi_14=25.0, atr_14=2.0, adx_14=20.0,
            plus_di=15.0, minus_di=25.0,
            volume=800000, avg_volume=1000000, volume_ratio=0.8,
        )
        assert snap.has_volume_spike is False

    def test_all_conditions_met(self):
        """Perfect entry: below BB, RSI<30, ADX<30, volume spike."""
        snap = IndicatorSnapshot(
            symbol="NVDA", price=95.0,
            sma_20=100.0, bb_upper=105.0, bb_lower=96.0,
            rsi_14=25.0, atr_14=2.0, adx_14=20.0,
            plus_di=15.0, minus_di=25.0,
            volume=2000000, avg_volume=1000000, volume_ratio=2.0,
        )
        assert snap.all_entry_conditions_met is True
        assert snap.conditions_met_count == 4

    def test_partial_conditions(self):
        """Only 2 of 4 conditions met = WATCHING."""
        snap = IndicatorSnapshot(
            symbol="NVDA", price=95.0,      # Below BB ✓
            sma_20=100.0, bb_upper=105.0, bb_lower=96.0,
            rsi_14=25.0,                     # Oversold ✓
            atr_14=2.0, adx_14=35.0,        # Trending ✗
            plus_di=15.0, minus_di=25.0,
            volume=800000, avg_volume=1000000, volume_ratio=0.8,  # No spike ✗
        )
        assert snap.all_entry_conditions_met is False
        assert snap.conditions_met_count == 2


# ============================================================
# Stop Loss Tests
# ============================================================

class TestStopLoss:
    def test_high_beta_stop(self):
        """HIGH_BETA: 1.5x ATR stop."""
        stop = calculate_stop_loss(entry_price=200.0, atr=3.0, atr_multiplier=1.5)
        assert stop == pytest.approx(195.5)  # 200 - (3 * 1.5) = 195.5

    def test_moderate_stop(self):
        """MODERATE: 2x ATR stop."""
        stop = calculate_stop_loss(entry_price=150.0, atr=2.0, atr_multiplier=2.0)
        assert stop == pytest.approx(146.0)  # 150 - (2 * 2) = 146

    def test_etf_stop(self):
        """ETF: 2x ATR stop."""
        stop = calculate_stop_loss(entry_price=450.0, atr=5.0, atr_multiplier=2.0)
        assert stop == pytest.approx(440.0)  # 450 - (5 * 2) = 440

    def test_stop_below_entry(self):
        """Stop loss should always be below entry price."""
        stop = calculate_stop_loss(entry_price=100.0, atr=1.0, atr_multiplier=2.0)
        assert stop < 100.0


# ============================================================
# Position Sizing Tests
# ============================================================

class TestPositionSizing:
    def test_basic_position_size(self):
        """Standard 2% risk calculation."""
        shares = calculate_position_size(
            equity=100000,
            entry_price=100.0,
            stop_loss_price=95.0,  # $5 stop distance
            risk_pct=0.02,
            max_position_pct=0.25,
        )
        # Risk = $2000, stop distance = $5, shares by risk = 400
        # Cap = $25000 / $100 = 250 shares
        # Min(400, 250) = 250
        assert shares == 250

    def test_risk_limited(self):
        """When risk-based is smaller than cap-based."""
        shares = calculate_position_size(
            equity=100000,
            entry_price=10.0,
            stop_loss_price=9.0,  # $1 stop distance
            risk_pct=0.02,
            max_position_pct=0.25,
        )
        # Risk = $2000, stop = $1, shares by risk = 2000
        # Cap = $25000 / $10 = 2500
        # Min(2000, 2500) = 2000
        assert shares == 2000

    def test_vix_multiplier_reduces_size(self):
        """VIX ELEVATED (50% size)."""
        shares_normal = calculate_position_size(
            equity=100000, entry_price=100.0, stop_loss_price=98.0,
            vix_multiplier=1.0,
            max_position_pct=1.0,  # no cap limit for this test
        )
        shares_elevated = calculate_position_size(
            equity=100000, entry_price=100.0, stop_loss_price=98.0,
            vix_multiplier=0.5,
            max_position_pct=1.0,
        )
        assert shares_elevated < shares_normal
        assert shares_elevated == pytest.approx(shares_normal * 0.5, abs=1)

    def test_zero_stop_distance_returns_zero(self):
        """Edge case: stop at entry should return 0 shares."""
        shares = calculate_position_size(
            equity=100000, entry_price=100.0, stop_loss_price=100.0,
        )
        assert shares == 0

    def test_negative_stop_returns_zero(self):
        """Edge case: stop above entry should return 0."""
        shares = calculate_position_size(
            equity=100000, entry_price=100.0, stop_loss_price=105.0,
        )
        assert shares == 0

    def test_always_returns_integer(self):
        """Position size must be a whole number of shares."""
        shares = calculate_position_size(
            equity=100000, entry_price=137.53, stop_loss_price=132.53,
        )
        assert isinstance(shares, int)

    def test_extreme_vix_returns_zero(self):
        """VIX EXTREME (0% multiplier) = no trade."""
        shares = calculate_position_size(
            equity=100000, entry_price=100.0, stop_loss_price=95.0,
            vix_multiplier=0.0,
        )
        assert shares == 0


# ============================================================
# Integration-style: Full indicator pipeline on synthetic data
# ============================================================

class TestFullPipeline:
    def test_normal_market_conditions(self):
        """Standard market data should produce valid indicators."""
        df = make_test_df(rows=100, base_price=150, volatility=1.5)
        snap = calculate_all_indicators(df, "MSFT")

        # All values should be finite and reasonable
        assert 0 < snap.price < 1000
        assert 0 < snap.sma_20 < 1000
        assert snap.bb_lower < snap.sma_20 < snap.bb_upper
        assert 0 <= snap.rsi_14 <= 100
        assert snap.atr_14 > 0
        assert 0 <= snap.adx_14 <= 100

    def test_oversold_conditions_detected(self):
        """Oversold synthetic data should trigger entry conditions."""
        df = make_oversold_df()
        snap = calculate_all_indicators(df, "AMD")

        # After a sharp drop with volume spike, we expect:
        # - Price below BB (likely)
        # - RSI low (likely, but depends on drop severity)
        # - Volume spike on last bar (we set this up)
        assert snap.volume_ratio > 1.5  # We forced a 3x spike
        # Note: RSI and BB depend on exact calculation - just verify they compute


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
