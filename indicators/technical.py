"""
Velocity Engine - Technical Indicators
Calculates all indicators used by Velocity 2.0 strategy.
Uses pandas-ta for battle-tested implementations.

All functions take a pandas DataFrame with columns: open, high, low, close, volume
and return the indicator values for the LATEST bar.
"""

import pandas as pd
import pandas_ta as ta
import numpy as np
from dataclasses import dataclass
from typing import Optional

from config.settings import (
    BB_PERIOD, BB_STD_DEV, RSI_PERIOD, ATR_PERIOD,
    ADX_PERIOD, SMA_PERIOD, VOLUME_AVG_PERIOD
)


@dataclass
class IndicatorSnapshot:
    """All indicator values for a single symbol at a point in time."""
    symbol: str
    price: float
    sma_20: float
    bb_upper: float
    bb_lower: float
    rsi_14: float
    atr_14: float
    adx_14: float
    plus_di: float
    minus_di: float
    volume: float
    avg_volume: float
    volume_ratio: float
    timestamp: Optional[pd.Timestamp] = None

    @property
    def is_below_lower_bb(self) -> bool:
        """Price is below Lower Bollinger Band."""
        return self.price < self.bb_lower

    @property
    def is_oversold(self) -> bool:
        """RSI indicates oversold condition."""
        return self.rsi_14 < 30

    @property
    def is_not_trending(self) -> bool:
        """ADX indicates no strong trend (safe for mean reversion)."""
        return self.adx_14 < 30

    @property
    def has_volume_spike(self) -> bool:
        """Volume is >= 1.5x the 20-period average."""
        return self.volume_ratio >= 1.5

    @property
    def all_entry_conditions_met(self) -> bool:
        """All 4 technical entry conditions for Velocity 2.0."""
        return (
            self.is_below_lower_bb
            and self.is_oversold
            and self.is_not_trending
            and self.has_volume_spike
        )

    @property
    def conditions_met_count(self) -> int:
        """How many of the 4 entry conditions are met (for WATCHING status)."""
        return sum([
            self.is_below_lower_bb,
            self.is_oversold,
            self.is_not_trending,
            self.has_volume_spike,
        ])

    def to_dict(self) -> dict:
        """Convert to dictionary for logging/storage."""
        return {
            "symbol": self.symbol,
            "price": round(self.price, 4),
            "sma_20": round(self.sma_20, 4),
            "bb_upper": round(self.bb_upper, 4),
            "bb_lower": round(self.bb_lower, 4),
            "rsi_14": round(self.rsi_14, 2),
            "atr_14": round(self.atr_14, 4),
            "adx_14": round(self.adx_14, 2),
            "plus_di": round(self.plus_di, 2),
            "minus_di": round(self.minus_di, 2),
            "volume": self.volume,
            "avg_volume": round(self.avg_volume, 0),
            "volume_ratio": round(self.volume_ratio, 2),
            "below_bb": self.is_below_lower_bb,
            "oversold": self.is_oversold,
            "not_trending": self.is_not_trending,
            "vol_spike": self.has_volume_spike,
            "all_met": self.all_entry_conditions_met,
        }


def validate_dataframe(df: pd.DataFrame, min_rows: int = 50) -> bool:
    """
    Validate that the DataFrame has the required columns and enough data.
    We need at least 50 rows for reliable indicator calculation
    (20 for BB/SMA + buffer for ATR/RSI warm-up).
    """
    required_cols = {"open", "high", "low", "close", "volume"}
    if not required_cols.issubset(set(df.columns)):
        missing = required_cols - set(df.columns)
        raise ValueError(f"DataFrame missing columns: {missing}")

    if len(df) < min_rows:
        raise ValueError(
            f"Need at least {min_rows} rows for indicator calculation, got {len(df)}"
        )

    if df["close"].isna().any():
        raise ValueError("DataFrame contains NaN values in 'close' column")

    return True


def calculate_bollinger_bands(df: pd.DataFrame) -> tuple[pd.Series, pd.Series, pd.Series]:
    """
    Calculate Bollinger Bands (20-period, 2 std dev).
    Returns: (lower_band, middle_band/SMA, upper_band)
    """
    bbands = df.ta.bbands(length=BB_PERIOD, std=BB_STD_DEV)
    # pandas-ta returns columns: BBL_20_2.0, BBM_20_2.0, BBU_20_2.0, BBB_20_2.0, BBP_20_2.0
    col_lower = f"BBL_{BB_PERIOD}_{BB_STD_DEV}_{BB_STD_DEV}"
    col_mid = f"BBM_{BB_PERIOD}_{BB_STD_DEV}_{BB_STD_DEV}"
    col_upper = f"BBU_{BB_PERIOD}_{BB_STD_DEV}_{BB_STD_DEV}"
    return bbands[col_lower], bbands[col_mid], bbands[col_upper]


def calculate_rsi(df: pd.DataFrame) -> pd.Series:
    """Calculate RSI (14-period)."""
    return df.ta.rsi(length=RSI_PERIOD)


def calculate_atr(df: pd.DataFrame) -> pd.Series:
    """Calculate ATR (14-period)."""
    return df.ta.atr(length=ATR_PERIOD)


def calculate_adx(df: pd.DataFrame) -> tuple[pd.Series, pd.Series, pd.Series]:
    """
    Calculate ADX with +DI and -DI (14-period).
    Returns: (adx, plus_di, minus_di)
    """
    adx_df = df.ta.adx(length=ADX_PERIOD)
    # pandas-ta returns: ADX_14, DMP_14, DMN_14
    col_adx = f"ADX_{ADX_PERIOD}"
    col_dmp = f"DMP_{ADX_PERIOD}"
    col_dmn = f"DMN_{ADX_PERIOD}"
    return adx_df[col_adx], adx_df[col_dmp], adx_df[col_dmn]


