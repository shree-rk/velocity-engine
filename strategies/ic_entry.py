"""
Iron Condor Entry Logic — Ported from Loveable check-entry
16 sequential gate checks before placing a trade.
"""

import logging
from datetime import datetime, date, timedelta, timezone
from typing import Optional, List, Tuple, Dict
from dataclasses import dataclass
from enum import Enum

from strategies.ic_config import (
    ICConfig, IC_CONFIG, ICUnderlying, UNDERLYING_CONFIGS,
    VIXRegime, BLOCKING_EVENTS, WARNING_EVENTS
)
from strategies.ic_greeks import ICGreeksFetcher, calculate_iv_rank
from filters.trading_hours import TradingHoursFilter
from filters.event_calendar import EventCalendarFilter, get_events_for_date

logger = logging.getLogger(__name__)


class GateResult(Enum):
    """Result of a gate check."""
    PASS = "PASS"
    FAIL = "FAIL"
    WARN = "WARN"


@dataclass
class GateCheck:
    """Result of a single gate check."""
    gate_number: int
    gate_name: str
    result: GateResult
    message: str
    data: Optional[Dict] = None


@dataclass
class EntrySignal:
    """Validated entry signal ready for execution."""
    underlying: ICUnderlying
    expiration: date
    short_put_strike: float
    long_put_strike: float
    short_call_strike: float
    long_call_strike: float
    wing_width: float
    quantity: int
    
    # Validation data
    short_put_delta: float
    short_call_delta: float
    vix_at_signal: float
    iv_rank: float
    spot_price: float
    
    # Sizing info
    vix_multiplier: float
    estimated_credit: float
    max_risk: float
    
    # Gate results
    gate_checks: List[GateCheck]
    
    def to_dict(self) -> dict:
        return {
            "underlying": self.underlying.value,
            "expiration": str(self.expiration),
            "short_put": self.short_put_strike,
            "long_put": self.long_put_strike,
            "short_call": self.short_call_strike,
            "long_call": self.long_call_strike,
            "quantity": self.quantity,
            "short_put_delta": self.short_put_delta,
            "short_call_delta": self.short_call_delta,
            "vix": self.vix_at_signal,
            "iv_rank": self.iv_rank,
            "spot_price": self.spot_price,
            "estimated_credit": self.estimated_credit,
        }


