"""
Alpaca Broker Implementation
Handles order execution, position management, and account data for Alpaca API.
Supports both paper and live trading modes.
"""

import logging
from decimal import Decimal
from typing import Optional
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import (
    MarketOrderRequest,
    LimitOrderRequest,
    StopLossRequest,
    GetOrdersRequest
)
from alpaca.trading.enums import (
    OrderSide,
    TimeInForce,
    OrderStatus,
    QueryOrderStatus
)
from alpaca.common.exceptions import APIError

from config.settings import (
    ALPACA_API_KEY,
    ALPACA_SECRET_KEY,
    ALPACA_TRADING_MODE,
    TradingMode
)

logger = logging.getLogger(__name__)


class OrderType(Enum):
    """Order types supported by the broker."""
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"


@dataclass
class OrderResult:
    """Result of an order submission."""
    success: bool
    order_id: Optional[str] = None
    symbol: Optional[str] = None
    side: Optional[str] = None
    qty: Optional[int] = None
    filled_qty: Optional[int] = None
    filled_avg_price: Optional[Decimal] = None
    status: Optional[str] = None
    error_message: Optional[str] = None
    submitted_at: Optional[datetime] = None


@dataclass
class Position:
    """Current position data."""
    symbol: str
    qty: int
    avg_entry_price: Decimal
    current_price: Decimal
    market_value: Decimal
    unrealized_pl: Decimal
    unrealized_plpc: Decimal  # Percent
    side: str  # 'long' or 'short'


@dataclass
class AccountInfo:
    """Account summary data."""
    equity: Decimal
    cash: Decimal
    buying_power: Decimal
    portfolio_value: Decimal
    pattern_day_trader: bool
    trading_blocked: bool
    account_blocked: bool
    created_at: datetime


