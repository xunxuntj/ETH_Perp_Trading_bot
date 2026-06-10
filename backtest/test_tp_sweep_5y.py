#!/usr/bin/env python3
"""
Take Profit (TP) Ratio Sweep (5-Year):
Sweeps TP ratios in [3.0, 4.0, 5.0, 6.0, 8.0, 10.0, 12.0] for BTC and ETH
using SuperTrend Breakout Strategy with 2.0% risk sizing.
"""

import os
import sys
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# Ensure parent directory is in path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from indicators import (
    calculate_supertrend, calculate_ema, calculate_dema, calculate_atr, calculate_rsi, calculate_adx
)

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

def load_data(contract: str) -> tuple:
    """Loads 5-year K-line data."""
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


class TPSweepSimulator:
    def __init__(self, fee_rate: float = 0.0004):
        self.fee_rate = fee_rate
        
    def get_contract_params(self, contract: str) -> tuple:
        c_upper = contract.upper()
        if "ETH" in c_upper:
            face_value = 0.01
            slippage = 0.1
        elif "BTC" in c_upper:
            face_value = 0.0001
            slippage = 1.0
        else:
            face_value = 1.0
            slippage = 0.01
        return face_value, slippage

    def run_single_asset(self, df: pd.DataFrame, contract: str, tp_ratio: float, risk_percent: float) -> dict:
        n = len(df)
        times = df.index.to_pydatetime()
        
        high = df['high'].values
        low = df['low'].values
        close = df['close'].values
        open_v = df['open'].values
        st_val = df['st_val'].values
        st_dir = df['st_dir'].values
        h1_st_val = df['h1_st_val'].values
        h1_st_dir = df['h1_st_dir'].values
        h1_close = df['h1_close'].values
        adx = df['adx_aligned'].values
        atr = df['atr_val'].values
        h1_ma = df['h1_ema_200'].values
        
        face_value, slippage = self.get_contract_params(contract)
        
        initial_capital = 1000.0
        equity = initial_capital
        capital_history = []
        trades = []
        
        in_pos = False
        pos_dir = None
        entry_price = 0.0
        sl = 0.0
        tp = None
        phase = 0
        qty = 0
        consecutive_losses = 0
        cooldown_until = None
        entry_time = None
        
        cb_until = None
        
        for i in range(1000, n):
            t_curr = times[i]
            
            if cb_until and t_curr >= cb_until:
                cb_until = None
                
            current_equity = equity
            if cooldown_until and t_curr >= cooldown_until:
                consecutive_losses = 0
                cooldown_until = None
                
            if in_pos:
                pnl = (close[i] - entry_price) * qty * face_value if pos_dir == "long" else (entry_price - close[i]) * qty * face_value
                current_equity += pnl
                    
            capital_history.append((t_curr, current_equity))
            closed_this_bar = False
            
            # 1. EVALUATE EXITS
            if in_pos:
                is_stopped = False
                is_tp_hit = False
                exit_price = sl
                exit_reason = "stop_loss"
                
                if pos_dir == "long":
                    if low[i] <= sl:
                        is_stopped = True
                        exit_price = min(open_v[i], sl)
                    if tp is not None and high[i] >= tp:
                        is_tp_hit = True
                        if not is_stopped:
                            exit_price = max(open_v[i], tp)
                            exit_reason = "take_profit"
                else: # short
                    if high[i] >= sl:
                        is_stopped = True
                        exit_price = max(open_v[i], sl)
                    if tp is not None and low[i] <= tp:
                        is_tp_hit = True
                        if not is_stopped:
                            exit_price = min(open_v[i], tp)
                            exit_reason = "take_profit"
                            
                if is_stopped or (is_tp_hit and exit_reason == "take_profit"):
                    actual_exit = exit_price - slippage if pos_dir == "long" else exit_price + slippage
                    pnl = (actual_exit - entry_price) * qty * face_value if pos_dir == "long" else (entry_price - actual_exit) * qty * face_value
                    fee = (entry_price + actual_exit) * qty * face_value * self.fee_rate
                    net_pnl = pnl - fee
                    
                    equity += net_pnl
                    if net_pnl < 0:
                        consecutive_losses += 1
                        if consecutive_losses >= 3:
                            cooldown_until = t_curr + timedelta(hours=48)
                    else:
                        consecutive_losses = 0
                    if equity <= 350.0:
                        cb_until = t_curr + timedelta(days=7)
                        
                    trades.append({"Net PnL": net_pnl, "Fee": fee})
                    in_pos = False
                    pos_dir = None
                    tp = None
                    closed_this_bar = True
                else:
                    # Trailing stop logic
                    is_long = (pos_dir == "long")
                    act_risk = current_equity * risk_percent
                    if 350.0 <= current_equity <= 500.0:
                        act_risk = 10.0
                    buf_u = act_risk * 1.0
                    locked_price = entry_price + (buf_u / (qty * face_value)) if is_long else entry_price - (buf_u / (qty * face_value))
                    st_30 = st_val[i-1]
                    st_1h = h1_st_val[i-1]
                    
                    is_surv = st_30 < entry_price if is_long else st_30 > entry_price
                    if is_surv:
                        phase = 1
                        sl = max(st_30, sl) if is_long else min(st_30, sl)
                    else:
                        is_hr = st_1h > locked_price if is_long else st_1h < locked_price
                        if is_hr:
                            phase = 3
                            sl = max(st_1h, sl) if is_long else min(st_1h, sl)
                        else:
                            phase = 2
                            cand = st_30
                            if is_long:
                                if st_30 > locked_price: cand = locked_price
                                sl = max(cand, sl)
                            else:
                                if st_30 < locked_price: cand = locked_price
                                sl = min(cand, sl)

            # 2. EVALUATE ENTRIES
            if not in_pos and not closed_this_bar and not cb_until and not cooldown_until:
                h1_c = h1_close[i-1]
                ma_v = h1_ma[i-1]
                
                trend_ok_long = (h1_c > ma_v)
                trend_ok_short = (h1_c < ma_v)
                adx_ok = (adx[i-1] > 25.0)
                
                entry_long = (st_dir[i-1] == 1)
                entry_short = (st_dir[i-1] == -1)
                
                if entry_long and trend_ok_long and adx_ok:
                    pos_dir = "long"
                elif entry_short and trend_ok_short and adx_ok:
                    pos_dir = "short"
                    
                if pos_dir is not None:
                    entry_price = opens[c][i] if 'opens' in locals() else open_v[i]
                    entry_time = t_curr
                    in_pos = True
                    phase = 1
                    sl = st_val[i-1]
                    
                    act_risk = current_equity * risk_percent
                    if 350.0 <= current_equity <= 500.0:
                        act_risk = 10.0
                    sl_d = abs(entry_price - sl)
                    if sl_d > 0:
                        qty = int(min(act_risk / (sl_d * face_value), (current_equity * 5.0) / (entry_price * face_value)))
                        if qty <= 0: qty = 1
                        if tp_ratio is not None:
                            tp = entry_price + tp_ratio * sl_d if pos_dir == "long" else entry_price - tp_ratio * sl_d
                        else:
                            tp = None
                    else:
                        qty = 1
                        tp = None
                        
        total_t = len(trades)
        if total_t == 0:
            return {"cagr": 0, "max_dd": 0, "profit_factor": 0, "final_equity": equity, "total_trades": 0}
            
        wins = [tr["Net PnL"] for tr in trades if tr["Net PnL"] > 0]
        losses = [tr["Net PnL"] for tr in trades if tr["Net PnL"] <= 0]
        pf = sum(wins) / abs(sum(losses)) if losses and sum(losses) != 0 else float('inf')
        win_rate = len(wins) / total_t
        
        # Max Drawdown
        df_cap = pd.DataFrame(capital_history, columns=["timestamp", "equity"])
        df_cap["running_max"] = df_cap["equity"].cummax()
        df_cap["drawdown"] = (df_cap["equity"] - df_cap["running_max"]) / df_cap["running_max"]
        max_dd = df_cap["drawdown"].min()
        
        days = (times[-1] - times[1000]).total_seconds() / (24 * 3600)
        cagr = (equity / initial_capital) ** (365.25 / days) - 1
        
        return {
            "total_trades": total_t,
            "win_rate": win_rate,
            "profit_factor": pf,
            "cagr": cagr,
            "max_dd": max_dd,
            "final_equity": equity
        }


