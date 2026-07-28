#!/usr/bin/env python3
"""
Backtest Script for Mode A (Ultimate Compound Regime Model) on Recent 60-Day, 120-Day, and 240-Day Windows.
Calculates exact performance metrics under 0.15% friction costs.
"""

import os
import sys
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# Ensure parent directory is in path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from indicators import (
    calculate_supertrend, calculate_dema, calculate_adx,
    calculate_ema, calculate_atr, calculate_rsi
)
from backtest.regime_classifier import (
    calculate_kaufman_er, calculate_choppiness_index, calculate_atr_zscore
)

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


def load_data(contract: str) -> tuple:
    file_30m = os.path.join(DATA_DIR, f"{contract}_30m_5y.csv")
    file_1h = os.path.join(DATA_DIR, f"{contract}_1h_5y.csv")
    df_30m = pd.read_csv(file_30m)
    df_1h = pd.read_csv(file_1h)
    df_30m['timestamp'] = pd.to_datetime(df_30m['timestamp'], unit='s')
    df_1h['timestamp'] = pd.to_datetime(df_1h['timestamp'], unit='s')
    df_30m.set_index('timestamp', inplace=True)
    df_1h.set_index('timestamp', inplace=True)
    return df_30m, df_1h


def prepare_dataset(contract: str) -> pd.DataFrame:
    df_30m, df_1h = load_data(contract)
    df_30m = df_30m.copy()
    df_1h = df_1h.copy()

    df_4h = df_1h.resample('4h').agg({
        'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'
    }).dropna()

    df_1d = df_1h.resample('1D').agg({
        'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'
    }).dropna()

    df_1h['atr_z'] = calculate_atr_zscore(df_1h, 14, 100)
    df_4h['er'] = calculate_kaufman_er(df_4h, 10)
    df_4h['chop'] = calculate_choppiness_index(df_4h, 14)

    df_1d['ema_50'] = df_1d['close'].ewm(span=50, adjust=False).mean()
    df_1d['ema_200'] = df_1d['close'].ewm(span=200, adjust=False).mean()
    df_1d['macro_trend'] = np.where(df_1d['close'] > df_1d['ema_50'], 1,
                           np.where(df_1d['close'] < df_1d['ema_50'], -1, 0))

    df_1h_shift = df_1h[['atr_z', 'close', 'high', 'low']].copy()
    df_1h_shift.index = df_1h_shift.index + pd.Timedelta(hours=1)
    df_1h_shift = df_1h_shift.rename(columns={'close': 'h1_close', 'high': 'h1_high', 'low': 'h1_low'})

    df_4h_shift = df_4h[['er', 'chop']].copy()
    df_4h_shift.index = df_4h_shift.index + pd.Timedelta(hours=4)

    df_1d_shift = df_1d[['macro_trend']].copy()
    df_1d_shift.index = df_1d_shift.index + pd.Timedelta(days=1)

    st_res = calculate_supertrend(df_30m, 10, 3.0)
    df_30m['st_val'] = st_res['supertrend']
    df_30m['st_dir'] = st_res['direction']
    df_30m['atr_30m'] = calculate_atr(df_30m, 14)

    df_30m = df_30m.reset_index()
    df_1h_shift = df_1h_shift.reset_index()
    df_4h_shift = df_4h_shift.reset_index()
    df_1d_shift = df_1d_shift.reset_index()

    for d in [df_30m, df_1h_shift, df_4h_shift, df_1d_shift]:
        d['timestamp'] = d['timestamp'].astype('datetime64[ns]')

    df_merged = pd.merge_asof(df_30m, df_1h_shift, on='timestamp', direction='backward')
    df_merged = pd.merge_asof(df_merged, df_4h_shift, on='timestamp', direction='backward')
    df_merged = pd.merge_asof(df_merged, df_1d_shift, on='timestamp', direction='backward')

    df_merged.set_index('timestamp', inplace=True)
    return df_merged


