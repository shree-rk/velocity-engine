from ib_insync import IB, Option, ComboLeg, Contract, LimitOrder
from datetime import date, timedelta

ib = IB()
ib.connect('127.0.0.1', 4002, clientId=1)
ib.reqMarketDataType(3)

today = date.today()
days_to_friday = (4 - today.weekday()) % 7
if days_to_friday == 0:
    days_to_friday = 7
next_friday = today + timedelta(days=days_to_friday)
exp_str = next_friday.strftime('%Y%m%d')

short_put = Option('SPY', exp_str, 638, 'P', 'SMART')
long_put = Option('SPY', exp_str, 633, 'P', 'SMART')
short_call = Option('SPY', exp_str, 705, 'C', 'SMART')
long_call = Option('SPY', exp_str, 710, 'C', 'SMART')
ib.qualifyContracts(short_put, long_put, short_call, long_call)

legs = [
    ComboLeg(conId=short_put.conId, ratio=1, action='SELL', exchange='SMART'),
    ComboLeg(conId=long_put.conId, ratio=1, action='BUY', exchange='SMART'),
    ComboLeg(conId=short_call.conId, ratio=1, action='SELL', exchange='SMART'),
    ComboLeg(conId=long_call.conId, ratio=1, action='BUY', exchange='SMART'),
]

combo = Contract()
combo.symbol = 'SPY'
combo.secType = 'BAG'
combo.currency = 'USD'
combo.exchange = 'SMART'
combo.comboLegs = legs

order = LimitOrder(action='SELL', totalQuantity=1, lmtPrice=0.50)

print('Placing Iron Condor order...')
trade = ib.placeOrder(combo, order)
ib.sleep(2)
print(f'Order Status: {trade.orderStatus.status}')
print(f'Order ID: {trade.order.orderId}')

ib.disconnect()
