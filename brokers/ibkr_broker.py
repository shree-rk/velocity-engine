"""
IBKR Broker Interface
Connects to Interactive Brokers for options trading.

Requires:
- IB Gateway or TWS running
- API access enabled in IBKR account
- ib_insync library

Setup:
1. Enable API in IBKR Account Management
2. Download and run IB Gateway
3. Configure connection settings below
"""

import logging
from datetime import datetime, date, timezone
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class IBKRConnectionStatus(Enum):
    """Connection status."""
    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    ERROR = "ERROR"


@dataclass
class IBKRConfig:
    """IBKR connection configuration."""
    host: str = "127.0.0.1"
    port: int = 4002  # 4002 for IB Gateway paper, 4001 for live
    client_id: int = 1
    readonly: bool = False
    account: str = ""  # Leave empty to use default
    
    # Paper trading uses different port
    paper_port: int = 4002
    live_port: int = 4001


@dataclass 
class IBKRAccountInfo:
    """Account information."""
    account_id: str
    net_liquidation: float
    buying_power: float
    available_funds: float
    cash_balance: float
    maintenance_margin: float
    initial_margin: float


@dataclass
class IBKRPosition:
    """Position from IBKR."""
    symbol: str
    sec_type: str  # STK, OPT, FUT
    quantity: int
    avg_cost: float
    market_value: float
    unrealized_pnl: float
    
    # For options
    strike: Optional[float] = None
    expiration: Optional[date] = None
    right: Optional[str] = None  # C or P


@dataclass
class IBKROrderResult:
    """Order execution result."""
    order_id: int
    status: str
    filled_qty: int
    avg_fill_price: float
    commission: float
    message: str


