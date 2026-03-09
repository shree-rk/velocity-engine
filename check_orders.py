from ib_insync import IB

ib = IB()
ib.connect('127.0.0.1', 4002, clientId=1)

print('Open Orders:')
for trade in ib.openTrades():
    print(f'  Order {trade.order.orderId}: {trade.orderStatus.status}')
    print(f'    Action: {trade.order.action}')
    print(f'    Qty: {trade.order.totalQuantity}')
    print(f'    Limit: {trade.order.lmtPrice}')

print('')
print('Positions:')
for pos in ib.positions():
    print(f'  {pos.contract.localSymbol}: {pos.position} @ {pos.avgCost}')

ib.disconnect()
