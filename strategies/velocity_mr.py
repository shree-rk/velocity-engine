"""
Velocity Mean Reversion Strategy
15-minute candle mean reversion using Bollinger Bands, RSI, ADX, and Volume.

Entry Conditions (ALL must be met):
1. Price below lower Bollinger Band (oversold)
2. RSI < 30 (oversold confirmation)
3. ADX > 20 (trending, not choppy)
4. Volume > 1.5x average (institutional interest)

Exit Conditions:
- Stop Loss: ATR-based (1.5x for high beta, 2x for moderate/ETF)
- Take Profit: Price returns to SMA-20 (mean reversion target)
- Time-based: Optional max hold period
"""

import logging
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

import yfinance as yf
import pandas as pd

from strategies.base import BaseStrategy, TradeSignal, SignalDirection
from indicators.technical import calculate_indicators, IndicatorSnapshot
from config.watchlists import (
    VELOCITY_MR_WATCHLIST,
    get_stock_config,
    get_all_symbols,
    StockCategory
)
from config.settings import (
    RISK_PER_TRADE,
    MAX_POSITION_SIZE_PCT
)

logger = logging.getLogger(__name__)


class VelocityMRStrategy(BaseStrategy):
    """
    Velocity Mean Reversion Strategy.
    
    Scans for oversold conditions with volume confirmation
    and trades the bounce back to the mean (SMA-20).
    """
    
    # Strategy parameters
    RSI_OVERSOLD = 30
    RSI_OVERBOUGHT = 70
    ADX_MIN = 20
    VOLUME_RATIO_MIN = 1.5
    BB_OVERSOLD_PCT = 0.0  # At or below lower band
    
    # ATR stop multipliers by category
    ATR_MULTIPLIERS = {
        StockCategory.HIGH_BETA: 1.5,
        StockCategory.MODERATE: 2.0,
        StockCategory.ETF: 2.0
    }
    
    def __init__(self, watchlist: Dict = None):
        """
        Initialize Velocity MR strategy.
        
        Args:
            watchlist: Optional custom watchlist. Uses default if not provided.
        """
        super().__init__(name="velocity_mr")
        
        self.watchlist = watchlist or VELOCITY_MR_WATCHLIST
        self.symbols = get_all_symbols(self.watchlist)
        
        logger.info(
            f"VelocityMR initialized with {len(self.symbols)} symbols: {self.symbols}"
        )
    
    def _fetch_market_data(
        self,
        symbol: str,
        period: str = "5d",
        interval: str = "15m"
    ) -> Optional[pd.DataFrame]:
        """
        Fetch market data from Yahoo Finance.
        
        Args:
            symbol: Stock symbol.
            period: Data period (e.g., "5d", "1mo").
            interval: Candle interval (e.g., "15m", "1h").
            
        Returns:
            DataFrame with OHLCV data or None if fetch fails.
        """
        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(period=period, interval=interval)
            
            if df.empty:
                logger.warning(f"No data returned for {symbol}")
                return None
            
            # Standardize column names
            df.columns = [c.lower() for c in df.columns]
            
            return df
            
        except Exception as e:
            logger.error(f"Failed to fetch data for {symbol}: {e}")
            return None
    
    def _calculate_bb_position(
        self,
        price: float,
        bb_upper: float,
        bb_lower: float
    ) -> float:
        """
        Calculate price position within Bollinger Bands.
        
        Returns:
            0.0 = at lower band, 1.0 = at upper band, 0.5 = at middle
        """
        if bb_upper == bb_lower:
            return 0.5
        
        return (price - bb_lower) / (bb_upper - bb_lower)
    
    def _check_entry_conditions(
        self,
        snapshot: IndicatorSnapshot
    ) -> tuple[bool, int, str]:
        """
        Check if entry conditions are met.
        
        Args:
            snapshot: Current indicator values.
            
        Returns:
            Tuple of (all_met, conditions_count, reason_string)
        """
        conditions = []
        reasons = []
        
        # Condition 1: Price below lower BB
        bb_position = self._calculate_bb_position(
            snapshot.price,
            snapshot.bb_upper,
            snapshot.bb_lower
        )
        
        if bb_position <= self.BB_OVERSOLD_PCT:
            conditions.append(True)
            reasons.append(f"BB:{bb_position:.2%}")
        else:
            conditions.append(False)
        
        # Condition 2: RSI oversold
        if snapshot.rsi_14 < self.RSI_OVERSOLD:
            conditions.append(True)
            reasons.append(f"RSI:{snapshot.rsi_14:.1f}")
        else:
            conditions.append(False)
        
        # Condition 3: ADX showing trend
        if snapshot.adx_14 > self.ADX_MIN:
            conditions.append(True)
            reasons.append(f"ADX:{snapshot.adx_14:.1f}")
        else:
            conditions.append(False)
        
        # Condition 4: Volume confirmation
        if snapshot.volume_ratio >= self.VOLUME_RATIO_MIN:
            conditions.append(True)
            reasons.append(f"Vol:{snapshot.volume_ratio:.1f}x")
        else:
            conditions.append(False)
        
        all_met = all(conditions)
        count = sum(conditions)
        reason = " | ".join(reasons) if reasons else "No conditions met"
        
        return all_met, count, reason
    
    def _get_atr_multiplier(self, symbol: str) -> float:
        """Get ATR stop multiplier for symbol based on category."""
        config = get_stock_config(symbol, self.watchlist)
        
        if config:
            return self.ATR_MULTIPLIERS.get(config.category, 2.0)
        
        return 2.0  # Default
    
    def scan(self, symbols: List[str] = None) -> List[TradeSignal]:
        """
        Scan symbols for entry signals.
        
        Args:
            symbols: Optional list of symbols. Uses watchlist if not provided.
            
        Returns:
            List of TradeSignal objects for valid entries.
        """
        if not self.enabled:
            logger.info("VelocityMR strategy is disabled, skipping scan")
            return []
        
        scan_symbols = symbols or self.symbols
        signals = []
        
        logger.info(f"Scanning {len(scan_symbols)} symbols for entry signals...")
        
        for symbol in scan_symbols:
            try:
                signal = self._scan_symbol(symbol)
                if signal:
                    signals.append(signal)
                    logger.info(
                        f"SIGNAL: {symbol} - {signal.reason} "
                        f"(strength: {signal.signal_strength:.2f})"
                    )
            except Exception as e:
                logger.error(f"Error scanning {symbol}: {e}")
        
        logger.info(f"Scan complete: {len(signals)} signals found")
        return signals
    
    def _scan_symbol(self, symbol: str) -> Optional[TradeSignal]:
        """
        Scan a single symbol for entry signal.
        
        Args:
            symbol: Stock symbol to scan.
            
        Returns:
            TradeSignal if conditions met, None otherwise.
        """
        # Fetch data
        df = self._fetch_market_data(symbol)
        if df is None or len(df) < 20:
            return None
        
        # Calculate indicators
        snapshot = calculate_indicators(df, symbol)
        if snapshot is None:
            return None
        
        # Check entry conditions
        all_met, count, reason = self._check_entry_conditions(snapshot)
        
        if not all_met:
            logger.debug(f"{symbol}: {count}/4 conditions - {reason}")
            return None
        
        # Calculate stop loss
        atr_mult = self._get_atr_multiplier(symbol)
        stop_loss = snapshot.price - (snapshot.atr_14 * atr_mult)
        
        # Take profit at SMA-20 (mean reversion target)
        take_profit = snapshot.sma_20
        
        # Calculate signal strength (0.5 - 1.0 based on oversold intensity)
        rsi_strength = (self.RSI_OVERSOLD - snapshot.rsi_14) / self.RSI_OVERSOLD
        vol_strength = min(snapshot.volume_ratio / 3.0, 1.0)  # Cap at 3x
        signal_strength = 0.5 + (0.25 * rsi_strength) + (0.25 * vol_strength)
        
        bb_position = self._calculate_bb_position(
            snapshot.price,
            snapshot.bb_upper,
            snapshot.bb_lower
        )
        
        return TradeSignal(
            symbol=symbol,
            direction=SignalDirection.LONG,
            strategy_name=self.name,
            entry_price=snapshot.price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            atr=snapshot.atr_14,
            risk_per_share=snapshot.price - stop_loss,
            signal_strength=signal_strength,
            conditions_met=count,
            total_conditions=4,
            rsi=snapshot.rsi_14,
            bb_position=bb_position,
            adx=snapshot.adx_14,
            volume_ratio=snapshot.volume_ratio,
            reason=reason,
            indicators={
                "sma_20": snapshot.sma_20,
                "bb_upper": snapshot.bb_upper,
                "bb_lower": snapshot.bb_lower,
                "plus_di": snapshot.plus_di,
                "minus_di": snapshot.minus_di,
                "volume": snapshot.volume,
                "avg_volume": snapshot.avg_volume
            }
        )
    
    def check_exit(
        self,
        symbol: str,
        entry_price: float,
        current_price: float,
        stop_loss: float,
        take_profit: Optional[float] = None
    ) -> Optional[TradeSignal]:
        """
        Check if position should be exited.
        
        Exit conditions:
        1. Stop loss hit
        2. Take profit hit (price >= SMA-20)
        3. RSI overbought (> 70)
        
        Args:
            symbol: Position symbol.
            entry_price: Entry price.
            current_price: Current price.
            stop_loss: Stop loss price.
            take_profit: Take profit price (SMA-20).
            
        Returns:
            Exit signal if should exit, None otherwise.
        """
        exit_reason = None
        
        # Check stop loss
        if current_price <= stop_loss:
            exit_reason = f"STOP_LOSS: {current_price:.2f} <= {stop_loss:.2f}"
        
        # Check take profit
        elif take_profit and current_price >= take_profit:
            exit_reason = f"TAKE_PROFIT: {current_price:.2f} >= {take_profit:.2f}"
        
        # Check RSI overbought (fetch fresh data)
        else:
            df = self._fetch_market_data(symbol, period="2d", interval="15m")
            if df is not None and len(df) >= 14:
                snapshot = calculate_indicators(df, symbol)
                if snapshot and snapshot.rsi_14 > self.RSI_OVERBOUGHT:
                    exit_reason = f"RSI_OVERBOUGHT: {snapshot.rsi_14:.1f} > {self.RSI_OVERBOUGHT}"
        
        if exit_reason:
            logger.info(f"EXIT SIGNAL: {symbol} - {exit_reason}")
            
            return TradeSignal(
                symbol=symbol,
                direction=SignalDirection.FLAT,
                strategy_name=self.name,
                entry_price=current_price,  # Exit at current price
                stop_loss=0,
                reason=exit_reason
            )
        
        return None
    
    def get_position_size(
        self,
        signal: TradeSignal,
        account_equity: float,
        risk_per_trade: float = None
    ) -> int:
        """
        Calculate position size based on risk.
        
        Uses fixed fractional position sizing:
        Position Size = (Equity * Risk%) / Risk Per Share
        
        Args:
            signal: Trade signal with entry and stop prices.
            account_equity: Current account equity.
            risk_per_trade: Risk per trade (default from config).
            
        Returns:
            Number of shares (integer).
        """
        if risk_per_trade is None:
            risk_per_trade = RISK_PER_TRADE
        
        # Risk amount in dollars
        risk_amount = account_equity * risk_per_trade
        
        # Risk per share
        risk_per_share = signal.entry_price - signal.stop_loss
        
        if risk_per_share <= 0:
            logger.warning(f"Invalid risk per share for {signal.symbol}")
            return 0
        
        # Calculate shares
        shares = int(risk_amount / risk_per_share)
        
        # Apply max position size cap
        max_position_value = account_equity * MAX_POSITION_SIZE_PCT
        max_shares = int(max_position_value / signal.entry_price)
        
        shares = min(shares, max_shares)
        
        logger.debug(
            f"{signal.symbol} position size: {shares} shares "
            f"(risk: ${risk_amount:.2f}, per share: ${risk_per_share:.2f})"
        )
        
        return max(shares, 0)
    
    def get_scan_summary(self, symbols: List[str] = None) -> Dict[str, Any]:
        """
        Get detailed scan summary without generating signals.
        
        Useful for dashboard display and debugging.
        
        Args:
            symbols: Symbols to scan.
            
        Returns:
            Dictionary with scan results per symbol.
        """
        scan_symbols = symbols or self.symbols
        results = {}
        
        for symbol in scan_symbols:
            try:
                df = self._fetch_market_data(symbol)
                if df is None or len(df) < 20:
                    results[symbol] = {"status": "no_data"}
                    continue
                
                snapshot = calculate_indicators(df, symbol)
                if snapshot is None:
                    results[symbol] = {"status": "indicator_error"}
                    continue
                
                all_met, count, reason = self._check_entry_conditions(snapshot)
                
                bb_position = self._calculate_bb_position(
                    snapshot.price,
                    snapshot.bb_upper,
                    snapshot.bb_lower
                )
                
                results[symbol] = {
                    "status": "signal" if all_met else "watching",
                    "price": snapshot.price,
                    "conditions_met": count,
                    "total_conditions": 4,
                    "rsi": snapshot.rsi_14,
                    "adx": snapshot.adx_14,
                    "bb_position": bb_position,
                    "volume_ratio": snapshot.volume_ratio,
                    "atr": snapshot.atr_14,
                    "reason": reason
                }
                
            except Exception as e:
                results[symbol] = {"status": "error", "error": str(e)}
        
        return results
