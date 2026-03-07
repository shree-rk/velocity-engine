"""
Velocity Engine Configuration
Centralized settings loaded from environment variables.
"""

import os
from enum import Enum
from typing import Optional
from dotenv import load_dotenv

# Load .env file
load_dotenv()


class TradingMode(Enum):
    """Trading mode - paper or live."""
    PAPER = "PAPER"
    LIVE = "LIVE"


# =============================================================================
# Alpaca API Configuration
# =============================================================================

ALPACA_API_KEY: str = os.getenv("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY: str = os.getenv("ALPACA_SECRET_KEY", "")

# Trading mode from env, defaults to PAPER for safety
_mode = os.getenv("ALPACA_TRADING_MODE", "PAPER").upper()
ALPACA_TRADING_MODE: TradingMode = TradingMode.LIVE if _mode == "LIVE" else TradingMode.PAPER


# =============================================================================
# Risk Management Parameters
# =============================================================================

# Base capital for position sizing (used if account equity unavailable)
BASE_CAPITAL: float = float(os.getenv("BASE_CAPITAL", "100000"))

# Maximum number of concurrent positions
MAX_POSITIONS: int = int(os.getenv("MAX_POSITIONS", "4"))

# Risk per trade as decimal (0.02 = 2%)
RISK_PER_TRADE: float = float(os.getenv("RISK_PER_TRADE", "0.02"))

# Maximum position size as percentage of equity (0.25 = 25%)
MAX_POSITION_SIZE_PCT: float = float(os.getenv("MAX_POSITION_SIZE_PCT", "0.25"))

# Alpha Shield drawdown limit as decimal (0.15 = 15%)
ALPHA_SHIELD_DRAWDOWN: float = float(os.getenv("ALPHA_SHIELD_DRAWDOWN", "0.15"))


# =============================================================================
# Scanning Configuration
# =============================================================================

# Minutes between scans
SCAN_INTERVAL_MINUTES: int = int(os.getenv("SCAN_INTERVAL_MINUTES", "3"))


# =============================================================================
# Database Configuration
# =============================================================================

DATABASE_HOST: str = os.getenv("DATABASE_HOST", "localhost")
DATABASE_PORT: int = int(os.getenv("DATABASE_PORT", "5432"))
DATABASE_NAME: str = os.getenv("DATABASE_NAME", "velocity_engine")
DATABASE_USER: str = os.getenv("DATABASE_USER", "postgres")
DATABASE_PASSWORD: str = os.getenv("DATABASE_PASSWORD", "")

DATABASE_URL: str = os.getenv(
    "DATABASE_URL",
    f"postgresql://{DATABASE_USER}:{DATABASE_PASSWORD}@{DATABASE_HOST}:{DATABASE_PORT}/{DATABASE_NAME}"
)


# =============================================================================
# Logging Configuration
# =============================================================================

LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")


# =============================================================================
# Validation
# =============================================================================

def validate_config() -> None:
    """
    Validate that required configuration is present.
    Raises ValueError if critical settings are missing.
    """
    errors = []
    
    if not ALPACA_API_KEY:
        errors.append("ALPACA_API_KEY is required")
    
    if not ALPACA_SECRET_KEY:
        errors.append("ALPACA_SECRET_KEY is required")
    
    if RISK_PER_TRADE <= 0 or RISK_PER_TRADE > 0.1:
        errors.append(f"RISK_PER_TRADE must be between 0 and 0.1, got {RISK_PER_TRADE}")
    
    if MAX_POSITIONS <= 0 or MAX_POSITIONS > 20:
        errors.append(f"MAX_POSITIONS must be between 1 and 20, got {MAX_POSITIONS}")
    
    if MAX_POSITION_SIZE_PCT <= 0 or MAX_POSITION_SIZE_PCT > 1.0:
        errors.append(f"MAX_POSITION_SIZE_PCT must be between 0 and 1, got {MAX_POSITION_SIZE_PCT}")
    
    if ALPHA_SHIELD_DRAWDOWN <= 0 or ALPHA_SHIELD_DRAWDOWN > 0.5:
        errors.append(f"ALPHA_SHIELD_DRAWDOWN must be between 0 and 0.5, got {ALPHA_SHIELD_DRAWDOWN}")
    
    if errors:
        raise ValueError("Configuration errors:\n" + "\n".join(f"  - {e}" for e in errors))
    
    # Print config summary
    print(f"  Mode:          {ALPACA_TRADING_MODE.value}")
    print(f"  Base Capital:  ${BASE_CAPITAL:,.0f}")
    print(f"  Max Positions: {MAX_POSITIONS}")
    print(f"  Risk/Trade:    {RISK_PER_TRADE:.1%}")
    print(f"  Max Position:  {MAX_POSITION_SIZE_PCT:.0%}")
    print(f"  Drawdown Limit:{ALPHA_SHIELD_DRAWDOWN:.0%}")
    print(f"  Scan Interval: {SCAN_INTERVAL_MINUTES} min")
    print(f"  Database:      {DATABASE_HOST}:{DATABASE_PORT}/{DATABASE_NAME}")
