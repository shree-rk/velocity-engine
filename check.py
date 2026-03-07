python -c "
from config.settings import validate_config, ALPACA_TRADING_MODE
print('=== Velocity Engine Config Check ===')
validate_config()
print('Config: OK')

from config.watchlists import VELOCITY_MR_WATCHLIST, get_all_symbols
symbols = get_all_symbols(VELOCITY_MR_WATCHLIST)
print(f'Watchlist: {len(symbols)} symbols - {symbols}')

from indicators.technical import IndicatorSnapshot
snap = IndicatorSnapshot(
    symbol='TEST', price=95.0, sma_20=100.0, bb_upper=105.0, bb_lower=96.0,
    rsi_14=25.0, atr_14=2.0, adx_14=20.0, plus_di=15.0, minus_di=25.0,
    volume=2000000, avg_volume=1000000, volume_ratio=2.0,
)
print(f'Indicators: {snap.conditions_met_count}/4 conditions met')
print(f'All entry conditions: {snap.all_entry_conditions_met}')
print('=== All OK! Ready for next batch ===')