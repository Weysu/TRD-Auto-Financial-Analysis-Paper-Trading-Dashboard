import sys
import os

# Ajoute le projet au path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from trd_auto.data.connectors.mt5_connector import MT5Connector

c = MT5Connector()

print("=== get_historical AAPL 1M ===")
df = c.get_historical('AAPL', '1M')
print(df.tail(5))
print(f'Bougies : {len(df)}')

print("\n=== get_quote AAPL ===")
quote = c.get_quote('AAPL')
print(quote)