def run_tp_sweep():
    contracts = ["BTC_USDT", "ETH_USDT"]
    datasets = {}
    
    print("=" * 80)
    print("🚀 PRECOMPUTING INDICATORS FOR TP SWEEP (5-YEAR)")
    print("=" * 80)
    
    for contract in contracts:
        df_30m, df_1h = load_data(contract)
        if df_30m is None or df_1h is None:
            print(f"❌ Missing data files for {contract}. Run download first.")
            return
            
        print(f"Processing indicators for {contract}...")
        df_30m = df_30m.copy()
        df_1h = df_1h.copy()
        
        # 30m indicators
        st_res = calculate_supertrend(df_30m, 10, 3.0)
        df_30m['st_val'] = st_res['supertrend']
        df_30m['st_dir'] = st_res['direction']
        df_30m['atr_val'] = calculate_atr(df_30m, 14)
        
        # 1H indicators
        st_res_1h = calculate_supertrend(df_1h, 10, 3.0)
        df_1h['st_val'] = st_res_1h['supertrend']
        df_1h['st_dir'] = st_res_1h['direction']
        df_1h['adx'] = calculate_adx(df_1h, 16)
        df_1h['ema_200'] = calculate_ema(df_1h['close'], 200)
        
        # Align 1H to 30m
        df_1h_aligned = df_1h.copy()
        df_1h_aligned.index = df_1h_aligned.index + pd.Timedelta(hours=1)
        
        rename_cols = {
            'st_val': 'h1_st_val',
            'st_dir': 'h1_st_dir',
            'adx': 'h1_adx',
            'close': 'h1_close',
            'ema_200': 'h1_ema_200'
        }
        df_1h_aligned = df_1h_aligned.reset_index().rename(columns=rename_cols)
        
        df_30m = df_30m.reset_index()
        df_30m['timestamp'] = df_30m['timestamp'].astype('datetime64[ns]')
        df_1h_aligned['timestamp'] = df_1h_aligned['timestamp'].astype('datetime64[ns]')
        
        df_merged = pd.merge_asof(
            df_30m,
            df_1h_aligned[['timestamp', 'h1_st_val', 'h1_st_dir', 'h1_adx', 'h1_close', 'h1_ema_200']],
            on='timestamp',
            direction='backward'
        ).rename(columns={'h1_adx': 'adx_aligned'})
        
        df_merged.set_index('timestamp', inplace=True)
        datasets[contract] = df_merged
        
    sim = TPSweepSimulator()
    
    print("\n" + "=" * 80)
    print("📈 RUNNING TAKE-PROFIT (TP) SWEEPS FOR BTC AND ETH (5-YEAR, 2.0% RISK)")
    print("=" * 80)
    
    tp_values = [3.0, 4.0, 5.0, 6.0, 8.0, 10.0, 12.0]
    
    for contract in contracts:
        print(f"\nAsset: {contract.upper()}")
        print("-" * 75)
        print(f"{'TP Ratio':10s} | {'5-Year CAGR':12s} | {'Max Drawdown':12s} | {'Profit Factor':13s} | {'Win Rate':10s} | {'Final Equity':12s}")
        print("-" * 75)
        
        for tp in tp_values:
            res = sim.run_single_asset(datasets[contract], contract, tp, risk_percent=0.02)
            print(f"{tp:9.1f}R | {res['cagr']*100:+11.2f}% | {abs(res['max_dd'])*100:11.2f}% | {res['profit_factor']:13.2f} | {res['win_rate']*100:9.2f}% | ${res['final_equity']:10.2f}")
        print("=" * 80)

if __name__ == "__main__":
    run_tp_sweep()
