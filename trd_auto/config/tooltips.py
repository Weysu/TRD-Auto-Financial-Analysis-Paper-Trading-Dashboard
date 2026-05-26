"""
Tooltip registry.
Keys must match exactly the labels used in the UI.
Add new entries here whenever a new indicator, metric, or bot is introduced.
"""

INDICATOR_TOOLTIPS: dict[str, str] = {
    "MA Crossover": (
        "Moving Average Crossover — Compares a fast SMA(20) with a slow SMA(50). "
        "A buy signal fires when the fast line crosses above the slow line, "
        "indicating an emerging uptrend. Sell when it crosses back below."
    ),
    "RSI": (
        "Relative Strength Index (14 periods) — Measures the speed and magnitude "
        "of recent price changes on a 0–100 scale. "
        "Below 30: oversold → buy signal. Above 70: overbought → sell signal. "
        "Calculated using Cutler's smoothing method."
    ),
    "Bollinger Bands": (
        "Bollinger Bands (20-period SMA ± 2 std dev) — Dynamic support/resistance levels. "
        "Price closing below the lower band signals a potential reversal upward (buy). "
        "Price closing above the upper band signals potential exhaustion (sell)."
    ),
    "MACD": (
        "MACD Crossover (12/26/9) — Measures momentum via the difference between "
        "two exponential moving averages. "
        "A buy signal fires when the MACD line crosses above the signal line. "
        "Sell when it crosses back below."
    ),
    "Confluence Score": (
        "Aggregates up to 4 strategy signals + sentiment into a single integer. "
        "Each strategy contributes 1 point when its position is active. "
        "Sentiment adds ±1. Maximum score: 5."
    ),
    "Sentiment": (
        "AI-scored news sentiment from the 5 latest headlines for this asset. "
        "Each headline is scored from −100 (very negative) to +100 (very positive) "
        "by Gemini Flash. The average is mapped to +1 / 0 / −1 and added to the confluence score."
    ),
    "SMA200 Filter": (
        "Trend regime filter — only allows buy signals when the last closing price "
        "is above the 200-period simple moving average. "
        "Prevents buying into assets in a structural downtrend."
    ),
}

METRIC_TOOLTIPS: dict[str, str] = {
    "Price": "Last closing price from the selected data source.",
    "Period Chg.": "Percentage change between the first and last close of the selected time range.",
    "High": "Highest closing price over the selected period.",
    "Low": "Lowest closing price over the selected period.",
    "Volatility": (
        "Annualised historical volatility — standard deviation of daily log returns "
        "scaled by √252. Higher values indicate larger price swings."
    ),
    "Equity": (
        "Mark-to-market portfolio value: cash + unrealized value of all open positions "
        "at current market prices."
    ),
    "Cash": "Uninvested capital available for new positions.",
    "Total Return": "Percentage gain or loss on the initial capital since bot inception.",
    "Open Positions": "Number of assets currently held by this bot.",
    "Total Return Backtest": (
        "Cumulative return of the strategy over the selected period, "
        "net of all simulated trades."
    ),
    "Buy & Hold": "Return of simply buying and holding the asset for the same period.",
    "Win Rate": "Percentage of closed trades that were profitable (PnL > 0).",
    "Max Drawdown": (
        "Largest peak-to-trough decline in the equity curve during the period. "
        "Expressed as a negative percentage."
    ),
    "Sharpe Ratio": (
        "Risk-adjusted return: annualised excess return divided by annualised volatility. "
        "Above 1.0 is generally considered acceptable; above 2.0 is strong."
    ),
    "Trades": "Total number of completed round-trip trades (entry + exit) in the backtest.",
}

BOT_TOOLTIPS: dict[str, str] = {
    "crypto_trend": (
        "Rides directional momentum on major crypto assets using MA crossover and MACD. "
        "Long timeframe, wide SL/TP to accommodate crypto volatility. Cycle: 4h."
    ),
    "crypto_reversion": (
        "Identifies oversold crypto conditions via RSI + Bollinger Bands. "
        "Sentiment-filtered — negative news blocks entry. Cycle: 4h."
    ),
    "equity_trend": (
        "Follows long-duration stock trends confirmed by SMA200. "
        "Only buys assets in a structural uptrend. Cycle: 6h."
    ),
    "equity_quality": (
        "High-conviction equity setups: 3 of 4 strategies aligned + SMA200 uptrend + sentiment check. "
        "Low trade frequency, higher quality. Cycle: 8h."
    ),
    "scanner": (
        "Scans the full asset universe every 6h. "
        "Requires all 4 strategies aligned + positive sentiment. Maximum selectivity."
    ),
    "breakout": (
        "Detects Bollinger Band breakouts confirmed by MACD momentum across all assets. "
        "Tightest SL/TP. Most frequent cycle at 2h."
    ),
}
