"""
Velocity Engine
Main orchestrator that coordinates strategies, risk management, and execution.

The Engine is the central hub that:
1. Runs strategy scans
2. Applies risk filters
3. Executes trades via broker
4. Monitors positions
5. Tracks performance
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from enum import Enum

from config.settings import (
    ALPACA_TRADING_MODE,
    TradingMode,
    SCAN_INTERVAL_MINUTES,
    MAX_POSITIONS
)
from strategies.base import BaseStrategy, TradeSignal, SignalDirection
from strategies.velocity_mr import VelocityMRStrategy
from core.risk_manager import RiskManager, RiskStatus
from brokers.alpaca_broker import AlpacaBroker, create_broker, Position, OrderResult
from filters.vix_filter import VixFilter, VixRegime, check_vix
from filters.event_calendar import EventCalendarFilter, check_events
from filters.trading_hours import TradingHoursFilter, check_trading_hours, MarketSession

logger = logging.getLogger(__name__)


class EngineState(Enum):
    """Engine operational states."""
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    PAUSED = "paused"
    ERROR = "error"


@dataclass
class ScanResult:
    """Result of a scan cycle."""
    timestamp: datetime
    symbols_scanned: int
    signals_found: int
    signals_executed: int
    signals_filtered: int
    
    filter_reasons: Dict[str, int] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    
    duration_ms: int = 0


@dataclass
class EngineStatus:
    """Current engine status."""
    state: EngineState
    mode: str  # PAPER or LIVE
    
    # Broker status
    broker_connected: bool
    market_open: bool
    
    # Filter status
    vix_regime: str
    vix_value: float
    events_blocked: bool
    trading_hours_ok: bool
    
    # Risk status
    alpha_shield_triggered: bool
    current_drawdown: float
    
    # Position status
    open_positions: int
    max_positions: int
    
    # Performance
    equity: float
    high_water_mark: float
    
    # Last scan
    last_scan_time: Optional[datetime]
    last_scan_signals: int
    
    message: str


class VelocityEngine:
    """
    Main trading engine orchestrator.
    
    Coordinates all components for automated trading.
    """
    
    def __init__(
        self,
        strategy: BaseStrategy = None,
        broker: AlpacaBroker = None,
        risk_manager: RiskManager = None,
        vix_filter: VixFilter = None,
        event_filter: EventCalendarFilter = None,
        hours_filter: TradingHoursFilter = None,
        auto_connect: bool = True
    ):
        """
        Initialize Velocity Engine.
        
        Args:
            strategy: Trading strategy (defaults to VelocityMR).
            broker: Broker instance (auto-creates if not provided).
            risk_manager: Risk manager instance.
            vix_filter: VIX filter instance.
            event_filter: Event calendar filter.
            hours_filter: Trading hours filter.
            auto_connect: Auto-connect to broker on init.
        """
        self.state = EngineState.STOPPED
        
        # Initialize filters
        self.vix_filter = vix_filter or VixFilter(cache_seconds=60)
        self.event_filter = event_filter or EventCalendarFilter()
        self.hours_filter = hours_filter or TradingHoursFilter(
            buffer_minutes_open=5,
            buffer_minutes_close=15
        )
        
        # Initialize risk manager (needs vix_filter)
        self.risk_manager = risk_manager or RiskManager(
            vix_filter=self.vix_filter
        )
        
        # Initialize strategy
        self.strategy = strategy or VelocityMRStrategy()
        
        # Initialize broker
        self.broker = broker
        if self.broker is None and auto_connect:
            try:
                self.broker = create_broker()
            except Exception as e:
                logger.error(f"Failed to create broker: {e}")
                self.broker = None
        
        # Scan tracking
        self._last_scan_result: Optional[ScanResult] = None
        self._scan_count = 0
        
        logger.info(
            f"VelocityEngine initialized - "
            f"Strategy: {self.strategy.name}, "
            f"Mode: {ALPACA_TRADING_MODE.value}"
        )
    
    # =========================================================================
    # Lifecycle Management
    # =========================================================================
    
    def start(self) -> bool:
        """
        Start the engine.
        
        Returns:
            True if started successfully.
        """
        if self.state == EngineState.RUNNING:
            logger.warning("Engine already running")
            return True
        
        self.state = EngineState.STARTING
        logger.info("Starting Velocity Engine...")
        
        # Connect broker if needed
        if self.broker is None:
            try:
                self.broker = create_broker()
            except Exception as e:
                logger.error(f"Failed to connect broker: {e}")
                self.state = EngineState.ERROR
                return False
        
        if not self.broker.is_connected:
            if not self.broker.connect():
                logger.error("Failed to connect to broker")
                self.state = EngineState.ERROR
                return False
        
        # Sync equity from broker
        self._sync_account()
        
        self.state = EngineState.RUNNING
        logger.info("✓ Velocity Engine started")
        return True
    
    def stop(self) -> None:
        """Stop the engine."""
        logger.info("Stopping Velocity Engine...")
        
        if self.broker and self.broker.is_connected:
            self.broker.disconnect()
        
        self.state = EngineState.STOPPED
        logger.info("✓ Velocity Engine stopped")
    
    def pause(self) -> None:
        """Pause the engine (stops scanning but stays connected)."""
        if self.state == EngineState.RUNNING:
            self.state = EngineState.PAUSED
            logger.info("Engine paused")
    
    def resume(self) -> None:
        """Resume a paused engine."""
        if self.state == EngineState.PAUSED:
            self.state = EngineState.RUNNING
            logger.info("Engine resumed")
    
    # =========================================================================
    # Account Sync
    # =========================================================================
    
    def _sync_account(self) -> bool:
        """Sync account data from broker."""
        if not self.broker or not self.broker.is_connected:
            return False
        
        try:
            # Update equity
            account = self.broker.get_account()
            if account:
                self.risk_manager.update_equity(float(account.equity))
            
            # Update positions
            positions = self.broker.get_positions()
            self.risk_manager.set_positions([
                {"symbol": p.symbol, "value": float(p.market_value)}
                for p in positions
            ])
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to sync account: {e}")
            return False
    
    # =========================================================================
    # Pre-Trade Checks
    # =========================================================================
    
    def _check_all_filters(self) -> tuple[bool, List[str]]:
        """
        Run all pre-trade filter checks.
        
        Returns:
            Tuple of (all_passed, list_of_blocking_reasons).
        """
        blocks = []
        
        # Check trading hours
        hours_status = self.hours_filter.get_status()
        if not hours_status.is_trading_allowed:
            blocks.append(f"Trading hours: {hours_status.message}")
        
        # Check VIX
        vix_reading = self.vix_filter.get_reading()
        if not vix_reading.trading_allowed:
            blocks.append(f"VIX: {vix_reading.message}")
        
        # Check event calendar
        event_status = self.event_filter.get_status()
        if event_status.is_blocked:
            blocks.append(f"Event: {event_status.message}")
        
        # Check Alpha Shield
        if self.risk_manager.is_alpha_shield_triggered():
            blocks.append("Alpha Shield triggered")
        
        return len(blocks) == 0, blocks
    
    # =========================================================================
    # Scan Cycle
    # =========================================================================
    
    def run_scan(self) -> ScanResult:
        """
        Run a complete scan cycle.
        
        1. Check all filters
        2. Run strategy scan
        3. Validate signals through risk manager
        4. Execute valid trades
        
        Returns:
            ScanResult with cycle details.
        """
        start_time = datetime.now(timezone.utc)
        
        result = ScanResult(
            timestamp=start_time,
            symbols_scanned=0,
            signals_found=0,
            signals_executed=0,
            signals_filtered=0
        )
        
        # Check engine state
        if self.state != EngineState.RUNNING:
            result.errors.append(f"Engine not running (state: {self.state.value})")
            return result
        
        # Sync account
        self._sync_account()
        
        # Run filter checks
        filters_ok, filter_blocks = self._check_all_filters()
        
        if not filters_ok:
            for block in filter_blocks:
                result.filter_reasons[block] = result.filter_reasons.get(block, 0) + 1
            
            logger.info(f"Scan blocked by filters: {filter_blocks}")
            
            # Still calculate duration
            result.duration_ms = int(
                (datetime.now(timezone.utc) - start_time).total_seconds() * 1000
            )
            
            self._last_scan_result = result
            self._scan_count += 1
            return result
        
        # Run strategy scan
        symbols = self.strategy.symbols if hasattr(self.strategy, 'symbols') else []
        result.symbols_scanned = len(symbols)
        
        try:
            signals = self.strategy.scan()
            result.signals_found = len(signals)
            
            logger.info(f"Scan found {len(signals)} signals")
            
            # Process each signal
            for signal in signals:
                executed = self._process_signal(signal, result)
                if executed:
                    result.signals_executed += 1
                else:
                    result.signals_filtered += 1
                    
        except Exception as e:
            logger.error(f"Scan error: {e}")
            result.errors.append(str(e))
        
        # Calculate duration
        result.duration_ms = int(
            (datetime.now(timezone.utc) - start_time).total_seconds() * 1000
        )
        
        self._last_scan_result = result
        self._scan_count += 1
        
        logger.info(
            f"Scan complete: {result.signals_executed}/{result.signals_found} executed, "
            f"{result.duration_ms}ms"
        )
        
        return result
    
    def _process_signal(self, signal: TradeSignal, result: ScanResult) -> bool:
        """
        Process a single trade signal.
        
        Args:
            signal: The trade signal to process.
            result: ScanResult to update with filter reasons.
            
        Returns:
            True if trade was executed.
        """
        # Check if new trades allowed
        allowed, reason = self.risk_manager.allows_new_trade()
        if not allowed:
            result.filter_reasons[reason] = result.filter_reasons.get(reason, 0) + 1
            logger.debug(f"{signal.symbol} filtered: {reason}")
            return False
        
        # Calculate position size
        equity = self.risk_manager._current_equity
        size_result = self.risk_manager.calculate_position_size(
            symbol=signal.symbol,
            entry_price=signal.entry_price,
            stop_loss=signal.stop_loss,
            equity=equity
        )
        
        if not size_result.is_valid:
            reason = size_result.rejection_reason or "Position sizing failed"
            result.filter_reasons[reason] = result.filter_reasons.get(reason, 0) + 1
            logger.debug(f"{signal.symbol} filtered: {reason}")
            return False
        
        # Execute trade
        return self._execute_entry(signal, size_result.shares)
    
    def _execute_entry(self, signal: TradeSignal, shares: int) -> bool:
        """
        Execute an entry order.
        
        Args:
            signal: Trade signal.
            shares: Number of shares to buy.
            
        Returns:
            True if order submitted successfully.
        """
        if not self.broker or not self.broker.is_connected:
            logger.error("Broker not connected, cannot execute trade")
            return False
        
        try:
            order_result = self.broker.submit_market_order(
                symbol=signal.symbol,
                qty=shares,
                side="buy",
                time_in_force="day"
            )
            
            if order_result.success:
                logger.info(
                    f"✓ ENTRY: {signal.symbol} - {shares} shares @ ~${signal.entry_price:.2f} "
                    f"(Order: {order_result.order_id})"
                )
                return True
            else:
                logger.error(f"Order failed: {order_result.error_message}")
                return False
                
        except Exception as e:
            logger.error(f"Execution error: {e}")
            return False
    
    # =========================================================================
    # Position Monitoring
    # =========================================================================
    
    def monitor_positions(self) -> List[OrderResult]:
        """
        Monitor open positions for exit conditions.
        
        Returns:
            List of exit orders executed.
        """
        if not self.broker or not self.broker.is_connected:
            return []
        
        exits = []
        positions = self.broker.get_positions()
        
        for position in positions:
            try:
                # Get current stop loss from position (would need to track this)
                # For now, just check strategy exit conditions
                exit_signal = self.strategy.check_exit(
                    symbol=position.symbol,
                    entry_price=float(position.avg_entry_price),
                    current_price=float(position.current_price),
                    stop_loss=0,  # Would need actual stop from storage
                    take_profit=None
                )
                
                if exit_signal:
                    result = self._execute_exit(position.symbol)
                    if result and result.success:
                        exits.append(result)
                        
            except Exception as e:
                logger.error(f"Error monitoring {position.symbol}: {e}")
        
        return exits
    
    def _execute_exit(self, symbol: str) -> Optional[OrderResult]:
        """
        Execute position exit.
        
        Args:
            symbol: Symbol to exit.
            
        Returns:
            OrderResult or None.
        """
        if not self.broker:
            return None
        
        try:
            result = self.broker.close_position(symbol)
            
            if result.success:
                logger.info(f"✓ EXIT: {symbol} (Order: {result.order_id})")
            
            return result
            
        except Exception as e:
            logger.error(f"Exit error for {symbol}: {e}")
            return None
    
    # =========================================================================
    # Status & Reporting
    # =========================================================================
    
    def get_status(self) -> EngineStatus:
        """Get current engine status."""
        # Get filter statuses
        vix_reading = self.vix_filter.get_reading()
        hours_status = self.hours_filter.get_status()
        event_status = self.event_filter.get_status()
        
        # Get risk status
        drawdown_abs, drawdown_pct = self.risk_manager.get_drawdown()
        
        # Position count
        position_count = self.risk_manager.get_position_count()
        
        # Build message
        if self.state != EngineState.RUNNING:
            message = f"Engine {self.state.value}"
        elif self.risk_manager.is_alpha_shield_triggered():
            message = "⚠️ Alpha Shield - Trading blocked"
        elif not hours_status.is_trading_allowed:
            message = f"⏰ {hours_status.message}"
        elif not vix_reading.trading_allowed:
            message = f"📊 VIX {vix_reading.value:.1f} - Trading blocked"
        elif event_status.is_blocked:
            message = f"📅 {event_status.message}"
        else:
            message = "✓ Ready to trade"
        
        return EngineStatus(
            state=self.state,
            mode=ALPACA_TRADING_MODE.value,
            broker_connected=self.broker.is_connected if self.broker else False,
            market_open=hours_status.session == MarketSession.REGULAR,
            vix_regime=vix_reading.regime.value,
            vix_value=vix_reading.value,
            events_blocked=event_status.is_blocked,
            trading_hours_ok=hours_status.is_trading_allowed,
            alpha_shield_triggered=self.risk_manager.is_alpha_shield_triggered(),
            current_drawdown=drawdown_pct,
            open_positions=position_count,
            max_positions=MAX_POSITIONS,
            equity=self.risk_manager._current_equity,
            high_water_mark=self.risk_manager._high_water_mark,
            last_scan_time=self._last_scan_result.timestamp if self._last_scan_result else None,
            last_scan_signals=self._last_scan_result.signals_found if self._last_scan_result else 0,
            message=message
        )
    
    def get_positions(self) -> List[Position]:
        """Get current positions from broker."""
        if not self.broker or not self.broker.is_connected:
            return []
        return self.broker.get_positions()
    
    def get_scan_summary(self) -> Dict[str, Any]:
        """Get detailed scan summary for all symbols."""
        return self.strategy.get_scan_summary()
