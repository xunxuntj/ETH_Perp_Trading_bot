#!/usr/bin/env python3
"""
Parameter Sweep Optimizer for DEMA Period, ADX Timeframe, and ADX Threshold
Over a 5-Year History (2021-2026) for BTC and ETH.
"""

import os
import sys
import pandas as pd
import numpy as np

# Ensure parent directory is in path to import backtest components
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.engine import BacktestEngine

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
RESULTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
os.makedirs(RESULTS_DIR, exist_ok=True)


def load_5y_data(contract: str) -> tuple:
    """Loads 5-year K-line data for 30m and 1h."""
    file_30m = os.path.join(DATA_DIR, f"{contract}_30m_5y.csv")
    file_1h = os.path.join(DATA_DIR, f"{contract}_1h_5y.csv")
    if not os.path.exists(file_30m) or not os.path.exists(file_1h):
        return None, None
    
    df_30m = pd.read_csv(file_30m)
    df_1h = pd.read_csv(file_1h)
    
    df_30m['timestamp'] = pd.to_datetime(df_30m['timestamp'], unit='s')
    df_1h['timestamp'] = pd.to_datetime(df_1h['timestamp'], unit='s')
    
    df_30m.set_index('timestamp', inplace=True)
    df_1h.set_index('timestamp', inplace=True)
    
    return df_30m, df_1h


def run_sweep():
    # Define parameters to sweep
    assets = {
        "BTC_USDT": {"tp_ratio": 22.0},
        "ETH_USDT": {"tp_ratio": 5.0}
    }
    
    dema_periods = [100, 150, 200, 250]
    adx_timeframes = ["30m", "1h"]
    adx_thresholds = [0.0, 15.0, 20.0, 25.0, 30.0, 35.0, 40.0]  # 0.0 represents no ADX filter
    
    initial_capital = 1000.0
    risk_amount = 10.0
    risk_mode = "fixed"
    
    for asset, params in assets.items():
        print(f"\n======================================================================")
        print(f"📊 STARTING GRID SWEEP FOR {asset} (TP = {params['tp_ratio']}R)")
        print(f"======================================================================")
        
        df_30m, df_1h = load_5y_data(asset)
        if df_30m is None or df_1h is None:
            print(f"❌ Data not found for {asset}. Please check backtest/data/ directory.")
            continue
            
        results = []
        
        # Total runs = 4 * 2 * 7 = 56 runs per asset
        total_combinations = len(dema_periods) * len(adx_timeframes) * len(adx_thresholds)
        completed = 0
        
        for dema in dema_periods:
            for adx_tf in adx_timeframes:
                for adx_thresh in adx_thresholds:
                    engine = BacktestEngine(
                        contract=asset,
                        initial_capital=initial_capital,
                        fee_rate=0.0004,
                        slippage_ticks=1.0
                    )
                    
                    # Run simulation
                    res = engine.run(
                        df_30m=df_30m,
                        df_1h=df_1h,
                        risk_mode=risk_mode,
                        risk_amount=risk_amount,
                        lock_profit_buffer=0.5,  # Align with new production defaults
                        adx_threshold=adx_thresh,
                        adx_length=16,           # Matches config default
                        adx_timeframe=adx_tf,
                        dema_period=dema,
                        tp_ratio=params["tp_ratio"]
                    )
                    
                    metrics = res["metrics"]
                    
                    results.append({
                        "DEMA": dema,
                        "ADX_TF": adx_tf,
                        "ADX_Thresh": "None" if adx_thresh == 0.0 else adx_thresh,
                        "Trades": metrics["total_trades"],
                        "WinRate": f"{metrics['win_rate']*100:.2f}%",
                        "NetProfit": metrics["total_pnl"],
                        "AnnReturn": f"{metrics['annualized_return']*100:+.2f}%",
                        "ProfitFactor": metrics["profit_factor"],
                        "MaxDD": f"{metrics['max_drawdown']*100:.2f}%",
                        "Sharpe": metrics["sharpe_ratio"],
                        "FinalEquity": metrics["final_equity"]
                    })
                    
                    completed += 1
                    if completed % 10 == 0 or completed == total_combinations:
                        print(f"Progress: {completed}/{total_combinations} runs finished...")
        
        # Sort and print results
        df_results = pd.DataFrame(results)
        df_results = df_results.sort_values(by="NetProfit", ascending=False).reset_index(drop=True)
        
        # Save to CSV
        output_file = os.path.join(RESULTS_DIR, f"sweep_dema_adx_{asset.lower()}.csv")
        df_results.to_csv(output_file, index=False)
        print(f"✅ Results saved to {output_file}")
        
        # Display Top 15 results
        print(f"\n🏆 TOP 15 CONFIGURATIONS FOR {asset} (Sorted by Net Profit):")
        print(df_results.head(15).to_markdown(index=False))
        
        # Display Bottom 5 results to show the impact of poor configs
        print(f"\n📉 BOTTOM 5 CONFIGURATIONS FOR {asset}:")
        print(df_results.tail(5).to_markdown(index=False))


if __name__ == "__main__":
    run_sweep()
