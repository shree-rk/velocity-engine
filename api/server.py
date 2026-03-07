"""
Velocity Engine API Server
FastAPI dashboard for monitoring and control.

Endpoints:
- GET  /api/status       - Engine status
- GET  /api/positions    - Current and historical positions
- GET  /api/trades       - Trade history
- GET  /api/signals      - Signal log
- GET  /api/equity       - Equity curve
- GET  /api/metrics      - Performance metrics
- POST /api/scan         - Trigger manual scan
- POST /api/engine/start - Start engine
- POST /api/engine/stop  - Stop engine
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from config.settings import ALPACA_TRADING_MODE, BASE_CAPITAL
from storage.models import DatabaseManager, PositionStatus
from storage.repository import (
    PositionRepository,
    TradeRepository,
    SignalRepository,
    EquityRepository,
    MetricsRepository,
    SystemStateRepository
)
from core.engine import VelocityEngine, EngineState
from filters.vix_filter import check_vix

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global engine instance
engine: Optional[VelocityEngine] = None
db: Optional[DatabaseManager] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    global engine, db
    
    # Startup
    logger.info("Starting Velocity API Server...")
    db = DatabaseManager()
    engine = VelocityEngine(auto_connect=True)
    
    yield
    
    # Shutdown
    logger.info("Shutting down...")
    if engine and engine.state == EngineState.RUNNING:
        engine.stop()


app = FastAPI(
    title="Velocity Engine API",
    description="Trading engine dashboard and control API",
    version="1.0.0",
    lifespan=lifespan
)

# CORS for frontend access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================================
# Response Models
# ============================================================================

class StatusResponse(BaseModel):
    state: str
    mode: str
    broker_connected: bool
    market_open: bool
    vix_regime: str
    vix_value: float
    events_blocked: bool
    trading_hours_ok: bool
    alpha_shield_triggered: bool
    current_drawdown: float
    open_positions: int
    max_positions: int
    equity: float
    high_water_mark: float
    last_scan_time: Optional[str]
    message: str


class PositionResponse(BaseModel):
    id: int
    symbol: str
    side: str
    status: str
    entry_price: Optional[float]
    entry_qty: Optional[int]
    exit_price: Optional[float]
    realized_pnl: Optional[float]
    realized_pnl_pct: Optional[float]
    stop_loss: Optional[float]
    take_profit: Optional[float]
    entry_time: Optional[str]
    exit_time: Optional[str]


class TradeResponse(BaseModel):
    id: int
    symbol: str
    side: str
    qty: int
    price: Optional[float]
    filled_qty: Optional[int]
    filled_avg_price: Optional[float]
    status: str
    submitted_at: str


class SignalResponse(BaseModel):
    id: int
    symbol: str
    signal_type: str
    status: str
    price_at_signal: float
    rsi_value: Optional[float]
    adx_value: Optional[float]
    conditions_met: Optional[int]
    created_at: str


class MetricsResponse(BaseModel):
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    total_pnl: float
    avg_win: float
    avg_loss: float
    profit_factor: float
    largest_win: float
    largest_loss: float
    avg_hold_time_hours: float


class ScanResultResponse(BaseModel):
    success: bool
    symbols_scanned: int
    signals_found: int
    signals_executed: int
    duration_ms: int
    message: str


# ============================================================================
# API Endpoints
# ============================================================================

@app.get("/")
async def root():
    """Health check."""
    return {
        "service": "Velocity Engine API",
        "status": "running",
        "mode": ALPACA_TRADING_MODE.value,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


@app.get("/api/status", response_model=StatusResponse)
async def get_status():
    """Get current engine status."""
    if not engine:
        raise HTTPException(status_code=503, detail="Engine not initialized")
    
    status = engine.get_status()
    
    return StatusResponse(
        state=status.state.value,
        mode=status.mode,
        broker_connected=status.broker_connected,
        market_open=status.market_open,
        vix_regime=status.vix_regime,
        vix_value=status.vix_value,
        events_blocked=status.events_blocked,
        trading_hours_ok=status.trading_hours_ok,
        alpha_shield_triggered=status.alpha_shield_triggered,
        current_drawdown=status.current_drawdown,
        open_positions=status.open_positions,
        max_positions=status.max_positions,
        equity=status.equity,
        high_water_mark=status.high_water_mark,
        last_scan_time=status.last_scan_time.isoformat() if status.last_scan_time else None,
        message=status.message
    )


@app.get("/api/positions")
async def get_positions(
    status: Optional[str] = Query(None, description="Filter by status: open, closed"),
    limit: int = Query(50, ge=1, le=500)
):
    """Get positions."""
    if not db:
        raise HTTPException(status_code=503, detail="Database not initialized")
    
    repo = PositionRepository(db)
    
    if status == "open":
        positions = repo.get_open_positions()
    elif status == "closed":
        positions = repo.get_closed_positions(limit=limit)
    else:
        # Get both
        open_pos = repo.get_open_positions()
        closed_pos = repo.get_closed_positions(limit=limit)
        positions = open_pos + closed_pos
    
    return [
        PositionResponse(
            id=p.id,
            symbol=p.symbol,
            side=p.side.value if p.side else "unknown",
            status=p.status.value if p.status else "unknown",
            entry_price=p.entry_price,
            entry_qty=p.entry_qty,
            exit_price=p.exit_price,
            realized_pnl=p.realized_pnl,
            realized_pnl_pct=p.realized_pnl_pct,
            stop_loss=p.stop_loss_price,
            take_profit=p.take_profit_price,
            entry_time=p.entry_time.isoformat() if p.entry_time else None,
            exit_time=p.exit_time.isoformat() if p.exit_time else None
        )
        for p in positions
    ]


@app.get("/api/positions/live")
async def get_live_positions():
    """Get live positions from broker."""
    if not engine or not engine.broker:
        raise HTTPException(status_code=503, detail="Broker not connected")
    
    positions = engine.get_positions()
    
    return [
        {
            "symbol": p.symbol,
            "qty": p.qty,
            "avg_entry_price": float(p.avg_entry_price),
            "current_price": float(p.current_price),
            "market_value": float(p.market_value),
            "unrealized_pnl": float(p.unrealized_pl),
            "unrealized_pnl_pct": float(p.unrealized_plpc),
            "side": p.side
        }
        for p in positions
    ]


@app.get("/api/trades")
async def get_trades(limit: int = Query(50, ge=1, le=500)):
    """Get trade history."""
    if not db:
        raise HTTPException(status_code=503, detail="Database not initialized")
    
    repo = TradeRepository(db)
    trades = repo.get_recent_trades(limit=limit)
    
    return [
        TradeResponse(
            id=t.id,
            symbol=t.symbol,
            side=t.side.value if t.side else "unknown",
            qty=t.qty,
            price=t.price,
            filled_qty=t.filled_qty,
            filled_avg_price=t.filled_avg_price,
            status=t.status,
            submitted_at=t.submitted_at.isoformat() if t.submitted_at else ""
        )
        for t in trades
    ]


@app.get("/api/signals")
async def get_signals(limit: int = Query(100, ge=1, le=500)):
    """Get signal history."""
    if not db:
        raise HTTPException(status_code=503, detail="Database not initialized")
    
    repo = SignalRepository(db)
    signals = repo.get_recent_signals(limit=limit)
    
    return [
        SignalResponse(
            id=s.id,
            symbol=s.symbol,
            signal_type=s.signal_type.value if s.signal_type else "unknown",
            status=s.status.value if s.status else "unknown",
            price_at_signal=s.price_at_signal,
            rsi_value=s.rsi_value,
            adx_value=s.adx_value,
            conditions_met=s.conditions_met,
            created_at=s.created_at.isoformat() if s.created_at else ""
        )
        for s in signals
    ]


@app.get("/api/equity")
async def get_equity(days: int = Query(30, ge=1, le=365)):
    """Get equity history."""
    if not db:
        raise HTTPException(status_code=503, detail="Database not initialized")
    
    repo = EquityRepository(db)
    snapshots = repo.get_daily_snapshots(days=days)
    
    return {
        "period_days": days,
        "snapshots": snapshots,
        "current_equity": engine.risk_manager._current_equity if engine else BASE_CAPITAL,
        "high_water_mark": engine.risk_manager._high_water_mark if engine else BASE_CAPITAL
    }


@app.get("/api/metrics", response_model=MetricsResponse)
async def get_metrics(days: Optional[int] = Query(None, ge=1, le=365)):
    """Get performance metrics."""
    if not db:
        raise HTTPException(status_code=503, detail="Database not initialized")
    
    since = None
    if days:
        since = datetime.now(timezone.utc) - timedelta(days=days)
    
    repo = MetricsRepository(db)
    metrics = repo.get_performance_metrics(since=since)
    
    return MetricsResponse(**metrics)


@app.get("/api/vix")
async def get_vix():
    """Get current VIX reading."""
    reading = check_vix()
    
    return {
        "value": reading.value,
        "regime": reading.regime.value,
        "trading_allowed": reading.trading_allowed,
        "position_multiplier": reading.position_size_multiplier,
        "message": reading.message,
        "timestamp": reading.timestamp.isoformat()
    }


@app.get("/api/watchlist")
async def get_watchlist():
    """Get configured watchlist."""
    if not engine:
        raise HTTPException(status_code=503, detail="Engine not initialized")
    
    symbols = engine.strategy.symbols if hasattr(engine.strategy, 'symbols') else []
    
    return {
        "strategy": engine.strategy.name,
        "symbols": symbols,
        "count": len(symbols)
    }


@app.get("/api/scan/summary")
async def get_scan_summary():
    """Get scan summary for all symbols."""
    if not engine:
        raise HTTPException(status_code=503, detail="Engine not initialized")
    
    summary = engine.get_scan_summary()
    
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "symbols": summary
    }


@app.post("/api/scan", response_model=ScanResultResponse)
async def trigger_scan():
    """Trigger a manual scan."""
    if not engine:
        raise HTTPException(status_code=503, detail="Engine not initialized")
    
    if engine.state != EngineState.RUNNING:
        # Start engine if needed
        engine.start()
    
    result = engine.run_scan()
    
    return ScanResultResponse(
        success=True,
        symbols_scanned=result.symbols_scanned,
        signals_found=result.signals_found,
        signals_executed=result.signals_executed,
        duration_ms=result.duration_ms,
        message=f"Scan complete: {result.signals_found} signals, {result.signals_executed} executed"
    )


@app.post("/api/engine/start")
async def start_engine():
    """Start the engine."""
    if not engine:
        raise HTTPException(status_code=503, detail="Engine not initialized")
    
    if engine.state == EngineState.RUNNING:
        return {"status": "already_running", "message": "Engine is already running"}
    
    success = engine.start()
    
    if success:
        return {"status": "started", "message": "Engine started successfully"}
    else:
        raise HTTPException(status_code=500, detail="Failed to start engine")


@app.post("/api/engine/stop")
async def stop_engine():
    """Stop the engine."""
    if not engine:
        raise HTTPException(status_code=503, detail="Engine not initialized")
    
    engine.stop()
    
    return {"status": "stopped", "message": "Engine stopped"}


@app.post("/api/engine/pause")
async def pause_engine():
    """Pause the engine."""
    if not engine:
        raise HTTPException(status_code=503, detail="Engine not initialized")
    
    engine.pause()
    
    return {"status": "paused", "message": "Engine paused"}


@app.post("/api/engine/resume")
async def resume_engine():
    """Resume the engine."""
    if not engine:
        raise HTTPException(status_code=503, detail="Engine not initialized")
    
    engine.resume()
    
    return {"status": "resumed", "message": "Engine resumed"}


# ============================================================================
# Error Handlers
# ============================================================================

@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    logger.error(f"Unhandled exception: {exc}")
    return JSONResponse(
        status_code=500,
        content={"detail": str(exc)}
    )


# ============================================================================
# Run Server
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "api.server:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_level="info"
    )
