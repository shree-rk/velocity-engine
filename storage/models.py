"""
Database Models
SQLAlchemy ORM models for the Velocity Engine.
Covers positions, trades, signals, and equity snapshots.
"""

from datetime import datetime
from decimal import Decimal
from enum import Enum as PyEnum
from typing import Optional

from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    String,
    Float,
    DateTime,
    Boolean,
    Enum,
    Text,
    ForeignKey,
    Index,
    UniqueConstraint
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker
from sqlalchemy.sql import func

from config.settings import DATABASE_URL


# Base class for all models
Base = declarative_base()


# ============================================================================
# Enums
# ============================================================================

class PositionSide(PyEnum):
    """Position side."""
    LONG = "long"
    SHORT = "short"


class PositionStatus(PyEnum):
    """Position lifecycle status."""
    PENDING = "pending"       # Order submitted, not filled
    OPEN = "open"             # Position active
    CLOSING = "closing"       # Exit order submitted
    CLOSED = "closed"         # Position exited


class OrderSideEnum(PyEnum):
    """Order side."""
    BUY = "buy"
    SELL = "sell"


class OrderTypeEnum(PyEnum):
    """Order type."""
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"


class SignalType(PyEnum):
    """Signal types."""
    ENTRY = "entry"
    EXIT = "exit"
    STOP_LOSS = "stop_loss"
    TAKE_PROFIT = "take_profit"


class SignalStatus(PyEnum):
    """Signal status."""
    PENDING = "pending"
    EXECUTED = "executed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


# ============================================================================
# Models
# ============================================================================

class Position(Base):
    """
    Active and historical positions.
    
    Tracks position lifecycle from entry to exit with P&L calculation.
    """
    __tablename__ = "positions"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # Identification
    symbol = Column(String(10), nullable=False, index=True)
    strategy = Column(String(50), nullable=False, default="velocity_mr")
    
    # Position details
    side = Column(Enum(PositionSide), nullable=False)
    status = Column(Enum(PositionStatus), nullable=False, default=PositionStatus.PENDING)
    
    # Entry
    entry_price = Column(Float, nullable=True)
    entry_qty = Column(Integer, nullable=True)
    entry_time = Column(DateTime, nullable=True)
    entry_order_id = Column(String(100), nullable=True)
    
    # Exit
    exit_price = Column(Float, nullable=True)
    exit_qty = Column(Integer, nullable=True)
    exit_time = Column(DateTime, nullable=True)
    exit_order_id = Column(String(100), nullable=True)
    exit_reason = Column(String(50), nullable=True)  # stop_loss, take_profit, signal, manual
    
    # Risk management
    stop_loss_price = Column(Float, nullable=True)
    take_profit_price = Column(Float, nullable=True)
    risk_amount = Column(Float, nullable=True)  # Dollar risk at entry
    
    # P&L
    realized_pnl = Column(Float, nullable=True)
    realized_pnl_pct = Column(Float, nullable=True)
    
    # Indicators at entry (for analysis)
    entry_rsi = Column(Float, nullable=True)
    entry_bb_position = Column(Float, nullable=True)  # % position within Bollinger Bands
    entry_atr = Column(Float, nullable=True)
    entry_vix = Column(Float, nullable=True)
    
    # Metadata
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    notes = Column(Text, nullable=True)
    
    # Relationships
    trades = relationship("Trade", back_populates="position")
    
    # Indexes
    __table_args__ = (
        Index("ix_positions_status_symbol", "status", "symbol"),
        Index("ix_positions_strategy_status", "strategy", "status"),
    )
    
    def __repr__(self):
        return (
            f"<Position(id={self.id}, symbol={self.symbol}, "
            f"side={self.side.value}, status={self.status.value})>"
        )
    
    def calculate_pnl(self) -> Optional[float]:
        """Calculate realized P&L if position is closed."""
        if self.entry_price and self.exit_price and self.entry_qty:
            if self.side == PositionSide.LONG:
                pnl = (self.exit_price - self.entry_price) * self.entry_qty
            else:
                pnl = (self.entry_price - self.exit_price) * self.entry_qty
            return round(pnl, 2)
        return None


class Trade(Base):
    """
    Individual trade executions.
    
    Each position may have multiple trades (partial fills, scaling).
    """
    __tablename__ = "trades"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # Link to position
    position_id = Column(Integer, ForeignKey("positions.id"), nullable=True)
    
    # Trade details
    symbol = Column(String(10), nullable=False, index=True)
    side = Column(Enum(OrderSideEnum), nullable=False)
    order_type = Column(Enum(OrderTypeEnum), nullable=False)
    
    # Execution
    qty = Column(Integer, nullable=False)
    price = Column(Float, nullable=True)  # Null until filled
    filled_qty = Column(Integer, nullable=True)
    filled_avg_price = Column(Float, nullable=True)
    
    # Order tracking
    broker_order_id = Column(String(100), nullable=True, index=True)
    status = Column(String(20), nullable=False, default="pending")
    
    # Timestamps
    submitted_at = Column(DateTime, default=func.now())
    filled_at = Column(DateTime, nullable=True)
    
    # Fees
    commission = Column(Float, nullable=True, default=0.0)
    
    # Relationships
    position = relationship("Position", back_populates="trades")
    
    # Indexes
    __table_args__ = (
        Index("ix_trades_symbol_submitted", "symbol", "submitted_at"),
    )
    
    def __repr__(self):
        return (
            f"<Trade(id={self.id}, symbol={self.symbol}, "
            f"side={self.side.value}, qty={self.qty}, status={self.status})>"
        )


