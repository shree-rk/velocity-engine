"""
Velocity Engine API Server
FastAPI dashboard for monitoring and control.
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, List
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
)
from core.engine import VelocityEngine, EngineState
from filters.vix_filter import check_vix
from filters.event_calendar import EventCalendarFilter

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

engine: Optional[VelocityEngine] = None
db: Optional[DatabaseManager] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global engine, db
    logger.info("Starting Velocity API Server...")
    db = DatabaseManager()
    engine = VelocityEngine(auto_connect=True)
    yield
    logger.info("Shutting down...")
    if engine and engine.state == EngineState.RUNNING:
        engine.stop()


app = FastAPI(
    title="Velocity Engine API",
    description="Trading engine dashboard and control API",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    return {
        "service": "Velocity Engine API",
        "status": "running",
        "mode": ALPACA_TRADING_MODE.value,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


@app.get("/api/status")
async def get_status():
    if not engine:
        raise HTTPException(status_code=503, detail="Engine not initialized")
    
    status = engine.get_status()
    
    return {
        "state": status.state.value,
        "mode": status.mode,
        "broker_connected": status.broker_connected,
        "market_open": status.market_open,
        "vix_regime": status.vix_regime,
        "vix_value": status.vix_value,
        "events_blocked": status.events_blocked,
        "trading_hours_ok": status.trading_hours_ok,
        "alpha_shield_triggered": status.alpha_shield_triggered,
        "current_drawdown": status.current_drawdown,
        "open_positions": status.open_positions,
        "max_positions": status.max_positions,
        "equity": status.equity,
        "high_water_mark": status.high_water_mark,
        "last_scan_time": status.last_scan_time.isoformat() if status.last_scan_time else None,
        "message": status.message
    }


@app.get("/api/positions")
async def get_positions(
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500)
):
    if not db:
        raise HTTPException(status_code=503, detail="Database not initialized")
    
    repo = PositionRepository(db)
    
    if status == "open":
        positions = repo.get_open_positions()
    elif status == "closed":
        positions = repo.get_closed_positions(limit=limit)
    else:
        open_pos = repo.get_open_positions()
        closed_pos = repo.get_closed_positions(limit=limit)
        positions = open_pos + closed_pos
    
    return [
        {
            "id": p.id,
            "symbol": p.symbol,
            "side": p.side.value if p.side else "unknown",
            "status": p.status.value if p.status else "unknown",
            "entry_price": p.entry_price,
            "entry_qty": p.entry_qty,
            "exit_price": p.exit_price,
            "realized_pnl": p.realized_pnl,
            "realized_pnl_pct": p.realized_pnl_pct,
            "stop_loss": p.stop_loss_price,
            "take_profit": p.take_profit_price,
            "entry_time": p.entry_time.isoformat() if p.entry_time else None,
            "exit_time": p.exit_time.isoformat() if p.exit_time else None
        }
        for p in positions
    ]


@app.get("/api/positions/live")
async def get_live_positions():
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


@app.get("/api/trades/history")
async def get_trade_history(limit: int = Query(50, ge=1, le=500)):
    """Get closed trade history with P&L details."""
    if not db:
        raise HTTPException(status_code=503, detail="Database not initialized")
    
    repo = PositionRepository(db)
    closed = repo.get_closed_positions(limit=limit)
    
    trades = []
    for p in closed:
        if p.entry_time and p.exit_time:
            hold_duration = p.exit_time - p.entry_time
            hours = hold_duration.total_seconds() / 3600
            if hours < 1:
                duration_str = f"{int(hold_duration.total_seconds() / 60)}m"
            elif hours < 24:
                duration_str = f"{hours:.1f}h"
            else:
                duration_str = f"{hours / 24:.1f}d"
        else:
            duration_str = "-"
        
        trades.append({
            "id": p.id,
            "symbol": p.symbol,
            "side": p.side.value if p.side else "long",
            "entry_price": p.entry_price or 0,
            "exit_price": p.exit_price or 0,
            "qty": p.entry_qty or 0,
            "pnl": p.realized_pnl or 0,
            "pnl_pct": p.realized_pnl_pct or 0,
            "entry_time": p.entry_time.isoformat() if p.entry_time else "",
            "exit_time": p.exit_time.isoformat() if p.exit_time else "",
            "hold_duration": duration_str
        })
    
    return trades


@app.get("/api/trades")
async def get_trades(limit: int = Query(50, ge=1, le=500)):
    if not db:
        raise HTTPException(status_code=503, detail="Database not initialized")
    
    repo = TradeRepository(db)
    trades = repo.get_recent_trades(limit=limit)
    
    return [
        {
            "id": t.id,
            "symbol": t.symbol,
            "side": t.side.value if t.side else "unknown",
            "qty": t.qty,
            "price": t.price,
            "filled_qty": t.filled_qty,
            "filled_avg_price": t.filled_avg_price,
            "status": t.status,
            "submitted_at": t.submitted_at.isoformat() if t.submitted_at else ""
        }
        for t in trades
    ]


@app.get("/api/signals")
async def get_signals(limit: int = Query(100, ge=1, le=500)):
    if not db:
        raise HTTPException(status_code=503, detail="Database not initialized")
    
    repo = SignalRepository(db)
    signals = repo.get_recent_signals(limit=limit)
    
    return [
        {
            "id": s.id,
            "symbol": s.symbol,
            "signal_type": s.signal_type.value if s.signal_type else "unknown",
            "status": s.status.value if s.status else "unknown",
            "price_at_signal": s.price_at_signal,
            "rsi_value": s.rsi_value,
            "adx_value": s.adx_value,
            "conditions_met": s.conditions_met,
            "created_at": s.created_at.isoformat() if s.created_at else ""
        }
        for s in signals
    ]


@app.get("/api/equity")
async def get_equity(days: int = Query(30, ge=1, le=365)):
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


@app.get("/api/metrics")
async def get_metrics(days: Optional[int] = Query(None, ge=1, le=365)):
    if not db:
        raise HTTPException(status_code=503, detail="Database not initialized")
    
    since = None
    if days:
        since = datetime.now(timezone.utc) - timedelta(days=days)
    
    repo = MetricsRepository(db)
    metrics = repo.get_performance_metrics(since=since)
    
    # Calculate compounded return
    current_equity = engine.risk_manager._current_equity if engine else BASE_CAPITAL
    starting_capital = BASE_CAPITAL
    compounded_return = ((current_equity - starting_capital) / starting_capital) * 100
    
    return {
        **metrics,
        "compounded_return": round(compounded_return, 2)
    }


@app.get("/api/events/upcoming")
async def get_upcoming_events(days: int = Query(14, ge=1, le=90)):
    """Get upcoming market events."""
    event_filter = EventCalendarFilter()
    today = datetime.now(timezone.utc).date()
    
    events = []
    for i in range(days):
        check_date = today + timedelta(days=i)
        day_events = event_filter.get_events_for_date(check_date)
        
        for event in day_events:
            if event in ["FOMC", "CPI", "NFP"]:
                impact = "HIGH"
            elif event in ["QUAD_WITCH"]:
                impact = "MEDIUM"
            else:
                impact = "LOW"
            
            events.append({
                "date": str(check_date),
                "event": event.replace("_", " ").title(),
                "impact": impact,
                "days_until": i
            })
    
    return events


@app.get("/api/vix")
async def get_vix():
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
    if not engine:
        raise HTTPException(status_code=503, detail="Engine not initialized")
    
    summary = engine.get_scan_summary()
    
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "symbols": summary
    }


@app.post("/api/scan")
async def trigger_scan():
    if not engine:
        raise HTTPException(status_code=503, detail="Engine not initialized")
    
    if engine.state != EngineState.RUNNING:
        engine.start()
    
    result = engine.run_scan()
    
    return {
        "success": True,
        "symbols_scanned": result.symbols_scanned,
        "signals_found": result.signals_found,
        "signals_executed": result.signals_executed,
        "duration_ms": result.duration_ms,
        "message": f"Scan complete: {result.signals_found} signals, {result.signals_executed} executed"
    }


@app.post("/api/engine/start")
async def start_engine():
    if not engine:
        raise HTTPException(status_code=503, detail="Engine not initialized")
    
    if engine.state == EngineState.RUNNING:
        return {"status": "already_running", "message": "Engine is already running"}
    
    success = engine.start()
    return {"status": "started" if success else "failed", "message": "Engine started" if success else "Failed"}


@app.post("/api/engine/stop")
async def stop_engine():
    if not engine:
        raise HTTPException(status_code=503, detail="Engine not initialized")
    engine.stop()
    return {"status": "stopped", "message": "Engine stopped"}


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    logger.error(f"Unhandled exception: {exc}")
    return JSONResponse(status_code=500, content={"detail": str(exc)})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api.server:app", host="0.0.0.0", port=8000, reload=False)
