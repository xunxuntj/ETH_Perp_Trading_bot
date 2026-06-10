import os
import json
import pandas as pd

RESULTS_DIR = r"c:\Users\Jason Zhang\OneDrive\6Career\100KProject\CryptoTrading\ETH_Perp_Trading_Bot\ETH_Perp_Trading_bot\backtest\results"
filepath = os.path.join(RESULTS_DIR, "optimal_5y_portfolio.json")

if not os.path.exists(filepath):
    print("JSON file not found.")
    exit(1)

with open(filepath, "r") as f:
    data = json.load(f)

sweep = data.get("portfolio_risk_sweep", [])
df = pd.DataFrame(sweep)

print("=== TOP 15 CONFIGURATIONS BY CAGR (5-YEAR TIMEFRAME) ===")
df_cagr = df.sort_values(by="cagr_pct", ascending=False)
for idx, row in df_cagr.head(15).iterrows():
    print(f"Combination: {row['assets']:20s} | Risk: {row['risk_size_pct']:.2f}% | CAGR: {row['cagr_pct']:+7.2f}% | Max DD: {row['max_dd_pct']:5.2f}% | Sharpe: {row['sharpe']:.2f} | Final Equity: ${row['final_equity']:.2f}")

print("\n=== TOP 15 CONFIGURATIONS BY SHARPE RATIO ===")
df_sharpe = df.sort_values(by="sharpe", ascending=False)
for idx, row in df_sharpe.head(15).iterrows():
    print(f"Combination: {row['assets']:20s} | Risk: {row['risk_size_pct']:.2f}% | CAGR: {row['cagr_pct']:+7.2f}% | Max DD: {row['max_dd_pct']:5.2f}% | Sharpe: {row['sharpe']:.2f} | Final Equity: ${row['final_equity']:.2f}")

print("\n=== TOP 10 CONFIGURATIONS WITH DRAWDOWN < 40% (SORTED BY CAGR) ===")
df_dd_40 = df[df["max_dd_pct"] < 40.0].sort_values(by="cagr_pct", ascending=False)
for idx, row in df_dd_40.head(10).iterrows():
    print(f"Combination: {row['assets']:20s} | Risk: {row['risk_size_pct']:.2f}% | CAGR: {row['cagr_pct']:+7.2f}% | Max DD: {row['max_dd_pct']:5.2f}% | Sharpe: {row['sharpe']:.2f} | Final Equity: ${row['final_equity']:.2f}")