class IBKRBroker:
    """
    IBKR Broker for options trading.
    
    Usage:
        broker = IBKRBroker(config)
        broker.connect()
        
        # Get account info
        account = broker.get_account_info()
        
        # Get options chain
        chain = broker.get_options_chain("SPY", expiration)
        
        # Place Iron Condor
        result = broker.place_iron_condor(...)
        
        broker.disconnect()
    """
    
    def __init__(self, config: IBKRConfig = None, paper_trading: bool = True):
        self.config = config or IBKRConfig()
        self.paper_trading = paper_trading
        self.status = IBKRConnectionStatus.DISCONNECTED
        self.ib = None  # Will hold ib_insync.IB instance
        self._account_id = None
        
        # Adjust port for paper/live
        if paper_trading:
            self.config.port = self.config.paper_port
        else:
            self.config.port = self.config.live_port
        
        logger.info(
            f"IBKRBroker initialized - "
            f"Mode: {'PAPER' if paper_trading else 'LIVE'}, "
            f"Port: {self.config.port}"
        )
    
    def connect(self) -> bool:
        """
        Connect to IBKR.
        
        Returns:
            True if connected successfully
        """
        try:
            # Import here to allow module to load without ib_insync
            from ib_insync import IB
            
            self.status = IBKRConnectionStatus.CONNECTING
            self.ib = IB()
            
            self.ib.connect(
                host=self.config.host,
                port=self.config.port,
                clientId=self.config.client_id,
                readonly=self.config.readonly
            )
            
            # Get account ID
            accounts = self.ib.managedAccounts()
            if accounts:
                self._account_id = accounts[0]
            
            self.status = IBKRConnectionStatus.CONNECTED
            logger.info(f"Connected to IBKR - Account: {self._account_id}")
            return True
            
        except ImportError:
            logger.error("ib_insync not installed. Run: pip install ib_insync")
            self.status = IBKRConnectionStatus.ERROR
            return False
        except Exception as e:
            logger.error(f"Failed to connect to IBKR: {e}")
            self.status = IBKRConnectionStatus.ERROR
            return False
    
    def disconnect(self):
        """Disconnect from IBKR."""
        if self.ib and self.ib.isConnected():
            self.ib.disconnect()
        self.status = IBKRConnectionStatus.DISCONNECTED
        logger.info("Disconnected from IBKR")
    
    def is_connected(self) -> bool:
        """Check if connected."""
        return self.ib is not None and self.ib.isConnected()
    
    def get_account_info(self) -> Optional[IBKRAccountInfo]:
        """Get account information."""
        if not self.is_connected():
            return None
        
        try:
            account_values = self.ib.accountSummary()
            
            values = {}
            for av in account_values:
                values[av.tag] = float(av.value) if av.value else 0
            
            return IBKRAccountInfo(
                account_id=self._account_id,
                net_liquidation=values.get("NetLiquidation", 0),
                buying_power=values.get("BuyingPower", 0),
                available_funds=values.get("AvailableFunds", 0),
                cash_balance=values.get("CashBalance", 0),
                maintenance_margin=values.get("MaintMarginReq", 0),
                initial_margin=values.get("InitMarginReq", 0)
            )
        except Exception as e:
            logger.error(f"Failed to get account info: {e}")
            return None
    
    def get_positions(self) -> List[IBKRPosition]:
        """Get all positions."""
        if not self.is_connected():
            return []
        
        try:
            positions = []
            for pos in self.ib.positions():
                contract = pos.contract
                
                ibkr_pos = IBKRPosition(
                    symbol=contract.symbol,
                    sec_type=contract.secType,
                    quantity=int(pos.position),
                    avg_cost=pos.avgCost,
                    market_value=0,  # Would need to fetch
                    unrealized_pnl=0
                )
                
                if contract.secType == "OPT":
                    ibkr_pos.strike = contract.strike
                    ibkr_pos.expiration = datetime.strptime(
                        contract.lastTradeDateOrContractMonth, "%Y%m%d"
                    ).date()
                    ibkr_pos.right = contract.right
                
                positions.append(ibkr_pos)
            
            return positions
        except Exception as e:
            logger.error(f"Failed to get positions: {e}")
            return []
    
    def get_options_chain(
        self,
        symbol: str,
        expiration: date,
        strike_range: tuple = None
    ) -> List[Dict[str, Any]]:
        """
        Get options chain for symbol and expiration.
        
        Args:
            symbol: Underlying symbol (SPY, SPX, QQQ)
            expiration: Option expiration date
            strike_range: Optional (min_strike, max_strike)
            
        Returns:
            List of option contracts with greeks
        """
        if not self.is_connected():
            return []
        
        try:
            from ib_insync import Stock, Index, Option
            
            # Create underlying contract
            if symbol == "SPX":
                underlying = Index(symbol, "CBOE")
            else:
                underlying = Stock(symbol, "SMART", "USD")
            
            # Qualify the contract
            self.ib.qualifyContracts(underlying)
            
            # Get chains
            chains = self.ib.reqSecDefOptParams(
                underlying.symbol,
                "",
                underlying.secType,
                underlying.conId
            )
            
            if not chains:
                return []
            
            # Find matching expiration
            exp_str = expiration.strftime("%Y%m%d")
            chain = chains[0]
            
            if exp_str not in chain.expirations:
                logger.warning(f"Expiration {expiration} not found in chain")
                return []
            
            # Get strikes
            strikes = sorted(chain.strikes)
            if strike_range:
                strikes = [s for s in strikes if strike_range[0] <= s <= strike_range[1]]
            
            # Build option contracts and get data
            options = []
            for strike in strikes:
                for right in ["C", "P"]:
                    opt = Option(symbol, exp_str, strike, right, "SMART")
                    
                    try:
                        self.ib.qualifyContracts(opt)
                        ticker = self.ib.reqMktData(opt, "", False, False)
                        self.ib.sleep(0.1)  # Wait for data
                        
                        options.append({
                            "symbol": symbol,
                            "expiration": expiration,
                            "strike": strike,
                            "right": right,
                            "bid": ticker.bid,
                            "ask": ticker.ask,
                            "last": ticker.last,
                            "delta": ticker.modelGreeks.delta if ticker.modelGreeks else None,
                            "gamma": ticker.modelGreeks.gamma if ticker.modelGreeks else None,
                            "theta": ticker.modelGreeks.theta if ticker.modelGreeks else None,
                            "vega": ticker.modelGreeks.vega if ticker.modelGreeks else None,
                            "iv": ticker.modelGreeks.impliedVol if ticker.modelGreeks else None,
                        })
                        
                        self.ib.cancelMktData(opt)
                    except Exception as e:
                        logger.debug(f"Error getting data for {strike}{right}: {e}")
            
            return options
            
        except Exception as e:
            logger.error(f"Failed to get options chain: {e}")
            return []
    
    def place_iron_condor(
        self,
        symbol: str,
        expiration: date,
        short_put_strike: float,
        long_put_strike: float,
        short_call_strike: float,
        long_call_strike: float,
        quantity: int,
        limit_credit: float
    ) -> Optional[IBKROrderResult]:
        """
        Place Iron Condor order.
        
        Args:
            symbol: Underlying symbol
            expiration: Option expiration
            short_put_strike: Short put strike
            long_put_strike: Long put strike (lower)
            short_call_strike: Short call strike
            long_call_strike: Long call strike (higher)
            quantity: Number of contracts
            limit_credit: Minimum credit to receive
            
        Returns:
            Order result or None if failed
        """
        if not self.is_connected():
            logger.error("Not connected to IBKR")
            return None
        
        try:
            from ib_insync import Option, ComboLeg, Contract, LimitOrder
            
            exp_str = expiration.strftime("%Y%m%d")
            
            # Create option contracts
            short_put = Option(symbol, exp_str, short_put_strike, "P", "SMART")
            long_put = Option(symbol, exp_str, long_put_strike, "P", "SMART")
            short_call = Option(symbol, exp_str, short_call_strike, "C", "SMART")
            long_call = Option(symbol, exp_str, long_call_strike, "C", "SMART")
            
            # Qualify contracts to get conIds
            contracts = [short_put, long_put, short_call, long_call]
            self.ib.qualifyContracts(*contracts)
            
            # Create combo legs
            legs = [
                ComboLeg(conId=short_put.conId, ratio=1, action="SELL", exchange="SMART"),
                ComboLeg(conId=long_put.conId, ratio=1, action="BUY", exchange="SMART"),
                ComboLeg(conId=short_call.conId, ratio=1, action="SELL", exchange="SMART"),
                ComboLeg(conId=long_call.conId, ratio=1, action="BUY", exchange="SMART"),
            ]
            
            # Create combo contract
            combo = Contract()
            combo.symbol = symbol
            combo.secType = "BAG"
            combo.currency = "USD"
            combo.exchange = "SMART"
            combo.comboLegs = legs
            
            # Create limit order (negative price for credit)
            order = LimitOrder(
                action="SELL",
                totalQuantity=quantity,
                lmtPrice=-limit_credit  # Negative for credit
            )
            
            # Place order
            trade = self.ib.placeOrder(combo, order)
            
            # Wait for fill (with timeout)
            self.ib.sleep(2)
            
            return IBKROrderResult(
                order_id=trade.order.orderId,
                status=trade.orderStatus.status,
                filled_qty=int(trade.orderStatus.filled),
                avg_fill_price=trade.orderStatus.avgFillPrice,
                commission=0,  # Would come from execution
                message=f"IC order placed: {symbol} {expiration}"
            )
            
        except Exception as e:
            logger.error(f"Failed to place Iron Condor: {e}")
            return None
    
    def close_iron_condor(
        self,
        symbol: str,
        expiration: date,
        short_put_strike: float,
        long_put_strike: float,
        short_call_strike: float,
        long_call_strike: float,
        quantity: int,
        limit_debit: float
    ) -> Optional[IBKROrderResult]:
        """
        Close Iron Condor position.
        
        Similar to place_iron_condor but with BUY action.
        """
        if not self.is_connected():
            logger.error("Not connected to IBKR")
            return None
        
        try:
            from ib_insync import Option, ComboLeg, Contract, LimitOrder
            
            exp_str = expiration.strftime("%Y%m%d")
            
            # Create option contracts
            short_put = Option(symbol, exp_str, short_put_strike, "P", "SMART")
            long_put = Option(symbol, exp_str, long_put_strike, "P", "SMART")
            short_call = Option(symbol, exp_str, short_call_strike, "C", "SMART")
            long_call = Option(symbol, exp_str, long_call_strike, "C", "SMART")
            
            contracts = [short_put, long_put, short_call, long_call]
            self.ib.qualifyContracts(*contracts)
            
            # Create combo legs (reverse of open)
            legs = [
                ComboLeg(conId=short_put.conId, ratio=1, action="BUY", exchange="SMART"),
                ComboLeg(conId=long_put.conId, ratio=1, action="SELL", exchange="SMART"),
                ComboLeg(conId=short_call.conId, ratio=1, action="BUY", exchange="SMART"),
                ComboLeg(conId=long_call.conId, ratio=1, action="SELL", exchange="SMART"),
            ]
            
            combo = Contract()
            combo.symbol = symbol
            combo.secType = "BAG"
            combo.currency = "USD"
            combo.exchange = "SMART"
            combo.comboLegs = legs
            
            order = LimitOrder(
                action="BUY",
                totalQuantity=quantity,
                lmtPrice=limit_debit
            )
            
            trade = self.ib.placeOrder(combo, order)
            self.ib.sleep(2)
            
            return IBKROrderResult(
                order_id=trade.order.orderId,
                status=trade.orderStatus.status,
                filled_qty=int(trade.orderStatus.filled),
                avg_fill_price=trade.orderStatus.avgFillPrice,
                commission=0,
                message=f"IC close order placed: {symbol} {expiration}"
            )
            
        except Exception as e:
            logger.error(f"Failed to close Iron Condor: {e}")
            return None
    
    def get_current_price(self, symbol: str) -> Optional[float]:
        """Get current price of underlying."""
        if not self.is_connected():
            return None
        
        try:
            from ib_insync import Stock, Index
            
            if symbol == "SPX":
                contract = Index(symbol, "CBOE")
            else:
                contract = Stock(symbol, "SMART", "USD")
            
            self.ib.qualifyContracts(contract)
            ticker = self.ib.reqMktData(contract, "", False, False)
            self.ib.sleep(0.5)
            
            price = ticker.marketPrice()
            self.ib.cancelMktData(contract)
            
            return price if price > 0 else None
            
        except Exception as e:
            logger.error(f"Failed to get price for {symbol}: {e}")
            return None


def create_ibkr_broker(paper_trading: bool = True) -> IBKRBroker:
    """Factory function to create IBKR broker."""
    config = IBKRConfig()
    return IBKRBroker(config=config, paper_trading=paper_trading)
