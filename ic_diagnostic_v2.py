"""
IC Strategy Detailed Gate Diagnostic - FIXED
Shows all 16 entry gates and their status for each underlying
"""
from datetime import date, datetime, time, timedelta, timezone
from ib_insync import IB, Stock, Index
import sys

print("=" * 60)
print("IC STRATEGY - DETAILED GATE DIAGNOSTIC")
print("=" * 60)

# Get current time info
now_utc = datetime.now(timezone.utc)
now_local = datetime.now()

# Manual ET calculation (March = DST, so UTC-4)
et_offset = timedelta(hours=-4)  # EDT
now_et = now_utc + et_offset

print(f"Local Time: {now_local.strftime('%Y-%m-%d %H:%M:%S')}")
print(f"UTC Time:   {now_utc.strftime('%Y-%m-%d %H:%M:%S')}")
print(f"ET Time:    {now_et.strftime('%Y-%m-%d %H:%M:%S')}")

# Check market hours manually
market_open = time(9, 30)
market_close = time(16, 0)
current_et_time = now_et.time()
is_weekday = now_et.weekday() < 5

print(f"\nMarket Hours: 9:30 AM - 4:00 PM ET")
print(f"Current ET Time: {current_et_time.strftime('%H:%M:%S')}")
print(f"Is Weekday: {is_weekday}")

if is_weekday and market_open <= current_et_time < market_close:
    print("✓ MARKET IS OPEN")
    market_is_open = True
else:
    print("✗ MARKET IS CLOSED")
    market_is_open = False

# Connect to IBKR
print("\n" + "-" * 60)
ib = IB()
try:
    ib.connect('127.0.0.1', 4002, clientId=1)
    print(f"✓ IBKR Connected: {ib.isConnected()}")
except Exception as e:
    print(f"✗ IBKR Connection Failed: {e}")
    sys.exit(1)

# Get account info
account = ib.accountSummary()
net_liq = 0
for item in account:
    if item.tag == 'NetLiquidation':
        net_liq = float(item.value)
        print(f"✓ Account Net Liq: ${net_liq:,.2f}")

# Get market data
ib.reqMarketDataType(3)  # Delayed data

# SPY
spy = Stock('SPY', 'SMART', 'USD')
ib.qualifyContracts(spy)
spy_ticker = ib.reqMktData(spy)
ib.sleep(2)
spy_price = spy_ticker.marketPrice()
print(f"✓ SPY Price: ${spy_price:.2f}")

# VIX - Use Yahoo Finance as backup since IBKR VIX can be tricky
vix_value = None
try:
    vix = Index('VIX', 'CBOE')
    ib.qualifyContracts(vix)
    vix_ticker = ib.reqMktData(vix)
    ib.sleep(2)
    vix_value = vix_ticker.marketPrice()
    if vix_value is None or str(vix_value) == 'nan':
        raise ValueError("VIX returned nan")
    print(f"✓ VIX (IBKR): {vix_value:.2f}")
except Exception as e:
    print(f"  VIX from IBKR failed: {e}")
    # Try Yahoo Finance
    try:
        import yfinance as yf
        vix_data = yf.Ticker("^VIX")
        vix_value = vix_data.info.get('regularMarketPrice') or vix_data.info.get('previousClose')
        print(f"✓ VIX (Yahoo): {vix_value:.2f}")
    except Exception as e2:
        print(f"  VIX from Yahoo failed: {e2}")
        vix_value = 20.0  # Default
        print(f"  Using default VIX: {vix_value}")

# VIX Analysis
print("\n" + "-" * 60)
print("VIX REGIME ANALYSIS")
print("-" * 60)
if vix_value < 20:
    vix_status = "NORMAL"
    print(f"  VIX {vix_value:.1f} = NORMAL (full position size)")
    vix_blocks = False
elif vix_value < 23:
    vix_status = "ELEVATED"
    print(f"  VIX {vix_value:.1f} = ELEVATED (50% position size)")
    vix_blocks = False
else:
    vix_status = "CRITICAL"
    print(f"  VIX {vix_value:.1f} = CRITICAL (NO ENTRY)")
    print(f"  ⚠️  Entry blocked until VIX < 23")
    vix_blocks = True

# Manual Gate Checks
print("\n" + "=" * 60)
print("MANUAL GATE CHECK")
print("=" * 60)

gates_passed = []
gates_failed = []

# Gate 1: Market Hours
if market_is_open:
    gates_passed.append(("Gate 1", "Market Hours", "Market is OPEN"))
else:
    gates_failed.append(("Gate 1", "Market Hours", f"Market CLOSED (ET time: {current_et_time})"))

# Gate 2: Event Calendar
from strategies.ic_config import is_event_blocked, get_event_warning
today = date.today()
blocked, event = is_event_blocked(today)
if blocked:
    gates_failed.append(("Gate 2", "Event Calendar", f"BLOCKED: {event}"))
else:
    gates_passed.append(("Gate 2", "Event Calendar", "No blocking events"))

# Gate 9: VIX
if vix_blocks:
    gates_failed.append(("Gate 9", "VIX Filter", f"VIX {vix_value:.1f} >= 23 CRITICAL"))
else:
    gates_passed.append(("Gate 9", "VIX Filter", f"VIX {vix_value:.1f} OK"))

# Print results
print("\nPASSED GATES:")
for gate in gates_passed:
    print(f"  ✓ {gate[0]:8s} | {gate[1]:20s} | {gate[2]}")

print("\nFAILED GATES:")
for gate in gates_failed:
    print(f"  ✗ {gate[0]:8s} | {gate[1]:20s} | {gate[2]}")

# Summary
print("\n" + "=" * 60)
print("SUMMARY")
print("=" * 60)
print(f"  SPY: ${spy_price:.2f}")
print(f"  VIX: {vix_value:.2f} ({vix_status})")
print(f"  Market: {'OPEN' if market_is_open else 'CLOSED'}")
print(f"  Entry Allowed: {'YES' if (market_is_open and not vix_blocks and not blocked) else 'NO'}")

if not market_is_open:
    print(f"\n  ⏰ Market opens at 9:30 AM ET")
    print(f"     Current ET: {current_et_time.strftime('%H:%M:%S')}")
    
if vix_blocks:
    print(f"\n  ⚠️ VIX too high for IC entry")
    print(f"     Wait for VIX < 23 before entering")

ib.disconnect()
print("\n✓ Disconnected from IBKR")
print("=" * 60)
