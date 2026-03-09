"""
IC Strategy Detailed Gate Diagnostic
Shows all 16 entry gates and their status for each underlying
"""
from datetime import date, datetime
from ib_insync import IB, Stock, Index

print("=" * 60)
print("IC STRATEGY - DETAILED GATE DIAGNOSTIC")
print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 60)

# Connect to IBKR
ib = IB()
ib.connect('127.0.0.1', 4002, clientId=1)
print(f"\n✓ IBKR Connected: {ib.isConnected()}")

# Get account info
account = ib.accountSummary()
net_liq = 0
for item in account:
    if item.tag == 'NetLiquidation':
        net_liq = float(item.value)
        print(f"✓ Account Net Liq: ${net_liq:,.2f}")

# Get market data
ib.reqMarketDataType(3)  # Delayed data

spy = Stock('SPY', 'SMART', 'USD')
ib.qualifyContracts(spy)
spy_ticker = ib.reqMktData(spy)
ib.sleep(2)
spy_price = spy_ticker.marketPrice()
print(f"✓ SPY Price: ${spy_price:.2f}")

vix = Index('VIX', 'CBOE')
ib.qualifyContracts(vix)
vix_ticker = ib.reqMktData(vix)
ib.sleep(2)
vix_value = vix_ticker.marketPrice()
print(f"✓ VIX: {vix_value:.2f}")

# VIX Analysis
print("\n" + "-" * 60)
print("VIX REGIME ANALYSIS")
print("-" * 60)
if vix_value < 20:
    print(f"  VIX {vix_value:.1f} = NORMAL (full position size)")
elif vix_value < 23:
    print(f"  VIX {vix_value:.1f} = ELEVATED (50% position size)")
elif vix_value < 25:
    print(f"  VIX {vix_value:.1f} = HIGH (NO ENTRY)")
else:
    print(f"  VIX {vix_value:.1f} = CRITICAL (NO ENTRY)")
    print(f"  ⚠️  Entry blocked until VIX < 23")

# Import strategy
from strategies.iron_condor import IronCondorStrategy
from strategies.ic_config import IC_CONFIG, is_event_blocked, get_event_warning

strategy = IronCondorStrategy(account_capital=100000.0)

# Check each underlying
underlyings = ["SPY", "SPX", "QQQ"]

for symbol in underlyings:
    print("\n" + "=" * 60)
    print(f"SCANNING: {symbol}")
    print("=" * 60)
    
    passed, signal, gates = strategy.check_entry(symbol)
    
    # Print each gate
    for gate in gates:
        status = "✓ PASS" if gate.passed else "✗ FAIL"
        print(f"  Gate {gate.gate_num:2d} | {gate.gate_name:20s} | {status} | {gate.message}")
        
        # If gate failed, stop showing more gates (they weren't checked)
        if not gate.passed:
            print(f"\n  ⛔ Entry blocked at Gate {gate.gate_num}")
            break
    
    if passed and signal:
        print(f"\n  ✅ SIGNAL GENERATED!")
        print(f"     Expiration: {signal.expiration}")
        print(f"     Put Spread: {signal.short_put_strike}/{signal.long_put_strike}")
        print(f"     Call Spread: {signal.short_call_strike}/{signal.long_call_strike}")
        print(f"     Quantity: {signal.quantity}")
        print(f"     Est Credit: ${signal.estimated_credit:.2f}")
        print(f"     Max Risk: ${signal.max_risk:.2f}")

# Event Calendar Check
print("\n" + "-" * 60)
print("EVENT CALENDAR")
print("-" * 60)
today = date.today()
blocked, event = is_event_blocked(today)
if blocked:
    print(f"  ⚠️  TODAY BLOCKED: {event}")
else:
    print(f"  ✓ No blocking events today")

warning = get_event_warning(today)
if warning:
    print(f"  ⚠️  TOMORROW: {warning}")

# Summary
print("\n" + "=" * 60)
print("SUMMARY")
print("=" * 60)
print(f"  Market Data: SPY ${spy_price:.2f}, VIX {vix_value:.2f}")
print(f"  VIX Status: {'BLOCKED (>=23)' if vix_value >= 23 else 'OK (<23)'}")
print(f"  Account: ${net_liq:,.0f}")
print(f"  Max Condors Allowed: {strategy.config.get_max_condors(net_liq)}")
print(f"  Open Positions: {len(strategy.open_positions)}")

ib.disconnect()
print("\n✓ Disconnected from IBKR")
print("=" * 60)
