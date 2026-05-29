import MetaTrader5 as mt5

# Connexion à MT5 (MT5 doit être ouvert)
if not mt5.initialize():
    print("Erreur connexion MT5")
    quit()

print(f"MT5 version : {mt5.version()}")
print(f"Compte : {mt5.account_info()}")

mt5.shutdown()