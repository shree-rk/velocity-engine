"""
Tests for Technical Indicators Module
Run with: pytest tests/test_indicators.py -v
"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

from indicators.technical import (
    IndicatorSnapshot,
    calculate_sma,
    calculate_bollinger_bands,
    calculate_rsi,
    calculate_atr,
    calculate_adx,
    calculate_volume_ratio,
    calculate_all_indicators,
    calculate_indicators
)


# ============================================================================
# Test Fixtures
# ============================================================================

@pytest.fixture
def sample_ohlcv_df():
    """Create sample OHLCV DataFrame for testing."""
    np.random.seed(42)
    n = 50  # Need enough data for indicators
    
    dates = pd.date_range(end=datetime.now(), periods=n, freq='15min')
    
    # Generate realistic price data
    base_price = 100.0
    returns = np.random.randn(n) * 0.02  # 2% volatility
    prices = base_price * np.exp(np.cumsum(returns))
    
    df = pd.DataFrame({
        'open': prices * (1 + np.random.randn(n) * 0.005),
        'high': prices * (1 + np.abs(np.random.randn(n) * 0.01)),
        'low': prices * (1 - np.abs(np.random.randn(n) * 0.01)),
        'close': prices,
        'volume': np.random.randint(1000000, 5000000, n)
    }, index=dates)
    
    return df


@pytest.fixture
def oversold_df():
    """Create DataFrame with oversold conditions."""
    n = 50
    dates = pd.date_range(end=datetime.now(), periods=n, freq='15min')
    
    # Create declining prices to trigger oversold RSI
    prices = np.linspace(120, 95, n)  # Steady decline
    
    df = pd.DataFrame({
        'open': prices + 0.5,
        'high': prices + 1,
        'low': prices - 1,
        'close': prices,
        'volume': [3000000] * n  # High volume
    }, index=dates)
    
    return df


# ============================================================================
# IndicatorSnapshot Tests
# ============================================================================

class TestIndicatorSnapshot:
    """Tests for IndicatorSnapshot dataclass."""
    
    def test_snapshot_creation(self):
        """Snapshot can be created with all required fields."""
        snap = IndicatorSnapshot(
            symbol="TEST",
            price=100.0,
            sma_20=102.0,
            bb_upper=110.0,
            bb_lower=94.0,
            rsi_14=45.0,
            atr_14=2.5,
            adx_14=25.0,
            plus_di=20.0,
            minus_di=15.0,
            volume=2000000,
            avg_volume=1500000,
            volume_ratio=1.33
        )
        
        assert snap.symbol == "TEST"
        assert snap.price == 100.0
        assert snap.rsi_14 == 45.0
    
    def test_is_oversold(self):
        """is_oversold property works correctly."""
        oversold = IndicatorSnapshot(
            symbol="TEST", price=100, sma_20=105, bb_upper=110, bb_lower=95,
            rsi_14=25.0, atr_14=2, adx_14=25, plus_di=15, minus_di=20,
            volume=2000000, avg_volume=1500000, volume_ratio=1.33
        )
        
        not_oversold = IndicatorSnapshot(
            symbol="TEST", price=100, sma_20=105, bb_upper=110, bb_lower=95,
            rsi_14=55.0, atr_14=2, adx_14=25, plus_di=15, minus_di=20,
            volume=2000000, avg_volume=1500000, volume_ratio=1.33
        )
        
        assert oversold.is_oversold is True
        assert not_oversold.is_oversold is False
    
    def test_is_overbought(self):
        """is_overbought property works correctly."""
        overbought = IndicatorSnapshot(
            symbol="TEST", price=100, sma_20=105, bb_upper=110, bb_lower=95,
            rsi_14=75.0, atr_14=2, adx_14=25, plus_di=25, minus_di=15,
            volume=2000000, avg_volume=1500000, volume_ratio=1.33
        )
        
        assert overbought.is_overbought is True
    
    def test_is_below_lower_band(self):
        """is_below_lower_band property works correctly."""
        below = IndicatorSnapshot(
            symbol="TEST", price=93.0, sma_20=100, bb_upper=106, bb_lower=94,
            rsi_14=28, atr_14=2, adx_14=25, plus_di=15, minus_di=25,
            volume=2000000, avg_volume=1500000, volume_ratio=1.5
        )
        
        above = IndicatorSnapshot(
            symbol="TEST", price=100.0, sma_20=100, bb_upper=106, bb_lower=94,
            rsi_14=50, atr_14=2, adx_14=25, plus_di=20, minus_di=20,
            volume=2000000, avg_volume=1500000, volume_ratio=1.0
        )
        
        assert below.is_below_lower_band is True
        assert above.is_below_lower_band is False
    
    def test_is_trending(self):
        """is_trending property works correctly."""
        trending = IndicatorSnapshot(
            symbol="TEST", price=100, sma_20=100, bb_upper=106, bb_lower=94,
            rsi_14=50, atr_14=2, adx_14=28.0, plus_di=20, minus_di=15,
            volume=2000000, avg_volume=1500000, volume_ratio=1.0
        )
        
        ranging = IndicatorSnapshot(
            symbol="TEST", price=100, sma_20=100, bb_upper=106, bb_lower=94,
            rsi_14=50, atr_14=2, adx_14=15.0, plus_di=18, minus_di=17,
            volume=2000000, avg_volume=1500000, volume_ratio=1.0
        )
        
        assert trending.is_trending is True
        assert ranging.is_trending is False
    
    def test_has_volume_confirmation(self):
        """has_volume_confirmation property works correctly."""
        high_vol = IndicatorSnapshot(
            symbol="TEST", price=100, sma_20=100, bb_upper=106, bb_lower=94,
            rsi_14=50, atr_14=2, adx_14=25, plus_di=20, minus_di=15,
            volume=3000000, avg_volume=1500000, volume_ratio=2.0
        )
        
        low_vol = IndicatorSnapshot(
            symbol="TEST", price=100, sma_20=100, bb_upper=106, bb_lower=94,
            rsi_14=50, atr_14=2, adx_14=25, plus_di=20, minus_di=15,
            volume=1200000, avg_volume=1500000, volume_ratio=0.8
        )
        
        assert high_vol.has_volume_confirmation is True
        assert low_vol.has_volume_confirmation is False
    
    def test_conditions_met_count(self):
        """conditions_met_count counts correctly."""
        # All 4 conditions met
        all_met = IndicatorSnapshot(
            symbol="TEST", price=93.0, sma_20=100, bb_upper=106, bb_lower=94,
            rsi_14=25.0, atr_14=2, adx_14=25.0, plus_di=15, minus_di=25,
            volume=3000000, avg_volume=1500000, volume_ratio=2.0
        )
        
        assert all_met.conditions_met_count == 4
        assert all_met.all_entry_conditions_met is True
        
        # Only 2 conditions met (RSI oversold, ADX trending)
        some_met = IndicatorSnapshot(
            symbol="TEST", price=100.0, sma_20=100, bb_upper=106, bb_lower=94,
            rsi_14=25.0, atr_14=2, adx_14=25.0, plus_di=20, minus_di=15,
            volume=1200000, avg_volume=1500000, volume_ratio=0.8
        )
        
        assert some_met.conditions_met_count == 2
        assert some_met.all_entry_conditions_met is False


# ============================================================================
# Individual Indicator Tests
# ============================================================================

class TestIndividualIndicators:
    """Tests for individual indicator calculations."""
    
    def test_calculate_sma(self, sample_ohlcv_df):
        """SMA calculation works correctly."""
        sma = calculate_sma(sample_ohlcv_df, period=20)
        
        assert len(sma) == len(sample_ohlcv_df)
        assert pd.notna(sma.iloc[-1])
        # First 19 values should be NaN (need 20 periods)
        assert pd.isna(sma.iloc[0])
    
    def test_calculate_bollinger_bands(self, sample_ohlcv_df):
        """Bollinger Bands calculation works correctly."""
        lower, mid, upper = calculate_bollinger_bands(sample_ohlcv_df, 20, 2.0)
        
        assert len(lower) == len(sample_ohlcv_df)
        # Upper should be above mid, mid above lower
        last_idx = -1
        if pd.notna(upper.iloc[last_idx]):
            assert upper.iloc[last_idx] > mid.iloc[last_idx]
            assert mid.iloc[last_idx] > lower.iloc[last_idx]
    
    def test_calculate_rsi(self, sample_ohlcv_df):
        """RSI calculation works correctly."""
        rsi = calculate_rsi(sample_ohlcv_df, period=14)
        
        assert len(rsi) == len(sample_ohlcv_df)
        # RSI should be between 0 and 100
        valid_rsi = rsi.dropna()
        assert (valid_rsi >= 0).all()
        assert (valid_rsi <= 100).all()
    
    def test_calculate_atr(self, sample_ohlcv_df):
        """ATR calculation works correctly."""
        atr = calculate_atr(sample_ohlcv_df, period=14)
        
        assert len(atr) == len(sample_ohlcv_df)
        # ATR should be positive
        valid_atr = atr.dropna()
        assert (valid_atr > 0).all()
    
    def test_calculate_adx(self, sample_ohlcv_df):
        """ADX calculation works correctly."""
        adx, plus_di, minus_di = calculate_adx(sample_ohlcv_df, period=14)
        
        assert len(adx) == len(sample_ohlcv_df)
        # ADX should be between 0 and 100
        valid_adx = adx.dropna()
        assert (valid_adx >= 0).all()
        assert (valid_adx <= 100).all()
    
    def test_calculate_volume_ratio(self, sample_ohlcv_df):
        """Volume ratio calculation works correctly."""
        vol_ratio = calculate_volume_ratio(sample_ohlcv_df, period=20)
        
        assert len(vol_ratio) == len(sample_ohlcv_df)
        # Volume ratio should be positive
        valid_ratio = vol_ratio.dropna()
        assert (valid_ratio > 0).all()


# ============================================================================
# Combined Indicator Tests
# ============================================================================

class TestCombinedIndicators:
    """Tests for combined indicator functions."""
    
    def test_calculate_all_indicators(self, sample_ohlcv_df):
        """calculate_all_indicators adds all columns."""
        result = calculate_all_indicators(sample_ohlcv_df)
        
        expected_columns = [
            'sma_20', 'bb_lower', 'bb_mid', 'bb_upper',
            'rsi_14', 'atr_14', 'adx_14', 'plus_di', 'minus_di',
            'avg_volume', 'volume_ratio'
        ]
        
        for col in expected_columns:
            assert col in result.columns, f"Missing column: {col}"
    
    def test_calculate_indicators_returns_snapshot(self, sample_ohlcv_df):
        """calculate_indicators returns IndicatorSnapshot."""
        snapshot = calculate_indicators(sample_ohlcv_df, "TEST")
        
        assert snapshot is not None
        assert isinstance(snapshot, IndicatorSnapshot)
        assert snapshot.symbol == "TEST"
        assert snapshot.price > 0
    
    def test_calculate_indicators_with_short_df(self):
        """calculate_indicators returns None for insufficient data."""
        short_df = pd.DataFrame({
            'open': [100, 101],
            'high': [102, 103],
            'low': [99, 100],
            'close': [101, 102],
            'volume': [1000000, 1100000]
        })
        
        result = calculate_indicators(short_df, "TEST")
        assert result is None
    
    def test_calculate_indicators_with_none(self):
        """calculate_indicators returns None for None input."""
        result = calculate_indicators(None, "TEST")
        assert result is None


# ============================================================================
# Integration Tests
# ============================================================================

class TestIndicatorIntegration:
    """Integration tests for the indicators module."""
    
    def test_oversold_detection(self, oversold_df):
        """Can detect oversold conditions from real-ish data."""
        snapshot = calculate_indicators(oversold_df, "OVERSOLD_TEST")
        
        assert snapshot is not None
        # With declining prices, RSI should be low
        assert snapshot.rsi_14 < 50  # At least below neutral
    
    def test_indicator_consistency(self, sample_ohlcv_df):
        """Indicators are consistent across multiple calls."""
        snap1 = calculate_indicators(sample_ohlcv_df, "TEST")
        snap2 = calculate_indicators(sample_ohlcv_df, "TEST")
        
        assert snap1.price == snap2.price
        assert snap1.rsi_14 == snap2.rsi_14
        assert snap1.adx_14 == snap2.adx_14


if __name__ == "__main__":
    pytest.main([__file__, "-v"])