"""Test IC Strategy with live IBKR connection"""
from datetime import date
from ib_insync import IB

# Connect to IBKR
ib = IB()
ib.connect('127.0.0.1', 4002, clientId=1)

print(f"Connected: {ib.isConnected()}")

# Get account info
account = ib.accountSummary()
for item in account:
    if item.tag in ['NetLiquidation', 'AvailableFunds', 'BuyingPower']:
        print(f"{item.tag}: ${float(item.value):,.2f}")

# Get SPY price
from ib_insync import Stock
spy = Stock('SPY', 'SMART', 'USD')
ib.qualifyContracts(spy)
ib.reqMarketDataType(3)  # Delayed data
ticker = ib.reqMktData(spy)
ib.sleep(2)
print(f"\nSPY Price: ${ticker.marketPrice():.2f}")

# Get VIX
from ib_insync import Index
vix = Index('VIX', 'CBOE')
ib.qualifyContracts(vix)
vix_ticker = ib.reqMktData(vix)
ib.sleep(2)
print(f"VIX: {vix_ticker.marketPrice():.2f}")

# Test IC Strategy
from strategies.iron_condor import IronCondorStrategy

strategy = IronCondorStrategy(account_capital=100000.0)

# Run entry scan (dry run - no broker connected to strategy yet)
print("\n--- Running Entry Scan (Dry Run) ---")
signal = strategy.run_entry_scan()

if signal:
    print(f"\nSignal Generated:")
    print(f"  {signal.underlying} exp {signal.expiration}")
    print(f"  Put: {signal.short_put_strike}/{signal.long_put_strike}")
    print(f"  Call: {signal.short_call_strike}/{signal.long_call_strike}")
    print(f"  Qty: {signal.quantity}")
    print(f"  Est Credit: ${signal.estimated_credit:.2f}")
else:
    print("No signal (check gate results above)")

ib.disconnect()
print("\nDone!")