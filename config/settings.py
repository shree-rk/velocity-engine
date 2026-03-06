"""
Velocity Engine - Central Configuration
Loads all settings from environment variables with safe defaults.
"""

import os
from pathlib import Path
from dotenv import load_dotenv
from enum import Enum

# Load .env file from project root
PROJECT_ROOT = Path(__file__).parent.parent
load_dotenv(PROJECT_ROOT / ".env")


# ============================================================
# Enums
# ============================================================

class TradingMode(Enum):
    PAPER = "paper"
    LIVE = "live"


class VIXRegime(Enum):
    NORMAL = "NORMAL"         # VIX < 20
    ELEVATED = "ELEVATED"     # VIX 20-25
    HIGH = "HIGH"             # VIX 25-30
    EXTREME = "EXTREME"       # VIX > 35


class SignalStatus(Enum):
    SIGNAL = "SIGNAL"
    WATCHING = "WATCHING"
    NEUTRAL = "NEUTRAL"
    TREND_BLOCKED = "TREND_BLOCKED"


class CircuitBreakerState(Enum):
    NOMINAL = "NOMINAL"       # Trading enabled
    TRIPPED = "TRIPPED"       # Trading halted


class ExitReason(Enum):
    TAKE_PROFIT = "TAKE_PROFIT"
    STOP_LOSS = "STOP_LOSS"
    MANUAL = "MANUAL"
    EMERGENCY_FLATTEN = "EMERGENCY_FLATTEN"


# ============================================================
# Alpaca Configuration
# ============================================================

ALPACA_API_KEY = os.getenv("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY", "")
ALPACA_TRADING_MODE = TradingMode(os.getenv("ALPACA_TRADING_MODE", "paper"))
LIVE_TRADING_CONFIRMED = os.getenv("LIVE_TRADING_CONFIRMED", "false").lower() == "true"

# Derive base URLs from mode
if ALPACA_TRADING_MODE == TradingMode.LIVE:
    ALPACA_BASE_URL = "https://api.alpaca.markets"
    ALPACA_DATA_URL = "https://data.alpaca.markets"
else:
    ALPACA_BASE_URL = "https://paper-api.alpaca.markets"
    ALPACA_DATA_URL = "https://data.alpaca.markets"  # Data URL is same for both


# ============================================================
# Database
# ============================================================

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://velocity:velocity_pass@localhost:5432/velocity_engine"
)


# ============================================================
# Trading Parameters
# ============================================================

BASE_CAPITAL = float(os.getenv("BASE_CAPITAL", "100000"))
MAX_POSITIONS = int(os.getenv("MAX_POSITIONS", "4"))
RISK_PER_TRADE = float(os.getenv("RISK_PER_TRADE", "0.02"))         # 2%
MAX_POSITION_PCT = float(os.getenv("MAX_POSITION_PCT", "0.25"))     # 25%
DRAWDOWN_THRESHOLD = float(os.getenv("DRAWDOWN_THRESHOLD", "0.15")) # 15%


# ============================================================
# Indicator Parameters (Velocity 2.0 - DO NOT CHANGE)
# ============================================================

BB_PERIOD = 20          # Bollinger Band period
BB_STD_DEV = 2.0        # Bollinger Band standard deviations
RSI_PERIOD = 14         # RSI period
ATR_PERIOD = 14         # ATR period
ADX_PERIOD = 14         # ADX period
SMA_PERIOD = 20         # SMA period (same as BB, used for take profit)
VOLUME_AVG_PERIOD = 20  # Volume average period

# Entry thresholds
RSI_OVERSOLD = 30       # RSI must be below this
ADX_TREND_THRESHOLD = 30  # ADX must be below this (no strong trend)
VOLUME_SPIKE_RATIO = 1.5  # Volume must be >= 1.5x average

# VIX failsafe default (used when Yahoo Finance is unavailable)
VIX_DEFAULT = 25.0      # Cautious default


# ============================================================
# VIX Regime Thresholds & Position Size Multipliers
# ============================================================

