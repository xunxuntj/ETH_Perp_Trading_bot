#!/usr/bin/env python3
"""
Strategy Exploration and Grid/Random Search Optimizer for ETH and SOL.
Calculates CAGR, Max Drawdown, Win Rate, and Profit Factor for hundreds of combinations,
targeting CAGR > 300% and Max Drawdown < 25%.
"""

import os
import sys
import json
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from multiprocessing import Pool

# Ensure parent directory is in path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from indicators import (
    calculate_supertrend, calculate_dema, calculate_adx,
    calculate_ema, calculate_atr, calculate_rsi
)

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
RESULTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
os.makedirs(RESULTS_DIR, exist_ok=True)


def load_data(contract: str) -> tuple:
    """Loads 30m and 1h K-lines."""
    file_30m = os.path.join(DATA_DIR, f"{contract}_30m.csv")
    file_1h = os.path.join(DATA_DIR, f"{contract}_1h.csv")
    if not os.path.exists(file_30m) or not os.path.exists(file_1h):
        return None, None
    df_30m = pd.read_csv(file_30m)
    df_1h = pd.read_csv(file_1h)
    df_30m['timestamp'] = pd.to_datetime(df_30m['timestamp'], unit='s')
    df_1h['timestamp'] = pd.to_datetime(df_1h['timestamp'], unit='s')
    df_30m.set_index('timestamp', inplace=True)
    df_1h.set_index('timestamp', inplace=True)
    return df_30m, df_1h


