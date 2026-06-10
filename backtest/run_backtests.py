#!/usr/bin/env python3
"""
Coordinating Runner Script for multi-symbol backtesting and parameter sweeps.
"""

import os
import sys
import argparse
import pandas as pd
try:
    from tabulate import tabulate
except ImportError:
    tabulate = None  # if missing, we fall back to manual formatting

# Ensure parent directory is in path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import BacktestEngine

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
RESULTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")


def load_data(contract: str, days: int = None) -> tuple:
    """Loads 30m and 1h datasets for a contract."""
    file_30m = os.path.join(DATA_DIR, f"{contract}_30m.csv")
    file_1h = os.path.join(DATA_DIR, f"{contract}_1h.csv")
    
    if not os.path.exists(file_30m) or not os.path.exists(file_1h):
        return None, None
        
    df_30m = pd.read_csv(file_30m)
    df_1h = pd.read_csv(file_1h)
    
    # Convert timestamps
    df_30m['timestamp'] = pd.to_datetime(df_30m['timestamp'], unit='s')
    df_1h['timestamp'] = pd.to_datetime(df_1h['timestamp'], unit='s')
    
    df_30m.set_index('timestamp', inplace=True)
    df_1h.set_index('timestamp', inplace=True)
    
    if days is not None:
        cutoff = df_30m.index.max() - pd.Timedelta(days=days)
        warmup_cutoff = cutoff - pd.Timedelta(days=30)
        df_30m = df_30m[df_30m.index >= warmup_cutoff]
        df_1h = df_1h[df_1h.index >= warmup_cutoff]
        
    return df_30m, df_1h


def run_standard_backtests(args):
    """Runs standard backtest runs for BTC, ETH, SOL."""
    os.makedirs(RESULTS_DIR, exist_ok=True)
    
    contracts = [args.contract] if args.contract else ["BTC_USDT", "ETH_USDT", "SOL_USDT"]
    results = []
    
    for contract in contracts:
        df_30m, df_1h = load_data(contract, days=args.days)
        if df_30m is None or df_1h is None:
            print(f"Skipping {contract} - data not found. Run downloader first.")
            continue
            
        engine = BacktestEngine(
            contract=contract,
            initial_capital=args.capital,
            fee_rate=args.fee,
            slippage_ticks=args.slippage
        )
        
        # Run simulation
        res = engine.run(
            df_30m=df_30m,
            df_1h=df_1h,
            risk_mode=args.risk_mode,
            risk_amount=args.risk_amount,
            risk_percent=args.risk_percent,
            lock_profit_buffer=args.buffer,
            adx_threshold=args.adx_threshold,
            adx_length=args.adx_length,
            adx_timeframe=args.adx_timeframe,
            dema_period=args.dema_period,
            tp_ratio=args.tp_ratio
        )
        
        metrics = res["metrics"]
        trades = res["trades"]
        
        # Save detailed trade log
        trades_df = pd.DataFrame(trades)
        if not trades_df.empty:
            trades_filepath = os.path.join(RESULTS_DIR, f"{contract}_trades.csv")
            trades_df.to_csv(trades_filepath, index=False)
            
        results.append({
            "Contract": contract,
            "Trades": metrics["total_trades"],
            "Win Rate (%)": f"{metrics['win_rate']*100:.1f}%",
            "Net Profit (U)": f"{metrics['total_pnl']:+.2f}",
            "Ann. Return (%)": f"{metrics['annualized_return']*100:+.1f}%",
            "Profit Factor": f"{metrics['profit_factor']:.2f}" if metrics['profit_factor'] is not None else "N/A",
            "Max DD (%)": f"{metrics['max_drawdown']*100:.1f}%",
            "Sharpe": f"{metrics['sharpe_ratio']:.2f}",
            "Final Equity (U)": f"{metrics['final_equity']:.2f}"
        })
        
    # Print results
    print("\n" + "=" * 80)
    print(f"📡 V9.7 STRATEGY BASELINE BACKTEST SUMMARY ({args.risk_mode.upper()} RISK)")
    print("=" * 80)
    
    df_results = pd.DataFrame(results)
    if tabulate is not None:
        print(tabulate(df_results, headers='keys', tablefmt='github', showindex=False))
    else:
        print(df_results.to_string(index=False))
        
    print("\nDetailed trade logs saved to backtest/results/ directory.")


