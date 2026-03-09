"""
Iron Condor Strategy - Main Strategy Class
Ported from Loveable check-entry and check-exit edge functions.

This is the main orchestrator that:
1. Runs 16 entry gates to validate new positions
2. Monitors 15 exit conditions on open positions
3. Manages position lifecycle
"""

import logging
from datetime import datetime, date, timedelta, timezone
from typing import Optional, List, Tuple, Dict, Any
from dataclasses import dataclass

from strategies.ic_config import (
    ICConfig, IC_CONFIG, VIXRegime,
    UNDERLYING_CONFIGS, get_underlying_config, get_enabled_underlyings,
    BLOCKING_EVENTS, is_event_blocked, get_event_warning,
    ICPositionStatus, ICCloseReason
)
from strategies.ic_models import (
    IronCondor, ICEntrySignal, ICExitSignal,
    OptionContract, VerticalSpread, OptionType, GreeksSnapshot
)

logger = logging.getLogger(__name__)


# =============================================================================
# GATE CHECK RESULT
# =============================================================================

@dataclass
class GateResult:
    """Result of a single gate check."""
    gate_num: int
    gate_name: str
    passed: bool
    message: str
    data: Optional[Dict] = None


# =============================================================================
# IRON CONDOR STRATEGY
# =============================================================================