class FastSimulator:
    def __init__(self, contract: str, initial_capital: float = 1000.0, fee_rate: float = 0.0004, slippage_ticks: float = 1.0):
        self.contract = contract
        self.initial_capital = initial_capital
        self.fee_rate = fee_rate
        
        # Base coin parameters
        self.face_value = self._get_face_value(contract)
        self.tick_size = self._get_tick_size(contract)
        self.slippage = slippage_ticks * self.tick_size
        
    def _get_face_value(self, contract: str) -> float:
        c_upper = contract.upper()
        if "ETH" in c_upper: return 0.01
        elif "BTC" in c_upper: return 0.0001
        elif "SOL" in c_upper: return 1.0
        return 0.01

    def _get_tick_size(self, contract: str) -> float:
        c_upper = contract.upper()
        if "ETH" in c_upper or "BTC" in c_upper: return 0.1
        elif "SOL" in c_upper: return 0.01
        return 0.01

    def run(self, df_merged: pd.DataFrame, cfg: dict) -> dict:
        """
        Simulates the trading strategy.
        Accepts a pre-merged DataFrame with all necessary indicators pre-calculated to maximize speed.
        """
        # Parse config
        timeframe = cfg.get("timeframe", "30m")
        trend_filter_1h = cfg.get("trend_filter_1h", "none") # "dema", "ema", "supertrend", "none"
        entry_signal = cfg.get("entry_signal", "supertrend") # "supertrend", "ema_cross", "rsi"
        tp_ratio = cfg.get("tp_ratio", None)
        sl_type = cfg.get("sl_type", "supertrend") # "supertrend", "atr"
        sl_atr_mult = cfg.get("sl_atr_mult", 2.0)
        trailing_stop = cfg.get("trailing_stop", "none") # "three_stage", "atr", "none"
        trailing_atr_mult = cfg.get("trailing_atr_mult", 2.0)
        lock_profit_buffer = cfg.get("lock_profit_buffer", 1.0)
        
        adx_filter = cfg.get("adx_filter", False)
        adx_threshold = cfg.get("adx_threshold", 20.0)
        
        volume_filter = cfg.get("volume_filter", False)
        volume_factor = cfg.get("volume_factor", 1.0)
        
        rsi_filter = cfg.get("rsi_filter", "none") # "none", "trend"
        
        # State variables
        equity = self.initial_capital
        capital_history = []
        trades = []
        
        in_pos = False
        pos_direction = None
        pos_entry_price = 0.0
        pos_stop_loss = 0.0
        pos_tp_price = None
        pos_phase = 0 # 0: None, 1: Survival, 2: Locked, 3: Hourly
        pos_qty = 0
        pos_entry_time = None
        pos_initial_30m_st = 0.0
        
        # Cooldowns
        consecutive_losses = 0
        cooldown_until = None
        cb_until = None
        
        warmup_len = 1000
        
        timestamps = df_merged.index
        high_prices = df_merged['high'].values
        low_prices = df_merged['low'].values
        close_prices = df_merged['close'].values
        open_prices = df_merged['open'].values
        volume_vals = df_merged['volume'].values
        
        # Retrieve pre-calculated indicators from DataFrame
        # 30m Supertrend
        st_val_30m = df_merged['st_val'].values
        st_dir_30m = df_merged['st_dir'].values
        
        # 1H Supertrend
        h1_st_val = df_merged['h1_st_val'].values
        h1_st_dir = df_merged['h1_st_dir'].values
        
        # DEMA and EMA
        h1_dema = df_merged['h1_dema'].values if 'h1_dema' in df_merged.columns else None
        h1_ema = df_merged['h1_ema'].values if 'h1_ema' in df_merged.columns else None
        dema_30m = df_merged['dema_30m'].values if 'dema_30m' in df_merged.columns else None
        ema_30m = df_merged['ema_30m'].values if 'ema_30m' in df_merged.columns else None
        
        # EMA Crossover
        ema_fast_30m = df_merged['ema_fast_30m'].values if 'ema_fast_30m' in df_merged.columns else None
        ema_slow_30m = df_merged['ema_slow_30m'].values if 'ema_slow_30m' in df_merged.columns else None
        
        # ADX
        adx_aligned = df_merged['adx_aligned'].values if 'adx_aligned' in df_merged.columns else None
        
        # RSI
        rsi_30m = df_merged['rsi_30m'].values if 'rsi_30m' in df_merged.columns else None
        
        # ATR and Volume MA
        atr_val = df_merged['atr_val'].values if 'atr_val' in df_merged.columns else None
        vol_ma = df_merged['vol_ma'].values if 'vol_ma' in df_merged.columns else None
        
        n = len(df_merged)
        
        for i in range(warmup_len, n):
            t_curr = timestamps[i]
            
            # Check cooldown or CB expiration
            if cooldown_until and t_curr >= cooldown_until:
                consecutive_losses = 0
                cooldown_until = None
            if cb_until and t_curr >= cb_until:
                cb_until = None
                
            # Track equity
            current_equity = equity
            if in_pos:
                curr_price = close_prices[i]
                if pos_direction == "long":
                    unrealized_pnl = (curr_price - pos_entry_price) * pos_qty * self.face_value
                else:
                    unrealized_pnl = (pos_entry_price - curr_price) * pos_qty * self.face_value
                current_equity += unrealized_pnl
                
            capital_history.append((t_curr, current_equity))
            
            # ----------------------------------------------------
            # CASE A: In Active Position - Evaluate Exits
            # ----------------------------------------------------
            if in_pos:
                # 1. Check Stop Loss or Take Profit hit
                is_stopped = False
                is_tp_hit = False
                exit_price = pos_stop_loss
                exit_reason = "stop_loss"
                
                if pos_direction == "long":
                    if low_prices[i] <= pos_stop_loss:
                        is_stopped = True
                        exit_price = min(open_prices[i], pos_stop_loss)
                    if tp_ratio is not None and pos_tp_price is not None and high_prices[i] >= pos_tp_price:
                        is_tp_hit = True
                        if is_stopped:
                            pass # SL takes precedence for conservative backtesting
                        else:
                            exit_price = max(open_prices[i], pos_tp_price)
                            exit_reason = "take_profit"
                else: # short
                    if high_prices[i] >= pos_stop_loss:
                        is_stopped = True
                        exit_price = max(open_prices[i], pos_stop_loss)
                    if tp_ratio is not None and pos_tp_price is not None and low_prices[i] <= pos_tp_price:
                        is_tp_hit = True
                        if is_stopped:
                            pass
                        else:
                            exit_price = min(open_prices[i], pos_tp_price)
                            exit_reason = "take_profit"
                            
                if is_stopped or (is_tp_hit and exit_reason == "take_profit"):
                    # Apply slippage
                    actual_exit_price = exit_price - self.slippage if pos_direction == "long" else exit_price + self.slippage
                    
                    # PNL calculation
                    pnl = (actual_exit_price - pos_entry_price) * pos_qty * self.face_value if pos_direction == "long" else (pos_entry_price - actual_exit_price) * pos_qty * self.face_value
                    entry_fee = pos_entry_price * pos_qty * self.face_value * self.fee_rate
                    exit_fee = actual_exit_price * pos_qty * self.face_value * self.fee_rate
                    net_pnl = pnl - (entry_fee + exit_fee)
                    
                    equity += net_pnl
                    
                    # Cool down rules
                    if net_pnl < 0:
                        consecutive_losses += 1
                        if consecutive_losses >= 3:
                            cooldown_until = t_curr + timedelta(hours=48)
                    else:
                        consecutive_losses = 0
                        
                    if equity <= 350.0:
                        cb_until = t_curr + timedelta(days=7)
                        
                    trades.append({
                        "net_pnl": net_pnl,
                        "fee": entry_fee + exit_fee
                    })
                    
                    in_pos = False
                    pos_direction = None
                    pos_phase = 0
                    pos_tp_price = None
                    continue
                
                # 2. Check Technical Exit (evaluated on completed bar i-1)
                technical_exit = False
                exit_reason_tech = ""
                
                st_dir_prev = st_dir_30m[i-1]
                h1_st_dir_prev = h1_st_dir[i-1]
                
                if pos_direction == "long":
                    # Timeframe specific exit
                    if timeframe == "1h":
                        if h1_st_dir_prev == -1:
                            technical_exit = True
                            exit_reason_tech = "1H ST Red"
                    else: # 30m
                        if pos_phase == 3 and h1_st_dir_prev == -1:
                            technical_exit = True
                            exit_reason_tech = "1H ST Red"
                        elif (pos_phase == 1 or pos_phase == 2) and st_dir_prev == -1:
                            technical_exit = True
                            exit_reason_tech = "30m ST Red"
                else: # short
                    if timeframe == "1h":
                        if h1_st_dir_prev == 1:
                            technical_exit = True
                            exit_reason_tech = "1H ST Green"
                    else: # 30m
                        if pos_phase == 3 and h1_st_dir_prev == 1:
                            technical_exit = True
                            exit_reason_tech = "1H ST Green"
                        elif (pos_phase == 1 or pos_phase == 2) and st_dir_prev == 1:
                            technical_exit = True
                            exit_reason_tech = "30m ST Green"
                            
                if technical_exit:
                    exit_price = open_prices[i]
                    actual_exit_price = exit_price - self.slippage if pos_direction == "long" else exit_price + self.slippage
                    pnl = (actual_exit_price - pos_entry_price) * pos_qty * self.face_value if pos_direction == "long" else (pos_entry_price - actual_exit_price) * pos_qty * self.face_value
                    entry_fee = pos_entry_price * pos_qty * self.face_value * self.fee_rate
                    exit_fee = actual_exit_price * pos_qty * self.face_value * self.fee_rate
                    net_pnl = pnl - (entry_fee + exit_fee)
                    
                    equity += net_pnl
                    
                    if net_pnl < 0:
                        consecutive_losses += 1
                        if consecutive_losses >= 3:
                            cooldown_until = t_curr + timedelta(hours=48)
                    else:
                        consecutive_losses = 0
                        
                    if equity <= 350.0:
                        cb_until = t_curr + timedelta(days=7)
                        
                    trades.append({
                        "net_pnl": net_pnl,
                        "fee": entry_fee + exit_fee
                    })
                    
                    # We skip immediate reversal inside fast explorer to keep strategy evaluation clean and fast.
                    in_pos = False
                    pos_direction = None
                    pos_phase = 0
                    pos_tp_price = None
                    continue
                
                # 3. Update Stop Loss Trailing Mechanism (using completed bar i-1)
                is_long_pos = (pos_direction == "long")
                survival_to_locked_price = pos_entry_price
                active_risk_amt = equity * 0.02
                if 350.0 <= equity <= 500.0:
                    active_risk_amt = 10.0
                    
                buffer_usdt = active_risk_amt * lock_profit_buffer
                position_token_size = pos_qty * self.face_value
                
                if trailing_stop == "three_stage":
                    if is_long_pos:
                        locked_to_hourly_price = pos_entry_price + (buffer_usdt / position_token_size)
                    else:
                        locked_to_hourly_price = pos_entry_price - (buffer_usdt / position_token_size)
                        
                    st_30m_val = st_val_30m[i-1]
                    st_1h_val = h1_st_val[i-1]
                    
                    is_survival = st_30m_val < survival_to_locked_price if is_long_pos else st_30m_val > survival_to_locked_price
                    if is_survival:
                        pos_phase = 1
                        pos_stop_loss = max(st_30m_val, pos_stop_loss) if is_long_pos else min(st_30m_val, pos_stop_loss)
                    else:
                        is_hourly = st_1h_val > locked_to_hourly_price if is_long_pos else st_1h_val < locked_to_hourly_price
                        if is_hourly:
                            pos_phase = 3
                            pos_stop_loss = max(st_1h_val, pos_stop_loss) if is_long_pos else min(st_1h_val, pos_stop_loss)
                        else:
                            pos_phase = 2
                            candidate_stop = st_30m_val
                            if is_long_pos:
                                if st_30m_val > locked_to_hourly_price:
                                    candidate_stop = locked_to_hourly_price
                                pos_stop_loss = max(candidate_stop, pos_stop_loss)
                            else:
                                if st_30m_val < locked_to_hourly_price:
                                    candidate_stop = locked_to_hourly_price
                                pos_stop_loss = min(candidate_stop, pos_stop_loss)
                                
                elif trailing_stop == "atr":
                    # Simple trailing stop ATR-based
                    current_atr = atr_val[i-1]
                    if is_long_pos:
                        candidate_sl = close_prices[i-1] - trailing_atr_mult * current_atr
                        pos_stop_loss = max(candidate_sl, pos_stop_loss)
                    else:
                        candidate_sl = close_prices[i-1] + trailing_atr_mult * current_atr
                        pos_stop_loss = min(candidate_sl, pos_stop_loss)
                        
            # ----------------------------------------------------
            # CASE B: No Position - Check Entry
            # ----------------------------------------------------
            else:
                st_dir_sig = st_dir_30m[i-1]
                st_val_sig = st_val_30m[i-1]
                h1_st_dir_sig = h1_st_dir[i-1]
                h1_st_val_sig = h1_st_val[i-1]
                
                can_cooldown = (not cooldown_until) and (not cb_until)
                if not can_cooldown:
                    continue
                    
                # 1. Evaluate Trend Filter (1H)
                trend_ok_long = True
                trend_ok_short = True
                
                if timeframe == "30m":
                    if trend_filter_1h == "supertrend":
                        trend_ok_long = (h1_st_dir_sig == 1)
                        trend_ok_short = (h1_st_dir_sig == -1)
                    elif trend_filter_1h == "dema":
                        dema_p = cfg.get("dema_period", 200)
                        dema_col = f"h1_dema_{dema_p}"
                        dema_val = df_merged[dema_col].values[i-1]
                        h1_close_sig = df_merged['h1_close'].values[i-1]
                        trend_ok_long = (h1_close_sig > dema_val)
                        trend_ok_short = (h1_close_sig < dema_val)
                    elif trend_filter_1h == "ema":
                        ema_p = cfg.get("dema_period", 200)
                        ema_col = f"h1_ema_{ema_p}"
                        ema_val = df_merged[ema_col].values[i-1]
                        h1_close_sig = df_merged['h1_close'].values[i-1]
                        trend_ok_long = (h1_close_sig > ema_val)
                        trend_ok_short = (h1_close_sig < ema_val)
                else: # Pure 1H timeframe
                    if trend_filter_1h == "dema":
                        dema_p = cfg.get("dema_period", 200)
                        dema_col = f"h1_dema_{dema_p}"
                        dema_val = df_merged[dema_col].values[i-1]
                        h1_close_sig = df_merged['h1_close'].values[i-1]
                        trend_ok_long = (h1_close_sig > dema_val)
                        trend_ok_short = (h1_close_sig < dema_val)
                    elif trend_filter_1h == "ema":
                        ema_p = cfg.get("dema_period", 200)
                        ema_col = f"h1_ema_{ema_p}"
                        ema_val = df_merged[ema_col].values[i-1]
                        h1_close_sig = df_merged['h1_close'].values[i-1]
                        trend_ok_long = (h1_close_sig > ema_val)
                        trend_ok_short = (h1_close_sig < ema_val)
                        
                # 2. Evaluate Entry Signal
                entry_long = False
                entry_short = False
                
                if entry_signal == "supertrend":
                    if timeframe == "30m":
                        entry_long = (st_dir_sig == 1)
                        entry_short = (st_dir_sig == -1)
                    else: # 1H ST
                        entry_long = (h1_st_dir_sig == 1)
                        entry_short = (h1_st_dir_sig == -1)
                elif entry_signal == "ema_cross" and ema_fast_30m is not None and ema_slow_30m is not None:
                    # Fast crosses above slow
                    entry_long = (ema_fast_30m[i-1] > ema_slow_30m[i-1]) and (ema_fast_30m[i-2] <= ema_slow_30m[i-2])
                    entry_short = (ema_fast_30m[i-1] < ema_slow_30m[i-1]) and (ema_fast_30m[i-2] >= ema_slow_30m[i-2])
                elif entry_signal == "rsi" and rsi_30m is not None:
                    # RSI breakout or pullback
                    rsi_val = rsi_30m[i-1]
                    entry_long = (rsi_val < 35) # oversold dip
                    entry_short = (rsi_val > 65) # overbought rip
                    
                # 3. Apply Filters (ADX, Volume, RSI Filter)
                adx_ok = True
                if adx_filter and adx_aligned is not None:
                    adx_ok = (adx_aligned[i-1] > adx_threshold)
                    
                vol_ok = True
                if volume_filter and vol_ma is not None:
                    vol_ok = (volume_vals[i-1] > volume_factor * vol_ma[i-1])
                    
                rsi_filter_ok = True
                if rsi_filter == "trend" and rsi_30m is not None:
                    rsi_filter_ok_long = (rsi_30m[i-1] < 60) # prevent buying top of trend
                    rsi_filter_ok_short = (rsi_30m[i-1] > 40) # prevent selling bottom of trend
                else:
                    rsi_filter_ok_long = True
                    rsi_filter_ok_short = True
                    
                # Check final trigger
                is_long_trigger = entry_long and trend_ok_long and adx_ok and vol_ok and rsi_filter_ok_long
                is_short_trigger = entry_short and trend_ok_short and adx_ok and vol_ok and rsi_filter_ok_short
                
                if is_long_trigger:
                    pos_direction = "long"
                elif is_short_trigger:
                    pos_direction = "short"
                    
                if pos_direction is not None:
                    pos_entry_price = open_prices[i]
                    pos_entry_time = t_curr
                    in_pos = True
                    pos_phase = 1
                    
                    # Stop loss initialization
                    if sl_type == "supertrend":
                        pos_stop_loss = st_val_sig if timeframe == "30m" else h1_st_val_sig
                    elif sl_type == "atr" and atr_val is not None:
                        current_atr = atr_val[i-1]
                        if pos_direction == "long":
                            pos_stop_loss = pos_entry_price - sl_atr_mult * current_atr
                        else:
                            pos_stop_loss = pos_entry_price + sl_atr_mult * current_atr
                            
                    # Size calculation (2% risk sizing)
                    active_risk_amt = equity * 0.02
                    if 350.0 <= equity <= 500.0:
                        active_risk_amt = 10.0
                        
                    sl_dist = abs(pos_entry_price - pos_stop_loss)
                    if sl_dist > 0:
                        calc_qty = active_risk_amt / (sl_dist * self.face_value)
                        max_qty_leverage = (equity * 10.0) / (pos_entry_price * self.face_value)
                        pos_qty = int(min(calc_qty, max_qty_leverage))
                        if pos_qty <= 0: pos_qty = 1
                        
                        # Take profit calculation
                        if tp_ratio is not None:
                            if pos_direction == "long":
                                pos_tp_price = pos_entry_price + tp_ratio * sl_dist
                            else:
                                pos_tp_price = pos_entry_price - tp_ratio * sl_dist
                        else:
                            pos_tp_price = None
                    else:
                        pos_qty = 1
                        pos_tp_price = None
                        
        # Calculate metrics
        metrics = self._calculate_metrics(trades, capital_history, equity)
        return metrics

    def _calculate_metrics(self, trades: list, capital_history: list, final_equity: float) -> dict:
        total_trades = len(trades)
        if total_trades == 0:
            return {
                "total_trades": 0, "win_rate": 0.0, "total_pnl": 0.0,
                "profit_factor": 0.0, "max_drawdown": 0.0,
                "annualized_return": 0.0, "final_equity": final_equity
            }
            
        df_trades = pd.DataFrame(trades)
        wins = df_trades[df_trades['net_pnl'] > 0]
        losses = df_trades[df_trades['net_pnl'] <= 0]
        
        win_count = len(wins)
        win_rate = win_count / total_trades
        
        total_pnl = df_trades['net_pnl'].sum()
        total_gains = wins['net_pnl'].sum()
        total_losses = abs(losses['net_pnl'].sum())
        profit_factor = total_gains / total_losses if total_losses > 0 else float('inf')
        
        # Max Drawdown
        df_cap = pd.DataFrame(capital_history, columns=['timestamp', 'equity'])
        df_cap['running_max'] = df_cap['equity'].cummax()
        df_cap['drawdown'] = (df_cap['equity'] - df_cap['running_max']) / df_cap['running_max']
        max_dd = df_cap['drawdown'].min()
        
        # CAGR calculation
        if len(capital_history) > 1:
            start_time = capital_history[0][0]
            end_time = capital_history[-1][0]
            duration_days = (end_time - start_time).total_seconds() / (24 * 3600)
            if duration_days > 0 and final_equity > 0:
                cagr = (final_equity / self.initial_capital) ** (365.25 / duration_days) - 1
            else:
                cagr = 0.0
        else:
            cagr = 0.0
            
        return {
            "total_trades": total_trades,
            "win_rate": win_rate,
            "total_pnl": total_pnl,
            "profit_factor": None if np.isinf(profit_factor) else profit_factor,
            "max_drawdown": max_dd,
            "annualized_return": cagr,
            "final_equity": final_equity
        }