def run_parameter_sweeps(args):
    """Runs parameter sweeps over variables to optimize the strategy."""
    contracts = [args.contract] if args.contract else ["BTC_USDT", "ETH_USDT", "SOL_USDT"]
    
    # Define sweep values
    buffers = [0.5, 1.0, 1.5, 2.0, 5.0, 10.0, 15.0]
    
    for contract in contracts:
        df_30m, df_1h = load_data(contract, days=args.days)
        if df_30m is None or df_1h is None:
            print(f"Skipping parameter sweep for {contract} - data not found.")
            continue
            
        print(f"\nRunning LOCK_PROFIT_BUFFER parameter sweep for {contract}...")
        sweep_results = []
        
        for buf in buffers:
            engine = BacktestEngine(
                contract=contract,
                initial_capital=args.capital,
                fee_rate=args.fee,
                slippage_ticks=args.slippage
            )
            
            res = engine.run(
                df_30m=df_30m,
                df_1h=df_1h,
                risk_mode=args.risk_mode,
                risk_amount=args.risk_amount,
                risk_percent=args.risk_percent,
                lock_profit_buffer=buf,
                adx_threshold=args.adx_threshold,
                adx_length=args.adx_length,
                adx_timeframe=args.adx_timeframe,
                dema_period=args.dema_period,
                tp_ratio=args.tp_ratio
            )
            
            metrics = res["metrics"]
            sweep_results.append({
                "Buffer (R)": buf,
                "Trades": metrics["total_trades"],
                "Win Rate (%)": f"{metrics['win_rate']*100:.1f}%",
                "Net Profit (U)": f"{metrics['total_pnl']:+.2f}",
                "Ann. Return (%)": f"{metrics['annualized_return']*100:+.1f}%",
                "Profit Factor": f"{metrics['profit_factor']:.2f}" if metrics['profit_factor'] is not None else "N/A",
                "Max DD (%)": f"{metrics['max_drawdown']*100:.1f}%",
                "Sharpe": f"{metrics['sharpe_ratio']:.2f}"
            })
            
        df_sweep = pd.DataFrame(sweep_results)
        print(f"\n--- {contract} Sweep Summary ---")
        if tabulate is not None:
            print(tabulate(df_sweep, headers='keys', tablefmt='github', showindex=False))
        else:
            print(df_sweep.to_string(index=False))


