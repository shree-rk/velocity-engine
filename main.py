"""
Velocity Engine - Main Entry Point

Usage:
    python main.py                  # Run single scan
    python main.py --scan           # Run single scan
    python main.py --status         # Show engine status
    python main.py --daemon         # Run as daemon with scheduler
    python main.py --positions      # Show current positions
"""

import argparse
import logging
import sys
import time
from datetime import datetime

from config.settings import (
    ALPACA_TRADING_MODE,
    validate_config,
    LOG_LEVEL,
    TradingMode
)
from core.engine import VelocityEngine, EngineState
from core.scheduler import create_scheduler

# Configure logging
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("velocity")


def print_banner():
    """Print startup banner."""
    print("""
╔═══════════════════════════════════════════════════════════╗
║                    VELOCITY ENGINE                        ║
║              Mean Reversion Trading System                ║
╚═══════════════════════════════════════════════════════════╝
    """)


def print_status(engine: VelocityEngine):
    """Print engine status."""
    status = engine.get_status()
    
    print("\n" + "=" * 50)
    print("ENGINE STATUS")
    print("=" * 50)
    print(f"  State:          {status.state.value.upper()}")
    print(f"  Mode:           {status.mode}")
    print(f"  Broker:         {'Connected' if status.broker_connected else 'Disconnected'}")
    print(f"  Market:         {'Open' if status.market_open else 'Closed'}")
    print()
    print("FILTERS:")
    print(f"  VIX:            {status.vix_value:.1f} ({status.vix_regime})")
    print(f"  Events:         {'Blocked' if status.events_blocked else 'Clear'}")
    print(f"  Trading Hours:  {'OK' if status.trading_hours_ok else 'Outside Hours'}")
    print()
    print("RISK:")
    print(f"  Alpha Shield:   {'TRIGGERED' if status.alpha_shield_triggered else 'OK'}")
    print(f"  Drawdown:       {status.current_drawdown:.2%}")
    print(f"  Positions:      {status.open_positions}/{status.max_positions}")
    print()
    print("ACCOUNT:")
    print(f"  Equity:         ${status.equity:,.2f}")
    print(f"  High Water:     ${status.high_water_mark:,.2f}")
    print()
    print(f"STATUS: {status.message}")
    print("=" * 50)


def print_positions(engine: VelocityEngine):
    """Print current positions."""
    positions = engine.get_positions()
    
    print("\n" + "=" * 60)
    print("CURRENT POSITIONS")
    print("=" * 60)
    
    if not positions:
        print("  No open positions")
    else:
        print(f"  {'Symbol':<8} {'Qty':>6} {'Entry':>10} {'Current':>10} {'P&L':>12} {'%':>8}")
        print("  " + "-" * 56)
        
        for p in positions:
            print(
                f"  {p.symbol:<8} {p.qty:>6} "
                f"${float(p.avg_entry_price):>9.2f} "
                f"${float(p.current_price):>9.2f} "
                f"${float(p.unrealized_pl):>11.2f} "
                f"{float(p.unrealized_plpc):>7.2f}%"
            )
    
    print("=" * 60)


def run_single_scan(engine: VelocityEngine):
    """Run a single scan cycle."""
    print("\nRunning scan...")
    
    result = engine.run_scan()
    
    print(f"\nScan Results ({result.duration_ms}ms):")
    print(f"  Symbols Scanned:  {result.symbols_scanned}")
    print(f"  Signals Found:    {result.signals_found}")
    print(f"  Signals Executed: {result.signals_executed}")
    print(f"  Signals Filtered: {result.signals_filtered}")
    
    if result.filter_reasons:
        print("\n  Filter Reasons:")
        for reason, count in result.filter_reasons.items():
            print(f"    - {reason}: {count}")
    
    if result.errors:
        print("\n  Errors:")
        for error in result.errors:
            print(f"    - {error}")


def run_daemon(engine: VelocityEngine):
    """Run engine as daemon with scheduler."""
    print("\nStarting daemon mode...")
    print("Press Ctrl+C to stop\n")
    
    scheduler = create_scheduler(engine)
    scheduler.start()
    
    try:
        while True:
            time.sleep(60)
            
            # Print heartbeat
            status = engine.get_status()
            print(
                f"[{datetime.now().strftime('%H:%M:%S')}] "
                f"Positions: {status.open_positions}/{status.max_positions} | "
                f"VIX: {status.vix_value:.1f} | "
                f"DD: {status.current_drawdown:.1%}"
            )
            
    except KeyboardInterrupt:
        print("\n\nShutting down...")
        scheduler.stop()
        engine.stop()
        print("Goodbye!")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Velocity Engine - Mean Reversion Trading System"
    )
    
    parser.add_argument(
        "--scan",
        action="store_true",
        help="Run a single scan cycle"
    )
    
    parser.add_argument(
        "--status",
        action="store_true",
        help="Show engine status"
    )
    
    parser.add_argument(
        "--positions",
        action="store_true",
        help="Show current positions"
    )
    
    parser.add_argument(
        "--daemon",
        action="store_true",
        help="Run as daemon with scheduler"
    )
    
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Show scan summary for all symbols"
    )
    
    args = parser.parse_args()
    
    # Print banner
    print_banner()
    
    # Validate configuration
    print("Validating configuration...")
    try:
        validate_config()
        print(f"  Mode: {ALPACA_TRADING_MODE.value}")
        print("  ✓ Configuration OK\n")
    except Exception as e:
        print(f"  ✗ Configuration Error: {e}")
        sys.exit(1)
    
    # Safety check for live mode
    if ALPACA_TRADING_MODE == TradingMode.LIVE:
        print("⚠️  WARNING: LIVE TRADING MODE")
        confirm = input("Type 'CONFIRM' to proceed: ")
        if confirm != "CONFIRM":
            print("Aborted.")
            sys.exit(0)
    
    # Initialize engine
    print("Initializing engine...")
    try:
        engine = VelocityEngine(auto_connect=True)
        
        if not engine.start():
            print("  ✗ Failed to start engine")
            sys.exit(1)
        
        print("  ✓ Engine started\n")
        
    except Exception as e:
        print(f"  ✗ Engine Error: {e}")
        sys.exit(1)
    
    # Execute requested action
    try:
        if args.status:
            print_status(engine)
        
        elif args.positions:
            print_positions(engine)
        
        elif args.summary:
            print("\nFetching scan summary...")
            summary = engine.get_scan_summary()
            
            print(f"\n{'Symbol':<8} {'Status':<10} {'Cond':>4} {'RSI':>6} {'ADX':>6} {'Vol':>5}")
            print("-" * 50)
            
            for symbol, data in summary.items():
                if data.get("status") == "error":
                    print(f"{symbol:<8} ERROR: {data.get('error', 'Unknown')}")
                elif data.get("status") == "no_data":
                    print(f"{symbol:<8} NO DATA")
                else:
                    print(
                        f"{symbol:<8} {data.get('status', 'N/A'):<10} "
                        f"{data.get('conditions_met', 0):>4}/4 "
                        f"{data.get('rsi', 0):>6.1f} "
                        f"{data.get('adx', 0):>6.1f} "
                        f"{data.get('volume_ratio', 0):>5.1f}x"
                    )
        
        elif args.daemon:
            run_daemon(engine)
        
        else:
            # Default: run single scan
            print_status(engine)
            run_single_scan(engine)
    
    finally:
        if not args.daemon:
            engine.stop()


if __name__ == "__main__":
    main()
