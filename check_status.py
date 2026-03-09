from ib_insync import IB

ib = IB()
ib.connect('127.0.0.1', 4002, clientId=1)

print('Account:', ib.managedAccounts())
print('')

# Check executions (filled orders)
print('Recent Executions:')
executions = ib.executions()
if executions:
    for exe in executions:
        print(f'  {exe.contract.localSymbol}: {exe.shares} @ {exe.price}')
else:
    print('  None (markets closed)')

print('')
print('Connection working - ready for Monday!')
ib.disconnect()
