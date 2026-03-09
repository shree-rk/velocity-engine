from ib_insync import IB, Stock, Option, ComboLeg, Contract, LimitOrder
from datetime import date, timedelta

ib = IB()
ib.connect('127.0.0.1', 4002, clientId=1)
ib.reqMarketDataType(3)

# Get SPY price
spy = Stock('SPY', 'SMART', 'USD')
ib.qualifyContracts(spy)
ticker = ib.reqMktData(spy)
ib.sleep(1)
spy_price = ticker.last or ticker.close or 671

# Setup expiration (next Friday)
today = date.today()
days_to_friday = (4 - today.weekday()) % 7
if days_to_friday == 0:
    days_to_friday = 7
next_friday = today + timedelta(days=days_to_friday)
exp_str = next_friday.strftime('%Y%m%d')

# IC strikes (5% OTM each side)
short_put_strike = round(spy_price * 0.95)
long_put_strike = short_put_strike - 5
short_call_strike = round(spy_price * 1.05)
long_call_strike = short_call_strike + 5

print(f'Creating IC: {exp_str}')
print(f'  Put spread: {short_put_strike}/{long_put_strike}')
print(f'  Call spread: {short_call_strike}/{long_call_strike}')

# Create option contracts
short_put = Option('SPY', exp_str, short_put_strike, 'P', 'SMART')
long_put = Option('SPY', exp_str, long_put_strike, 'P', 'SMART')
short_call = Option('SPY', exp_str, short_call_strike, 'C', 'SMART')
long_call = Option('SPY', exp_str, long_call_strike, 'C', 'SMART')

# Qualify to get conIds
ib.qualifyContracts(short_put, long_put, short_call, long_call)
print(f'Contracts qualified!')

# For now, just verify - don't place order yet
print(f'Short Put conId: {short_put.conId}')
print(f'Long Put conId: {long_put.conId}')
print(f'Short Call conId: {short_call.conId}')
print(f'Long Call conId: {long_call.conId}')

ib.disconnect()
print('Ready to trade!')