def run_adx_sweeps(args):
    """Runs parameter sweeps over ADX thresholds to optimize the strategy."""
    contracts = [args.contract] if args.contract else ["BTC_USDT", "ETH_USDT", "SOL_USDT"]
    adx_thresholds = [15.0, 20.0, 25.0, 30.0, 35.0]
    
    for contract in contracts:
        df_30m, df_1h = load_data(contract, days=args.days)
        if df_30m is None or df_1h is None:
            print(f"Skipping ADX sweep for {contract} - data not found.")
            continue
            
        print(f"\nRunning ADX_THRESHOLD parameter sweep for {contract} (Buffer = {args.buffer})...")
        sweep_results = []
        
        for adx in adx_thresholds:
            engine = BacktestEngine(
                contract=contract,
                initial_capital=args.capital,
                fee_rate=args.fee,
                slippage_ticks=args.slippage
            )
            
            res = engine.run(
                df_30m=df_30m,
                df_1h=df_1h,
                risk_mode=args.risk_mode,
                risk_amount=args.risk_amount,
                risk_percent=args.risk_percent,
                lock_profit_buffer=args.buffer,
                adx_threshold=adx,
                adx_length=args.adx_length,
                adx_timeframe=args.adx_timeframe,
                dema_period=args.dema_period,
                tp_ratio=args.tp_ratio
            )
            
            metrics = res["metrics"]
            sweep_results.append({
                "ADX Thresh": adx,
                "Trades": metrics["total_trades"],
                "Win Rate (%)": f"{metrics['win_rate']*100:.1f}%",
                "Net Profit (U)": f"{metrics['total_pnl']:+.2f}",
                "Ann. Return (%)": f"{metrics['annualized_return']*100:+.1f}%",
                "Profit Factor": f"{metrics['profit_factor']:.2f}" if metrics['profit_factor'] is not None else "N/A",
                "Max DD (%)": f"{metrics['max_drawdown']*100:.1f}%",
                "Sharpe": f"{metrics['sharpe_ratio']:.2f}"
            })
            
        df_sweep = pd.DataFrame(sweep_results)
        print(f"\n--- {contract} ADX Sweep Summary ---")
        if tabulate is not None:
            print(tabulate(df_sweep, headers='keys', tablefmt='github', showindex=False))
        else:
            print(df_sweep.to_string(index=False))


def run_grid_sweeps(args):
    """Runs a joint grid sweep of LOCK_PROFIT_BUFFER and ADX_THRESHOLD."""
    contracts = [args.contract] if args.contract else ["BTC_USDT", "ETH_USDT", "SOL_USDT"]
    buffers = [0.5, 1.0, 1.5, 2.0]
    adx_thresholds = [15.0, 20.0, 25.0, 30.0, 35.0]
    
    for contract in contracts:
        df_30m, df_1h = load_data(contract, days=args.days)
        if df_30m is None or df_1h is None:
            print(f"Skipping grid sweep for {contract} - data not found.")
            continue
            
        print(f"\nRunning Joint Grid Sweep (Buffer x ADX) for {contract}...")
        grid_results = []
        
        for buf in buffers:
            for adx in adx_thresholds:
                engine = BacktestEngine(
                    contract=contract,
                    initial_capital=args.capital,
                    fee_rate=args.fee,
                    slippage_ticks=args.slippage
                )
                
                res = engine.run(
                    df_30m=df_30m,
                    df_1h=df_1h,
                    risk_mode=args.risk_mode,
                    risk_amount=args.risk_amount,
                    risk_percent=args.risk_percent,
                    lock_profit_buffer=buf,
                    adx_threshold=adx,
                    adx_length=args.adx_length,
                    adx_timeframe=args.adx_timeframe,
                    dema_period=args.dema_period,
                    tp_ratio=args.tp_ratio
                )
                
                metrics = res["metrics"]
                grid_results.append({
                    "Buffer (R)": buf,
                    "ADX Thresh": adx,
                    "Trades": metrics["total_trades"],
                    "Win Rate (%)": f"{metrics['win_rate']*100:.1f}%",
                    "Net Profit (U)": f"{metrics['total_pnl']:+.2f}",
                    "Ann. Return (%)": f"{metrics['annualized_return']*100:+.1f}%",
                    "Profit Factor": f"{metrics['profit_factor']:.2f}" if metrics['profit_factor'] is not None else "N/A",
                    "Max DD (%)": f"{metrics['max_drawdown']*100:.1f}%",
                    "Sharpe": f"{metrics['sharpe_ratio']:.2f}"
                })
                
        df_grid = pd.DataFrame(grid_results)
        df_grid['Net Profit Float'] = df_grid['Net Profit (U)'].astype(float)
        df_grid = df_grid.sort_values('Net Profit Float', ascending=False).drop(columns=['Net Profit Float']).reset_index(drop=True)
        
        print(f"\n--- {contract} Joint Grid Sweep Summary (Top Results) ---")
        if tabulate is not None:
            print(tabulate(df_grid.head(10), headers='keys', tablefmt='github', showindex=False))
        else:
            print(df_grid.head(10).to_string(index=False))


