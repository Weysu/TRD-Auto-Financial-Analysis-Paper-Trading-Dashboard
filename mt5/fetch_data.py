import MetaTrader5 as mt5
import pandas as pd

mt5.initialize()

symbol = "AAPL.US"

# Active le symbole si pas déjà fait
mt5.symbol_select(symbol, True)

rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1, 0, 1000)

if rates is None:
    print(f"Erreur : {mt5.last_error()}")
else:
    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    df = df.rename(columns={
        'time': 'timestamp',
        'open': 'open',
        'high': 'high',
        'low': 'low',
        'close': 'close',
        'tick_volume': 'volume'
    })
    print(df[['timestamp', 'open', 'high', 'low', 'close', 'volume']].tail(10))
    print(f"\nTotal bougies : {len(df)}")

mt5.shutdown()