def run_mode_a_simulation(datasets: dict, days_window: int, weights: dict, initial_capital: float = 700.0,
                           friction_rate: float = 0.0015, risk_percent: float = 0.012) -> dict:
    contracts = list(datasets.keys())
    face_values = {"BTC_USDT": 0.0001, "ETH_USDT": 0.01, "SOL_USDT": 1.0}
    slippages = {"BTC_USDT": 1.0, "ETH_USDT": 0.1, "SOL_USDT": 0.01}
    tp_ratios = {"BTC_USDT": 5.0, "ETH_USDT": 6.0, "SOL_USDT": 5.5}

    # Find common end timestamp and filter to recent days
    common_idx = None
    for c in contracts:
        if common_idx is None:
            common_idx = datasets[c].index
        else:
            common_idx = common_idx.intersection(datasets[c].index)
    common_idx = common_idx.sort_values()

    end_time = common_idx[-1]
    start_time = end_time - pd.Timedelta(days=days_window)
    window_idx = common_idx[common_idx >= start_time]

    sliced_datasets = {c: datasets[c].loc[window_idx] for c in contracts}
    n = len(window_idx)

    equity = initial_capital
    capital_history = []
    trades = []

    pos_states = {
        c: {
            "in_pos": False, "dir": None, "entry_price": 0.0, "sl": 0.0,
            "tp": None, "qty": 0, "entry_time": None
        } for c in contracts
    }

    timestamps = window_idx.to_pydatetime()

    for i in range(n):
        t_curr = timestamps[i]

        current_total_equity = equity
        for c in contracts:
            st = pos_states[c]
            if st["in_pos"]:
                curr_c = sliced_datasets[c]['close'].values[i]
                pnl = (curr_c - st["entry_price"]) * st["qty"] * face_values[c] if st["dir"] == "long" else (st["entry_price"] - curr_c) * st["qty"] * face_values[c]
                current_total_equity += pnl

        capital_history.append({"timestamp": t_curr, "equity": current_total_equity})

        for c in contracts:
            st = pos_states[c]
            df_c = sliced_datasets[c]

            high_p = df_c['high'].values[i]
            low_p = df_c['low'].values[i]
            close_p = df_c['close'].values[i]
            open_p = df_c['open'].values[i]

            st_val_30m = df_c['st_val'].values[i-1] if i > 0 else df_c['st_val'].values[i]
            st_dir_30m = df_c['st_dir'].values[i-1] if i > 0 else df_c['st_dir'].values[i]

            atr_z = df_c['atr_z'].values[i-1] if i > 0 else df_c['atr_z'].values[i]
            chop = df_c['chop'].values[i-1] if i > 0 else df_c['chop'].values[i]
            er = df_c['er'].values[i-1] if i > 0 else df_c['er'].values[i]
            macro_trend = df_c['macro_trend'].values[i-1] if i > 0 else df_c['macro_trend'].values[i]

            slip = slippages[c]
            fv = face_values[c]

            is_risk = (atr_z > 3.0)
            is_chop = (chop > 54.0 or er < 0.35)
            is_trend_long = (not is_risk and not is_chop and chop < 51.0 and er > 0.40 and macro_trend == 1)
            is_trend_short = (not is_risk and not is_chop and chop < 51.0 and er > 0.40 and macro_trend == -1)

            # EXITS
            if st["in_pos"]:
                is_stopped = False
                is_tp_hit = False
                exit_price = st["sl"]
                exit_reason = "stop_loss"

                if st["dir"] == "long":
                    if low_p <= st["sl"]:
                        is_stopped = True
                        exit_price = min(open_p, st["sl"])
                    elif st["tp"] is not None and high_p >= st["tp"]:
                        is_tp_hit = True
                        exit_price = max(open_p, st["tp"])
                        exit_reason = "take_profit"
                else:
                    if high_p >= st["sl"]:
                        is_stopped = True
                        exit_price = max(open_p, st["sl"])
                    elif st["tp"] is not None and low_p <= st["tp"]:
                        is_tp_hit = True
                        exit_price = min(open_p, st["tp"])
                        exit_reason = "take_profit"

                if is_stopped or is_tp_hit:
                    actual_exit = exit_price - slip if st["dir"] == "long" else exit_price + slip
                    raw_pnl = (actual_exit - st["entry_price"]) * st["qty"] * fv if st["dir"] == "long" else (st["entry_price"] - actual_exit) * st["qty"] * fv
                    notional = (st["entry_price"] + actual_exit) * st["qty"] * fv
                    friction_cost = notional * (friction_rate / 2.0)
                    net_pnl = raw_pnl - friction_cost

                    equity += net_pnl
                    trades.append({
                        "contract": c, "entry_time": st["entry_time"], "exit_time": t_curr,
                        "dir": st["dir"], "entry_price": st["entry_price"], "exit_price": actual_exit,
                        "pnl": net_pnl, "reason": exit_reason
                    })
                    st["in_pos"] = False
                    st["dir"] = None
                    st["tp"] = None
                    continue

                if st["dir"] == "long":
                    st["sl"] = max(st_val_30m, st["sl"])
                else:
                    st["sl"] = min(st_val_30m, st["sl"]) if st["sl"] > 0 else st_val_30m

            # ENTRIES
            if not st["in_pos"] and not is_risk and not is_chop:
                long_pullback = (is_trend_long and st_dir_30m == 1 and close_p >= st_val_30m)
                short_pullback = (is_trend_short and st_dir_30m == -1 and close_p <= st_val_30m)

                if long_pullback or short_pullback:
                    pos_dir = "long" if long_pullback else "short"
                    entry_p = open_p
                    st["dir"] = pos_dir
                    st["entry_price"] = entry_p
                    st["entry_time"] = t_curr
                    st["in_pos"] = True
                    st["sl"] = st_val_30m

                    asset_cap = current_total_equity * weights[c]
                    act_risk = asset_cap * risk_percent
                    sl_dist = abs(entry_p - st["sl"])

                    if sl_dist > 0:
                        qty = int(act_risk / (sl_dist * fv))
                        if qty <= 0: qty = 1
                        st["qty"] = qty
                        tp_dist = sl_dist * tp_ratios[c]
                        st["tp"] = entry_p + tp_dist if pos_dir == "long" else entry_p - tp_dist
                    else:
                        st["qty"] = 1
                        st["tp"] = None

    return {"capital": equity, "equity_curve": pd.DataFrame(capital_history), "trades": pd.DataFrame(trades)}