def run_dema_sweeps(args):
    """Runs parameter sweeps over DEMA periods to optimize the strategy."""
    contracts = [args.contract] if args.contract else ["BTC_USDT", "ETH_USDT", "SOL_USDT"]
    dema_periods = [100, 150, 200, 250]
    
    for contract in contracts:
        df_30m, df_1h = load_data(contract, days=args.days)
        if df_30m is None or df_1h is None:
            print(f"Skipping DEMA sweep for {contract} - data not found.")
            continue
            
        print(f"\nRunning DEMA_PERIOD parameter sweep for {contract} (Buffer = {args.buffer}, ADX Threshold = {args.adx_threshold})...")
        sweep_results = []
        
        for dema in dema_periods:
            engine = BacktestEngine(
                contract=contract,
                initial_capital=args.capital,
                fee_rate=args.fee,
                slippage_ticks=args.slippage
            )
            
            res = engine.run(
                df_30m=df_30m,
                df_1h=df_1h,
                risk_mode=args.risk_mode,
                risk_amount=args.risk_amount,
                risk_percent=args.risk_percent,
                lock_profit_buffer=args.buffer,
                adx_threshold=args.adx_threshold,
                adx_length=args.adx_length,
                adx_timeframe=args.adx_timeframe,
                dema_period=dema,
                tp_ratio=args.tp_ratio
            )
            
            metrics = res["metrics"]
            sweep_results.append({
                "DEMA Period": dema,
                "Trades": metrics["total_trades"],
                "Win Rate (%)": f"{metrics['win_rate']*100:.1f}%",
                "Net Profit (U)": f"{metrics['total_pnl']:+.2f}",
                "Ann. Return (%)": f"{metrics['annualized_return']*100:+.1f}%",
                "Profit Factor": f"{metrics['profit_factor']:.2f}" if metrics['profit_factor'] is not None else "N/A",
                "Max DD (%)": f"{metrics['max_drawdown']*100:.1f}%",
                "Sharpe": f"{metrics['sharpe_ratio']:.2f}"
            })
            
        df_sweep = pd.DataFrame(sweep_results)
        print(f"\n--- {contract} DEMA Sweep Summary ---")
        if tabulate is not None:
            print(tabulate(df_sweep, headers='keys', tablefmt='github', showindex=False))
        else:
            print(df_sweep.to_string(index=False))