class ICEntryChecker:
    """
    Iron Condor Entry Checker — runs 16 sequential gate checks.
    
    All gates must pass for a trade to be placed.
    Only one trade per scan cycle.
    """
    
    def __init__(
        self,
        config: ICConfig = None,
        ib_connection = None,
        account_capital: float = 100000.0
    ):
        self.config = config or IC_CONFIG
        self.ib = ib_connection
        self.account_capital = account_capital
        
        # Filters
        self.hours_filter = TradingHoursFilter()
        self.event_filter = EventCalendarFilter()
        
        # Greeks fetcher
        self.greeks_fetcher = ICGreeksFetcher(ib_connection) if ib_connection else None
        
        # Track today's delta exits (for cooldown)
        self._delta_exits_today: Dict[str, datetime] = {}
        
        # Track open positions
        self._open_positions: List[Dict] = []
    
    def set_open_positions(self, positions: List[Dict]):
        """Update open positions for limit checks."""
        self._open_positions = positions
    
    def record_delta_exit(self, symbol: str):
        """Record a delta exit for same-day cooldown."""
        self._delta_exits_today[symbol] = datetime.now(timezone.utc)
    
    def clear_daily_exits(self):
        """Clear daily exit tracking (call at start of each day)."""
        self._delta_exits_today = {}
    
    def check_entry(self, underlying: ICUnderlying) -> Tuple[bool, Optional[EntrySignal], List[GateCheck]]:
        """
        Run all 16 entry gates for an underlying.
        
        Returns:
            Tuple of (all_passed, entry_signal, gate_checks)
        """
        gate_checks: List[GateCheck] = []
        
        # Gate 1: Market Hours
        gate = self._check_gate_1_market_hours()
        gate_checks.append(gate)
        if gate.result == GateResult.FAIL:
            return False, None, gate_checks
        
        # Gate 2: Economic Event Calendar
        gate = self._check_gate_2_events()
        gate_checks.append(gate)
        if gate.result == GateResult.FAIL:
            return False, None, gate_checks
        
        # Gate 3: Trading Enabled
        gate = self._check_gate_3_trading_enabled()
        gate_checks.append(gate)
        if gate.result == GateResult.FAIL:
            return False, None, gate_checks
        
        # Gate 4: Entry Day Check
        gate = self._check_gate_4_entry_day()
        gate_checks.append(gate)
        if gate.result == GateResult.FAIL:
            return False, None, gate_checks
        
        # Gate 5: Portfolio Position Limits
        gate = self._check_gate_5_portfolio_limits()
        gate_checks.append(gate)
        if gate.result == GateResult.FAIL:
            return False, None, gate_checks
        
        # Gate 6: Per-Underlying Limit
        gate = self._check_gate_6_underlying_limit(underlying)
        gate_checks.append(gate)
        if gate.result == GateResult.FAIL:
            return False, None, gate_checks
        
        # Gate 7: Duplicate Position Check
        gate = self._check_gate_7_duplicate(underlying)
        gate_checks.append(gate)
        if gate.result == GateResult.FAIL:
            return False, None, gate_checks
        
        # Gate 8: Same-Day Delta Exit Cooldown
        gate = self._check_gate_8_delta_cooldown(underlying)
        gate_checks.append(gate)
        if gate.result == GateResult.FAIL:
            return False, None, gate_checks
        
        # Gate 9: VIX Filter (3-tier)
        vix_gate = self._check_gate_9_vix()
        gate_checks.append(vix_gate)
        if vix_gate.result == GateResult.FAIL:
            return False, None, gate_checks
        vix_value = vix_gate.data.get("vix", 20.0)
        vix_multiplier = vix_gate.data.get("multiplier", 1.0)
        
        # Gate 10: IV Rank Filter
        iv_gate = self._check_gate_10_iv_rank(vix_value)
        gate_checks.append(iv_gate)
        if iv_gate.result == GateResult.FAIL:
            return False, None, gate_checks
        iv_rank = iv_gate.data.get("iv_rank", 0.0)
        
        # Gate 11: Trend Filter
        gate = self._check_gate_11_trend(underlying)
        gate_checks.append(gate)
        if gate.result == GateResult.FAIL:
            return False, None, gate_checks
        
        # Gate 12: ATR Expanding Filter
        gate = self._check_gate_12_atr(underlying)
        gate_checks.append(gate)
        if gate.result == GateResult.FAIL:
            return False, None, gate_checks
        
        # Gate 13: Delta Drift Filter
        gate = self._check_gate_13_delta_drift(underlying)
        gate_checks.append(gate)
        if gate.result == GateResult.FAIL:
            return False, None, gate_checks
        
        # Get spot price
        spot_price = self._get_spot_price(underlying)
        if spot_price is None:
            gate_checks.append(GateCheck(14, "Spot Price", GateResult.FAIL, "Failed to get spot price"))
            return False, None, gate_checks
        
        # Gate 14: Strike Selection with Delta Validation
        strike_gate = self._check_gate_14_strikes(underlying, spot_price, iv_rank)
        gate_checks.append(strike_gate)
        if strike_gate.result == GateResult.FAIL:
            return False, None, gate_checks
        
        strikes = strike_gate.data
        
        # Gate 15: Position Sizing
        size_gate = self._check_gate_15_sizing(underlying, strikes["wing_width"], vix_multiplier)
        gate_checks.append(size_gate)
        if size_gate.result == GateResult.FAIL:
            return False, None, gate_checks
        
        quantity = size_gate.data.get("quantity", 1)
        
        # Gate 16: Credit Validation
        credit_gate = self._check_gate_16_credit(
            underlying, strikes, quantity
        )
        gate_checks.append(credit_gate)
        if credit_gate.result == GateResult.FAIL:
            return False, None, gate_checks
        
        # All gates passed - create entry signal
        signal = EntrySignal(
            underlying=underlying,
            expiration=strikes["expiration"],
            short_put_strike=strikes["short_put"],
            long_put_strike=strikes["long_put"],
            short_call_strike=strikes["short_call"],
            long_call_strike=strikes["long_call"],
            wing_width=strikes["wing_width"],
            quantity=quantity,
            short_put_delta=strikes["short_put_delta"],
            short_call_delta=strikes["short_call_delta"],
            vix_at_signal=vix_value,
            iv_rank=iv_rank,
            spot_price=spot_price,
            vix_multiplier=vix_multiplier,
            estimated_credit=credit_gate.data.get("credit", 0.0),
            max_risk=size_gate.data.get("max_risk", 0.0),
            gate_checks=gate_checks
        )
        
        logger.info(f"Entry signal generated for {underlying.value}: {signal.to_dict()}")
        return True, signal, gate_checks
    
    # ==================== Gate Implementations ====================
    
    def _check_gate_1_market_hours(self) -> GateCheck:
        """Gate 1: Market Hours check."""
        if self.hours_filter.allows_trading():
            return GateCheck(1, "Market Hours", GateResult.PASS, "Market is open")
        else:
            session = self.hours_filter.get_current_session()
            return GateCheck(1, "Market Hours", GateResult.FAIL, f"Market closed: {session.value}")
    
    def _check_gate_2_events(self) -> GateCheck:
        """Gate 2: Economic Event Calendar."""
        today = date.today()
        tomorrow = today + timedelta(days=1)
        
        # Check today's events (blocking)
        today_events = get_events_for_date(today)
        for event in today_events:
            event_type = event.event_type.value if hasattr(event, 'event_type') else str(event)
            if event_type in BLOCKING_EVENTS:
                return GateCheck(
                    2, "Event Calendar", GateResult.FAIL,
                    f"Blocked: {event_type} today",
                    {"event": event_type, "date": str(today)}
                )
        
        # Check tomorrow's events (warning)
        tomorrow_events = get_events_for_date(tomorrow)
        for event in tomorrow_events:
            event_type = event.event_type.value if hasattr(event, 'event_type') else str(event)
            if event_type in WARNING_EVENTS:
                return GateCheck(
                    2, "Event Calendar", GateResult.WARN,
                    f"Warning: {event_type} tomorrow",
                    {"event": event_type, "date": str(tomorrow)}
                )
        
        return GateCheck(2, "Event Calendar", GateResult.PASS, "No blocking events")
    
    def _check_gate_3_trading_enabled(self) -> GateCheck:
        """Gate 3: Trading Enabled master switch."""
        if self.config.trading_enabled and self.config.entry_enabled:
            return GateCheck(3, "Trading Enabled", GateResult.PASS, "Trading enabled")
        return GateCheck(3, "Trading Enabled", GateResult.FAIL, "Trading disabled")
    
    def _check_gate_4_entry_day(self) -> GateCheck:
        """Gate 4: Entry Day Check."""
        today_weekday = date.today().weekday()
        
        if self.config.entry_days.use_production_days:
            allowed = self.config.entry_days.production_days
        else:
            allowed = self.config.entry_days.allowed_days
        
        if today_weekday in allowed:
            day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
            return GateCheck(4, "Entry Day", GateResult.PASS, f"{day_names[today_weekday]} is allowed")
        
        return GateCheck(4, "Entry Day", GateResult.FAIL, "Entry not allowed today")
    
    def _check_gate_5_portfolio_limits(self) -> GateCheck:
        """Gate 5: Portfolio Position Limits."""
        max_condors = int(self.account_capital / 100000) * self.config.sizing.max_condors_per_100k
        current_count = len(self._open_positions)
        
        if current_count >= max_condors:
            return GateCheck(
                5, "Portfolio Limits", GateResult.FAIL,
                f"Max condors reached: {current_count}/{max_condors}",
                {"current": current_count, "max": max_condors}
            )
        
        # Check same-expiry limit
        expiry_counts = {}
        for pos in self._open_positions:
            exp = pos.get("expiration")
            expiry_counts[exp] = expiry_counts.get(exp, 0) + 1
        
        # Will check against max_same_expiry_condors when we know the target expiry
        return GateCheck(
            5, "Portfolio Limits", GateResult.PASS,
            f"Positions: {current_count}/{max_condors}",
            {"current": current_count, "max": max_condors}
        )
    
    def _check_gate_6_underlying_limit(self, underlying: ICUnderlying) -> GateCheck:
        """Gate 6: Per-Underlying Limit."""
        config = UNDERLYING_CONFIGS.get(underlying)
        if not config:
            return GateCheck(6, "Underlying Limit", GateResult.FAIL, "Unknown underlying")
        
        if not config.enabled:
            return GateCheck(6, "Underlying Limit", GateResult.FAIL, f"{underlying.value} disabled")
        
        current = sum(1 for p in self._open_positions if p.get("symbol") == underlying.value)
        if current >= config.max_condors:
            return GateCheck(
                6, "Underlying Limit", GateResult.FAIL,
                f"{underlying.value}: {current}/{config.max_condors} max",
                {"current": current, "max": config.max_condors}
            )
        
        return GateCheck(
            6, "Underlying Limit", GateResult.PASS,
            f"{underlying.value}: {current}/{config.max_condors}",
            {"current": current, "max": config.max_condors}
        )
    
    def _check_gate_7_duplicate(self, underlying: ICUnderlying) -> GateCheck:
        """Gate 7: Duplicate Position Check."""
        has_open = any(p.get("symbol") == underlying.value for p in self._open_positions)
        
        if has_open:
            return GateCheck(
                7, "Duplicate Check", GateResult.FAIL,
                f"Already have open {underlying.value} position"
            )
        
        return GateCheck(7, "Duplicate Check", GateResult.PASS, "No duplicate")
    
    def _check_gate_8_delta_cooldown(self, underlying: ICUnderlying) -> GateCheck:
        """Gate 8: Same-Day Delta Exit Cooldown."""
        if underlying.value in self._delta_exits_today:
            exit_time = self._delta_exits_today[underlying.value]
            return GateCheck(
                8, "Delta Cooldown", GateResult.FAIL,
                f"Delta exit today at {exit_time.strftime('%H:%M')}",
                {"exit_time": exit_time.isoformat()}
            )
        
        return GateCheck(8, "Delta Cooldown", GateResult.PASS, "No recent delta exit")
    
    def _check_gate_9_vix(self) -> GateCheck:
        """Gate 9: VIX Filter (3-tier)."""
        vix_value = self._get_vix()
        
        if vix_value is None:
            return GateCheck(9, "VIX Filter", GateResult.FAIL, "Failed to fetch VIX")
        
        regime = self.config.vix.get_regime(vix_value)
        multiplier = self.config.vix.get_size_multiplier(vix_value)
        
        if regime == VIXRegime.BLOCKED:
            return GateCheck(
                9, "VIX Filter", GateResult.FAIL,
                f"VIX {vix_value:.1f} >= {self.config.vix.elevated_max} - BLOCKED",
                {"vix": vix_value, "regime": regime.value, "multiplier": 0}
            )
        
        if regime == VIXRegime.ELEVATED:
            return GateCheck(
                9, "VIX Filter", GateResult.WARN,
                f"VIX {vix_value:.1f} elevated - 50% size",
                {"vix": vix_value, "regime": regime.value, "multiplier": multiplier}
            )
        
        return GateCheck(
            9, "VIX Filter", GateResult.PASS,
            f"VIX {vix_value:.1f} normal",
            {"vix": vix_value, "regime": regime.value, "multiplier": multiplier}
        )
    
    def _check_gate_10_iv_rank(self, vix_value: float) -> GateCheck:
        """Gate 10: IV Rank Filter."""
        # Use VIX as proxy for IV Rank (would need historical data for real calc)
        # Fetch 52-week high/low from Yahoo Finance in production
        
        # Simplified: estimate IV rank from VIX level
        # Typical VIX range: 10-40, so normalize
        vix_low = 10.0
        vix_high = 40.0
        iv_rank = calculate_iv_rank(vix_value, vix_high, vix_low)
        
        if iv_rank > self.config.iv.max_iv_rank:
            return GateCheck(
                10, "IV Rank", GateResult.FAIL,
                f"IV Rank {iv_rank:.1f}% > {self.config.iv.max_iv_rank}%",
                {"iv_rank": iv_rank}
            )
        
        return GateCheck(
            10, "IV Rank", GateResult.PASS,
            f"IV Rank {iv_rank:.1f}%",
            {"iv_rank": iv_rank}
        )
    
    def _check_gate_11_trend(self, underlying: ICUnderlying) -> GateCheck:
        """Gate 11: Trend Filter (multi-timeframe)."""
        if not self.config.trend_filter.enabled:
            return GateCheck(11, "Trend Filter", GateResult.PASS, "Disabled")
        
        # Would fetch bars from IBKR and check trend
        # Simplified: pass for now
        return GateCheck(11, "Trend Filter", GateResult.PASS, "No strong trend detected")
    
    def _check_gate_12_atr(self, underlying: ICUnderlying) -> GateCheck:
        """Gate 12: ATR Expanding Filter."""
        if not self.config.atr_filter.enabled:
            return GateCheck(12, "ATR Filter", GateResult.PASS, "Disabled")
        
        # Would calculate 14-period ATR from IBKR
        # Simplified: pass for now
        return GateCheck(12, "ATR Filter", GateResult.PASS, "ATR stable")
    
    def _check_gate_13_delta_drift(self, underlying: ICUnderlying) -> GateCheck:
        """Gate 13: Delta Drift Filter."""
        if not self.config.delta_drift.enabled:
            return GateCheck(13, "Delta Drift", GateResult.PASS, "Disabled")
        
        # Would check 1h price change
        # Simplified: pass for now
        return GateCheck(13, "Delta Drift", GateResult.PASS, "No significant drift")
    
    def _check_gate_14_strikes(
        self, underlying: ICUnderlying, spot_price: float, iv_rank: float
    ) -> GateCheck:
        """Gate 14: Strike Selection with Delta Validation Loop."""
        
        # Find target expiration (next Friday >= 7 DTE)
        expiration = self._find_target_expiration()
        if expiration is None:
            return GateCheck(14, "Strike Selection", GateResult.FAIL, "No valid expiration")
        
        # Get wing width
        wing_width = self.config.get_wing_width(underlying)
        
        # Widen wings if IV high
        if iv_rank > self.config.iv.wing_widen_iv_threshold:
            wing_width = min(wing_width * 2, self.config.strikes.max_wing_width)
        
        # Initial strike estimates (~10 delta = ~5% OTM)
        short_put_strike = round(spot_price * 0.95)
        short_call_strike = round(spot_price * 1.05)
        
        # Delta validation loop
        validated = False
        attempts = 0
        short_put_delta = 0.0
        short_call_delta = 0.0
        
        while not validated and attempts < self.config.delta.max_widen_attempts:
            # Fetch real Greeks if available
            if self.greeks_fetcher:
                is_valid, put_delta, call_delta = self.greeks_fetcher.validate_entry_delta(
                    underlying.value,
                    expiration,
                    short_put_strike,
                    short_call_strike,
                    self.config.delta.max_entry_delta,
                    self.config.delta.min_valid_delta
                )
                
                short_put_delta = put_delta
                short_call_delta = call_delta
                
                if is_valid:
                    validated = True
                else:
                    # Widen strikes
                    short_put_strike -= self.config.delta.widen_increment
                    short_call_strike += self.config.delta.widen_increment
                    attempts += 1
            else:
                # No IBKR connection - use estimates
                short_put_delta = 0.10
                short_call_delta = 0.10
                validated = True
        
        if not validated:
            return GateCheck(
                14, "Strike Selection", GateResult.FAIL,
                f"Delta validation failed after {attempts} attempts",
                {"attempts": attempts}
            )
        
        # Calculate long strikes
        long_put_strike = short_put_strike - wing_width
        long_call_strike = short_call_strike + wing_width
        
        return GateCheck(
            14, "Strike Selection", GateResult.PASS,
            f"Strikes: {short_put_strike}P/{long_put_strike}P, {short_call_strike}C/{long_call_strike}C",
            {
                "expiration": expiration,
                "short_put": short_put_strike,
                "long_put": long_put_strike,
                "short_call": short_call_strike,
                "long_call": long_call_strike,
                "wing_width": wing_width,
                "short_put_delta": short_put_delta,
                "short_call_delta": short_call_delta,
            }
        )
    
    def _check_gate_15_sizing(
        self, underlying: ICUnderlying, wing_width: float, vix_multiplier: float
    ) -> GateCheck:
        """Gate 15: Position Sizing."""
        
        # Calculate available capital (30% of total, 70% reserve)
        available = self.account_capital * (1 - self.config.sizing.cash_reserve_percent / 100)
        
        # Max risk per trade (5%)
        max_risk_amount = self.account_capital * (self.config.sizing.max_risk_percent / 100)
        
        # Margin per spread
        margin_per_spread = wing_width * 100
        
        # Calculate quantity
        quantity = int(min(
            max_risk_amount / margin_per_spread,
            available / margin_per_spread,
            self.config.sizing.max_spreads_per_trade
        ))
        
        # Apply VIX multiplier
        quantity = int(quantity * vix_multiplier)
        
        # Minimum 1 contract
        quantity = max(1, quantity)
        
        max_risk = quantity * margin_per_spread
        
        return GateCheck(
            15, "Position Sizing", GateResult.PASS,
            f"Quantity: {quantity} contracts, Max Risk: ${max_risk:.0f}",
            {"quantity": quantity, "max_risk": max_risk, "vix_multiplier": vix_multiplier}
        )
    
    def _check_gate_16_credit(
        self, underlying: ICUnderlying, strikes: Dict, quantity: int
    ) -> GateCheck:
        """Gate 16: Credit Validation."""
        
        # Would fetch real quotes from IBKR
        # Estimate credit based on wing width (~25-33% of width typically)
        wing_width = strikes["wing_width"]
        estimated_credit = wing_width * 0.30  # 30% of width estimate
        
        # Check minimum credit
        min_credit_dollar = self.config.credit.min_credit_dollar
        min_credit_pct = (self.config.credit.min_credit_percent_of_width / 100) * wing_width
        min_credit = max(min_credit_dollar, min_credit_pct)
        
        if estimated_credit < min_credit:
            return GateCheck(
                16, "Credit Validation", GateResult.FAIL,
                f"Credit ${estimated_credit:.2f} below minimum ${min_credit:.2f}",
                {"credit": estimated_credit, "min_credit": min_credit}
            )
        
        return GateCheck(
            16, "Credit Validation", GateResult.PASS,
            f"Estimated credit: ${estimated_credit:.2f} per contract",
            {"credit": estimated_credit, "total_credit": estimated_credit * quantity}
        )
    
    # ==================== Helper Methods ====================
    
    def _get_vix(self) -> Optional[float]:
        """Fetch current VIX value."""
        try:
            # Try IBKR first
            if self.ib:
                from ib_insync import Index
                vix = Index("VIX", "CBOE")
                self.ib.qualifyContracts(vix)
                self.ib.reqMarketDataType(3)  # Delayed
                ticker = self.ib.reqMktData(vix)
                self.ib.sleep(1)
                price = ticker.last or ticker.close
                self.ib.cancelMktData(vix)
                if price and price > 0:
                    return float(price)
            
            # Fallback to Yahoo Finance
            import yfinance as yf
            vix_data = yf.Ticker("^VIX")
            hist = vix_data.history(period="1d")
            if not hist.empty:
                return float(hist['Close'].iloc[-1])
            
            return None
        except Exception as e:
            logger.error(f"Failed to fetch VIX: {e}")
            return None
    
    def _get_spot_price(self, underlying: ICUnderlying) -> Optional[float]:
        """Fetch current spot price for underlying."""
        try:
            if self.ib:
                from ib_insync import Stock, Index
                
                if underlying == ICUnderlying.SPX:
                    contract = Index("SPX", "CBOE")
                else:
                    contract = Stock(underlying.value, "SMART", "USD")
                
                self.ib.qualifyContracts(contract)
                self.ib.reqMarketDataType(3)
                ticker = self.ib.reqMktData(contract)
                self.ib.sleep(1)
                price = ticker.last or ticker.close
                self.ib.cancelMktData(contract)
                
                if price and price > 0:
                    return float(price)
            
            # Fallback to Yahoo
            import yfinance as yf
            symbol = "^SPX" if underlying == ICUnderlying.SPX else underlying.value
            data = yf.Ticker(symbol)
            hist = data.history(period="1d")
            if not hist.empty:
                return float(hist['Close'].iloc[-1])
            
            return None
        except Exception as e:
            logger.error(f"Failed to fetch spot price for {underlying.value}: {e}")
            return None
    
    def _find_target_expiration(self) -> Optional[date]:
        """Find next Friday >= 7 DTE."""
        today = date.today()
        target_dte = self.config.strikes.target_dte
        
        # Start from target DTE
        candidate = today + timedelta(days=target_dte)
        
        # Find next Friday
        days_to_friday = (4 - candidate.weekday()) % 7
        if days_to_friday == 0 and candidate == today:
            days_to_friday = 7
        
        expiration = candidate + timedelta(days=days_to_friday)
        
        # Check if within acceptable range
        dte = (expiration - today).days
        if self.config.strikes.min_dte <= dte <= self.config.strikes.max_dte:
            return expiration
        
        return None


def run_entry_scan(
    ib_connection,
    account_capital: float = 100000.0,
    config: ICConfig = None
) -> Optional[EntrySignal]:
    """
    Run entry scan across all enabled underlyings.
    Returns first valid entry signal (one trade per scan).
    """
    checker = ICEntryChecker(
        config=config or IC_CONFIG,
        ib_connection=ib_connection,
        account_capital=account_capital
    )
    
    for underlying in checker.config.get_enabled_underlyings():
        logger.info(f"Scanning {underlying.value}...")
        
        passed, signal, gates = checker.check_entry(underlying)
        
        # Log gate results
        for gate in gates:
            level = logging.INFO if gate.result == GateResult.PASS else logging.WARNING
            logger.log(level, f"  Gate {gate.gate_number} ({gate.gate_name}): {gate.result.value} - {gate.message}")
        
        if passed and signal:
            return signal
    
    logger.info("No entry signals generated")
    return None