def compute_metrics(eq_df: pd.DataFrame, trades_df: pd.DataFrame, initial_capital: float = 700.0) -> dict:
    if eq_df.empty or len(eq_df) < 2:
        return {}

    eq_df = eq_df.set_index('timestamp')
    eq_df['returns'] = eq_df['equity'].pct_change().fillna(0)

    total_days = (eq_df.index[-1] - eq_df.index[0]).days
    total_years = max(total_days / 365.25, 0.01)

    end_equity = eq_df['equity'].iloc[-1]
    cagr = (end_equity / initial_capital) ** (1.0 / total_years) - 1.0 if end_equity > 0 else -1.0
    abs_return = (end_equity - initial_capital) / initial_capital

    eq_df['peak'] = eq_df['equity'].cummax()
    eq_df['dd'] = (eq_df['equity'] - eq_df['peak']) / eq_df['peak']
    max_dd = abs(eq_df['dd'].min())

    mean_ret = eq_df['returns'].mean() * 17520
    std_ret = eq_df['returns'].std() * np.sqrt(17520)
    sharpe = mean_ret / std_ret if std_ret > 0 else 0.0

    downside_returns = eq_df['returns'][eq_df['returns'] < 0]
    downside_std = downside_returns.std() * np.sqrt(17520)
    sortino = mean_ret / downside_std if downside_std > 0 else 0.0

    calmar = cagr / max_dd if max_dd > 0 else 0.0

    if not trades_df.empty and 'pnl' in trades_df.columns:
        num_trades = trades_df[pd.to_numeric(trades_df['pnl'], errors='coerce').notnull()].copy()
        num_trades['pnl'] = num_trades['pnl'].astype(float)
        
        total_trades = len(num_trades)
        win_trades = num_trades[num_trades['pnl'] > 0]
        loss_trades = num_trades[num_trades['pnl'] < 0]

        win_rate = len(win_trades) / total_trades if total_trades > 0 else 0.0
        gross_profit = win_trades['pnl'].sum()
        gross_loss = abs(loss_trades['pnl'].sum())

        profit_factor = gross_profit / gross_loss if gross_loss > 0 else 99.0
        recovery_factor = (end_equity - initial_capital) / (max_dd * initial_capital) if max_dd > 0 else 0.0

        avg_win = win_trades['pnl'].mean() if not win_trades.empty else 0.0
        avg_loss = abs(loss_trades['pnl'].mean()) if not loss_trades.empty else 1.0
        win_loss_ratio = avg_win / avg_loss if avg_loss > 0 else 0.0
    else:
        total_trades, win_rate, profit_factor, recovery_factor, win_loss_ratio = 0, 0.0, 0.0, 0.0, 0.0

    return {
        "CAGR": cagr, "AbsReturn": abs_return, "MaxDD": max_dd, "Sharpe": sharpe, "Sortino": sortino,
        "Calmar": calmar, "ProfitFactor": profit_factor, "RecoveryFactor": recovery_factor,
        "WinRate": win_rate, "WinLossRatio": win_loss_ratio, "TotalTrades": total_trades,
        "EndEquity": end_equity
    }