def run_tp_sweeps(args):
    """Runs parameter sweeps over Take Profit ratios to optimize the strategy."""
    contracts = [args.contract] if args.contract else ["BTC_USDT", "ETH_USDT", "SOL_USDT"]
    tp_ratios = [None, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
    
    for contract in contracts:
        df_30m, df_1h = load_data(contract, days=args.days)
        if df_30m is None or df_1h is None:
            print(f"Skipping TP sweep for {contract} - data not found.")
            continue
            
        print(f"\nRunning TAKE_PROFIT_RATIO parameter sweep for {contract} (Buffer = {args.buffer}, ADX Threshold = {args.adx_threshold}, DEMA Period = {args.dema_period})...")
        sweep_results = []
        
        for tp in tp_ratios:
            engine = BacktestEngine(
                contract=contract,
                initial_capital=args.capital,
                fee_rate=args.fee,
                slippage_ticks=args.slippage
            )
            
            res = engine.run(
                df_30m=df_30m,
                df_1h=df_1h,
                risk_mode=args.risk_mode,
                risk_amount=args.risk_amount,
                risk_percent=args.risk_percent,
                lock_profit_buffer=args.buffer,
                adx_threshold=args.adx_threshold,
                adx_length=args.adx_length,
                adx_timeframe=args.adx_timeframe,
                dema_period=args.dema_period,
                tp_ratio=tp
            )
            
            metrics = res["metrics"]
            sweep_results.append({
                "TP Ratio (R)": "No TP" if tp is None else f"{tp:.1f} R",
                "Trades": metrics["total_trades"],
                "Win Rate (%)": f"{metrics['win_rate']*100:.1f}%",
                "Net Profit (U)": f"{metrics['total_pnl']:+.2f}",
                "Ann. Return (%)": f"{metrics['annualized_return']*100:+.1f}%",
                "Profit Factor": f"{metrics['profit_factor']:.2f}" if metrics['profit_factor'] is not None else "N/A",
                "Max DD (%)": f"{metrics['max_drawdown']*100:.1f}%",
                "Sharpe": f"{metrics['sharpe_ratio']:.2f}"
            })
            
        df_sweep = pd.DataFrame(sweep_results)
        print(f"\n--- {contract} TP Sweep Summary ---")
        if tabulate is not None:
            print(tabulate(df_sweep, headers='keys', tablefmt='github', showindex=False))
        else:
            print(df_sweep.to_string(index=False))


def main():
    parser = argparse.ArgumentParser(description="V9.7 Backtester & Sweep Optimizer")
    parser.add_argument("--capital", type=float, default=1000.0, help="Initial capital in USDT")
    parser.add_argument("--contract", type=str, default=None, choices=["BTC_USDT", "ETH_USDT", "SOL_USDT"], help="Specific contract to run (BTC_USDT, ETH_USDT, SOL_USDT)")
    parser.add_argument("--fee", type=float, default=0.0004, help="One-way fee rate (default: 0.04%%)")
    parser.add_argument("--slippage", type=float, default=1.0, help="Friction slippage in ticks")
    parser.add_argument("--risk-mode", type=str, default="fixed", choices=["fixed", "percent"], help="Risk sizing mode")
    parser.add_argument("--risk-amount", type=float, default=10.0, help="Fixed risk amount in USDT")
    parser.add_argument("--risk-percent", type=float, default=0.02, help="Percentage risk of equity (2%% = 0.02)")
    parser.add_argument("--buffer", type=float, default=1.0, help="Baseline profit lock buffer multiplier (R value)")
    parser.add_argument("--days", type=int, default=None, help="Number of recent days to run backtest over")
    parser.add_argument("--adx-length", type=int, default=None, help="Custom ADX calculation length (e.g. 14)")
    parser.add_argument("--adx-threshold", type=float, default=None, help="Custom ADX threshold (e.g. 25.0 or 35.0)")
    parser.add_argument("--adx-timeframe", type=str, default=None, choices=["30m", "1h"], help="Custom ADX timeframe (e.g. '1h' or '30m')")
    parser.add_argument("--dema-period", type=int, default=None, help="Custom DEMA calculation period (e.g. 200)")
    parser.add_argument("--tp-ratio", type=float, default=None, help="Custom Take Profit ratio in R units (e.g. 2.0)")
    parser.add_argument("--sweep", action="store_true", help="Run profit buffer parameter sweeps")
    parser.add_argument("--adx-sweep", action="store_true", help="Run ADX threshold parameter sweeps")
    parser.add_argument("--dema-sweep", action="store_true", help="Run DEMA period parameter sweeps")
    parser.add_argument("--tp-sweep", action="store_true", help="Run Take Profit ratio parameter sweeps")
    parser.add_argument("--grid-sweep", action="store_true", help="Run joint buffer and ADX threshold grid sweeps")
    
    args = parser.parse_args()
    
    if args.grid_sweep:
        run_grid_sweeps(args)
    elif args.adx_sweep:
        run_adx_sweeps(args)
    elif args.dema_sweep:
        run_dema_sweeps(args)
    elif args.tp_sweep:
        run_tp_sweeps(args)
    elif args.sweep:
        run_parameter_sweeps(args)
    else:
        run_standard_backtests(args)


if __name__ == "__main__":
    main()
