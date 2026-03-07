"""
Technical Indicators Module
Calculates all indicators needed for the Velocity Mean Reversion strategy.

Indicators:
- SMA (20-period)
- Bollinger Bands (20-period, 2 std dev)
- RSI (14-period)
- ATR (14-period)
- ADX with +DI/-DI (14-period)
- Volume ratio (current vs 20-period average)
"""

from dataclasses import dataclass
from typing import Optional

import pandas as pd
import pandas_ta as ta


@dataclass
class IndicatorSnapshot:
    """
    Point-in-time snapshot of all indicator values for a symbol.
    
    This is what gets passed to the strategy for signal generation.
    """
    # Required fields (no defaults) - must come first
    symbol: str
    price: float
    
    # Moving Averages
    sma_20: float
    
    # Bollinger Bands
    bb_upper: float
    bb_lower: float
    
    # Momentum
    rsi_14: float
    
    # Volatility
    atr_14: float
    
    # Trend Strength
    adx_14: float
    plus_di: float
    minus_di: float
    
    # Volume
    volume: float
    avg_volume: float
    volume_ratio: float
    
    # Optional fields (with defaults) - must come last
    bb_mid: float = 0.0  # Same as SMA-20
    
    @property
    def is_oversold(self) -> bool:
        """Check if RSI indicates oversold condition."""
        return self.rsi_14 < 30
    
    @property
    def is_overbought(self) -> bool:
        """Check if RSI indicates overbought condition."""
        return self.rsi_14 > 70
    
    @property
    def is_below_lower_band(self) -> bool:
        """Check if price is at or below lower Bollinger Band."""
        return self.price <= self.bb_lower
    
    @property
    def is_trending(self) -> bool:
        """Check if ADX indicates a trend (> 20)."""
        return self.adx_14 > 20
    
    @property
    def has_volume_confirmation(self) -> bool:
        """Check if volume is above average (1.5x)."""
        return self.volume_ratio >= 1.5
    
    @property
    def conditions_met_count(self) -> int:
        """Count how many entry conditions are met."""
        count = 0
        if self.is_below_lower_band:
            count += 1
        if self.is_oversold:
            count += 1
        if self.is_trending:
            count += 1
        if self.has_volume_confirmation:
            count += 1
        return count
    
    @property
    def all_entry_conditions_met(self) -> bool:
        """Check if all 4 entry conditions are met."""
        return self.conditions_met_count == 4


