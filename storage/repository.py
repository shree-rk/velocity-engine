"""
Repository Layer
CRUD operations for all database models.
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any
from decimal import Decimal

from sqlalchemy import desc, func, and_
from sqlalchemy.orm import Session

from storage.models import (
    DatabaseManager,
    Position, Trade, Signal, EquitySnapshot, SystemState,
    PositionSide, PositionStatus, SignalType, SignalStatus,
    OrderSideEnum, OrderTypeEnum
)

logger = logging.getLogger(__name__)


class PositionRepository:
    """Repository for Position operations."""
    
    def __init__(self, db: DatabaseManager):
        self.db = db
    
    def create(
        self,
        symbol: str,
        side: PositionSide,
        entry_price: float,
        entry_qty: int,
        stop_loss: float,
        take_profit: Optional[float] = None,
        strategy: str = "velocity_mr",
        **kwargs
    ) -> Position:
        """Create a new position."""
        with self.db.get_session() as session:
            position = Position(
                symbol=symbol,
                strategy=strategy,
                side=side,
                status=PositionStatus.OPEN,
                entry_price=entry_price,
                entry_qty=entry_qty,
                entry_time=datetime.now(timezone.utc),
                stop_loss_price=stop_loss,
                take_profit_price=take_profit,
                **kwargs
            )
            session.add(position)
            session.commit()
            session.refresh(position)
            logger.info(f"Created position: {symbol} {side.value} {entry_qty} @ {entry_price}")
            return position
    
    def get_by_id(self, position_id: int) -> Optional[Position]:
        """Get position by ID."""
        with self.db.get_session() as session:
            return session.query(Position).filter(Position.id == position_id).first()
    
    def get_open_positions(self) -> List[Position]:
        """Get all open positions."""
        with self.db.get_session() as session:
            return session.query(Position).filter(
                Position.status == PositionStatus.OPEN
            ).all()
    
    def get_by_symbol(self, symbol: str, status: PositionStatus = None) -> List[Position]:
        """Get positions by symbol."""
        with self.db.get_session() as session:
            query = session.query(Position).filter(Position.symbol == symbol)
            if status:
                query = query.filter(Position.status == status)
            return query.order_by(desc(Position.created_at)).all()
    
    def close_position(
        self,
        position_id: int,
        exit_price: float,
        exit_reason: str = "signal"
    ) -> Optional[Position]:
        """Close a position."""
        with self.db.get_session() as session:
            position = session.query(Position).filter(Position.id == position_id).first()
            if not position:
                return None
            
            position.status = PositionStatus.CLOSED
            position.exit_price = exit_price
            position.exit_qty = position.entry_qty
            position.exit_time = datetime.now(timezone.utc)
            position.exit_reason = exit_reason
            
            # Calculate P&L
            if position.side == PositionSide.LONG:
                pnl = (exit_price - position.entry_price) * position.entry_qty
            else:
                pnl = (position.entry_price - exit_price) * position.entry_qty
            
            position.realized_pnl = pnl
            position.realized_pnl_pct = (pnl / (position.entry_price * position.entry_qty)) * 100
            
            session.commit()
            logger.info(f"Closed position {position_id}: {position.symbol} P&L: ${pnl:.2f}")
            return position
    
    def get_closed_positions(
        self,
        since: datetime = None,
        limit: int = 100
    ) -> List[Position]:
        """Get closed positions."""
        with self.db.get_session() as session:
            query = session.query(Position).filter(Position.status == PositionStatus.CLOSED)
            if since:
                query = query.filter(Position.exit_time >= since)
            return query.order_by(desc(Position.exit_time)).limit(limit).all()
    
    def get_position_count(self) -> int:
        """Get count of open positions."""
        with self.db.get_session() as session:
            return session.query(Position).filter(
                Position.status == PositionStatus.OPEN
            ).count()


class TradeRepository:
    """Repository for Trade operations."""
    
    def __init__(self, db: DatabaseManager):
        self.db = db
    
    def create(
        self,
        symbol: str,
        side: OrderSideEnum,
        order_type: OrderTypeEnum,
        qty: int,
        price: Optional[float] = None,
        broker_order_id: Optional[str] = None,
        position_id: Optional[int] = None
    ) -> Trade:
        """Create a new trade record."""
        with self.db.get_session() as session:
            trade = Trade(
                symbol=symbol,
                side=side,
                order_type=order_type,
                qty=qty,
                price=price,
                broker_order_id=broker_order_id,
                position_id=position_id,
                status="submitted"
            )
            session.add(trade)
            session.commit()
            session.refresh(trade)
            return trade
    
    def update_fill(
        self,
        trade_id: int,
        filled_qty: int,
        filled_avg_price: float
    ) -> Optional[Trade]:
        """Update trade with fill information."""
        with self.db.get_session() as session:
            trade = session.query(Trade).filter(Trade.id == trade_id).first()
            if trade:
                trade.filled_qty = filled_qty
                trade.filled_avg_price = filled_avg_price
                trade.filled_at = datetime.now(timezone.utc)
                trade.status = "filled" if filled_qty == trade.qty else "partial"
                session.commit()
            return trade
    
    def get_recent_trades(self, limit: int = 50) -> List[Trade]:
        """Get recent trades."""
        with self.db.get_session() as session:
            return session.query(Trade).order_by(
                desc(Trade.submitted_at)
            ).limit(limit).all()
    
    def get_trades_for_position(self, position_id: int) -> List[Trade]:
        """Get all trades for a position."""
        with self.db.get_session() as session:
            return session.query(Trade).filter(
                Trade.position_id == position_id
            ).order_by(Trade.submitted_at).all()


class SignalRepository:
    """Repository for Signal operations."""
    
    def __init__(self, db: DatabaseManager):
        self.db = db
    
    def create(
        self,
        symbol: str,
        signal_type: SignalType,
        price_at_signal: float,
        strategy: str = "velocity_mr",
        **kwargs
    ) -> Signal:
        """Create a new signal."""
        with self.db.get_session() as session:
            signal = Signal(
                symbol=symbol,
                strategy=strategy,
                signal_type=signal_type,
                status=SignalStatus.PENDING,
                price_at_signal=price_at_signal,
                **kwargs
            )
            session.add(signal)
            session.commit()
            session.refresh(signal)
            return signal
    
    def mark_executed(self, signal_id: int, trade_id: int) -> Optional[Signal]:
        """Mark signal as executed."""
        with self.db.get_session() as session:
            signal = session.query(Signal).filter(Signal.id == signal_id).first()
            if signal:
                signal.status = SignalStatus.EXECUTED
                signal.executed_at = datetime.now(timezone.utc)
                signal.result_trade_id = trade_id
                session.commit()
            return signal
    
    def get_recent_signals(self, limit: int = 100) -> List[Signal]:
        """Get recent signals."""
        with self.db.get_session() as session:
            return session.query(Signal).order_by(
                desc(Signal.created_at)
            ).limit(limit).all()
    
    def get_pending_signals(self) -> List[Signal]:
        """Get pending signals."""
        with self.db.get_session() as session:
            return session.query(Signal).filter(
                Signal.status == SignalStatus.PENDING
            ).all()


class EquityRepository:
    """Repository for EquitySnapshot operations."""
    
    def __init__(self, db: DatabaseManager):
        self.db = db
    
    def create_snapshot(
        self,
        equity: float,
        cash: float,
        positions_value: float,
        high_water_mark: float,
        open_positions: int = 0,
        vix_value: Optional[float] = None
    ) -> EquitySnapshot:
        """Create equity snapshot."""
        drawdown = high_water_mark - equity
        drawdown_pct = drawdown / high_water_mark if high_water_mark > 0 else 0
        
        with self.db.get_session() as session:
            snapshot = EquitySnapshot(
                equity=equity,
                cash=cash,
                positions_value=positions_value,
                high_water_mark=high_water_mark,
                drawdown=drawdown,
                drawdown_pct=drawdown_pct,
                open_positions=open_positions,
                vix_at_snapshot=vix_value
            )
            session.add(snapshot)
            session.commit()
            session.refresh(snapshot)
            return snapshot
    
    def get_latest(self) -> Optional[EquitySnapshot]:
        """Get most recent snapshot."""
        with self.db.get_session() as session:
            return session.query(EquitySnapshot).order_by(
                desc(EquitySnapshot.snapshot_time)
            ).first()
    
    def get_equity_history(
        self,
        since: datetime = None,
        limit: int = 500
    ) -> List[EquitySnapshot]:
        """Get equity history."""
        with self.db.get_session() as session:
            query = session.query(EquitySnapshot)
            if since:
                query = query.filter(EquitySnapshot.snapshot_time >= since)
            return query.order_by(EquitySnapshot.snapshot_time).limit(limit).all()
    
    def get_daily_snapshots(self, days: int = 30) -> List[Dict]:
        """Get daily equity snapshots."""
        since = datetime.now(timezone.utc) - timedelta(days=days)
        snapshots = self.get_equity_history(since=since, limit=days * 50)
        
        # Group by date and take last of each day
        daily = {}
        for snap in snapshots:
            date_key = snap.snapshot_time.date()
            daily[date_key] = snap
        
        return [
            {
                "date": str(date),
                "equity": snap.equity,
                "drawdown_pct": snap.drawdown_pct
            }
            for date, snap in sorted(daily.items())
        ]


class MetricsRepository:
    """Repository for calculating performance metrics."""
    
    def __init__(self, db: DatabaseManager):
        self.db = db
        self.position_repo = PositionRepository(db)
    
    def get_performance_metrics(self, since: datetime = None) -> Dict[str, Any]:
        """Calculate performance metrics."""
        with self.db.get_session() as session:
            query = session.query(Position).filter(
                Position.status == PositionStatus.CLOSED
            )
            if since:
                query = query.filter(Position.exit_time >= since)
            
            closed_positions = query.all()
            
            if not closed_positions:
                return {
                    "total_trades": 0,
                    "winning_trades": 0,
                    "losing_trades": 0,
                    "win_rate": 0,
                    "total_pnl": 0,
                    "avg_win": 0,
                    "avg_loss": 0,
                    "profit_factor": 0,
                    "largest_win": 0,
                    "largest_loss": 0,
                    "avg_hold_time_hours": 0
                }
            
            wins = [p for p in closed_positions if p.realized_pnl and p.realized_pnl > 0]
            losses = [p for p in closed_positions if p.realized_pnl and p.realized_pnl < 0]
            
            total_wins = sum(p.realized_pnl for p in wins) if wins else 0
            total_losses = abs(sum(p.realized_pnl for p in losses)) if losses else 0
            
            # Calculate hold times
            hold_times = []
            for p in closed_positions:
                if p.entry_time and p.exit_time:
                    hold_times.append((p.exit_time - p.entry_time).total_seconds() / 3600)
            
            return {
                "total_trades": len(closed_positions),
                "winning_trades": len(wins),
                "losing_trades": len(losses),
                "win_rate": len(wins) / len(closed_positions) * 100 if closed_positions else 0,
                "total_pnl": sum(p.realized_pnl or 0 for p in closed_positions),
                "avg_win": total_wins / len(wins) if wins else 0,
                "avg_loss": total_losses / len(losses) if losses else 0,
                "profit_factor": total_wins / total_losses if total_losses > 0 else float('inf'),
                "largest_win": max((p.realized_pnl for p in wins), default=0),
                "largest_loss": min((p.realized_pnl for p in losses), default=0),
                "avg_hold_time_hours": sum(hold_times) / len(hold_times) if hold_times else 0
            }


class SystemStateRepository:
    """Repository for system state."""
    
    def __init__(self, db: DatabaseManager):
        self.db = db
    
    def get(self, key: str) -> Optional[str]:
        """Get state value."""
        with self.db.get_session() as session:
            state = session.query(SystemState).filter(SystemState.key == key).first()
            return state.value if state else None
    
    def set(self, key: str, value: str) -> None:
        """Set state value."""
        with self.db.get_session() as session:
            state = session.query(SystemState).filter(SystemState.key == key).first()
            if state:
                state.value = value
            else:
                state = SystemState(key=key, value=value)
                session.add(state)
            session.commit()
    
    def delete(self, key: str) -> bool:
        """Delete state key."""
        with self.db.get_session() as session:
            state = session.query(SystemState).filter(SystemState.key == key).first()
            if state:
                session.delete(state)
                session.commit()
                return True
            return False