class AlpacaBroker:
    """
    Alpaca Trading API wrapper.
    
    Handles all interactions with Alpaca for order execution,
    position management, and account queries.
    """
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        paper: Optional[bool] = None
    ):
        """
        Initialize Alpaca broker connection.
        
        Args:
            api_key: Alpaca API key (uses config default if not provided)
            secret_key: Alpaca secret key (uses config default if not provided)
            paper: True for paper trading (uses config default if not provided)
        """
        self.api_key = api_key or ALPACA_API_KEY
        self.secret_key = secret_key or ALPACA_SECRET_KEY
        
        # Determine paper mode from config if not explicitly set
        if paper is None:
            self.paper = ALPACA_TRADING_MODE == TradingMode.PAPER
        else:
            self.paper = paper
        
        self._client: Optional[TradingClient] = None
        self._connected = False
        
        logger.info(
            f"AlpacaBroker initialized - Mode: {'PAPER' if self.paper else 'LIVE'}"
        )
    
    def connect(self) -> bool:
        """
        Establish connection to Alpaca API.
        
        Returns:
            True if connection successful, False otherwise.
        """
        try:
            self._client = TradingClient(
                api_key=self.api_key,
                secret_key=self.secret_key,
                paper=self.paper
            )
            
            # Verify connection by fetching account
            account = self._client.get_account()
            self._connected = True
            
            logger.info(
                f"Connected to Alpaca - Account: {account.account_number}, "
                f"Equity: ${float(account.equity):,.2f}"
            )
            return True
            
        except APIError as e:
            logger.error(f"Alpaca API error during connect: {e}")
            self._connected = False
            return False
        except Exception as e:
            logger.error(f"Failed to connect to Alpaca: {e}")
            self._connected = False
            return False
    
    def disconnect(self) -> None:
        """Close broker connection."""
        self._client = None
        self._connected = False
        logger.info("Disconnected from Alpaca")
    
    @property
    def is_connected(self) -> bool:
        """Check if broker is connected."""
        return self._connected and self._client is not None
    
    def _ensure_connected(self) -> None:
        """Raise error if not connected."""
        if not self.is_connected:
            raise ConnectionError("Broker not connected. Call connect() first.")
    
    # === Account Methods ===
    
    def get_account(self) -> Optional[AccountInfo]:
        """
        Get current account information.
        
        Returns:
            AccountInfo dataclass or None if error.
        """
        self._ensure_connected()
        
        try:
            account = self._client.get_account()
            
            return AccountInfo(
                equity=Decimal(str(account.equity)),
                cash=Decimal(str(account.cash)),
                buying_power=Decimal(str(account.buying_power)),
                portfolio_value=Decimal(str(account.portfolio_value)),
                pattern_day_trader=account.pattern_day_trader,
                trading_blocked=account.trading_blocked,
                account_blocked=account.account_blocked,
                created_at=account.created_at
            )
            
        except APIError as e:
            logger.error(f"Failed to get account: {e}")
            return None
    
    def get_buying_power(self) -> Optional[Decimal]:
        """Get current buying power."""
        account = self.get_account()
        return account.buying_power if account else None
    
    def get_equity(self) -> Optional[Decimal]:
        """Get current account equity."""
        account = self.get_account()
        return account.equity if account else None
    
    # === Position Methods ===
    
    def get_positions(self) -> list[Position]:
        """
        Get all current positions.
        
        Returns:
            List of Position dataclasses.
        """
        self._ensure_connected()
        
        try:
            positions = self._client.get_all_positions()
            
            return [
                Position(
                    symbol=pos.symbol,
                    qty=int(pos.qty),
                    avg_entry_price=Decimal(str(pos.avg_entry_price)),
                    current_price=Decimal(str(pos.current_price)),
                    market_value=Decimal(str(pos.market_value)),
                    unrealized_pl=Decimal(str(pos.unrealized_pl)),
                    unrealized_plpc=Decimal(str(pos.unrealized_plpc)) * 100,
                    side=pos.side.value if hasattr(pos.side, 'value') else str(pos.side)
                )
                for pos in positions
            ]
            
        except APIError as e:
            logger.error(f"Failed to get positions: {e}")
            return []
    
    def get_position(self, symbol: str) -> Optional[Position]:
        """
        Get position for a specific symbol.
        
        Args:
            symbol: Stock ticker symbol.
            
        Returns:
            Position dataclass or None if no position.
        """
        self._ensure_connected()
        
        try:
            pos = self._client.get_open_position(symbol)
            
            return Position(
                symbol=pos.symbol,
                qty=int(pos.qty),
                avg_entry_price=Decimal(str(pos.avg_entry_price)),
                current_price=Decimal(str(pos.current_price)),
                market_value=Decimal(str(pos.market_value)),
                unrealized_pl=Decimal(str(pos.unrealized_pl)),
                unrealized_plpc=Decimal(str(pos.unrealized_plpc)) * 100,
                side=pos.side.value if hasattr(pos.side, 'value') else str(pos.side)
            )
            
        except APIError as e:
            if "position does not exist" in str(e).lower():
                return None
            logger.error(f"Failed to get position for {symbol}: {e}")
            return None
    
    def has_position(self, symbol: str) -> bool:
        """Check if we have an open position in symbol."""
        return self.get_position(symbol) is not None
    
    def get_position_count(self) -> int:
        """Get count of open positions."""
        return len(self.get_positions())
    
    # === Order Methods ===
    
    def submit_market_order(
        self,
        symbol: str,
        qty: int,
        side: str,
        time_in_force: str = "day"
    ) -> OrderResult:
        """
        Submit a market order.
        
        Args:
            symbol: Stock ticker symbol.
            qty: Number of shares.
            side: 'buy' or 'sell'.
            time_in_force: 'day', 'gtc', 'ioc', 'fok'.
            
        Returns:
            OrderResult with order details.
        """
        self._ensure_connected()
        
        try:
            order_side = OrderSide.BUY if side.lower() == "buy" else OrderSide.SELL
            tif = self._parse_time_in_force(time_in_force)
            
            request = MarketOrderRequest(
                symbol=symbol,
                qty=qty,
                side=order_side,
                time_in_force=tif
            )
            
            order = self._client.submit_order(request)
            
            logger.info(
                f"Market order submitted: {side.upper()} {qty} {symbol} - "
                f"Order ID: {order.id}"
            )
            
            return OrderResult(
                success=True,
                order_id=str(order.id),
                symbol=order.symbol,
                side=order.side.value,
                qty=int(order.qty),
                filled_qty=int(order.filled_qty) if order.filled_qty else 0,
                filled_avg_price=Decimal(str(order.filled_avg_price)) if order.filled_avg_price else None,
                status=order.status.value,
                submitted_at=order.submitted_at
            )
            
        except APIError as e:
            logger.error(f"Market order failed for {symbol}: {e}")
            return OrderResult(success=False, error_message=str(e))
    
    def submit_limit_order(
        self,
        symbol: str,
        qty: int,
        side: str,
        limit_price: Decimal,
        time_in_force: str = "day"
    ) -> OrderResult:
        """
        Submit a limit order.
        
        Args:
            symbol: Stock ticker symbol.
            qty: Number of shares.
            side: 'buy' or 'sell'.
            limit_price: Limit price.
            time_in_force: 'day', 'gtc', 'ioc', 'fok'.
            
        Returns:
            OrderResult with order details.
        """
        self._ensure_connected()
        
        try:
            order_side = OrderSide.BUY if side.lower() == "buy" else OrderSide.SELL
            tif = self._parse_time_in_force(time_in_force)
            
            request = LimitOrderRequest(
                symbol=symbol,
                qty=qty,
                side=order_side,
                time_in_force=tif,
                limit_price=float(limit_price)
            )
            
            order = self._client.submit_order(request)
            
            logger.info(
                f"Limit order submitted: {side.upper()} {qty} {symbol} @ ${limit_price} - "
                f"Order ID: {order.id}"
            )
            
            return OrderResult(
                success=True,
                order_id=str(order.id),
                symbol=order.symbol,
                side=order.side.value,
                qty=int(order.qty),
                filled_qty=int(order.filled_qty) if order.filled_qty else 0,
                filled_avg_price=Decimal(str(order.filled_avg_price)) if order.filled_avg_price else None,
                status=order.status.value,
                submitted_at=order.submitted_at
            )
            
        except APIError as e:
            logger.error(f"Limit order failed for {symbol}: {e}")
            return OrderResult(success=False, error_message=str(e))
    
    def cancel_order(self, order_id: str) -> bool:
        """
        Cancel an open order.
        
        Args:
            order_id: Alpaca order ID.
            
        Returns:
            True if cancelled successfully.
        """
        self._ensure_connected()
        
        try:
            self._client.cancel_order_by_id(order_id)
            logger.info(f"Order cancelled: {order_id}")
            return True
            
        except APIError as e:
            logger.error(f"Failed to cancel order {order_id}: {e}")
            return False
    
    def cancel_all_orders(self) -> int:
        """
        Cancel all open orders.
        
        Returns:
            Number of orders cancelled.
        """
        self._ensure_connected()
        
        try:
            cancelled = self._client.cancel_orders()
            count = len(cancelled) if cancelled else 0
            logger.info(f"Cancelled {count} orders")
            return count
            
        except APIError as e:
            logger.error(f"Failed to cancel all orders: {e}")
            return 0
    
    def get_order(self, order_id: str) -> Optional[OrderResult]:
        """
        Get order details by ID.
        
        Args:
            order_id: Alpaca order ID.
            
        Returns:
            OrderResult or None if not found.
        """
        self._ensure_connected()
        
        try:
            order = self._client.get_order_by_id(order_id)
            
            return OrderResult(
                success=True,
                order_id=str(order.id),
                symbol=order.symbol,
                side=order.side.value,
                qty=int(order.qty),
                filled_qty=int(order.filled_qty) if order.filled_qty else 0,
                filled_avg_price=Decimal(str(order.filled_avg_price)) if order.filled_avg_price else None,
                status=order.status.value,
                submitted_at=order.submitted_at
            )
            
        except APIError as e:
            logger.error(f"Failed to get order {order_id}: {e}")
            return None
    
    def get_open_orders(self, symbol: Optional[str] = None) -> list[OrderResult]:
        """
        Get all open orders, optionally filtered by symbol.
        
        Args:
            symbol: Optional symbol filter.
            
        Returns:
            List of OrderResult objects.
        """
        self._ensure_connected()
        
        try:
            request = GetOrdersRequest(
                status=QueryOrderStatus.OPEN,
                symbols=[symbol] if symbol else None
            )
            
            orders = self._client.get_orders(request)
            
            return [
                OrderResult(
                    success=True,
                    order_id=str(order.id),
                    symbol=order.symbol,
                    side=order.side.value,
                    qty=int(order.qty),
                    filled_qty=int(order.filled_qty) if order.filled_qty else 0,
                    filled_avg_price=Decimal(str(order.filled_avg_price)) if order.filled_avg_price else None,
                    status=order.status.value,
                    submitted_at=order.submitted_at
                )
                for order in orders
            ]
            
        except APIError as e:
            logger.error(f"Failed to get open orders: {e}")
            return []
    
    # === Position Exit Methods ===
    
    def close_position(self, symbol: str) -> OrderResult:
        """
        Close entire position for a symbol.
        
        Args:
            symbol: Stock ticker symbol.
            
        Returns:
            OrderResult from the closing order.
        """
        self._ensure_connected()
        
        try:
            order = self._client.close_position(symbol)
            
            logger.info(f"Position closed: {symbol} - Order ID: {order.id}")
            
            return OrderResult(
                success=True,
                order_id=str(order.id),
                symbol=order.symbol,
                side=order.side.value,
                qty=int(order.qty),
                status=order.status.value,
                submitted_at=order.submitted_at
            )
            
        except APIError as e:
            logger.error(f"Failed to close position {symbol}: {e}")
            return OrderResult(success=False, error_message=str(e))
    
    def close_all_positions(self) -> list[OrderResult]:
        """
        Close all open positions.
        
        Returns:
            List of OrderResults from closing orders.
        """
        self._ensure_connected()
        
        try:
            results = self._client.close_all_positions(cancel_orders=True)
            
            logger.info(f"Closed all positions: {len(results)} orders submitted")
            
            return [
                OrderResult(
                    success=True,
                    order_id=str(order.id),
                    symbol=order.symbol,
                    side=order.side.value,
                    qty=int(order.qty),
                    status=order.status.value,
                    submitted_at=order.submitted_at
                )
                for order in results
            ]
            
        except APIError as e:
            logger.error(f"Failed to close all positions: {e}")
            return []
    
    # === Helper Methods ===
    
    def _parse_time_in_force(self, tif: str) -> TimeInForce:
        """Convert string to TimeInForce enum."""
        mapping = {
            "day": TimeInForce.DAY,
            "gtc": TimeInForce.GTC,
            "ioc": TimeInForce.IOC,
            "fok": TimeInForce.FOK
        }
        return mapping.get(tif.lower(), TimeInForce.DAY)
    
    def is_market_open(self) -> bool:
        """
        Check if market is currently open.
        
        Returns:
            True if market is open.
        """
        self._ensure_connected()
        
        try:
            clock = self._client.get_clock()
            return clock.is_open
            
        except APIError as e:
            logger.error(f"Failed to get market clock: {e}")
            return False
    
    def get_market_hours(self) -> Optional[dict]:
        """
        Get today's market hours.
        
        Returns:
            Dict with 'is_open', 'next_open', 'next_close' or None.
        """
        self._ensure_connected()
        
        try:
            clock = self._client.get_clock()
            
            return {
                "is_open": clock.is_open,
                "next_open": clock.next_open,
                "next_close": clock.next_close,
                "timestamp": clock.timestamp
            }
            
        except APIError as e:
            logger.error(f"Failed to get market hours: {e}")
            return None


# Factory function for easy instantiation
def create_broker(paper: Optional[bool] = None) -> AlpacaBroker:
    """
    Create and connect an AlpacaBroker instance.
    
    Args:
        paper: True for paper trading, False for live.
                Uses config default if not specified.
    
    Returns:
        Connected AlpacaBroker instance.
        
    Raises:
        ConnectionError: If connection fails.
    """
    broker = AlpacaBroker(paper=paper)
    
    if not broker.connect():
        raise ConnectionError("Failed to connect to Alpaca API")
    
    return broker
