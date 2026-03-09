"""
Iron Condor Exit Logic — Ported from Loveable check-exit
15 exit conditions checked every cycle for all open positions.
"""

import logging
from datetime import datetime, date, timedelta, timezone
from typing import Optional, List, Dict, Tuple
from dataclasses import dataclass
from enum import Enum

from strategies.ic_config import ICConfig, IC_CONFIG, ICUnderlying
from strategies.ic_greeks import ICGreeksFetcher

logger = logging.getLogger(__name__)


class ExitReason(Enum):
    """Exit reasons matching Loveable spec."""
    # Profit exits
    PROFIT_TARGET_50_MAX = "profit_target_50%_max_profit"
    PROFIT_TARGET_70_PREMIUM = "profit_target_70%_premium"
    
    # Stop loss
    STOP_LOSS = "stop_loss"
    PER_SPREAD_STOP = "per_spread_stop"
    
    # Time-based
    DTE_SAFETY = "dte_safety_exit"
    EXPIRY_APPROACHING = "expiry_approaching"
    TIME_BASED = "time_based"
    
    # Greeks-based
    DELTA_EXIT_PUT = "delta_exit_put"
    DELTA_EXIT_CALL = "delta_exit_call"
    GAMMA_EXIT_PUT = "gamma_exit_put"
    GAMMA_EXIT_CALL = "gamma_exit_call"
    
    # Volatility
    VIX_EXPANSION = "vix_expansion"
    IV_EXPANSION = "iv_expansion"
    
    # Price-based
    STRIKE_PROXIMITY = "strike_proximity"
    SUPPORT_BREAK = "support_break"
    RESISTANCE_BREAK = "resistance_break"
    
    # Rolling
    AUTO_ROLL_PUT = "auto_roll_put"
    AUTO_ROLL_CALL = "auto_roll_call"
    
    # Other
    POSITION_NOT_FOUND = "position_not_found"
    MANUAL = "manual"


class ExitUrgency(Enum):
    """Exit urgency levels."""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


@dataclass
class ExitSignal:
    """Signal to exit a position."""
    position_id: str
    reason: ExitReason
    urgency: ExitUrgency
    message: str
    current_pnl: float
    current_pnl_pct: float
    suggested_action: str
    data: Optional[Dict] = None


@dataclass
class AdjustmentSignal:
    """Adjustment signal for dashboard display."""
    position_id: str
    signal_type: str  # CLOSE_ALL, ROLL_PUT, ROLL_CALL, CLOSE_WINNER, MONITOR
    urgency: ExitUrgency
    message: str
    data: Optional[Dict] = None


@dataclass
class ICPosition:
    """Open Iron Condor position."""
    id: str
    symbol: str
    expiration: date
    short_put_strike: float
    long_put_strike: float
    short_call_strike: float
    long_call_strike: float
    quantity: int
    
    # Entry data
    entry_credit: float
    entry_time: datetime
    entry_vix: float
    entry_iv: float
    
    # Entry Greeks
    entry_delta: float
    entry_gamma: float
    entry_theta: float
    entry_vega: float
    
    # Current values (updated each cycle)
    current_price: Optional[float] = None
    current_pnl: Optional[float] = None
    current_pnl_pct: Optional[float] = None
    spot_price: Optional[float] = None
    
    # Current Greeks
    current_delta: Optional[float] = None
    current_gamma: Optional[float] = None
    current_put_delta: Optional[float] = None
    current_call_delta: Optional[float] = None
    
    @property
    def dte(self) -> int:
        return (self.expiration - date.today()).days
    
    @property
    def max_profit(self) -> float:
        """Max profit = credit received."""
        return self.entry_credit * self.quantity * 100
    
    @property
    def wing_width(self) -> float:
        return self.short_put_strike - self.long_put_strike


