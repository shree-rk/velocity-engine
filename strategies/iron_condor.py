"""
Iron Condor Strategy
Weekly Iron Condors on SPY/SPX with VIX-based entry timing.
"""

import logging
from datetime import datetime, date, timedelta, timezone
from typing import Optional, List, Tuple
from dataclasses import dataclass

from strategies.ic_config import ICConfig, ICUnderlying, IC_DEFAULT_CONFIG
from strategies.ic_models import (
    IronCondor, ICSignal, ICStatus, ICCloseReason,
    OptionContract, VerticalSpread, OptionType
)
from filters.vix_filter import check_vix, VixRegime
from filters.event_calendar import EventCalendarFilter, get_events_for_date
from config.settings import BASE_CAPITAL

logger = logging.getLogger(__name__)


@dataclass
class ICStrategyStatus:
    """Current strategy status."""
    enabled: bool
    vix_value: float
    vix_regime: str
    vix_allows_entry: bool
    events_block_entry: bool
    next_blocking_event: Optional[str]
    days_until_event: Optional[int]
    open_positions: int
    max_positions: int
    can_open_new: bool
    message: str


class IronCondorStrategy:
    """
    Iron Condor Strategy for SPY/SPX.
    
    Entry Rules:
    - VIX between 15-35 (optimal 18-30)
    - No major events in next 2 days
    - Target 7 DTE weekly options
    - 10-delta short strikes
    - 2% account risk per trade
    
    Exit Rules:
    - 50% profit target
    - 2x credit stop loss
    - Close at 2 DTE
    """
    
    def __init__(
        self,
        config: ICConfig = None,
        account_value: float = None
    ):
        self.config = config or IC_DEFAULT_CONFIG
        self.account_value = account_value or BASE_CAPITAL
        self.enabled = True
        
        # Track open positions
        self.open_positions: List[IronCondor] = []
        
        # Event filter
        self.event_filter = EventCalendarFilter()
        
        logger.info(
            f"IronCondorStrategy initialized - "
            f"Underlyings: {[u.value for u in self.config.underlyings]}, "
            f"Target DTE: {self.config.target_dte}, "
            f"Risk/Trade: {self.config.risk_per_trade_pct:.1%}"
        )
    
    @property
    def name(self) -> str:
        return "iron_condor"
    
    def get_status(self) -> ICStrategyStatus:
        """Get current strategy status."""
        vix = check_vix()
        vix_allows = self.config.min_vix <= vix.value <= self.config.max_vix
        
        # Check events
        events_block, next_event, days_until = self._check_upcoming_events()
        
        # Position count
        open_count = len([p for p in self.open_positions if p.status == ICStatus.OPEN])
        can_open = (
            self.enabled and
            vix_allows and
            not events_block and
            open_count < self.config.max_total_positions
        )
        
        # Build message
        if not self.enabled:
            message = "Strategy disabled"
        elif not vix_allows:
            if vix.value < self.config.min_vix:
                message = f"VIX too low ({vix.value:.1f}), waiting for higher volatility"
            else:
                message = f"VIX too high ({vix.value:.1f}), risk elevated"
        elif events_block:
            message = f"Blocking due to {next_event} in {days_until} days"
        elif open_count >= self.config.max_total_positions:
            message = "Max positions reached"
        else:
            message = "Ready to trade"
        
        return ICStrategyStatus(
            enabled=self.enabled,
            vix_value=vix.value,
            vix_regime=vix.regime.value,
            vix_allows_entry=vix_allows,
            events_block_entry=events_block,
            next_blocking_event=next_event,
            days_until_event=days_until,
            open_positions=open_count,
            max_positions=self.config.max_total_positions,
            can_open_new=can_open,
            message=message
        )
    
    def _check_upcoming_events(self) -> Tuple[bool, Optional[str], Optional[int]]:
        """Check if upcoming events block new entries."""
        today = date.today()
        
        for i in range(self.config.block_days_before_event + 1):
            check_date = today + timedelta(days=i)
            events = get_events_for_date(check_date)
            
            for event in events:
                event_name = event.event_type.value if hasattr(event, 'event_type') else str(event)
                
                # High impact events block entry
                if event_name in ["FOMC", "CPI", "NFP"]:
                    return True, event_name, i
        
        return False, None, None
    
    def calculate_position_size(
        self,
        max_loss_per_contract: float,
        underlying: ICUnderlying
    ) -> int:
        """
        Calculate number of contracts based on risk.
        
        Args:
            max_loss_per_contract: Max loss per single contract
            underlying: The underlying symbol
            
        Returns:
            Number of contracts to trade
        """
        risk_amount = self.account_value * self.config.risk_per_trade_pct
        
        if max_loss_per_contract <= 0:
            return 0
        
        contracts = int(risk_amount / max_loss_per_contract)
        
        # Minimum 1 contract if any size allowed
        contracts = max(1, contracts)
        
        # Cap based on underlying
        if underlying == ICUnderlying.SPX:
            contracts = min(contracts, 2)  # SPX is 10x SPY
        else:
            contracts = min(contracts, 10)  # Max 10 contracts
        
        return contracts
    
    def find_target_expiration(self, underlying: ICUnderlying) -> Optional[date]:
        """
        Find the best expiration date close to target DTE.
        
        For weekly options, this is typically the next Friday.
        """
        today = date.today()
        target = today + timedelta(days=self.config.target_dte)
        
        # Find next Friday (weekday 4)
        days_until_friday = (4 - target.weekday()) % 7
        if days_until_friday == 0 and target == today:
            days_until_friday = 7
        
        expiration = target + timedelta(days=days_until_friday)
        
        # Check if within acceptable range
        dte = (expiration - today).days
        if self.config.min_dte <= dte <= self.config.max_dte:
            return expiration
        
        # Try this week's Friday
        this_friday = today + timedelta(days=(4 - today.weekday()) % 7)
        if this_friday > today:
            dte = (this_friday - today).days
            if self.config.min_dte <= dte <= self.config.max_dte:
                return this_friday
        
        # Try next week's Friday
        next_friday = this_friday + timedelta(days=7)
        dte = (next_friday - today).days
        if self.config.min_dte <= dte <= self.config.max_dte:
            return next_friday
        
        return None
    
    def select_strikes(
        self,
        underlying: ICUnderlying,
        current_price: float,
        options_chain: List[OptionContract]
    ) -> Optional[Tuple[float, float, float, float]]:
        """
        Select strikes for Iron Condor.
        
        Returns:
            Tuple of (short_put, long_put, short_call, long_call) strikes
            or None if no valid strikes found.
        """
        width = self.config.get_spread_width(underlying)
        
        # Separate puts and calls
        puts = [o for o in options_chain if o.option_type == OptionType.PUT]
        calls = [o for o in options_chain if o.option_type == OptionType.CALL]
        
        if not puts or not calls:
            return None
        
        # Find short put (OTM, ~10 delta)
        short_put = self._find_strike_by_delta(
            puts,
            target_delta=-self.config.short_put_delta,
            delta_range=(-self.config.delta_range[1], -self.config.delta_range[0])
        )
        
        # Find short call (OTM, ~10 delta)
        short_call = self._find_strike_by_delta(
            calls,
            target_delta=self.config.short_call_delta,
            delta_range=self.config.delta_range
        )
        
        if short_put is None or short_call is None:
            # Fallback: use price-based selection
            short_put_strike = round(current_price * 0.95 / width) * width
            short_call_strike = round(current_price * 1.05 / width) * width
        else:
            short_put_strike = short_put.strike
            short_call_strike = short_call.strike
        
        # Calculate long strikes
        long_put_strike = short_put_strike - width
        long_call_strike = short_call_strike + width
        
        return (short_put_strike, long_put_strike, short_call_strike, long_call_strike)
    
    def _find_strike_by_delta(
        self,
        options: List[OptionContract],
        target_delta: float,
        delta_range: Tuple[float, float]
    ) -> Optional[OptionContract]:
        """Find option closest to target delta."""
        valid_options = [
            o for o in options
            if o.delta is not None and delta_range[0] <= o.delta <= delta_range[1]
        ]
        
        if not valid_options:
            return None
        
        # Find closest to target
        return min(valid_options, key=lambda o: abs(o.delta - target_delta))
    
    def generate_signal(
        self,
        underlying: ICUnderlying,
        current_price: float,
        options_chain: List[OptionContract],
        vix_value: float
    ) -> Optional[ICSignal]:
        """
        Generate Iron Condor signal if conditions are met.
        
        Args:
            underlying: The underlying to trade
            current_price: Current price of underlying
            options_chain: Available options
            vix_value: Current VIX value
            
        Returns:
            ICSignal if trade should be taken, None otherwise
        """
        # Check VIX
        if not (self.config.min_vix <= vix_value <= self.config.max_vix):
            logger.debug(f"VIX {vix_value} outside range, no signal")
            return None
        
        # Check events
        events_block, event_name, _ = self._check_upcoming_events()
        if events_block:
            logger.debug(f"Event {event_name} blocking entry")
            return None
        
        # Check position limits
        underlying_positions = len([
            p for p in self.open_positions
            if p.status == ICStatus.OPEN and p.underlying == underlying.value
        ])
        
        if underlying_positions >= self.config.max_concurrent_per_underlying:
            logger.debug(f"Max positions for {underlying.value} reached")
            return None
        
        # Find expiration
        expiration = self.find_target_expiration(underlying)
        if expiration is None:
            logger.debug("No valid expiration found")
            return None
        
        # Select strikes
        strikes = self.select_strikes(underlying, current_price, options_chain)
        if strikes is None:
            logger.debug("Could not select strikes")
            return None
        
        short_put, long_put, short_call, long_call = strikes
        width = self.config.get_spread_width(underlying)
        
        # Estimate credit (would come from actual chain in production)
        # Rough estimate: 25-35% of width in high VIX
        vix_factor = min(1.0, (vix_value - 15) / 20)  # 0-1 scale
        estimated_credit_pct = 0.25 + (vix_factor * 0.15)  # 25-40%
        estimated_credit = width * estimated_credit_pct
        
        # Check minimum credit
        if estimated_credit / width < self.config.min_credit_pct:
            logger.debug(f"Credit {estimated_credit:.2f} below minimum")
            return None
        
        # Calculate max loss and position size
        max_loss_per_contract = (width - estimated_credit) * 100
        contracts = self.calculate_position_size(max_loss_per_contract, underlying)
        
        # Get deltas (estimated if not from chain)
        short_put_delta = -0.10
        short_call_delta = 0.10
        
        for opt in options_chain:
            if opt.strike == short_put and opt.option_type == OptionType.PUT and opt.delta:
                short_put_delta = opt.delta
            if opt.strike == short_call and opt.option_type == OptionType.CALL and opt.delta:
                short_call_delta = opt.delta
        
        signal = ICSignal(
            underlying=underlying.value,
            expiration=expiration,
            short_put_strike=short_put,
            long_put_strike=long_put,
            short_call_strike=short_call,
            long_call_strike=long_call,
            expected_credit=estimated_credit,
            expected_max_loss=max_loss_per_contract,
            short_put_delta=short_put_delta,
            short_call_delta=short_call_delta,
            underlying_price=current_price,
            vix_at_signal=vix_value,
            recommended_contracts=contracts
        )
        
        logger.info(
            f"IC Signal: {underlying.value} {expiration} "
            f"P:{short_put}/{long_put} C:{short_call}/{long_call} "
            f"Credit: ${estimated_credit:.2f} x {contracts}"
        )
        
        return signal
    
    def check_exit_conditions(self, position: IronCondor, current_price: float) -> Optional[ICCloseReason]:
        """
        Check if position should be closed.
        
        Args:
            position: The Iron Condor position
            current_price: Current price of the IC (debit to close)
            
        Returns:
            ICCloseReason if should close, None otherwise
        """
        if position.status != ICStatus.OPEN:
            return None
        
        entry_credit = position.entry_credit or 0
        
        # Profit target: 50% of credit
        profit_target = entry_credit * (1 - self.config.profit_target_pct)
        if current_price <= profit_target:
            return ICCloseReason.PROFIT_TARGET
        
        # Stop loss: 2x credit
        stop_loss = entry_credit * self.config.stop_loss_multiplier
        if current_price >= stop_loss:
            return ICCloseReason.STOP_LOSS
        
        # DTE exit
        if position.dte <= self.config.close_at_dte:
            return ICCloseReason.DTE_EXIT
        
        return None
    
    def create_position(self, signal: ICSignal, fill_credit: float) -> IronCondor:
        """
        Create Iron Condor position from signal.
        
        Args:
            signal: The entry signal
            fill_credit: Actual credit received
            
        Returns:
            IronCondor position
        """
        # Create option contracts
        short_put = OptionContract(
            symbol=signal.underlying,
            expiration=signal.expiration,
            strike=signal.short_put_strike,
            option_type=OptionType.PUT,
            delta=signal.short_put_delta
        )
        long_put = OptionContract(
            symbol=signal.underlying,
            expiration=signal.expiration,
            strike=signal.long_put_strike,
            option_type=OptionType.PUT
        )
        short_call = OptionContract(
            symbol=signal.underlying,
            expiration=signal.expiration,
            strike=signal.short_call_strike,
            option_type=OptionType.CALL,
            delta=signal.short_call_delta
        )
        long_call = OptionContract(
            symbol=signal.underlying,
            expiration=signal.expiration,
            strike=signal.long_call_strike,
            option_type=OptionType.CALL
        )
        
        # Create spreads
        put_spread = VerticalSpread(short_leg=short_put, long_leg=long_put)
        call_spread = VerticalSpread(short_leg=short_call, long_leg=long_call)
        
        # Create Iron Condor
        ic = IronCondor(
            underlying=signal.underlying,
            expiration=signal.expiration,
            put_spread=put_spread,
            call_spread=call_spread,
            contracts=signal.recommended_contracts,
            status=ICStatus.OPEN,
            entry_time=datetime.now(timezone.utc),
            entry_credit=fill_credit,
            entry_vix=signal.vix_at_signal
        )
        
        self.open_positions.append(ic)
        
        logger.info(
            f"Opened IC: {signal.underlying} "
            f"P:{signal.short_put_strike}/{signal.long_put_strike} "
            f"C:{signal.short_call_strike}/{signal.long_call_strike} "
            f"x{signal.recommended_contracts} @ ${fill_credit:.2f}"
        )
        
        return ic
    
    def close_position(
        self,
        position: IronCondor,
        close_debit: float,
        reason: ICCloseReason
    ) -> IronCondor:
        """
        Close Iron Condor position.
        
        Args:
            position: The position to close
            close_debit: Debit paid to close
            reason: Reason for closing
            
        Returns:
            Updated position
        """
        position.status = ICStatus.CLOSED
        position.exit_time = datetime.now(timezone.utc)
        position.exit_debit = close_debit
        position.close_reason = reason
        
        # Calculate P&L
        entry_credit = position.entry_credit or 0
        pnl_per_contract = (entry_credit - close_debit) * 100
        position.realized_pnl = pnl_per_contract * position.contracts
        
        logger.info(
            f"Closed IC: {position.underlying} "
            f"Reason: {reason.value} "
            f"P&L: ${position.realized_pnl:.2f}"
        )
        
        return position
    
    def get_open_positions(self) -> List[IronCondor]:
        """Get all open positions."""
        return [p for p in self.open_positions if p.status == ICStatus.OPEN]
    
    def get_closed_positions(self, limit: int = 50) -> List[IronCondor]:
        """Get closed positions."""
        closed = [p for p in self.open_positions if p.status == ICStatus.CLOSED]
        return sorted(closed, key=lambda p: p.exit_time or datetime.min, reverse=True)[:limit]
    
    def get_total_pnl(self) -> float:
        """Get total realized P&L."""
        return sum(p.realized_pnl or 0 for p in self.open_positions if p.status == ICStatus.CLOSED)
    
    def enable(self):
        """Enable the strategy."""
        self.enabled = True
        logger.info("Iron Condor strategy enabled")
    
    def disable(self):
        """Disable the strategy."""
        self.enabled = False
        logger.info("Iron Condor strategy disabled")
