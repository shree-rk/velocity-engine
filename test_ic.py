from ib_insync import IB, Stock
from datetime import datetime, timedelta, date

ib = IB()
ib.connect('127.0.0.1', 4002, clientId=1)
ib.reqMarketDataType(3)

# Get SPY price
spy = Stock('SPY', 'SMART', 'USD')
ib.qualifyContracts(spy)
ticker = ib.reqMktData(spy)
ib.sleep(1)
spy_price = ticker.last or ticker.close or 571
print(f'SPY Price: {spy_price}')

# Find Friday expiration
chains = ib.reqSecDefOptParams(spy.symbol, '', spy.secType, spy.conId)
chain = chains[0]

today = date.today()
days_to_friday = (4 - today.weekday()) % 7
if days_to_friday == 0:
    days_to_friday = 7
next_friday = today + timedelta(days=days_to_friday)
print(f'Target Expiration: {next_friday} ({days_to_friday} DTE)')

# Calculate IC strikes
short_put = round(spy_price * 0.95)
long_put = short_put - 5
short_call = round(spy_price * 1.05)
long_call = short_call + 5

print(f'Put Spread:  Sell {short_put}P / Buy {long_put}P')
print(f'Call Spread: Sell {short_call}C / Buy {long_call}C')

ib.disconnect()
print('Done!')
