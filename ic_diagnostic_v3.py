"""
IC Strategy Detailed Gate Diagnostic v3
With expiration debug
"""
from datetime import date, datetime, timedelta
from ib_insync import IB, Stock, Index
import sys

print("=" * 60)
print("IC STRATEGY - GATE DIAGNOSTIC v3")
print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 60)

# Connect to IBKR
ib = IB()
ib.connect('127.0.0.1', 4002, clientId=1)
print(f"✓ IBKR Connected")

# Get account info
account = ib.accountSummary()
net_liq = 0
for item in account:
    if item.tag == 'NetLiquidation':
        net_liq = float(item.value)
        print(f"✓ Account: ${net_liq:,.2f}")

# Get market data
ib.reqMarketDataType(3)

spy = Stock('SPY', 'SMART', 'USD')
ib.qualifyContracts(spy)
spy_ticker = ib.reqMktData(spy)
ib.sleep(2)
spy_price = spy_ticker.marketPrice()
print(f"✓ SPY: ${spy_price:.2f}")

# VIX
vix_value = None
try:
    vix = Index('VIX', 'CBOE')
    ib.qualifyContracts(vix)
    vix_ticker = ib.reqMktData(vix)
    ib.sleep(2)
    vix_value = vix_ticker.marketPrice()
    if vix_value and str(vix_value) != 'nan':
        print(f"✓ VIX: {vix_value:.2f}")
    else:
        raise ValueError("nan")
except:
    try:
        import yfinance as yf
        vix_data = yf.Ticker("^VIX")
        hist = vix_data.history(period="1d")
        if not hist.empty:
            vix_value = hist['Close'].iloc[-1]
        else:
            vix_value = vix_data.info.get('regularMarketPrice', 20.0)
        print(f"✓ VIX (Yahoo): {vix_value:.2f}")
    except:
        vix_value = 20.0
        print(f"✓ VIX (default): {vix_value:.2f}")

# Expiration Debug
print("\n" + "-" * 60)
print("EXPIRATION FINDER DEBUG")
print("-" * 60)

today = date.today()
print(f"Today: {today} ({today.strftime('%A')})")

# Config values
target_dte = 7
min_dte = 5
max_dte = 14  # Increased from 10

# Find valid Friday expirations
print(f"\nLooking for Friday expirations with DTE {min_dte}-{max_dte}:")

valid_expirations = []
for days_ahead in range(1, 21):
    check_date = today + timedelta(days=days_ahead)
    if check_date.weekday() == 4:  # Friday
        dte = (check_date - today).days
        status = "✓ VALID" if min_dte <= dte <= max_dte else "✗ outside range"
        print(f"  {check_date} (Fri) - DTE {dte:2d} - {status}")
        if min_dte <= dte <= max_dte:
            valid_expirations.append(check_date)

if valid_expirations:
    selected_exp = valid_expirations[0]
    print(f"\n→ Selected Expiration: {selected_exp} (DTE {(selected_exp - today).days})")
else:
    print("\n✗ No valid expiration found!")

# VIX Analysis
print("\n" + "-" * 60)
print("VIX ANALYSIS")
print("-" * 60)
if vix_value >= 25:
    print(f"  VIX {vix_value:.1f} = CRITICAL (>= 25)")
    print(f"  ⛔ NO ENTRY - VIX too high")
    vix_ok = False
elif vix_value >= 23:
    print(f"  VIX {vix_value:.1f} = HIGH (23-25)")
    print(f"  ⛔ NO ENTRY - VIX elevated")
    vix_ok = False
elif vix_value >= 20:
    print(f"  VIX {vix_value:.1f} = ELEVATED (20-23)")
    print(f"  ✓ Entry OK with 50% position size")
    vix_ok = True
else:
    print(f"  VIX {vix_value:.1f} = NORMAL (< 20)")
    print(f"  ✓ Entry OK with full position size")
    vix_ok = True

# Manual Strike Calculation
if valid_expirations and vix_ok:
    print("\n" + "-" * 60)
    print("STRIKE CALCULATION (Manual)")
    print("-" * 60)
    
    exp = valid_expirations[0]
    dte = (exp - today).days
    
    # Estimate ~10 delta distance
    iv = vix_value / 100
    std_dev = spy_price * iv * (dte / 365) ** 0.5
    delta_dist = round(0.4 * std_dev)
    
    short_put = round(spy_price - delta_dist)
    short_call = round(spy_price + delta_dist)
    wing_width = 5
    long_put = short_put - wing_width
    long_call = short_call + wing_width
    
    print(f"  Spot: ${spy_price:.2f}")
    print(f"  Expiration: {exp} ({dte} DTE)")
    print(f"  IV estimate: {vix_value:.1f}%")
    print(f"  Delta distance: ~${delta_dist}")
    print(f"")
    print(f"  Put Spread:  ${short_put} / ${long_put}")
    print(f"  Call Spread: ${short_call} / ${long_call}")
    print(f"  Wing Width:  ${wing_width}")
    print(f"")
    print(f"  Breakeven Low:  ${short_put - 1.5:.2f} (est)")
    print(f"  Breakeven High: ${short_call + 1.5:.2f} (est)")

# Summary
print("\n" + "=" * 60)
print("ENTRY DECISION")
print("=" * 60)

can_enter = bool(valid_expirations) and vix_ok
if can_enter:
    print("  ✅ ENTRY POSSIBLE")
    print(f"     Expiration: {valid_expirations[0]}")
    print(f"     VIX: {vix_value:.1f}")
else:
    print("  ⛔ ENTRY BLOCKED")
    if not valid_expirations:
        print("     Reason: No valid expiration in range")
    if not vix_ok:
        print(f"     Reason: VIX {vix_value:.1f} >= 23")

ib.disconnect()
print("\n✓ Done")