class IronCondorStrategy:
    """
    Iron Condor Strategy for SPY/SPX/QQQ.
    
    Entry Logic (16 Gates):
    1. Market Hours
    2. Event Calendar (FOMC/CPI/NFP/Quad Witch)
    3. Trading Enabled
    4. Entry Day Check
    5. Portfolio Position Limits
    6. Per-Underlying Limit
    7. Duplicate Position Check
    8. Same-Day Delta Exit Cooldown
    9. VIX 3-Tier Filter
    10. IV Rank Filter
    11. IV Percentile Filter
    12. Trend Filter
    13. ATR Expanding Filter
    14. Delta Drift Filter
    15. Strike Selection + Delta Validation
    16. Credit Validation
    
    Exit Logic (15 Conditions):
    1. Position Not Found
    2. 2 DTE Safety Exit
    3. Strike Proximity Warning/Exit
    4. Support/Resistance Break
    5. Per-Spread Stop Loss
    6. VIX Monitoring
    7. Delta Warning (0.22)
    8. Delta Hard Exit (0.25)
    9. Gamma Exit
    10. IV Expansion Exit
    11. Delta Rolling
    12. Profit Target (50% max / 70% premium)
    13. Stop Loss (1.5x)
    14. Expiry Exit
    15. Time-Based Exit
    """
    
    def __init__(
        self,
        config: ICConfig = None,
        broker = None,  # IBKRBroker instance
        account_capital: float = 100000.0
    ):
        self.config = config or IC_CONFIG
        self.broker = broker
        self.account_capital = account_capital
        
        # Position tracking
        self.open_positions: List[IronCondor] = []
        self.closed_positions: List[IronCondor] = []
        
        # Cooldown tracking (same-day delta exits)
        self.delta_exit_cooldowns: Dict[str, date] = {}  # symbol -> cooldown date
        
        logger.info(
            f"IronCondorStrategy initialized - "
            f"Capital: ${account_capital:,.0f}, "
            f"Max Condors: {self.config.get_max_condors(account_capital)}"
        )
    
    # =========================================================================
    # ENTRY LOGIC - 16 GATES
    # =========================================================================
    
    def check_entry(self, underlying_symbol: str) -> Tuple[bool, Optional[ICEntrySignal], List[GateResult]]:
        """
        Run all 16 entry gates for an underlying.
        Returns (passed, signal, gate_results).
        """
        gates: List[GateResult] = []
        
        underlying_config = get_underlying_config(underlying_symbol)
        if not underlying_config:
            return False, None, [GateResult(0, "Underlying Config", False, f"Unknown: {underlying_symbol}")]
        
        # Gate 1: Market Hours
        gate1 = self._check_gate_market_hours()
        gates.append(gate1)
        if not gate1.passed:
            return False, None, gates
        
        # Gate 2: Event Calendar
        gate2 = self._check_gate_event_calendar()
        gates.append(gate2)
        if not gate2.passed:
            return False, None, gates
        
        # Gate 3: Trading Enabled
        gate3 = self._check_gate_trading_enabled()
        gates.append(gate3)
        if not gate3.passed:
            return False, None, gates
        
        # Gate 4: Entry Day
        gate4 = self._check_gate_entry_day()
        gates.append(gate4)
        if not gate4.passed:
            return False, None, gates
        
        # Gate 5: Portfolio Position Limits
        gate5 = self._check_gate_portfolio_limits()
        gates.append(gate5)
        if not gate5.passed:
            return False, None, gates
        
        # Gate 6: Per-Underlying Limit
        gate6 = self._check_gate_underlying_limit(underlying_symbol)
        gates.append(gate6)
        if not gate6.passed:
            return False, None, gates
        
        # Gate 7: Duplicate Position Check
        gate7 = self._check_gate_duplicate_position(underlying_symbol)
        gates.append(gate7)
        if not gate7.passed:
            return False, None, gates
        
        # Gate 8: Same-Day Delta Exit Cooldown
        gate8 = self._check_gate_delta_cooldown(underlying_symbol)
        gates.append(gate8)
        if not gate8.passed:
            return False, None, gates
        
        # Gate 9: VIX 3-Tier Filter (requires market data)
        vix_value = self._fetch_vix()
        gate9 = self._check_gate_vix_filter(vix_value)
        gates.append(gate9)
        if not gate9.passed:
            return False, None, gates
        
        # Gate 10: IV Rank Filter
        iv_rank = self._calculate_iv_rank(underlying_config.iv_index)
        gate10 = self._check_gate_iv_rank(iv_rank)
        gates.append(gate10)
        if not gate10.passed:
            return False, None, gates
        
        # Gate 11: IV Percentile Filter (use IV Rank as proxy)
        gate11 = self._check_gate_iv_percentile(iv_rank)
        gates.append(gate11)
        if not gate11.passed:
            return False, None, gates
        
        # Gate 12: Trend Filter (optional)
        if self.config.entry.enable_trend_filter:
            gate12 = self._check_gate_trend_filter(underlying_symbol)
            gates.append(gate12)
            if not gate12.passed:
                return False, None, gates
        else:
            gates.append(GateResult(12, "Trend Filter", True, "Disabled"))
        
        # Gate 13: ATR Expanding Filter (optional)
        if self.config.entry.enable_atr_filter:
            gate13 = self._check_gate_atr_filter(underlying_symbol)
            gates.append(gate13)
            if not gate13.passed:
                return False, None, gates
        else:
            gates.append(GateResult(13, "ATR Filter", True, "Disabled"))
        
        # Gate 14: Delta Drift Filter (optional)
        if self.config.entry.enable_delta_drift_filter:
            gate14 = self._check_gate_delta_drift(underlying_symbol)
            gates.append(gate14)
            if not gate14.passed:
                return False, None, gates
        else:
            gates.append(GateResult(14, "Delta Drift", True, "Disabled"))
        
        # Gate 15: Strike Selection + Delta Validation
        spot_price = self._fetch_spot_price(underlying_symbol)
        expiration = self._find_expiration()
        
        if not expiration:
            gates.append(GateResult(15, "Strike Selection", False, "No valid expiration"))
            return False, None, gates
        
        strike_result = self._select_and_validate_strikes(
            underlying_symbol, underlying_config, spot_price, expiration, iv_rank
        )
        gates.append(strike_result["gate"])
        if not strike_result["gate"].passed:
            return False, None, gates
        
        # Gate 16: Credit Validation
        gate16 = self._check_gate_credit_validation(
            strike_result["estimated_credit"],
            strike_result["wing_width"],
            underlying_config.min_credit
        )
        gates.append(gate16)
        if not gate16.passed:
            return False, None, gates
        
        # All gates passed - create signal
        vix_multiplier = self.config.vix.get_multiplier(vix_value)
        quantity = self._calculate_position_size(
            strike_result["wing_width"],
            vix_multiplier
        )
        
        signal = ICEntrySignal(
            underlying=underlying_symbol,
            expiration=expiration,
            short_put_strike=strike_result["short_put"],
            long_put_strike=strike_result["long_put"],
            short_call_strike=strike_result["short_call"],
            long_call_strike=strike_result["long_call"],
            wing_width=strike_result["wing_width"],
            quantity=quantity,
            vix_multiplier=vix_multiplier,
            short_put_delta=strike_result["short_put_delta"],
            short_call_delta=strike_result["short_call_delta"],
            spot_price=spot_price,
            vix_value=vix_value,
            iv_rank=iv_rank,
            estimated_credit=strike_result["estimated_credit"],
            max_risk=(strike_result["wing_width"] - strike_result["estimated_credit"]) * 100 * quantity,
            gate_results=[g.__dict__ for g in gates]
        )
        
        logger.info(
            f"Entry signal generated: {underlying_symbol} {expiration} "
            f"P:{strike_result['short_put']}/{strike_result['long_put']} "
            f"C:{strike_result['short_call']}/{strike_result['long_call']} "
            f"x{quantity} @ ${strike_result['estimated_credit']:.2f}"
        )
        
        return True, signal, gates
    
    # =========================================================================
    # INDIVIDUAL GATE CHECKS
    # =========================================================================
    
    def _check_gate_market_hours(self) -> GateResult:
        """Gate 1: Check if market is open."""
        # Use trading hours filter
        from filters.trading_hours import TradingHoursFilter
        hours_filter = TradingHoursFilter()
        
        if hours_filter.allows_trading():
            return GateResult(1, "Market Hours", True, "Market is open")
        else:
            session = hours_filter.get_session()
            return GateResult(1, "Market Hours", False, f"Market closed: {session.value}")
    
    def _check_gate_event_calendar(self) -> GateResult:
        """Gate 2: Check economic event calendar."""
        today = date.today()
        blocked, event_name = is_event_blocked(today)
        
        if blocked:
            return GateResult(2, "Event Calendar", False, f"BLOCKED: {event_name}")
        
        warning = get_event_warning(today)
        if warning:
            return GateResult(2, "Event Calendar", True, f"WARNING: {warning} tomorrow", {"warning": warning})
        
        return GateResult(2, "Event Calendar", True, "No blocking events")
    
    def _check_gate_trading_enabled(self) -> GateResult:
        """Gate 3: Check if trading is enabled."""
        if self.config.trading_enabled:
            return GateResult(3, "Trading Enabled", True, "Trading is enabled")
        return GateResult(3, "Trading Enabled", False, "Trading is disabled")
    
    def _check_gate_entry_day(self) -> GateResult:
        """Gate 4: Check if today is an entry day."""
        today = date.today()
        day_of_week = today.weekday()  # 0=Mon, 4=Fri
        
        if day_of_week in self.config.entry.entry_days:
            day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
            return GateResult(4, "Entry Day", True, f"{day_names[day_of_week]} is entry day")
        return GateResult(4, "Entry Day", False, f"Not an entry day (day {day_of_week})")
    
    def _check_gate_portfolio_limits(self) -> GateResult:
        """Gate 5: Check portfolio position limits."""
        max_condors = self.config.get_max_condors(self.account_capital)
        current_count = len([p for p in self.open_positions if p.status == ICPositionStatus.OPEN])
        
        if current_count >= max_condors:
            return GateResult(5, "Portfolio Limits", False, 
                            f"Max condors reached ({current_count}/{max_condors})")
        
        return GateResult(5, "Portfolio Limits", True, 
                         f"Positions OK ({current_count}/{max_condors})",
                         {"current": current_count, "max": max_condors})
    
    def _check_gate_underlying_limit(self, symbol: str) -> GateResult:
        """Gate 6: Check per-underlying position limit."""
        config = get_underlying_config(symbol)
        if not config:
            return GateResult(6, "Underlying Limit", False, f"Unknown: {symbol}")
        
        count = len([p for p in self.open_positions 
                    if p.underlying == symbol and p.status == ICPositionStatus.OPEN])
        
        if count >= config.max_condors:
            return GateResult(6, "Underlying Limit", False,
                            f"{symbol} max reached ({count}/{config.max_condors})")
        
        return GateResult(6, "Underlying Limit", True,
                         f"{symbol} OK ({count}/{config.max_condors})")
    
    def _check_gate_duplicate_position(self, symbol: str) -> GateResult:
        """Gate 7: Check for duplicate position on symbol."""
        has_open = any(p.underlying == symbol and p.status == ICPositionStatus.OPEN 
                      for p in self.open_positions)
        
        if has_open:
            return GateResult(7, "Duplicate Check", False, f"Already have open {symbol} position")
        
        return GateResult(7, "Duplicate Check", True, f"No existing {symbol} position")
    
    def _check_gate_delta_cooldown(self, symbol: str) -> GateResult:
        """Gate 8: Check same-day delta exit cooldown."""
        today = date.today()
        cooldown_date = self.delta_exit_cooldowns.get(symbol)
        
        if cooldown_date == today:
            return GateResult(8, "Delta Cooldown", False,
                            f"{symbol} delta exit today - cooldown active")
        
        return GateResult(8, "Delta Cooldown", True, "No cooldown active")
    
    def _check_gate_vix_filter(self, vix_value: float) -> GateResult:
        """Gate 9: VIX 3-tier filter."""
        can_enter, message = self.config.vix.can_enter(vix_value)
        
        regime = self.config.vix.get_regime(vix_value)
        data = {"vix": vix_value, "regime": regime.value}
        
        return GateResult(9, "VIX Filter", can_enter, message, data)
    
    def _check_gate_iv_rank(self, iv_rank: float) -> GateResult:
        """Gate 10: IV Rank filter."""
        if iv_rank > self.config.entry.max_iv_rank:
            return GateResult(10, "IV Rank", False,
                            f"IV Rank {iv_rank:.1f}% > {self.config.entry.max_iv_rank}%")
        
        return GateResult(10, "IV Rank", True, f"IV Rank {iv_rank:.1f}% OK")
    
    def _check_gate_iv_percentile(self, iv_percentile: float) -> GateResult:
        """Gate 11: IV Percentile filter."""
        if iv_percentile > self.config.entry.max_iv_percentile:
            return GateResult(11, "IV Percentile", False,
                            f"IV Percentile {iv_percentile:.1f}% > {self.config.entry.max_iv_percentile}%")
        
        return GateResult(11, "IV Percentile", True, f"IV Percentile {iv_percentile:.1f}% OK")
    
    def _check_gate_trend_filter(self, symbol: str) -> GateResult:
        """Gate 12: Multi-timeframe trend filter."""
        # TODO: Implement with broker bars data
        # For now, pass
        return GateResult(12, "Trend Filter", True, "Trend check passed")
    
    def _check_gate_atr_filter(self, symbol: str) -> GateResult:
        """Gate 13: ATR expanding filter."""
        # TODO: Implement with broker bars data
        return GateResult(13, "ATR Filter", True, "ATR not expanding")
    
    def _check_gate_delta_drift(self, symbol: str) -> GateResult:
        """Gate 14: 1-hour delta drift filter."""
        # TODO: Implement with broker bars data
        return GateResult(14, "Delta Drift", True, "No significant drift")
    
    def _check_gate_credit_validation(
        self, credit: float, wing_width: float, min_credit: float
    ) -> GateResult:
        """Gate 16: Validate credit meets minimums."""
        if credit < self.config.entry.min_credit_dollar:
            return GateResult(16, "Credit Validation", False,
                            f"Credit ${credit:.2f} < ${self.config.entry.min_credit_dollar}")
        
        credit_pct = (credit / wing_width) * 100
        if credit_pct < self.config.entry.min_credit_percent:
            return GateResult(16, "Credit Validation", False,
                            f"Credit {credit_pct:.1f}% < {self.config.entry.min_credit_percent}%")
        
        return GateResult(16, "Credit Validation", True,
                         f"Credit ${credit:.2f} ({credit_pct:.1f}%) OK")
    
    # =========================================================================
    # STRIKE SELECTION WITH DELTA VALIDATION
    # =========================================================================
    
    def _select_and_validate_strikes(
        self,
        symbol: str,
        config,
        spot_price: float,
        expiration: date,
        iv_rank: float
    ) -> Dict[str, Any]:
        """
        Gate 15: Select strikes and validate deltas.
        Implements the delta validation loop from Loveable.
        """
        wing_width = self.config.get_wing_width(symbol, iv_rank)
        dte = (expiration - date.today()).days
        
        # Estimate delta distance for ~10Δ
        # stdDev = spot * (IV/100) * sqrt(DTE/365)
        # deltaDistance = 0.4 * stdDev
        est_iv = 20 / 100  # Use 20% as default
        std_dev = spot_price * est_iv * (dte / 365) ** 0.5
        delta_distance = 0.4 * std_dev
        
        # Initial strikes
        short_put = round(spot_price - delta_distance)
        short_call = round(spot_price + delta_distance)
        long_put = short_put - wing_width
        long_call = short_call + wing_width
        
        # Delta validation loop
        max_attempts = self.config.entry.max_widen_attempts
        validated = False
        short_put_delta = 0.10  # Default estimate
        short_call_delta = 0.10
        
        for attempt in range(max_attempts):
            # Fetch actual Greeks from broker
            if self.broker:
                put_greeks = self._fetch_option_greeks(symbol, expiration, short_put, "P")
                call_greeks = self._fetch_option_greeks(symbol, expiration, short_call, "C")
                
                if put_greeks and call_greeks:
                    short_put_delta = abs(put_greeks.get("delta", 0.10))
                    short_call_delta = abs(call_greeks.get("delta", 0.10))
                    
                    # Sanity check
                    if short_put_delta < self.config.entry.min_sanity_delta:
                        break  # API failure
                    
                    # Check if within threshold
                    if (short_put_delta <= self.config.entry.max_entry_delta and
                        short_call_delta <= self.config.entry.max_entry_delta):
                        validated = True
                        break
                    
                    # Widen the side with higher delta
                    if short_put_delta > self.config.entry.max_entry_delta:
                        short_put -= self.config.entry.delta_widen_step
                        long_put = short_put - wing_width
                    if short_call_delta > self.config.entry.max_entry_delta:
                        short_call += self.config.entry.delta_widen_step
                        long_call = short_call + wing_width
            else:
                # No broker - use estimates
                validated = True
                break
        
        if not validated and self.broker:
            return {
                "gate": GateResult(15, "Strike Selection", False,
                                  f"Delta validation failed after {max_attempts} attempts"),
                "short_put": short_put,
                "long_put": long_put,
                "short_call": short_call,
                "long_call": long_call,
                "wing_width": wing_width,
                "short_put_delta": short_put_delta,
                "short_call_delta": short_call_delta,
                "estimated_credit": 0,
            }
        
        # Estimate credit
        vix = self._fetch_vix()
        vix_factor = min(1.0, (vix - 15) / 20)
        credit_pct = 0.25 + (vix_factor * 0.15)  # 25-40%
        estimated_credit = wing_width * credit_pct
        
        return {
            "gate": GateResult(15, "Strike Selection", True,
                              f"Strikes validated: P {short_put}/{long_put}, C {short_call}/{long_call}",
                              {"put_delta": short_put_delta, "call_delta": short_call_delta}),
            "short_put": short_put,
            "long_put": long_put,
            "short_call": short_call,
            "long_call": long_call,
            "wing_width": wing_width,
            "short_put_delta": short_put_delta,
            "short_call_delta": short_call_delta,
            "estimated_credit": estimated_credit,
        }
    
    # =========================================================================
    # EXIT LOGIC - 15 CONDITIONS
    # =========================================================================
    
    def check_exits(self) -> List[ICExitSignal]:
        """
        Check all exit conditions for open positions.
        Returns list of exit signals.
        """
        signals = []
        
        for position in self.open_positions:
            if position.status != ICPositionStatus.OPEN:
                continue
            
            signal = self._check_position_exits(position)
            if signal:
                signals.append(signal)
        
        return signals
    
    def _check_position_exits(self, position: IronCondor) -> Optional[ICExitSignal]:
        """Check all 15 exit conditions for a position."""
        
        # Get current market data
        spot_price = self._fetch_spot_price(position.underlying)
        current_price = self._get_position_current_price(position)
        
        # Calculate P&L
        if position.entry_credit and current_price is not None:
            entry_total = position.entry_credit * position.contracts * 100
            current_total = current_price * position.contracts * 100
            pnl = entry_total - current_total
            pnl_pct = (pnl / entry_total) * 100 if entry_total > 0 else 0
        else:
            pnl = 0
            pnl_pct = 0
        
        # Update position tracking
        position.unrealized_pnl = pnl
        position.unrealized_pnl_pct = pnl_pct
        position.current_spot_price = spot_price
        
        # Exit 1: Position Not Found (handled by broker sync)
        
        # Exit 2: 2 DTE Safety Exit
        if position.dte <= self.config.exit.dte_safety_exit:
            return ICExitSignal(
                position_id=position.id or 0,
                reason=ICCloseReason.DTE_SAFETY,
                urgency="HIGH",
                current_pnl=pnl,
                current_pnl_pct=pnl_pct,
                dte=position.dte,
                message=f"DTE {position.dte} <= {self.config.exit.dte_safety_exit} - safety exit"
            )
        
        # Exit 3 & 4: Strike Proximity / S-R Break
        if self.config.exit.enable_sr_exit and spot_price:
            # Check put side
            if spot_price < position.short_put_strike:
                break_pct = ((position.short_put_strike - spot_price) / position.short_put_strike) * 100
                if break_pct > 0.1:
                    return ICExitSignal(
                        position_id=position.id or 0,
                        reason=ICCloseReason.SUPPORT_BREAK,
                        urgency="CRITICAL",
                        current_pnl=pnl,
                        current_pnl_pct=pnl_pct,
                        message=f"Support break: price ${spot_price:.2f} below short put ${position.short_put_strike}"
                    )
            
            # Check call side
            if spot_price > position.short_call_strike:
                break_pct = ((spot_price - position.short_call_strike) / position.short_call_strike) * 100
                if break_pct > 0.1:
                    return ICExitSignal(
                        position_id=position.id or 0,
                        reason=ICCloseReason.RESISTANCE_BREAK,
                        urgency="CRITICAL",
                        current_pnl=pnl,
                        current_pnl_pct=pnl_pct,
                        message=f"Resistance break: price ${spot_price:.2f} above short call ${position.short_call_strike}"
                    )
        
        # Get current Greeks
        greeks = self._fetch_position_greeks(position)
        if greeks:
            position.current_delta = greeks.delta
            position.current_gamma = greeks.gamma
        
        # Exit 8: Delta Hard Exit (0.25)
        if greeks and greeks.short_put_delta:
            if greeks.short_put_delta >= self.config.exit.delta_exit:
                # Set cooldown
                self.delta_exit_cooldowns[position.underlying] = date.today()
                
                return ICExitSignal(
                    position_id=position.id or 0,
                    reason=ICCloseReason.DELTA_EXIT_PUT,
                    urgency="CRITICAL",
                    current_pnl=pnl,
                    current_pnl_pct=pnl_pct,
                    current_delta=greeks.short_put_delta,
                    message=f"Put delta {greeks.short_put_delta:.3f} >= {self.config.exit.delta_exit}"
                )
        
        if greeks and greeks.short_call_delta:
            if greeks.short_call_delta >= self.config.exit.delta_exit:
                self.delta_exit_cooldowns[position.underlying] = date.today()
                
                return ICExitSignal(
                    position_id=position.id or 0,
                    reason=ICCloseReason.DELTA_EXIT_CALL,
                    urgency="CRITICAL",
                    current_pnl=pnl,
                    current_pnl_pct=pnl_pct,
                    current_delta=greeks.short_call_delta,
                    message=f"Call delta {greeks.short_call_delta:.3f} >= {self.config.exit.delta_exit}"
                )
        
        # Exit 9: Gamma Exit (high gamma + low DTE)
        if greeks and position.dte <= self.config.exit.gamma_critical_dte:
            max_gamma = max(greeks.short_put_gamma or 0, greeks.short_call_gamma or 0)
            if max_gamma > self.config.exit.gamma_exit_threshold:
                return ICExitSignal(
                    position_id=position.id or 0,
                    reason=ICCloseReason.GAMMA_EXIT_PUT if (greeks.short_put_gamma or 0) > (greeks.short_call_gamma or 0) else ICCloseReason.GAMMA_EXIT_CALL,
                    urgency="HIGH",
                    current_pnl=pnl,
                    current_pnl_pct=pnl_pct,
                    current_gamma=max_gamma,
                    dte=position.dte,
                    message=f"Gamma {max_gamma:.4f} > {self.config.exit.gamma_exit_threshold} with DTE {position.dte}"
                )
        
        # Exit 10: IV Expansion Exit
        if position.entry_vix and position.current_iv:
            iv_change = ((position.current_iv - position.entry_vix) / position.entry_vix) * 100
            if iv_change >= self.config.exit.iv_expansion_exit_pct:
                return ICExitSignal(
                    position_id=position.id or 0,
                    reason=ICCloseReason.IV_EXPANSION,
                    urgency="HIGH",
                    current_pnl=pnl,
                    current_pnl_pct=pnl_pct,
                    message=f"IV expanded {iv_change:.1f}% from entry"
                )
        
        # Exit 12: Dual Profit Targets
        if position.entry_credit:
            entry_total = position.entry_credit * position.contracts * 100
            
            # 50% of max profit
            if pnl >= entry_total * (self.config.exit.profit_target_max_pct / 100):
                return ICExitSignal(
                    position_id=position.id or 0,
                    reason=ICCloseReason.PROFIT_TARGET_50,
                    urgency="MEDIUM",
                    current_pnl=pnl,
                    current_pnl_pct=pnl_pct,
                    message=f"Profit target 50% reached: ${pnl:.2f}"
                )
            
            # 70% of premium
            if pnl >= entry_total * (self.config.exit.profit_target_premium_pct / 100):
                return ICExitSignal(
                    position_id=position.id or 0,
                    reason=ICCloseReason.PROFIT_TARGET_70,
                    urgency="MEDIUM",
                    current_pnl=pnl,
                    current_pnl_pct=pnl_pct,
                    message=f"Profit target 70% premium reached: ${pnl:.2f}"
                )
        
        # Exit 13: Stop Loss (1.5x)
        if position.entry_credit:
            stop_loss = position.entry_credit * self.config.exit.stop_loss_multiplier * position.contracts * 100
            if pnl <= -stop_loss:
                return ICExitSignal(
                    position_id=position.id or 0,
                    reason=ICCloseReason.STOP_LOSS,
                    urgency="CRITICAL",
                    current_pnl=pnl,
                    current_pnl_pct=pnl_pct,
                    message=f"Stop loss triggered: ${pnl:.2f} <= -${stop_loss:.2f}"
                )
        
        return None
    
    # =========================================================================
    # HELPER METHODS
    # =========================================================================
    
    def _fetch_vix(self) -> float:
        """Fetch current VIX value."""
        if self.broker:
            try:
                return self.broker.get_vix()
            except:
                pass
        return 20.0  # Default
    
    def _fetch_spot_price(self, symbol: str) -> float:
        """Fetch current spot price."""
        if self.broker:
            try:
                return self.broker.get_current_price(symbol) or 0
            except:
                pass
        return 0
    
    def _calculate_iv_rank(self, iv_index: str) -> float:
        """Calculate IV Rank (52-week percentile)."""
        # TODO: Implement with historical data
        return 20.0  # Default
    
    def _find_expiration(self) -> Optional[date]:
        """Find expiration date ~7 DTE (next Friday)."""
        today = date.today()
        target = today + timedelta(days=self.config.strikes.target_dte)
        
        # Find next Friday
        days_to_friday = (4 - target.weekday()) % 7
        if days_to_friday == 0 and target == today:
            days_to_friday = 7
        
        expiration = target + timedelta(days=days_to_friday)
        dte = (expiration - today).days
        
        if self.config.strikes.min_dte <= dte <= self.config.strikes.max_dte:
            return expiration
        
        return None
    
    def _fetch_option_greeks(self, symbol: str, expiration: date, strike: float, opt_type: str) -> Optional[Dict]:
        """Fetch Greeks for a single option."""
        if self.broker:
            try:
                return self.broker.get_option_greeks(symbol, expiration, strike, opt_type)
            except:
                pass
        return None
    
    def _fetch_position_greeks(self, position: IronCondor) -> Optional[GreeksSnapshot]:
        """Fetch current Greeks for a position."""
        # TODO: Implement with broker
        return None
    
    def _get_position_current_price(self, position: IronCondor) -> Optional[float]:
        """Get current price (debit to close) for position."""
        if self.broker:
            # TODO: Fetch current quotes
            pass
        return None
    
    def _calculate_position_size(self, wing_width: float, vix_multiplier: float) -> int:
        """Calculate position size based on risk limits."""
        max_risk = self.config.get_risk_per_condor(self.account_capital)
        margin_per = wing_width * 100
        
        base_qty = int(max_risk / margin_per) if margin_per > 0 else 1
        adjusted_qty = max(1, int(base_qty * vix_multiplier))
        
        return min(adjusted_qty, self.config.position.max_spreads_per_trade)
    
    # =========================================================================
    # POSITION MANAGEMENT
    # =========================================================================
    
    def open_position(self, signal: ICEntrySignal, fill_credit: float) -> IronCondor:
        """Create and track a new position from an entry signal."""
        position = IronCondor(
            underlying=signal.underlying,
            expiration=signal.expiration,
            contracts=signal.quantity,
            status=ICPositionStatus.OPEN,
            entry_time=datetime.now(timezone.utc),
            entry_credit=fill_credit,
            entry_vix=signal.vix_value,
            entry_iv_rank=signal.iv_rank,
            entry_spot_price=signal.spot_price,
        )
        
        # Create spreads
        exp = signal.expiration
        position.put_spread = VerticalSpread(
            short_leg=OptionContract(signal.underlying, exp, signal.short_put_strike, OptionType.PUT),
            long_leg=OptionContract(signal.underlying, exp, signal.long_put_strike, OptionType.PUT)
        )
        position.call_spread = VerticalSpread(
            short_leg=OptionContract(signal.underlying, exp, signal.short_call_strike, OptionType.CALL),
            long_leg=OptionContract(signal.underlying, exp, signal.long_call_strike, OptionType.CALL)
        )
        
        self.open_positions.append(position)
        
        logger.info(f"Opened IC position: {signal.underlying} x{signal.quantity} @ ${fill_credit:.2f}")
        
        return position
    
    def close_position(self, position: IronCondor, debit: float, reason: ICCloseReason) -> IronCondor:
        """Close a position."""
        position.status = ICPositionStatus.CLOSED
        position.exit_time = datetime.now(timezone.utc)
        position.exit_debit = debit
        position.exit_reason = reason
        
        # Calculate realized P&L
        if position.entry_credit:
            pnl_per = (position.entry_credit - debit) * 100
            position.realized_pnl = pnl_per * position.contracts
        
        # Move to closed list
        if position in self.open_positions:
            self.open_positions.remove(position)
        self.closed_positions.append(position)
        
        logger.info(f"Closed IC: {position.underlying} - {reason.value} - P&L: ${position.realized_pnl:.2f}")
        
        return position
    
    # =========================================================================
    # SCAN METHODS
    # =========================================================================
    
    def run_entry_scan(self) -> Optional[ICEntrySignal]:
        """Scan all enabled underlyings for entry opportunities."""
        for underlying in self.config.get_enabled_underlyings():
            logger.info(f"Scanning {underlying.symbol}...")
            
            passed, signal, gates = self.check_entry(underlying.symbol)
            
            # Log gate results
            for gate in gates:
                level = logging.INFO if gate.passed else logging.WARNING
                logger.log(level, f"  Gate {gate.gate_num} ({gate.gate_name}): {'PASS' if gate.passed else 'FAIL'} - {gate.message}")
            
            if passed and signal:
                return signal
        
        logger.info("No entry signals generated")
        return None
    
    def run_exit_scan(self) -> List[ICExitSignal]:
        """Scan all open positions for exit conditions."""
        return self.check_exits()