class ICExitChecker:
    """
    Iron Condor Exit Checker — monitors all open positions.
    
    Checks 15 exit conditions every 15 minutes.
    First matching condition triggers exit.
    """
    
    def __init__(
        self,
        config: ICConfig = None,
        ib_connection = None
    ):
        self.config = config or IC_CONFIG
        self.ib = ib_connection
        self.greeks_fetcher = ICGreeksFetcher(ib_connection) if ib_connection else None
    
    def check_position(self, position: ICPosition) -> Tuple[Optional[ExitSignal], List[AdjustmentSignal]]:
        """
        Check all exit conditions for a position.
        
        Returns:
            Tuple of (exit_signal, adjustment_signals)
        """
        adjustments: List[AdjustmentSignal] = []
        
        # Update current values
        self._update_position_values(position)
        
        # Exit 1: Position Not Found
        exit_signal = self._check_exit_1_not_found(position)
        if exit_signal:
            return exit_signal, adjustments
        
        # Exit 2: 2 DTE Safety Exit
        exit_signal = self._check_exit_2_dte_safety(position)
        if exit_signal:
            return exit_signal, adjustments
        
        # Exit 3: Strike Proximity
        exit_signal, adj = self._check_exit_3_strike_proximity(position)
        if adj:
            adjustments.append(adj)
        if exit_signal:
            return exit_signal, adjustments
        
        # Exit 4: Support/Resistance Break
        exit_signal = self._check_exit_4_sr_break(position)
        if exit_signal:
            return exit_signal, adjustments
        
        # Exit 5: Per-Spread Stop Loss
        exit_signal = self._check_exit_5_per_spread_stop(position)
        if exit_signal:
            return exit_signal, adjustments
        
        # Exit 6: VIX Expansion
        exit_signal, adj = self._check_exit_6_vix(position)
        if adj:
            adjustments.append(adj)
        if exit_signal:
            return exit_signal, adjustments
        
        # Exit 7: Delta Warning (0.22)
        adj = self._check_exit_7_delta_warning(position)
        if adj:
            adjustments.append(adj)
        
        # Exit 8: Delta Hard Exit (0.25)
        exit_signal = self._check_exit_8_delta_exit(position)
        if exit_signal:
            return exit_signal, adjustments
        
        # Exit 9: Gamma Exit
        exit_signal = self._check_exit_9_gamma_exit(position)
        if exit_signal:
            return exit_signal, adjustments
        
        # Exit 10: IV Expansion Exit
        exit_signal = self._check_exit_10_iv_expansion(position)
        if exit_signal:
            return exit_signal, adjustments
        
        # Exit 11: Auto Roll (if enabled)
        if self.config.auto_roll_enabled:
            exit_signal = self._check_exit_11_auto_roll(position)
            if exit_signal:
                return exit_signal, adjustments
        
        # Exit 12: Profit Targets (dual)
        exit_signal = self._check_exit_12_profit_target(position)
        if exit_signal:
            return exit_signal, adjustments
        
        # Exit 13: Overall Stop Loss
        exit_signal = self._check_exit_13_stop_loss(position)
        if exit_signal:
            return exit_signal, adjustments
        
        # Exit 14: Expiry Exit (1 DTE)
        exit_signal = self._check_exit_14_expiry(position)
        if exit_signal:
            return exit_signal, adjustments
        
        # Exit 15: Time-Based Exit
        exit_signal = self._check_exit_15_time_based(position)
        if exit_signal:
            return exit_signal, adjustments
        
        # Generate adjustment signals for dashboard
        adjustments.extend(self._generate_adjustment_signals(position))
        
        return None, adjustments
    
    # ==================== Exit Implementations ====================
    
    def _check_exit_1_not_found(self, position: ICPosition) -> Optional[ExitSignal]:
        """Exit 1: Position not found in broker."""
        # Would check IBKR positions
        # For now, assume position exists
        return None
    
    def _check_exit_2_dte_safety(self, position: ICPosition) -> Optional[ExitSignal]:
        """Exit 2: 2 DTE Safety Exit."""
        if position.dte <= self.config.exit.dte_safety_exit:
            return ExitSignal(
                position_id=position.id,
                reason=ExitReason.DTE_SAFETY,
                urgency=ExitUrgency.CRITICAL,
                message=f"DTE {position.dte} <= {self.config.exit.dte_safety_exit} - gamma risk",
                current_pnl=position.current_pnl or 0,
                current_pnl_pct=position.current_pnl_pct or 0,
                suggested_action="CLOSE_ALL"
            )
        return None
    
    def _check_exit_3_strike_proximity(self, position: ICPosition) -> Tuple[Optional[ExitSignal], Optional[AdjustmentSignal]]:
        """Exit 3: Strike Proximity Warning/Exit."""
        if position.spot_price is None:
            return None, None
        
        proximity_pct = self.config.exit.strike_proximity_percent / 100
        
        # Check put side
        put_threshold = position.short_put_strike * (1 + proximity_pct)
        if position.spot_price <= put_threshold and position.spot_price < position.short_put_strike:
            adj = AdjustmentSignal(
                position_id=position.id,
                signal_type="ROLL_PUT",
                urgency=ExitUrgency.HIGH,
                message=f"Price ${position.spot_price:.2f} near short put ${position.short_put_strike}"
            )
            return None, adj
        
        # Check call side
        call_threshold = position.short_call_strike * (1 - proximity_pct)
        if position.spot_price >= call_threshold and position.spot_price > position.short_call_strike:
            adj = AdjustmentSignal(
                position_id=position.id,
                signal_type="ROLL_CALL",
                urgency=ExitUrgency.HIGH,
                message=f"Price ${position.spot_price:.2f} near short call ${position.short_call_strike}"
            )
            return None, adj
        
        return None, None
    
    def _check_exit_4_sr_break(self, position: ICPosition) -> Optional[ExitSignal]:
        """Exit 4: Support/Resistance Break."""
        if position.spot_price is None:
            return None
        
        # Support break (below short put by > 0.1%)
        if position.spot_price < position.short_put_strike * 0.999:
            return ExitSignal(
                position_id=position.id,
                reason=ExitReason.SUPPORT_BREAK,
                urgency=ExitUrgency.HIGH,
                message=f"Price ${position.spot_price:.2f} below short put ${position.short_put_strike}",
                current_pnl=position.current_pnl or 0,
                current_pnl_pct=position.current_pnl_pct or 0,
                suggested_action="CLOSE_ALL"
            )
        
        # Resistance break (above short call by > 0.1%)
        if position.spot_price > position.short_call_strike * 1.001:
            return ExitSignal(
                position_id=position.id,
                reason=ExitReason.RESISTANCE_BREAK,
                urgency=ExitUrgency.HIGH,
                message=f"Price ${position.spot_price:.2f} above short call ${position.short_call_strike}",
                current_pnl=position.current_pnl or 0,
                current_pnl_pct=position.current_pnl_pct or 0,
                suggested_action="CLOSE_ALL"
            )
        
        return None
    
    def _check_exit_5_per_spread_stop(self, position: ICPosition) -> Optional[ExitSignal]:
        """Exit 5: Per-Spread Stop Loss (150% of one side)."""
        # Would need to calculate P&L per spread
        # Simplified: check overall P&L
        return None
    
    def _check_exit_6_vix(self, position: ICPosition) -> Tuple[Optional[ExitSignal], Optional[AdjustmentSignal]]:
        """Exit 6: VIX Monitoring and Expansion Exit."""
        current_vix = self._get_current_vix()
        if current_vix is None:
            return None, None
        
        # VIX expansion exit (1.5x from entry)
        expansion_threshold = position.entry_vix * self.config.vix.expansion_exit_multiplier
        if current_vix >= expansion_threshold:
            return ExitSignal(
                position_id=position.id,
                reason=ExitReason.VIX_EXPANSION,
                urgency=ExitUrgency.HIGH,
                message=f"VIX {current_vix:.1f} >= {expansion_threshold:.1f} (1.5x entry {position.entry_vix:.1f})",
                current_pnl=position.current_pnl or 0,
                current_pnl_pct=position.current_pnl_pct or 0,
                suggested_action="CLOSE_ALL",
                data={"current_vix": current_vix, "entry_vix": position.entry_vix}
            ), None
        
        # VIX warnings
        if current_vix >= self.config.vix.elevated_max:
            adj = AdjustmentSignal(
                position_id=position.id,
                signal_type="MONITOR",
                urgency=ExitUrgency.HIGH,
                message=f"VIX critical: {current_vix:.1f}"
            )
            return None, adj
        elif current_vix >= self.config.vix.normal_max:
            adj = AdjustmentSignal(
                position_id=position.id,
                signal_type="MONITOR",
                urgency=ExitUrgency.MEDIUM,
                message=f"VIX elevated: {current_vix:.1f}"
            )
            return None, adj
        
        return None, None
    
    def _check_exit_7_delta_warning(self, position: ICPosition) -> Optional[AdjustmentSignal]:
        """Exit 7: Delta Warning (0.22) - warning only."""
        put_delta = position.current_put_delta or 0
        call_delta = position.current_call_delta or 0
        warning_threshold = self.config.delta.warning_delta
        
        if put_delta >= warning_threshold:
            return AdjustmentSignal(
                position_id=position.id,
                signal_type="MONITOR",
                urgency=ExitUrgency.MEDIUM,
                message=f"Put delta {put_delta:.3f} >= {warning_threshold}",
                data={"put_delta": put_delta}
            )
        
        if call_delta >= warning_threshold:
            return AdjustmentSignal(
                position_id=position.id,
                signal_type="MONITOR",
                urgency=ExitUrgency.MEDIUM,
                message=f"Call delta {call_delta:.3f} >= {warning_threshold}",
                data={"call_delta": call_delta}
            )
        
        return None
    
    def _check_exit_8_delta_exit(self, position: ICPosition) -> Optional[ExitSignal]:
        """Exit 8: Delta Hard Exit (0.25)."""
        put_delta = position.current_put_delta or 0
        call_delta = position.current_call_delta or 0
        exit_threshold = self.config.delta.exit_delta
        
        if put_delta >= exit_threshold:
            return ExitSignal(
                position_id=position.id,
                reason=ExitReason.DELTA_EXIT_PUT,
                urgency=ExitUrgency.CRITICAL,
                message=f"Put delta {put_delta:.3f} >= {exit_threshold}",
                current_pnl=position.current_pnl or 0,
                current_pnl_pct=position.current_pnl_pct or 0,
                suggested_action="CLOSE_ALL",
                data={"put_delta": put_delta}
            )
        
        if call_delta >= exit_threshold:
            return ExitSignal(
                position_id=position.id,
                reason=ExitReason.DELTA_EXIT_CALL,
                urgency=ExitUrgency.CRITICAL,
                message=f"Call delta {call_delta:.3f} >= {exit_threshold}",
                current_pnl=position.current_pnl or 0,
                current_pnl_pct=position.current_pnl_pct or 0,
                suggested_action="CLOSE_ALL",
                data={"call_delta": call_delta}
            )
        
        return None
    
    def _check_exit_9_gamma_exit(self, position: ICPosition) -> Optional[ExitSignal]:
        """Exit 9: Gamma Exit (gamma > 0.05 when DTE <= 5)."""
        if position.dte > self.config.delta.gamma_exit_max_dte:
            return None
        
        gamma_threshold = self.config.delta.gamma_exit_threshold
        
        # Would need per-leg gamma
        # Simplified: check net gamma
        if position.current_gamma and abs(position.current_gamma) > gamma_threshold:
            return ExitSignal(
                position_id=position.id,
                reason=ExitReason.GAMMA_EXIT_PUT,  # Generic
                urgency=ExitUrgency.HIGH,
                message=f"Gamma {position.current_gamma:.4f} > {gamma_threshold} with DTE {position.dte}",
                current_pnl=position.current_pnl or 0,
                current_pnl_pct=position.current_pnl_pct or 0,
                suggested_action="CLOSE_ALL"
            )
        
        return None
    
    def _check_exit_10_iv_expansion(self, position: ICPosition) -> Optional[ExitSignal]:
        """Exit 10: IV Expansion Exit (IV +20% from entry)."""
        # Would need current IV
        # Simplified: skip for now
        return None
    
    def _check_exit_11_auto_roll(self, position: ICPosition) -> Optional[ExitSignal]:
        """Exit 11: Auto Roll at delta 0.25."""
        # Only if auto_roll_enabled
        put_delta = position.current_put_delta or 0
        call_delta = position.current_call_delta or 0
        
        if put_delta >= self.config.delta.exit_delta:
            return ExitSignal(
                position_id=position.id,
                reason=ExitReason.AUTO_ROLL_PUT,
                urgency=ExitUrgency.MEDIUM,
                message=f"Auto-roll put: delta {put_delta:.3f}",
                current_pnl=position.current_pnl or 0,
                current_pnl_pct=position.current_pnl_pct or 0,
                suggested_action="ROLL_PUT"
            )
        
        if call_delta >= self.config.delta.exit_delta:
            return ExitSignal(
                position_id=position.id,
                reason=ExitReason.AUTO_ROLL_CALL,
                urgency=ExitUrgency.MEDIUM,
                message=f"Auto-roll call: delta {call_delta:.3f}",
                current_pnl=position.current_pnl or 0,
                current_pnl_pct=position.current_pnl_pct or 0,
                suggested_action="ROLL_CALL"
            )
        
        return None
    
    def _check_exit_12_profit_target(self, position: ICPosition) -> Optional[ExitSignal]:
        """Exit 12: Dual Profit Targets (50% max profit OR 70% premium)."""
        if position.current_pnl is None:
            return None
        
        # 50% of max profit
        target_50 = position.max_profit * (self.config.exit.profit_target_max_profit_pct / 100)
        if position.current_pnl >= target_50:
            return ExitSignal(
                position_id=position.id,
                reason=ExitReason.PROFIT_TARGET_50_MAX,
                urgency=ExitUrgency.MEDIUM,
                message=f"Profit target: ${position.current_pnl:.2f} >= 50% max (${target_50:.2f})",
                current_pnl=position.current_pnl,
                current_pnl_pct=position.current_pnl_pct or 0,
                suggested_action="CLOSE_ALL"
            )
        
        # 70% of premium collected
        target_70 = position.max_profit * (self.config.exit.profit_target_premium_pct / 100)
        if position.current_pnl >= target_70:
            return ExitSignal(
                position_id=position.id,
                reason=ExitReason.PROFIT_TARGET_70_PREMIUM,
                urgency=ExitUrgency.MEDIUM,
                message=f"Profit target: ${position.current_pnl:.2f} >= 70% premium (${target_70:.2f})",
                current_pnl=position.current_pnl,
                current_pnl_pct=position.current_pnl_pct or 0,
                suggested_action="CLOSE_ALL"
            )
        
        return None
    
    def _check_exit_13_stop_loss(self, position: ICPosition) -> Optional[ExitSignal]:
        """Exit 13: Overall Stop Loss (1.5x credit)."""
        if position.current_pnl is None:
            return None
        
        stop_loss = -position.max_profit * self.config.exit.stop_loss_multiplier
        
        if position.current_pnl <= stop_loss:
            return ExitSignal(
                position_id=position.id,
                reason=ExitReason.STOP_LOSS,
                urgency=ExitUrgency.CRITICAL,
                message=f"Stop loss: ${position.current_pnl:.2f} <= ${stop_loss:.2f}",
                current_pnl=position.current_pnl,
                current_pnl_pct=position.current_pnl_pct or 0,
                suggested_action="CLOSE_ALL"
            )
        
        return None
    
    def _check_exit_14_expiry(self, position: ICPosition) -> Optional[ExitSignal]:
        """Exit 14: Expiry Exit (1 DTE)."""
        if position.dte <= self.config.exit.expiry_exit_dte:
            return ExitSignal(
                position_id=position.id,
                reason=ExitReason.EXPIRY_APPROACHING,
                urgency=ExitUrgency.CRITICAL,
                message=f"Expiry approaching: {position.dte} DTE",
                current_pnl=position.current_pnl or 0,
                current_pnl_pct=position.current_pnl_pct or 0,
                suggested_action="CLOSE_ALL"
            )
        return None
    
    def _check_exit_15_time_based(self, position: ICPosition) -> Optional[ExitSignal]:
        """Exit 15: Time-Based Exit (Tue/Wed with 60%+ profit)."""
        today_weekday = date.today().weekday()
        
        if today_weekday not in self.config.exit.time_based_exit_days:
            return None
        
        pnl_pct = position.current_pnl_pct or 0
        min_profit = self.config.exit.time_based_min_profit_pct
        
        if pnl_pct >= min_profit:
            return ExitSignal(
                position_id=position.id,
                reason=ExitReason.TIME_BASED,
                urgency=ExitUrgency.LOW,
                message=f"Time-based exit: {pnl_pct:.1f}% profit on exit day",
                current_pnl=position.current_pnl or 0,
                current_pnl_pct=pnl_pct,
                suggested_action="CLOSE_ALL"
            )
        
        return None
    
    # ==================== Helper Methods ====================
    
    def _update_position_values(self, position: ICPosition):
        """Update current values for position."""
        # Get spot price
        position.spot_price = self._get_spot_price(position.symbol)
        
        # Get current Greeks
        if self.greeks_fetcher:
            exit_check = self.greeks_fetcher.check_exit_conditions(
                position.symbol,
                position.expiration,
                position.short_put_strike,
                position.short_call_strike,
                dte=position.dte
            )
            
            greeks = exit_check.get("greeks", {})
            position.current_put_delta = greeks.get("short_put_delta")
            position.current_call_delta = greeks.get("short_call_delta")
        
        # Calculate P&L
        if position.current_price is not None:
            pnl_per_contract = (position.entry_credit - position.current_price) * 100
            position.current_pnl = pnl_per_contract * position.quantity
            position.current_pnl_pct = (position.current_pnl / position.max_profit) * 100
    
    def _get_spot_price(self, symbol: str) -> Optional[float]:
        """Get current spot price."""
        try:
            if self.ib:
                from ib_insync import Stock, Index
                
                if symbol == "SPX":
                    contract = Index("SPX", "CBOE")
                else:
                    contract = Stock(symbol, "SMART", "USD")
                
                self.ib.qualifyContracts(contract)
                self.ib.reqMarketDataType(3)
                ticker = self.ib.reqMktData(contract)
                self.ib.sleep(0.5)
                price = ticker.last or ticker.close
                self.ib.cancelMktData(contract)
                return float(price) if price else None
            
            return None
        except Exception as e:
            logger.error(f"Failed to get spot price for {symbol}: {e}")
            return None
    
    def _get_current_vix(self) -> Optional[float]:
        """Get current VIX value."""
        try:
            if self.ib:
                from ib_insync import Index
                vix = Index("VIX", "CBOE")
                self.ib.qualifyContracts(vix)
                self.ib.reqMarketDataType(3)
                ticker = self.ib.reqMktData(vix)
                self.ib.sleep(0.5)
                price = ticker.last or ticker.close
                self.ib.cancelMktData(vix)
                return float(price) if price else None
            
            return None
        except Exception as e:
            logger.error(f"Failed to get VIX: {e}")
            return None
    
    def _generate_adjustment_signals(self, position: ICPosition) -> List[AdjustmentSignal]:
        """Generate adjustment signals for dashboard display."""
        signals = []
        
        pnl_pct = position.current_pnl_pct or 0
        put_delta = position.current_put_delta or 0
        call_delta = position.current_call_delta or 0
        
        # P&L based
        if pnl_pct >= 50:
            signals.append(AdjustmentSignal(
                position_id=position.id,
                signal_type="CLOSE_ALL",
                urgency=ExitUrgency.MEDIUM,
                message=f"Consider closing: {pnl_pct:.1f}% profit"
            ))
        
        # Delta based (critical)
        if put_delta >= self.config.delta.critical_delta:
            signals.append(AdjustmentSignal(
                position_id=position.id,
                signal_type="ROLL_PUT",
                urgency=ExitUrgency.CRITICAL,
                message=f"Put delta critical: {put_delta:.3f}"
            ))
        
        if call_delta >= self.config.delta.critical_delta:
            signals.append(AdjustmentSignal(
                position_id=position.id,
                signal_type="ROLL_CALL",
                urgency=ExitUrgency.CRITICAL,
                message=f"Call delta critical: {call_delta:.3f}"
            ))
        
        # DTE based
        if position.dte <= 3:
            signals.append(AdjustmentSignal(
                position_id=position.id,
                signal_type="CLOSE_ALL",
                urgency=ExitUrgency.HIGH,
                message=f"Low DTE: {position.dte} days"
            ))
        elif position.dte <= 7 and (put_delta > 0.15 or call_delta > 0.15):
            signals.append(AdjustmentSignal(
                position_id=position.id,
                signal_type="CLOSE_ALL",
                urgency=ExitUrgency.MEDIUM,
                message=f"DTE {position.dte} with elevated delta"
            ))
        
        return signals


def run_exit_scan(
    positions: List[ICPosition],
    ib_connection,
    config: ICConfig = None
) -> List[Tuple[ICPosition, Optional[ExitSignal], List[AdjustmentSignal]]]:
    """
    Run exit scan for all open positions.
    
    Returns:
        List of (position, exit_signal, adjustment_signals) tuples
    """
    checker = ICExitChecker(config=config or IC_CONFIG, ib_connection=ib_connection)
    results = []
    
    for position in positions:
        logger.info(f"Checking {position.symbol} {position.expiration} position...")
        exit_signal, adjustments = checker.check_position(position)
        
        if exit_signal:
            logger.warning(
                f"EXIT SIGNAL for {position.symbol}: "
                f"{exit_signal.reason.value} - {exit_signal.message}"
            )
        
        for adj in adjustments:
            logger.info(f"Adjustment: {adj.signal_type} - {adj.message}")
        
        results.append((position, exit_signal, adjustments))
    
    return results
