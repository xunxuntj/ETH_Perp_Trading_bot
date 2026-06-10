#!/usr/bin/env python3
"""
Control Verification Script: Empirical proof for channel-switching, 
cooldown limits, and parameter sweeps over 5-year history (2021-2026).
"""

import os
import sys
import pandas as pd
import numpy as np

# Ensure parent directory is in path to import components
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.engine import BacktestEngine
from backtest.sweep_dema_adx_filters import load_5y_data

RESULTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
os.makedirs(RESULTS_DIR, exist_ok=True)


def run_control_experiments():
    assets = {
        "BTC_USDT": {
            "tp_ratio": 22.0,
            "dema": 200,
            "adx_tf": "30m",
            "adx_thresh": 35.0
        },
        "ETH_USDT": {
            "tp_ratio": 5.0,
            "dema": 150,
            "adx_tf": "30m",
            "adx_thresh": 30.0
        }
    }
    
    initial_capital = 1000.0
    risk_amount = 10.0
    risk_mode = "fixed"
    
    summary = []
    
    for asset, opt in assets.items():
        df_30m, df_1h = load_5y_data(asset)
        if df_30m is None or df_1h is None:
            print(f"❌ Data not found for {asset}")
            continue
            
        print(f"\n=======================================================")
        print(f"🧪 RUNNING CONTROL EXPERIMENTS FOR {asset}")
        print(f"=======================================================")
        
        # ----------------------------------------------------
        # EXPERIMENT 1: Benefit of Channel-Switching (V2 phase logic)
        # ----------------------------------------------------
        # Baseline: Standard V2 Phase Logic (Survival -> Locked -> Hourly)
        engine_v2 = BacktestEngine(asset, initial_capital)
        res_v2 = engine_v2.run(
            df_30m, df_1h, risk_mode, risk_amount,
            lock_profit_buffer=0.5,
            adx_threshold=opt["adx_thresh"],
            adx_timeframe=opt["adx_tf"],
            dema_period=opt["dema"],
            tp_ratio=opt["tp_ratio"]
        )
        pnl_v2 = res_v2["metrics"]["total_pnl"]
        dd_v2 = res_v2["metrics"]["max_drawdown"]
        sharpe_v2 = res_v2["metrics"]["sharpe_ratio"]
        
        # Alternative A: Pure 30m SuperTrend Trailing (No switch to 1H)
        # We simulate this by setting lock_profit_buffer very high (e.g. 1000R), so it never transitions to Stage 3 Hourly
        engine_pure30m = BacktestEngine(asset, initial_capital)
        res_pure30m = engine_pure30m.run(
            df_30m, df_1h, risk_mode, risk_amount,
            lock_profit_buffer=1000.0,
            adx_threshold=opt["adx_thresh"],
            adx_timeframe=opt["adx_tf"],
            dema_period=opt["dema"],
            tp_ratio=opt["tp_ratio"]
        )
        pnl_pure30m = res_pure30m["metrics"]["total_pnl"]
        dd_pure30m = res_pure30m["metrics"]["max_drawdown"]
        sharpe_pure30m = res_pure30m["metrics"]["sharpe_ratio"]
        
        print(f"🔹 [Exp 1: Channel-Switching vs Pure 30m]")
        print(f"  - V2 3-Stage (30m -> Locked -> 1H): Net PnL: ${pnl_v2:+.2f} | MaxDD: {dd_v2*100:.2f}% | Sharpe: {sharpe_v2:.3f}")
        print(f"  - Pure 30m ST Trailing:            Net PnL: ${pnl_pure30m:+.2f} | MaxDD: {dd_pure30m*100:.2f}% | Sharpe: {sharpe_pure30m:.3f}")
        
        # ----------------------------------------------------
        # EXPERIMENT 2: Cooldown Mechanism Verification
        # ----------------------------------------------------
        # Baseline has max_losses = 3, cooldown = 48h.
        # Let's test with Cooldown Disabled. We simulate this by modifying engine config dynamically,
        # but in engine.py, MAX_CONSECUTIVE_LOSSES is imported from config.
        # We can temporarily patch config or pass a parameter if supported.
        # Wait, since MAX_CONSECUTIVE_LOSSES is imported as a module global in engine.py:
        # We can override it via engine module namespace.
        import backtest.engine
        
        # Cooldown Disabled
        backtest.engine.MAX_CONSECUTIVE_LOSSES = 9999  # Practically disabled
        engine_no_cd = BacktestEngine(asset, initial_capital)
        res_no_cd = engine_no_cd.run(
            df_30m, df_1h, risk_mode, risk_amount,
            lock_profit_buffer=0.5,
            adx_threshold=opt["adx_thresh"],
            adx_timeframe=opt["adx_tf"],
            dema_period=opt["dema"],
            tp_ratio=opt["tp_ratio"]
        )
        pnl_no_cd = res_no_cd["metrics"]["total_pnl"]
        dd_no_cd = res_no_cd["metrics"]["max_drawdown"]
        sharpe_no_cd = res_no_cd["metrics"]["sharpe_ratio"]
        
        print(f"🔹 [Exp 2: Cooldown (3 Losses/48h) vs No Cooldown]")
        print(f"  - With Cooldown (Baseline):   Net PnL: ${pnl_v2:+.2f} | MaxDD: {dd_v2*100:.2f}% | Sharpe: {sharpe_v2:.3f}")
        print(f"  - Without Cooldown:           Net PnL: ${pnl_no_cd:+.2f} | MaxDD: {dd_no_cd*100:.2f}% | Sharpe: {sharpe_no_cd:.3f}")
        
        # ----------------------------------------------------
        # EXPERIMENT 3: Cooldown Limit (2 vs 3 vs 4 vs 5 losses)
        # ----------------------------------------------------
        cd_limits = [2, 3, 4, 5]
        cd_results = []
        for limit in cd_limits:
            backtest.engine.MAX_CONSECUTIVE_LOSSES = limit
            engine_cd_lim = BacktestEngine(asset, initial_capital)
            res_cd_lim = engine_cd_lim.run(
                df_30m, df_1h, risk_mode, risk_amount,
                lock_profit_buffer=0.5,
                adx_threshold=opt["adx_thresh"],
                adx_timeframe=opt["adx_tf"],
                dema_period=opt["dema"],
                tp_ratio=opt["tp_ratio"]
            )
            cd_results.append({
                "Limit": limit,
                "PnL": res_cd_lim["metrics"]["total_pnl"],
                "MaxDD": res_cd_lim["metrics"]["max_drawdown"],
                "Sharpe": res_cd_lim["metrics"]["sharpe_ratio"]
            })
            
        print(f"🔹 [Exp 3: Consecutive Loss Limits]")
        for r in cd_results:
            print(f"  - Max Losses = {r['Limit']}: PnL: ${r['PnL']:+.2f} | MaxDD: {r['MaxDD']*100:.2f}% | Sharpe: {r['Sharpe']:.3f}")
            
        # Restore baseline
        backtest.engine.MAX_CONSECUTIVE_LOSSES = 3
        
        # ----------------------------------------------------
        # EXPERIMENT 4: Lock Profit Buffer Sweep (0.1R to 2.0R)
        # ----------------------------------------------------
        buffers = [0.1, 0.5, 1.0, 2.0, 5.0]
        buf_results = []
        for buf in buffers:
            engine_buf = BacktestEngine(asset, initial_capital)
            res_buf = engine_buf.run(
                df_30m, df_1h, risk_mode, risk_amount,
                lock_profit_buffer=buf,
                adx_threshold=opt["adx_thresh"],
                adx_timeframe=opt["adx_tf"],
                dema_period=opt["dema"],
                tp_ratio=opt["tp_ratio"]
            )
            buf_results.append({
                "Buffer": buf,
                "PnL": res_buf["metrics"]["total_pnl"],
                "MaxDD": res_buf["metrics"]["max_drawdown"],
                "Sharpe": res_buf["metrics"]["sharpe_ratio"]
            })
            
        print(f"🔹 [Exp 4: Lock Profit Buffer Sweep]")
        for r in buf_results:
            print(f"  - Buffer = {r['Buffer']} R: PnL: ${r['PnL']:+.2f} | MaxDD: {r['MaxDD']*100:.2f}% | Sharpe: {r['Sharpe']:.3f}")


if __name__ == "__main__":
    run_control_experiments()