VIX_THRESHOLDS = {
    VIXRegime.NORMAL:   {"min": 0,  "max": 20, "size_multiplier": 1.0,  "can_trade": True},
    VIXRegime.ELEVATED: {"min": 20, "max": 25, "size_multiplier": 0.5,  "can_trade": True},
    VIXRegime.HIGH:     {"min": 25, "max": 30, "size_multiplier": 0.25, "can_trade": True},
    VIXRegime.EXTREME:  {"min": 35, "max": 999,"size_multiplier": 0.0,  "can_trade": False},
}


# ============================================================
# Scan Schedule (minutes/seconds)
# ============================================================

SCAN_INTERVAL_MINUTES = int(os.getenv("SCAN_INTERVAL_MINUTES", "3"))
MONITOR_INTERVAL_SECONDS = int(os.getenv("MONITOR_INTERVAL_SECONDS", "60"))
VIX_UPDATE_MINUTES = int(os.getenv("VIX_UPDATE_MINUTES", "5"))
EQUITY_RECONCILE_MINUTES = int(os.getenv("EQUITY_RECONCILE_MINUTES", "30"))
BROKER_SYNC_MINUTES = int(os.getenv("BROKER_SYNC_MINUTES", "15"))


# ============================================================
# Market Hours (US Eastern)
# ============================================================

MARKET_OPEN_HOUR = 9
MARKET_OPEN_MINUTE = 30
MARKET_CLOSE_HOUR = 16
MARKET_CLOSE_MINUTE = 0
MARKET_TIMEZONE = "US/Eastern"


# ============================================================
# Data Feed
# ============================================================

CANDLE_TIMEFRAME = "15Min"  # 15-minute candles
CANDLE_LOOKBACK_DAYS = 7    # Fetch 7 days of history for indicator calculation
DATA_FEED = "iex"           # Alpaca IEX feed


# ============================================================
# Logging
# ============================================================

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)


# ============================================================
# API Server
# ============================================================

API_HOST = os.getenv("API_HOST", "0.0.0.0")
API_PORT = int(os.getenv("API_PORT", "8000"))


# ============================================================
# Safety Checks on Import
# ============================================================

def validate_config():
    """Run on startup to catch configuration errors early."""
    errors = []

    if not ALPACA_API_KEY:
        errors.append("ALPACA_API_KEY is not set")
    if not ALPACA_SECRET_KEY:
        errors.append("ALPACA_SECRET_KEY is not set")

    if ALPACA_TRADING_MODE == TradingMode.LIVE and not LIVE_TRADING_CONFIRMED:
        errors.append(
            "LIVE trading mode selected but LIVE_TRADING_CONFIRMED is not 'true'. "
            "Set LIVE_TRADING_CONFIRMED=true in .env to enable live trading."
        )

    if RISK_PER_TRADE <= 0 or RISK_PER_TRADE > 0.05:
        errors.append(f"RISK_PER_TRADE={RISK_PER_TRADE} is outside safe range (0-5%)")

    if MAX_POSITIONS < 1 or MAX_POSITIONS > 10:
        errors.append(f"MAX_POSITIONS={MAX_POSITIONS} is outside safe range (1-10)")

    if errors:
        for e in errors:
            print(f"  CONFIG ERROR: {e}")
        raise SystemExit("Fix configuration errors in .env before starting.")

    # Print startup config summary
    print(f"  Mode:          {ALPACA_TRADING_MODE.value.upper()}")
    print(f"  Base Capital:  ${BASE_CAPITAL:,.0f}")
    print(f"  Max Positions: {MAX_POSITIONS}")
    print(f"  Risk/Trade:    {RISK_PER_TRADE*100:.1f}%")
    print(f"  Max Position:  {MAX_POSITION_PCT*100:.0f}%")
    print(f"  Drawdown Limit:{DRAWDOWN_THRESHOLD*100:.0f}%")
    print(f"  Scan Interval: {SCAN_INTERVAL_MINUTES} min")
    print(f"  Database:      {DATABASE_URL.split('@')[-1] if '@' in DATABASE_URL else 'local'}")