def calculate_sma(df: pd.DataFrame) -> pd.Series:
    """Calculate SMA (20-period) - same as BB middle band."""
    return df.ta.sma(length=SMA_PERIOD)


def calculate_volume_ratio(df: pd.DataFrame) -> tuple[float, float, float]:
    """
    Calculate volume ratio for the latest bar.
    Returns: (current_volume, average_volume, ratio)
    """
    current_vol = float(df["volume"].iloc[-1])
    avg_vol = float(df["volume"].rolling(window=VOLUME_AVG_PERIOD).mean().iloc[-1])

    if avg_vol == 0:
        return current_vol, avg_vol, 0.0

    ratio = current_vol / avg_vol
    return current_vol, avg_vol, ratio


def calculate_all_indicators(df: pd.DataFrame, symbol: str) -> IndicatorSnapshot:
    """
    Calculate ALL indicators for a symbol and return a snapshot.
    This is the main function called by the strategy scanner.

    Args:
        df: DataFrame with OHLCV data (at least 50 rows of 15-min candles)
        symbol: Ticker symbol (for labeling)

    Returns:
        IndicatorSnapshot with all values for the latest bar
    """
    # Validate input
    validate_dataframe(df)

    # Ensure columns are lowercase (Alpaca sometimes capitalizes)
    df.columns = [c.lower() for c in df.columns]

    # Calculate all indicators
    bb_lower, bb_mid, bb_upper = calculate_bollinger_bands(df)
    rsi = calculate_rsi(df)
    atr = calculate_atr(df)
    adx, plus_di, minus_di = calculate_adx(df)
    sma = calculate_sma(df)
    current_vol, avg_vol, vol_ratio = calculate_volume_ratio(df)

    # Get latest values (last row)
    latest_idx = -1

    snapshot = IndicatorSnapshot(
        symbol=symbol,
        price=float(df["close"].iloc[latest_idx]),
        sma_20=float(sma.iloc[latest_idx]) if not pd.isna(sma.iloc[latest_idx]) else 0.0,
        bb_upper=float(bb_upper.iloc[latest_idx]) if not pd.isna(bb_upper.iloc[latest_idx]) else 0.0,
        bb_lower=float(bb_lower.iloc[latest_idx]) if not pd.isna(bb_lower.iloc[latest_idx]) else 0.0,
        rsi_14=float(rsi.iloc[latest_idx]) if not pd.isna(rsi.iloc[latest_idx]) else 50.0,
        atr_14=float(atr.iloc[latest_idx]) if not pd.isna(atr.iloc[latest_idx]) else 0.0,
        adx_14=float(adx.iloc[latest_idx]) if not pd.isna(adx.iloc[latest_idx]) else 0.0,
        plus_di=float(plus_di.iloc[latest_idx]) if not pd.isna(plus_di.iloc[latest_idx]) else 0.0,
        minus_di=float(minus_di.iloc[latest_idx]) if not pd.isna(minus_di.iloc[latest_idx]) else 0.0,
        volume=current_vol,
        avg_volume=avg_vol,
        volume_ratio=vol_ratio,
        timestamp=df.index[latest_idx] if isinstance(df.index, pd.DatetimeIndex) else None,
    )

    return snapshot


def calculate_stop_loss(entry_price: float, atr: float, atr_multiplier: float) -> float:
    """
    Calculate stop loss price.
    Stop = entry_price - (ATR x category_multiplier)

    Args:
        entry_price: The price at which the position was entered
        atr: Current ATR(14) value
        atr_multiplier: Category-specific multiplier (1.5x for HIGH_BETA, 2x for MODERATE/ETF)

    Returns:
        Stop loss price
    """
    stop_distance = atr * atr_multiplier
    return entry_price - stop_distance


def calculate_position_size(
    equity: float,
    entry_price: float,
    stop_loss_price: float,
    risk_pct: float = 0.02,
    max_position_pct: float = 0.25,
    vix_multiplier: float = 1.0,
) -> int:
    """
    Calculate number of shares to buy using the 2% risk rule.

    Formula:
        risk_amount = equity * risk_pct * vix_multiplier
        stop_distance = entry_price - stop_loss_price
        shares_by_risk = risk_amount / stop_distance
        shares_by_cap = (equity * max_position_pct) / entry_price
        final_shares = min(shares_by_risk, shares_by_cap)

    Args:
        equity: Current portfolio equity
        entry_price: Expected entry price
        stop_loss_price: Calculated stop loss price
        risk_pct: Risk per trade (default 2%)
        max_position_pct: Max position as % of equity (default 25%)
        vix_multiplier: Position size multiplier from VIX regime

    Returns:
        Number of shares (integer, rounded down)
    """
    if entry_price <= 0 or stop_loss_price >= entry_price:
        return 0

    # Risk-based sizing
    risk_amount = equity * risk_pct * vix_multiplier
    stop_distance = entry_price - stop_loss_price

    if stop_distance <= 0:
        return 0

    shares_by_risk = risk_amount / stop_distance

    # Cap-based sizing
    max_position_value = equity * max_position_pct
    shares_by_cap = max_position_value / entry_price

    # Take the smaller of the two
    final_shares = min(shares_by_risk, shares_by_cap)

    # Round down to whole shares
    return max(0, int(final_shares))
