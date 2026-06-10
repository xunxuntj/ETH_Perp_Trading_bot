#!/usr/bin/env python3
"""
Detailed Backtester and Reporter for the Optimal Joint Portfolio Strategy (ETH + SOL) on 5-Year Data.
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

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
RESULTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")


def load_data(contract: str) -> tuple:
    """Loads 5-year K-line data."""
    file_30m = os.path.join(DATA_DIR, f"{contract}_30m_5y.csv")
    file_1h = os.path.join(DATA_DIR, f"{contract}_1h_5y.csv")
    df_30m = pd.read_csv(file_30m)
    df_1h = pd.read_csv(file_1h)
    df_30m['timestamp'] = pd.to_datetime(df_30m['timestamp'], unit='s')
    df_1h['timestamp'] = pd.to_datetime(df_1h['timestamp'], unit='s')
    df_30m.set_index('timestamp', inplace=True)
    df_1h.set_index('timestamp', inplace=True)
    return df_30m, df_1h


def run_detailed_backtest():
    print("=" * 80)
    print("📈 RUNNING DETAILED 5-YEAR BACKTEST: OPTIMAL ETH + SOL PORTFOLIO (2% RISK)")
    print("=" * 80)
    
    contracts = ["ETH_USDT", "SOL_USDT"]
    datasets = {}
    
    # 1. Precompute Indicators
    for contract in contracts:
        df_30m, df_1h = load_data(contract)
        df_30m = df_30m.copy()
        df_1h = df_1h.copy()
        
        # 30m indicators
        st_res = calculate_supertrend(df_30m, 10, 3.0)
        df_30m['st_val'] = st_res['supertrend']
        df_30m['st_dir'] = st_res['direction']
        df_30m['atr_val'] = calculate_atr(df_30m, 14)
        df_30m['rsi_30m'] = calculate_rsi(df_30m['close'], 14)
        
        # 1H indicators
        st_res_1h = calculate_supertrend(df_1h, 10, 3.0)
        df_1h['st_val'] = st_res_1h['supertrend']
        df_1h['st_dir'] = st_res_1h['direction']
        df_1h['adx'] = calculate_adx(df_1h, 16)
        
        if contract == "ETH_USDT":
            df_1h['ema_150'] = calculate_ema(df_1h['close'], 150)
        else:
            df_1h['dema_150'] = calculate_dema(df_1h['close'], 150)
            
        # Align 1H to 30m
        df_1h_aligned = df_1h.copy()
        df_1h_aligned.index = df_1h_aligned.index + pd.Timedelta(hours=1)
        
        rename_cols = {
            'st_val': 'h1_st_val',
            'st_dir': 'h1_st_dir',
            'adx': 'h1_adx',
            'close': 'h1_close'
        }
        if contract == "ETH_USDT":
            rename_cols['ema_150'] = 'h1_ema_150'
        else:
            rename_cols['dema_150'] = 'h1_dema_150'
            
        df_1h_aligned = df_1h_aligned.reset_index().rename(columns=rename_cols)
        
        # Merge
        df_30m = df_30m.reset_index()
        df_30m['timestamp'] = df_30m['timestamp'].astype('datetime64[ns]')
        df_1h_aligned['timestamp'] = df_1h_aligned['timestamp'].astype('datetime64[ns]')
        
        merge_cols = ['timestamp', 'h1_st_val', 'h1_st_dir', 'h1_adx', 'h1_close', 
                      'h1_ema_150' if contract == "ETH_USDT" else 'h1_dema_150']
        
        df_merged = pd.merge_asof(
            df_30m,
            df_1h_aligned[merge_cols],
            on='timestamp',
            direction='backward'
        ).rename(columns={'h1_adx': 'adx_aligned'})
        
        df_merged.set_index('timestamp', inplace=True)
        datasets[contract] = df_merged

    # 2. Simulator parameters
    initial_capital = 1000.0
    fee_rate = 0.0004
    risk_percent = 0.02
    
    eth_fv = 0.01
    eth_slip = 0.1
    sol_fv = 1.0
    sol_slip = 0.01
    
    df_eth = datasets["ETH_USDT"]
    df_sol = datasets["SOL_USDT"]
    
    # Unpack arrays for speed
    # ETH
    eth_times = df_eth.index.to_pydatetime()
    eth_high = df_eth['high'].values
    eth_low = df_eth['low'].values
    eth_close = df_eth['close'].values
    eth_open = df_eth['open'].values
    eth_st_val = df_eth['st_val'].values
    eth_st_dir = df_eth['st_dir'].values
    eth_h1_st_val = df_eth['h1_st_val'].values
    eth_h1_st_dir = df_eth['h1_st_dir'].values
    eth_h1_close = df_eth['h1_close'].values
    eth_h1_ema_150 = df_eth['h1_ema_150'].values
    eth_adx = df_eth['adx_aligned'].values
    eth_atr = df_eth['atr_val'].values
    
    # SOL
    sol_times = df_sol.index.to_pydatetime()
    sol_high = df_sol['high'].values
    sol_low = df_sol['low'].values
    sol_close = df_sol['close'].values
    sol_open = df_sol['open'].values
    sol_st_val = df_sol['st_val'].values
    sol_st_dir = df_sol['st_dir'].values
    sol_h1_st_val = df_sol['h1_st_val'].values
    sol_h1_st_dir = df_sol['h1_st_dir'].values
    sol_h1_close = df_sol['h1_close'].values
    sol_h1_dema_150 = df_sol['h1_dema_150'].values
    sol_adx = df_sol['adx_aligned'].values
    sol_atr = df_sol['atr_val'].values
    
    n = min(len(df_eth), len(df_sol))
    warmup_len = 1000
    
    # Simulation States
    equity = initial_capital
    capital_history = []
    trades = []
    
    eth_in_pos = False
    eth_pos_dir = None
    eth_entry_price = 0.0
    eth_sl = 0.0
    eth_tp = None
    eth_phase = 0
    eth_qty = 0
    eth_consecutive_losses = 0
    eth_cooldown_until = None
    eth_entry_time = None
    
    sol_in_pos = False
    sol_pos_dir = None
    sol_entry_price = 0.0
    sol_sl = 0.0
    sol_tp = None
    sol_phase = 0
    sol_qty = 0
    sol_consecutive_losses = 0
    sol_cooldown_until = None
    sol_entry_time = None
    
    cb_until = None
    
    for i in range(warmup_len, n):
        t_curr = eth_times[i]
        
        # Check global circuit breaker
        if cb_until and t_curr >= cb_until:
            cb_until = None
        # Check individual cooldowns
        if eth_cooldown_until and t_curr >= eth_cooldown_until:
            eth_consecutive_losses = 0
            eth_cooldown_until = None
        if sol_cooldown_until and t_curr >= sol_cooldown_until:
            sol_consecutive_losses = 0
            sol_cooldown_until = None
            
        # Compute current portfolio equity
        current_equity = equity
        if eth_in_pos:
            curr_price = eth_close[i]
            pnl = (curr_price - eth_entry_price) * eth_qty * eth_fv if eth_pos_dir == "long" else (eth_entry_price - curr_price) * eth_qty * eth_fv
            current_equity += pnl
        if sol_in_pos:
            curr_price = sol_close[i]
            pnl = (curr_price - sol_entry_price) * sol_qty * sol_fv if sol_pos_dir == "long" else (sol_entry_price - curr_price) * sol_qty * sol_fv
            current_equity += pnl
            
        capital_history.append((t_curr, current_equity))
        
        eth_closed_this_bar = False
        sol_closed_this_bar = False
        
        # ----------------------------------------------------
        # 1. EVALUATE EXITS & TRAILING STOPS (ETH)
        # ----------------------------------------------------
        if eth_in_pos:
            is_stopped = False
            is_tp_hit = False
            exit_price = eth_sl
            exit_reason = "stop_loss"
            
            if eth_pos_dir == "long":
                if eth_low[i] <= eth_sl:
                    is_stopped = True
                    exit_price = min(eth_open[i], eth_sl)
                if eth_tp is not None and eth_high[i] >= eth_tp:
                    is_tp_hit = True
                    if not is_stopped:
                        exit_price = max(eth_open[i], eth_tp)
                        exit_reason = "take_profit"
            else: # short
                if eth_high[i] >= eth_sl:
                    is_stopped = True
                    exit_price = max(eth_open[i], eth_sl)
                if eth_tp is not None and eth_low[i] <= eth_tp:
                    is_tp_hit = True
                    if not is_stopped:
                        exit_price = min(eth_open[i], eth_tp)
                        exit_reason = "take_profit"
                        
            if is_stopped or (is_tp_hit and exit_reason == "take_profit"):
                actual_exit = exit_price - eth_slip if eth_pos_dir == "long" else exit_price + eth_slip
                pnl = (actual_exit - eth_entry_price) * eth_qty * eth_fv if eth_pos_dir == "long" else (eth_entry_price - actual_exit) * eth_qty * eth_fv
                fee = (eth_entry_price + actual_exit) * eth_qty * eth_fv * fee_rate
                net_pnl = pnl - fee
                
                equity += net_pnl
                if net_pnl < 0:
                    eth_consecutive_losses += 1
                    if eth_consecutive_losses >= 3:
                        eth_cooldown_until = t_curr + timedelta(hours=48)
                else:
                    eth_consecutive_losses = 0
                if equity <= 350.0:
                    cb_until = t_curr + timedelta(days=7)
                    
                trades.append({
                    "Symbol": "ETH_USDT",
                    "Direction": eth_pos_dir,
                    "Entry Time": eth_entry_time,
                    "Exit Time": t_curr,
                    "Entry Price": eth_entry_price,
                    "Exit Price": actual_exit,
                    "Exit Reason": exit_reason,
                    "Net PnL": net_pnl,
                    "Fee": fee,
                    "Equity After": equity
                })
                eth_in_pos = False
                eth_pos_dir = None
                eth_tp = None
                eth_closed_this_bar = True
            else:
                # Check technical exits
                tech_exit = (eth_phase == 3 and eth_h1_st_dir[i-1] == -1 if eth_pos_dir == "long" else eth_phase == 3 and eth_h1_st_dir[i-1] == 1) or \
                            ((eth_phase == 1 or eth_phase == 2) and eth_st_dir[i-1] == -1 if eth_pos_dir == "long" else (eth_phase == 1 or eth_phase == 2) and eth_st_dir[i-1] == 1)
                            
                if tech_exit:
                    exit_price = eth_open[i]
                    actual_exit = exit_price - eth_slip if eth_pos_dir == "long" else exit_price + eth_slip
                    pnl = (actual_exit - eth_entry_price) * eth_qty * eth_fv if eth_pos_dir == "long" else (eth_entry_price - actual_exit) * eth_qty * eth_fv
                    fee = (eth_entry_price + actual_exit) * eth_qty * eth_fv * fee_rate
                    net_pnl = pnl - fee
                    
                    equity += net_pnl
                    if net_pnl < 0:
                        eth_consecutive_losses += 1
                        if eth_consecutive_losses >= 3:
                            eth_cooldown_until = t_curr + timedelta(hours=48)
                    else:
                        eth_consecutive_losses = 0
                    if equity <= 350.0:
                        cb_until = t_curr + timedelta(days=7)
                        
                    trades.append({
                        "Symbol": "ETH_USDT",
                        "Direction": eth_pos_dir,
                        "Entry Time": eth_entry_time,
                        "Exit Time": t_curr,
                        "Entry Price": eth_entry_price,
                        "Exit Price": actual_exit,
                        "Exit Reason": "technical_exit",
                        "Net PnL": net_pnl,
                        "Fee": fee,
                        "Equity After": equity
                    })
                    eth_in_pos = False
                    eth_pos_dir = None
                    eth_tp = None
                    eth_closed_this_bar = True
                else:
                    # Update trailing SL
                    is_long = (eth_pos_dir == "long")
                    act_risk = current_equity * risk_percent
                    if 350.0 <= current_equity <= 500.0:
                        act_risk = 10.0
                    buf_u = act_risk * 1.0 # lock_profit_buffer = 1.0
                    
                    # Three-stage trailing stop
                    locked_price = eth_entry_price + (buf_u / (eth_qty * eth_fv)) if is_long else eth_entry_price - (buf_u / (eth_qty * eth_fv))
                    st_30 = eth_st_val[i-1]
                    st_1h = eth_h1_st_val[i-1]
                    
                    is_surv = st_30 < eth_entry_price if is_long else st_30 > eth_entry_price
                    if is_surv:
                        eth_phase = 1
                        eth_sl = max(st_30, eth_sl) if is_long else min(st_30, eth_sl)
                    else:
                        is_hr = st_1h > locked_price if is_long else st_1h < locked_price
                        if is_hr:
                            eth_phase = 3
                            eth_sl = max(st_1h, eth_sl) if is_long else min(st_1h, eth_sl)
                        else:
                            eth_phase = 2
                            cand = st_30
                            if is_long:
                                if st_30 > locked_price: cand = locked_price
                                eth_sl = max(cand, eth_sl)
                            else:
                                if st_30 < locked_price: cand = locked_price
                                eth_sl = min(cand, eth_sl)

        # ----------------------------------------------------
        # 2. EVALUATE EXITS & TRAILING STOPS (SOL)
        # ----------------------------------------------------
        if sol_in_pos:
            is_stopped = False
            exit_price = sol_sl
            exit_reason = "stop_loss"
            
            if sol_pos_dir == "long":
                if sol_low[i] <= sol_sl:
                    is_stopped = True
                    exit_price = min(sol_open[i], sol_sl)
            else: # short
                if sol_high[i] >= sol_sl:
                    is_stopped = True
                    exit_price = max(sol_open[i], sol_sl)
                    
            if is_stopped:
                actual_exit = exit_price - sol_slip if sol_pos_dir == "long" else exit_price + sol_slip
                pnl = (actual_exit - sol_entry_price) * sol_qty * sol_fv if sol_pos_dir == "long" else (sol_entry_price - actual_exit) * sol_qty * sol_fv
                fee = (sol_entry_price + actual_exit) * sol_qty * sol_fv * fee_rate
                net_pnl = pnl - fee
                
                equity += net_pnl
                if net_pnl < 0:
                    sol_consecutive_losses += 1
                    if sol_consecutive_losses >= 3:
                        sol_cooldown_until = t_curr + timedelta(hours=48)
                else:
                    sol_consecutive_losses = 0
                if equity <= 350.0:
                    cb_until = t_curr + timedelta(days=7)
                    
                trades.append({
                    "Symbol": "SOL_USDT",
                    "Direction": sol_pos_dir,
                    "Entry Time": sol_entry_time,
                    "Exit Time": t_curr,
                    "Entry Price": sol_entry_price,
                    "Exit Price": actual_exit,
                    "Exit Reason": exit_reason,
                    "Net PnL": net_pnl,
                    "Fee": fee,
                    "Equity After": equity
                })
                sol_in_pos = False
                sol_pos_dir = None
                sol_tp = None
                sol_closed_this_bar = True
            else:
                # Check technical exits
                tech_exit = (sol_phase == 3 and sol_h1_st_dir[i-1] == -1 if sol_pos_dir == "long" else sol_phase == 3 and sol_h1_st_dir[i-1] == 1) or \
                            ((sol_phase == 1 or sol_phase == 2) and sol_st_dir[i-1] == -1 if sol_pos_dir == "long" else (sol_phase == 1 or sol_phase == 2) and sol_st_dir[i-1] == 1)
                            
                if tech_exit:
                    exit_price = sol_open[i]
                    actual_exit = exit_price - sol_slip if sol_pos_dir == "long" else exit_price + sol_slip
                    pnl = (actual_exit - sol_entry_price) * sol_qty * sol_fv if sol_pos_dir == "long" else (sol_entry_price - actual_exit) * sol_qty * sol_fv
                    fee = (sol_entry_price + actual_exit) * sol_qty * sol_fv * fee_rate
                    net_pnl = pnl - fee
                    
                    equity += net_pnl
                    if net_pnl < 0:
                        sol_consecutive_losses += 1
                        if sol_consecutive_losses >= 3:
                            sol_cooldown_until = t_curr + timedelta(hours=48)
                    else:
                        sol_consecutive_losses = 0
                    if equity <= 350.0:
                        cb_until = t_curr + timedelta(days=7)
                        
                    trades.append({
                        "Symbol": "SOL_USDT",
                        "Direction": sol_pos_dir,
                        "Entry Time": sol_entry_time,
                        "Exit Time": t_curr,
                        "Entry Price": sol_entry_price,
                        "Exit Price": actual_exit,
                        "Exit Reason": "technical_exit",
                        "Net PnL": net_pnl,
                        "Fee": fee,
                        "Equity After": equity
                    })
                    sol_in_pos = False
                    sol_pos_dir = None
                    sol_tp = None
                    sol_closed_this_bar = True
                else:
                    # Update trailing SL
                    is_long = (sol_pos_dir == "long")
                    act_risk = current_equity * risk_percent
                    if 350.0 <= current_equity <= 500.0:
                        act_risk = 10.0
                    buf_u = act_risk * 1.0
                    
                    # Three-stage trailing stop
                    locked_price = sol_entry_price + (buf_u / (sol_qty * sol_fv)) if is_long else sol_entry_price - (buf_u / (sol_qty * sol_fv))
                    st_30 = sol_st_val[i-1]
                    st_1h = sol_h1_st_val[i-1]
                    
                    is_surv = st_30 < sol_entry_price if is_long else st_30 > sol_entry_price
                    if is_surv:
                        sol_phase = 1
                        sol_sl = max(st_30, sol_sl) if is_long else min(st_30, sol_sl)
                    else:
                        is_hr = st_1h > locked_price if is_long else st_1h < locked_price
                        if is_hr:
                            sol_phase = 3
                            sol_sl = max(st_1h, sol_sl) if is_long else min(st_1h, sol_sl)
                        else:
                            sol_phase = 2
                            cand = st_30
                            if is_long:
                                if st_30 > locked_price: cand = locked_price
                                sol_sl = max(cand, sol_sl)
                            else:
                                if st_30 < locked_price: cand = locked_price
                                sol_sl = min(cand, sol_sl)

        # ----------------------------------------------------
        # 3. EVALUATE ENTRIS (ETH)
        # ----------------------------------------------------
        if not eth_in_pos and not eth_closed_this_bar and not cb_until and not eth_cooldown_until:
            # 1H EMA 150 Filter
            h1_close_sig = eth_h1_close[i-1]
            ema_val = eth_h1_ema_150[i-1]
            trend_ok_long = (h1_close_sig > ema_val)
            trend_ok_short = (h1_close_sig < ema_val)
            
            # SuperTrend Signal
            entry_long = (eth_st_dir[i-1] == 1)
            entry_short = (eth_st_dir[i-1] == -1)
            
            # ADX > 30.0 Filter
            adx_ok = (eth_adx[i-1] > 30.0)
            
            if entry_long and trend_ok_long and adx_ok:
                eth_pos_dir = "long"
            elif entry_short and trend_ok_short and adx_ok:
                eth_pos_dir = "short"
                
            if eth_pos_dir is not None:
                eth_entry_price = eth_open[i]
                eth_entry_time = t_curr
                eth_in_pos = True
                eth_phase = 1
                eth_sl = eth_st_val[i-1]
                
                # Size calculation (2% risk sizing)
                act_risk = current_equity * risk_percent
                if 350.0 <= current_equity <= 500.0:
                    act_risk = 10.0
                sl_d = abs(eth_entry_price - eth_sl)
                if sl_d > 0:
                    eth_qty = int(min(act_risk / (sl_d * eth_fv), (current_equity * 5.0) / (eth_entry_price * eth_fv)))
                    if eth_qty <= 0: eth_qty = 1
                    eth_tp = eth_entry_price + 5.0 * sl_d if eth_pos_dir == "long" else eth_entry_price - 5.0 * sl_d
                else:
                    eth_qty = 1
                    eth_tp = None

        # ----------------------------------------------------
        # 4. EVALUATE ENTRIS (SOL)
        # ----------------------------------------------------
        if not sol_in_pos and not sol_closed_this_bar and not cb_until and not sol_cooldown_until:
            # 1H DEMA 150 Filter
            h1_close_sig = sol_h1_close[i-1]
            dema_val = sol_h1_dema_150[i-1]
            trend_ok_long = (h1_close_sig > dema_val)
            trend_ok_short = (h1_close_sig < dema_val)
            
            # SuperTrend Signal
            entry_long = (sol_st_dir[i-1] == 1)
            entry_short = (sol_st_dir[i-1] == -1)
            
            # ADX > 25.0 Filter
            adx_ok = (sol_adx[i-1] > 25.0)
            
            if entry_long and trend_ok_long and adx_ok:
                sol_pos_dir = "long"
            elif entry_short and trend_ok_short and adx_ok:
                sol_pos_dir = "short"
                
            if sol_pos_dir is not None:
                sol_entry_price = sol_open[i]
                sol_entry_time = t_curr
                sol_in_pos = True
                sol_phase = 1
                sol_sl = sol_st_val[i-1]
                
                # Size calculation (2% risk sizing)
                act_risk = current_equity * risk_percent
                if 350.0 <= current_equity <= 500.0:
                    act_risk = 10.0
                sl_d = abs(sol_entry_price - sol_sl)
                if sl_d > 0:
                    sol_qty = int(min(act_risk / (sl_d * sol_fv), (current_equity * 5.0) / (sol_entry_price * sol_fv)))
                    if sol_qty <= 0: sol_qty = 1
                    sol_tp = None # No TP for SOL
                else:
                    sol_qty = 1
                    sol_tp = None

    # Write trades file
    df_trades = pd.DataFrame(trades)
    os.makedirs(RESULTS_DIR, exist_ok=True)
    df_trades.to_csv(os.path.join(RESULTS_DIR, "portfolio_trades_5y.csv"), index=False)
    
    # Calculate detailed statistics
    total_trades = len(df_trades)
    if total_trades == 0:
        print("❌ No trades were executed in the backtest.")
        return
        
    wins = df_trades[df_trades["Net PnL"] > 0]
    losses = df_trades[df_trades["Net PnL"] <= 0]
    win_rate = len(wins) / total_trades if total_trades > 0 else 0
    
    total_gains = wins["Net PnL"].sum()
    total_losses = abs(losses["Net PnL"].sum())
    profit_factor = total_gains / total_losses if total_losses > 0 else float('inf')
    
    # Max Drawdown
    df_cap = pd.DataFrame(capital_history, columns=["timestamp", "equity"])
    df_cap["running_max"] = df_cap["equity"].cummax()
    df_cap["drawdown"] = (df_cap["equity"] - df_cap["running_max"]) / df_cap["running_max"]
    max_dd = df_cap["drawdown"].min()
    
    start_time = capital_history[0][0]
    end_time = capital_history[-1][0]
    duration_days = (end_time - start_time).total_seconds() / (24 * 3600)
    cagr = (equity / initial_capital) ** (365.25 / duration_days) - 1
    
    # Consecutive losses
    consecutive_loss_max = 0
    curr_loss_streak = 0
    for idx, row in df_trades.iterrows():
        if row["Net PnL"] <= 0:
            curr_loss_streak += 1
            consecutive_loss_max = max(consecutive_loss_max, curr_loss_streak)
        else:
            curr_loss_streak = 0
            
    # Average trade
    avg_win = wins["Net PnL"].mean() if len(wins) > 0 else 0
    avg_loss = losses["Net PnL"].mean() if len(losses) > 0 else 0
    avg_trade = df_trades["Net PnL"].mean()
    win_loss_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else float('inf')
    
    # Sharpe ratio (daily returns)
    df_cap.set_index("timestamp", inplace=True)
    df_daily = df_cap["equity"].resample("D").last().ffill()
    df_daily_ret = df_daily.pct_change().dropna()
    daily_vol = df_daily_ret.std()
    daily_mean = df_daily_ret.mean()
    sharpe = (daily_mean / daily_vol) * np.sqrt(365.25) if daily_vol != 0 else 0.0
    
    print("\n" + "=" * 80)
    print("📋 DETAILED 5-YEAR BACKTEST PORTFOLIO REPORT SUMMARY")
    print("=" * 80)
    print(f"  Initial Capital:       1,000.00 USDT")
    print(f"  Final Equity:          {equity:.2f} USDT")
    print(f"  Net Profit:            {equity - initial_capital:+.2f} USDT")
    print(f"  Annualized CAGR:       {cagr*100:+.2f}%")
    print(f"  Maximum Drawdown:      {max_dd*100:.2f}%")
    print(f"  Profit Factor (PF):    {profit_factor:.2f}")
    print(f"  Sharpe Ratio:          {sharpe:.2f}")
    print("-" * 80)
    print(f"  Total Trades Executed: {total_trades}")
    print(f"  Winning Trades:        {len(wins)} ({win_rate*100:.1f}%)")
    print(f"  Losing Trades:         {len(losses)} ({(1-win_rate)*100:.1f}%)")
    print(f"  Max Consecutive Loss:  {consecutive_loss_max} trades")
    print("-" * 80)
    print(f"  Average Win Amount:    {avg_win:+.2f} USDT")
    print(f"  Average Loss Amount:   {avg_loss:+.2f} USDT")
    print(f"  Average PnL per Trade: {avg_trade:+.2f} USDT")
    print(f"  Avg Win / Avg Loss:    {win_loss_ratio:.2f}")
    print("=" * 80)


if __name__ == "__main__":
    run_detailed_backtest()