def calculate_sma(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """Calculate Simple Moving Average."""
    return ta.sma(df['close'], length=period)


def calculate_bollinger_bands(
    df: pd.DataFrame,
    period: int = 20,
    std_dev: float = 2.0
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """
    Calculate Bollinger Bands.
    
    Returns:
        Tuple of (lower_band, mid_band, upper_band)
    """
    bbands = ta.bbands(df['close'], length=period, std=std_dev)
    
    if bbands is None or bbands.empty:
        empty = pd.Series([None] * len(df), index=df.index)
        return empty, empty, empty
    
    # pandas_ta bbands column names vary by version
    # Could be: BBL_20_2.0, BBM_20_2.0, BBU_20_2.0
    # Or: BBL_20_2, BBM_20_2, BBU_20_2 (without decimal)
    # Find columns by prefix
    cols = bbands.columns.tolist()
    
    lower_col = None
    mid_col = None
    upper_col = None
    
    for col in cols:
        if col.startswith('BBL'):
            lower_col = col
        elif col.startswith('BBM'):
            mid_col = col
        elif col.startswith('BBU'):
            upper_col = col
    
    if lower_col and mid_col and upper_col:
        return bbands[lower_col], bbands[mid_col], bbands[upper_col]
    
    # Fallback: return empty series
    empty = pd.Series([None] * len(df), index=df.index)
    return empty, empty, empty


def calculate_rsi(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Calculate Relative Strength Index."""
    return ta.rsi(df['close'], length=period)


def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Calculate Average True Range."""
    return ta.atr(df['high'], df['low'], df['close'], length=period)


def calculate_adx(
    df: pd.DataFrame,
    period: int = 14
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """
    Calculate ADX with Directional Indicators.
    
    Returns:
        Tuple of (adx, plus_di, minus_di)
    """
    adx_data = ta.adx(df['high'], df['low'], df['close'], length=period)
    
    if adx_data is None:
        return pd.Series(), pd.Series(), pd.Series()
    
    # Column names: ADX_14, DMP_14, DMN_14
    adx_col = f'ADX_{period}'
    plus_di_col = f'DMP_{period}'
    minus_di_col = f'DMN_{period}'
    
    return adx_data[adx_col], adx_data[plus_di_col], adx_data[minus_di_col]


def calculate_volume_ratio(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """Calculate volume ratio (current volume / average volume)."""
    avg_volume = df['volume'].rolling(window=period).mean()
    return df['volume'] / avg_volume


def calculate_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calculate all indicators and add them to the dataframe.
    
    Args:
        df: DataFrame with OHLCV columns (open, high, low, close, volume)
        
    Returns:
        DataFrame with indicator columns added
    """
    result = df.copy()
    
    # Ensure lowercase column names
    result.columns = [c.lower() for c in result.columns]
    
    # SMA
    result['sma_20'] = calculate_sma(result, 20)
    
    # Bollinger Bands
    bb_lower, bb_mid, bb_upper = calculate_bollinger_bands(result, 20, 2.0)
    result['bb_lower'] = bb_lower
    result['bb_mid'] = bb_mid
    result['bb_upper'] = bb_upper
    
    # RSI
    result['rsi_14'] = calculate_rsi(result, 14)
    
    # ATR
    result['atr_14'] = calculate_atr(result, 14)
    
    # ADX
    adx, plus_di, minus_di = calculate_adx(result, 14)
    result['adx_14'] = adx
    result['plus_di'] = plus_di
    result['minus_di'] = minus_di
    
    # Volume
    result['avg_volume'] = result['volume'].rolling(window=20).mean()
    result['volume_ratio'] = calculate_volume_ratio(result, 20)
    
    return result


def calculate_indicators(df: pd.DataFrame, symbol: str) -> Optional[IndicatorSnapshot]:
    """
    Calculate all indicators and return a snapshot of the latest values.
    
    This is the main function used by the strategy.
    
    Args:
        df: DataFrame with OHLCV data
        symbol: Stock symbol
        
    Returns:
        IndicatorSnapshot with latest values, or None if calculation fails
    """
    if df is None or len(df) < 20:
        return None
    
    try:
        # Calculate all indicators
        result = calculate_all_indicators(df)
        
        # Get the latest row
        latest = result.iloc[-1]
        
        # Build snapshot - all required fields must be provided
        return IndicatorSnapshot(
            symbol=symbol,
            price=float(latest['close']),
            sma_20=float(latest['sma_20']) if pd.notna(latest['sma_20']) else 0.0,
            bb_upper=float(latest['bb_upper']) if pd.notna(latest['bb_upper']) else 0.0,
            bb_lower=float(latest['bb_lower']) if pd.notna(latest['bb_lower']) else 0.0,
            rsi_14=float(latest['rsi_14']) if pd.notna(latest['rsi_14']) else 50.0,
            atr_14=float(latest['atr_14']) if pd.notna(latest['atr_14']) else 0.0,
            adx_14=float(latest['adx_14']) if pd.notna(latest['adx_14']) else 0.0,
            plus_di=float(latest['plus_di']) if pd.notna(latest['plus_di']) else 0.0,
            minus_di=float(latest['minus_di']) if pd.notna(latest['minus_di']) else 0.0,
            volume=float(latest['volume']) if pd.notna(latest['volume']) else 0.0,
            avg_volume=float(latest['avg_volume']) if pd.notna(latest['avg_volume']) else 0.0,
            volume_ratio=float(latest['volume_ratio']) if pd.notna(latest['volume_ratio']) else 0.0,
            bb_mid=float(latest['bb_mid']) if pd.notna(latest['bb_mid']) else 0.0
        )
        
    except Exception as e:
        print(f"Error calculating indicators for {symbol}: {e}")
        return None


def get_latest_snapshot(df: pd.DataFrame, symbol: str) -> Optional[IndicatorSnapshot]:
    """
    Alias for calculate_indicators for backwards compatibility.
    """
    return calculate_indicators(df, symbol)