def main():
    contracts = ["BTC_USDT", "ETH_USDT", "SOL_USDT"]
    weights = {"BTC_USDT": 0.40, "ETH_USDT": 0.35, "SOL_USDT": 0.25}

    print("=" * 80)
    print("🚀 LOADING DATASET FOR MODE A RECENT WINDOWS BACKTEST...")
    print("=" * 80)

    datasets = {}
    for c in contracts:
        datasets[c] = prepare_dataset(c)

    windows = [60, 120, 240]
    results = {}

    for w in windows:
        print(f"\n⚡ Running Mode A Backtest on Past {w} Days...")
        sim_res = run_mode_a_simulation(datasets, days_window=w, weights=weights, initial_capital=700.0, friction_rate=0.0015, risk_percent=0.012)
        metrics = compute_metrics(sim_res["equity_curve"], sim_res["trades"], initial_capital=700.0)
        results[w] = metrics

    print("\n" + "=" * 80)
    print("📊 MODE A (ULTIMATE COMPOUND REGIME) RECENT WINDOWS BACKTEST SUMMARY")
    print("=" * 80)
    print(f"{'Metric':<25} | {'Past 60 Days':<18} | {'Past 120 Days':<18} | {'Past 240 Days':<18}")
    print("-" * 88)
    print(f"{'Initial Capital':<25} | {'700.00 USDT':<18} | {'700.00 USDT':<18} | {'700.00 USDT':<18}")
    print(f"{'Ending Capital':<25} | {results[60].get('EndEquity',0):.2f} USDT{'':<8} | {results[120].get('EndEquity',0):.2f} USDT{'':<8} | {results[240].get('EndEquity',0):.2f} USDT{'':<8}")
    print(f"{'Period Net Return':<25} | {results[60].get('AbsReturn',0)*100:+.2f}%{'':<11} | {results[120].get('AbsReturn',0)*100:+.2f}%{'':<11} | {results[240].get('AbsReturn',0)*100:+.2f}%{'':<11}")
    print(f"{'Annualized CAGR':<25} | {results[60].get('CAGR',0)*100:+.2f}%{'':<11} | {results[120].get('CAGR',0)*100:+.2f}%{'':<11} | {results[240].get('CAGR',0)*100:+.2f}%{'':<11}")
    print(f"{'Max Drawdown (Max DD)':<25} | {results[60].get('MaxDD',0)*100:.2f}%{'':<11} | {results[120].get('MaxDD',0)*100:.2f}%{'':<11} | {results[240].get('MaxDD',0)*100:.2f}%{'':<11}")
    print(f"{'Sharpe Ratio':<25} | {results[60].get('Sharpe',0):.2f}{'':<13} | {results[120].get('Sharpe',0):.2f}{'':<13} | {results[240].get('Sharpe',0):.2f}{'':<13}")
    print(f"{'Sortino Ratio':<25} | {results[60].get('Sortino',0):.2f}{'':<13} | {results[120].get('Sortino',0):.2f}{'':<13} | {results[240].get('Sortino',0):.2f}{'':<13}")
    print(f"{'Win Rate':<25} | {results[60].get('WinRate',0)*100:.2f}%{'':<11} | {results[120].get('WinRate',0)*100:.2f}%{'':<11} | {results[240].get('WinRate',0)*100:.2f}%{'':<11}")
    print(f"{'Avg Win/Loss Ratio':<25} | {results[60].get('WinLossRatio',0):.2f}{'':<13} | {results[120].get('WinLossRatio',0):.2f}{'':<13} | {results[240].get('WinLossRatio',0):.2f}{'':<13}")
    print(f"{'Total Trades':<25} | {results[60].get('TotalTrades',0)}{'':<14} | {results[120].get('TotalTrades',0)}{'':<14} | {results[240].get('TotalTrades',0)}{'':<14}")


if __name__ == "__main__":
    main()