# Task wrapper for parallel processing
def evaluate_strategy(task_args) -> dict:
    contract, cfg, data_path = task_args
    # Re-load or load globally? Since it runs in pool, it's safer to load indicators once and share.
    # To keep task_args size light, we pre-merge the indicators data and pass it.
    # Let's write the explorer to merge df once per contract, then pass slices.
    return {"cfg": cfg, "metrics": None}


def main():
    print("=" * 80)
    print("🚀 STRATEGY EXPLORATION ENGINE - SEARCHING FOR OPTIMAL CONFIGURATIONS")
    print("=" * 80)
    
    contracts = ["ETH_USDT", "SOL_USDT"]
    results = {}
    
    for contract in contracts:
        df_30m, df_1h = load_data(contract)
        if df_30m is None or df_1h is None:
            print(f"Skipping {contract} - data not found. Run downloader first.")
            continue
            
        print(f"\n📊 Pre-computing indicators for {contract}...")
        
        # Make working copies
        df_30m = df_30m.copy()
        df_1h = df_1h.copy()
        
        # 30m base indicators
        st_res_30m = calculate_supertrend(df_30m, 10, 3.0)
        df_30m['st_val'] = st_res_30m['supertrend']
        df_30m['st_dir'] = st_res_30m['direction']
        
        df_30m['dema_30m'] = calculate_dema(df_30m['close'], 100)
        df_30m['ema_30m'] = calculate_ema(df_30m['close'], 100)
        df_30m['ema_fast_30m'] = calculate_ema(df_30m['close'], 12)
        df_30m['ema_slow_30m'] = calculate_ema(df_30m['close'], 26)
        df_30m['rsi_30m'] = calculate_rsi(df_30m['close'], 14)
        df_30m['atr_val'] = calculate_atr(df_30m, 14)
        df_30m['vol_ma'] = df_30m['volume'].rolling(window=20).mean()
        
        # 1H base indicators
        st_res_1h = calculate_supertrend(df_1h, 10, 3.0)
        df_1h['st_val'] = st_res_1h['supertrend']
        df_1h['st_dir'] = st_res_1h['direction']
        
        df_1h['adx'] = calculate_adx(df_1h, 16)
        for p in [100, 150, 200]:
            df_1h[f'dema_{p}'] = calculate_dema(df_1h['close'], p)
            df_1h[f'ema_{p}'] = calculate_ema(df_1h['close'], p)
        
        # Align 1H to 30m
        df_1h_aligned = df_1h.copy()
        df_1h_aligned.index = df_1h_aligned.index + pd.Timedelta(hours=1)
        
        rename_cols = {
            'st_val': 'h1_st_val',
            'st_dir': 'h1_st_dir',
            'adx': 'h1_adx',
            'close': 'h1_close'
        }
        for p in [100, 150, 200]:
            rename_cols[f'dema_{p}'] = f'h1_dema_{p}'
            rename_cols[f'ema_{p}'] = f'h1_ema_{p}'
            
        df_1h_aligned = df_1h_aligned.reset_index().rename(columns=rename_cols)
        
        # Merge them
        df_30m = df_30m.reset_index()
        df_30m['timestamp'] = df_30m['timestamp'].astype('datetime64[ns]')
        df_1h_aligned['timestamp'] = df_1h_aligned['timestamp'].astype('datetime64[ns]')
        
        merge_cols = ['timestamp', 'h1_st_val', 'h1_st_dir', 'h1_adx', 'h1_close']
        for p in [100, 150, 200]:
            merge_cols.extend([f'h1_dema_{p}', f'h1_ema_{p}'])
            
        df_merged = pd.merge_asof(
            df_30m,
            df_1h_aligned[merge_cols],
            on='timestamp',
            direction='backward'
        ).rename(columns={'h1_adx': 'adx_aligned'})
        
        df_merged.set_index('timestamp', inplace=True)
        
        # Setup simulator
        sim = FastSimulator(contract)
        
        # Let's generate strategies
        print(f"🔍 Generating strategy configurations for {contract}...")
        configs = []
        
        # 1. Baseline Archetype (Supertrend + 1H Filters + sweeps on TP, Buffer, DEMA/EMA)
        for trend_filter in ["dema", "ema", "supertrend", "none"]:
            for dema_p in [100, 150, 200]:
                for tp in [None, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0]:
                    for buf in [0.5, 1.0, 2.0]:
                        for adx_t in [20.0, 25.0, 30.0, 35.0]:
                            configs.append({
                                "timeframe": "30m",
                                "trend_filter_1h": trend_filter,
                                "dema_period": dema_p,
                                "entry_signal": "supertrend",
                                "tp_ratio": tp,
                                "lock_profit_buffer": buf,
                                "adx_filter": True,
                                "adx_threshold": adx_t,
                                "volume_filter": False,
                                "trailing_stop": "three_stage"
                            })
                            
        # 2. EMA Crossover Archetype
        for trend_filter in ["dema", "ema", "none"]:
            for dema_p in [100, 150]:
                for tp in [3.0, 4.0, 6.0, 8.0, 10.0]:
                    for sl_atr in [1.5, 2.0, 2.5]:
                        for adx_t in [20.0, 25.0]:
                            configs.append({
                                "timeframe": "30m",
                                "trend_filter_1h": trend_filter,
                                "dema_period": dema_p,
                                "entry_signal": "ema_cross",
                                "tp_ratio": tp,
                                "sl_type": "atr",
                                "sl_atr_mult": sl_atr,
                                "adx_filter": True,
                                "adx_threshold": adx_t,
                                "volume_filter": True,
                                "volume_factor": 1.0,
                                "trailing_stop": "atr",
                                "trailing_atr_mult": sl_atr
                            })
                            
        # 3. Pure 1H Timeframe Archetype (ST + DEMA + TP sweeps)
        for dema_p in [100, 150, 200]:
            for tp in [None, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0]:
                for adx_t in [15.0, 20.0, 25.0]:
                    configs.append({
                        "timeframe": "1h",
                        "trend_filter_1h": "dema",
                        "dema_period": dema_p,
                        "entry_signal": "supertrend",
                        "tp_ratio": tp,
                        "adx_filter": True,
                        "adx_threshold": adx_t,
                        "volume_filter": False,
                        "trailing_stop": "atr",
                        "trailing_atr_mult": 3.0,
                        "sl_type": "atr",
                        "sl_atr_mult": 3.0
                    })
                    
        print(f"Total configurations generated: {len(configs)}")
        print(f"⏳ Running backtest search for {contract} (may take 1-2 minutes)...")
        
        profitable_configs = []
        
        # Run loop
        count = 0
        for cfg in configs:
            metrics = sim.run(df_merged, cfg)
            
            # Save if CAGR > 300% and Drawdown < 25%
            # Or save top performing ones if none beat this high target
            cagr = metrics["annualized_return"]
            max_dd = abs(metrics["max_drawdown"])
            pf = metrics["profit_factor"]
            
            if cagr >= 3.0 and max_dd <= 0.25:
                # We found one that meets all criteria!
                 profitable_configs.append({
                     "metrics": metrics,
                     "cfg": cfg
                 })
                 print(f"🏆 FOUND WINNING STRATEGY for {contract}: Net Profit: {metrics['total_pnl']:+.2f} U, Ann. Return: {cagr*100:+.1f}%, Max DD: -{max_dd*100:.1f}%, PF: {pf:.2f}")
            
            # Track top results anyway just in case the bar is too high
            cfg["metrics_summary"] = {
                "total_trades": metrics["total_trades"],
                "win_rate": f"{metrics['win_rate']*100:.1f}%",
                "total_pnl": metrics["total_pnl"],
                "annualized_return_pct": f"{cagr*100:+.1f}%",
                "max_drawdown_pct": f"{max_dd*100:.1f}%",
                "profit_factor": metrics["profit_factor"]
            }
            count += 1
            if count % 1000 == 0:
                print(f"Processed {count}/{len(configs)} configurations...")
                
        # Sort and take top 20 by CAGR
        configs_sorted = sorted(configs, key=lambda x: (x["metrics_summary"]["total_pnl"]), reverse=True)
        top_20 = configs_sorted[:20]
        
        results[contract] = {
            "winning_configs": profitable_configs,
            "top_20_configs": top_20
        }
        
    # Write to json file
    filepath = os.path.join(RESULTS_DIR, "optimal_strategies.json")
    with open(filepath, "w") as f:
        json.dump(results, f, indent=4)
        
    print(f"\n✅ Exploration finished! Results saved to: backtest/results/optimal_strategies.json")
    print("=" * 80)


if __name__ == "__main__":
    main()