class Signal(Base):
    """
    Trading signals generated by strategies.
    
    Signals are evaluated and may become trades.
    """
    __tablename__ = "signals"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # Identification
    symbol = Column(String(10), nullable=False, index=True)
    strategy = Column(String(50), nullable=False, default="velocity_mr")
    signal_type = Column(Enum(SignalType), nullable=False)
    status = Column(Enum(SignalStatus), nullable=False, default=SignalStatus.PENDING)
    
    # Signal details
    price_at_signal = Column(Float, nullable=False)
    target_price = Column(Float, nullable=True)
    stop_price = Column(Float, nullable=True)
    
    # Conditions at signal
    rsi_value = Column(Float, nullable=True)
    bb_position = Column(Float, nullable=True)
    atr_value = Column(Float, nullable=True)
    adx_value = Column(Float, nullable=True)
    volume_ratio = Column(Float, nullable=True)
    vix_value = Column(Float, nullable=True)
    
    # Scoring
    signal_strength = Column(Float, nullable=True)  # 0-1 confidence
    conditions_met = Column(Integer, nullable=True)  # Number of conditions met
    
    # Timestamps
    created_at = Column(DateTime, default=func.now())
    expires_at = Column(DateTime, nullable=True)
    executed_at = Column(DateTime, nullable=True)
    
    # Result
    result_trade_id = Column(Integer, ForeignKey("trades.id"), nullable=True)
    
    # Indexes
    __table_args__ = (
        Index("ix_signals_status_created", "status", "created_at"),
        Index("ix_signals_strategy_symbol", "strategy", "symbol"),
    )
    
    def __repr__(self):
        return (
            f"<Signal(id={self.id}, symbol={self.symbol}, "
            f"type={self.signal_type.value}, status={self.status.value})>"
        )


class EquitySnapshot(Base):
    """
    Periodic equity snapshots for performance tracking.
    
    Captures account equity at regular intervals for drawdown
    calculation and performance analysis.
    """
    __tablename__ = "equity_snapshots"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # Equity values
    equity = Column(Float, nullable=False)
    cash = Column(Float, nullable=False)
    positions_value = Column(Float, nullable=False)
    
    # Drawdown tracking
    high_water_mark = Column(Float, nullable=False)
    drawdown = Column(Float, nullable=False)  # Absolute
    drawdown_pct = Column(Float, nullable=False)  # Percentage
    
    # Position summary
    open_positions = Column(Integer, nullable=False, default=0)
    
    # Performance
    daily_pnl = Column(Float, nullable=True)
    daily_pnl_pct = Column(Float, nullable=True)
    
    # Context
    vix_at_snapshot = Column(Float, nullable=True)
    
    # Timestamp
    snapshot_time = Column(DateTime, default=func.now(), index=True)
    
    def __repr__(self):
        return (
            f"<EquitySnapshot(id={self.id}, equity={self.equity:.2f}, "
            f"drawdown={self.drawdown_pct:.2%})>"
        )


class SystemState(Base):
    """
    System state and control flags.
    
    Tracks circuit breakers, trading status, and operational state.
    """
    __tablename__ = "system_state"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String(50), nullable=False, unique=True, index=True)
    value = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    
    def __repr__(self):
        return f"<SystemState(key={self.key}, value={self.value})>"


class StrategyConfig(Base):
    """
    Strategy configuration stored in database.
    
    Allows runtime configuration changes without code deployment.
    """
    __tablename__ = "strategy_configs"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    strategy_name = Column(String(50), nullable=False, index=True)
    config_key = Column(String(50), nullable=False)
    config_value = Column(Text, nullable=False)
    
    is_active = Column(Boolean, default=True)
    
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    
    __table_args__ = (
        UniqueConstraint("strategy_name", "config_key", name="uq_strategy_config"),
    )
    
    def __repr__(self):
        return (
            f"<StrategyConfig(strategy={self.strategy_name}, "
            f"key={self.config_key})>"
        )


# ============================================================================
# Database Setup Functions
# ============================================================================

def create_database_engine(db_url: Optional[str] = None, echo: bool = False):
    """
    Create SQLAlchemy engine.
    
    Args:
        db_url: Database URL (uses config default if not provided).
        echo: If True, log all SQL statements.
        
    Returns:
        SQLAlchemy Engine.
    """
    url = db_url or DATABASE_URL
    return create_engine(url, echo=echo)


def create_all_tables(engine):
    """Create all tables in the database."""
    Base.metadata.create_all(engine)


def drop_all_tables(engine):
    """Drop all tables from the database."""
    Base.metadata.drop_all(engine)


def get_session_factory(engine):
    """Get a session factory for the engine."""
    return sessionmaker(bind=engine)


class DatabaseManager:
    """
    Database manager for easy session handling.
    
    Usage:
        db = DatabaseManager()
        with db.session() as session:
            session.add(position)
            session.commit()
    """
    
    def __init__(self, db_url: Optional[str] = None, echo: bool = False):
        """
        Initialize database manager.
        
        Args:
            db_url: Database URL.
            echo: Log SQL statements.
        """
        self.engine = create_database_engine(db_url, echo)
        self.Session = get_session_factory(self.engine)
    
    def create_tables(self):
        """Create all tables."""
        create_all_tables(self.engine)
    
    def drop_tables(self):
        """Drop all tables."""
        drop_all_tables(self.engine)
    
    def session(self):
        """Get a new session (use as context manager)."""
        return self.Session()
    
    def get_session(self):
        """Get a new session."""
        return self.Session()
