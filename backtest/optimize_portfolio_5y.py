#!/usr/bin/env python3
"""
5-Asset Portfolio Optimizer over 5-Year History (2021-2026).
Optimizes parameter configurations for BTC, ETH, SOL, LINK, and DOGE,
sweeps all 15 asset combinations containing BTC, and sweeps joint risk sizing.
"""

import os
import sys
import json
import itertools
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta

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


class FastSimulator5Asset:
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
        elif "SOL" in c_upper:
            face_value = 1.0
            slippage = 0.01
        elif "LINK" in c_upper:
            face_value = 1.0
            slippage = 0.005
        elif "DOGE" in c_upper:
            face_value = 100.0  # 1 contract = 100 DOGE on OKX
            slippage = 0.00005
        else:
            face_value = 1.0
            slippage = 0.01
        return face_value, slippage

    def run_single(self, df_merged: pd.DataFrame, contract: str, cfg: dict) -> dict:
        """
        Runs a fast single-asset backtest using NumPy arrays.
        """
        face_value, slippage = self.get_contract_params(contract)
        
        # Unpack config
        entry_signal = cfg.get("entry_signal", "supertrend")
        trend_filter = cfg.get("trend_filter_1h", "ema")
        dema_period = cfg.get("dema_period", 150)
        tp_ratio = cfg.get("tp_ratio", 5.0)
        adx_threshold = cfg.get("adx_threshold", 25.0)
        rsi_pullback_lower = cfg.get("rsi_pullback_lower", 40.0)
        rsi_pullback_upper = cfg.get("rsi_pullback_upper", 60.0)
        sl_type = cfg.get("sl_type", "supertrend")
        sl_atr_mult = cfg.get("sl_atr_mult", 2.5)
        
        risk_percent = 0.02
        
        # Prepare arrays
        times = df_merged.index.to_pydatetime()
        high = df_merged['high'].values
        low = df_merged['low'].values
        close = df_merged['close'].values
        open_p = df_merged['open'].values
        st_val = df_merged['st_val'].values
        st_dir = df_merged['st_dir'].values
        h1_st_val = df_merged['h1_st_val'].values
        h1_st_dir = df_merged['h1_st_dir'].values
        h1_close = df_merged['h1_close'].values
        adx = df_merged['adx_aligned'].values
        
        # Pullback indicators
        rsi = df_merged['rsi_30m'].values if 'rsi_30m' in df_merged.columns else None
        atr = df_merged['atr_val'].values if 'atr_val' in df_merged.columns else None
        
        # Trend filter array
        if trend_filter == "ema":
            h1_ma = df_merged[f'h1_ema_{dema_period}'].values
        elif trend_filter == "dema":
            h1_ma = df_merged[f'h1_dema_{dema_period}'].values
        else:
            h1_ma = np.zeros(len(df_merged))
            
        n = len(df_merged)
        equity = 1000.0
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
        max_equity = 1000.0
        max_dd = 0.0
        
        for i in range(1000, n):
            t_curr = times[i]
            
            if cb_until and t_curr >= cb_until:
                cb_until = None
            if cooldown_until and t_curr >= cooldown_until:
                consecutive_losses = 0
                cooldown_until = None
                
            current_equity = equity
            if in_pos:
                pnl = (close[i] - entry_price) * qty * face_value if pos_dir == "long" else (entry_price - close[i]) * qty * face_value
                current_equity += pnl
                
            if current_equity > max_equity:
                max_equity = current_equity
            dd = (current_equity - max_equity) / max_equity
            if dd < max_dd:
                max_dd = dd
                
            closed_this_bar = False
            
            # EXITS
            if in_pos:
                is_stopped = False
                is_tp_hit = False
                exit_price = sl
                exit_reason = "stop_loss"
                
                if pos_dir == "long":
                    if low[i] <= sl:
                        is_stopped = True
                        exit_price = min(open_p[i], sl)
                    if tp is not None and high[i] >= tp:
                        is_tp_hit = True
                        if not is_stopped:
                            exit_price = max(open_p[i], tp)
                            exit_reason = "take_profit"
                else: # short
                    if high[i] >= sl:
                        is_stopped = True
                        exit_price = max(open_p[i], sl)
                    if tp is not None and low[i] <= tp:
                        is_tp_hit = True
                        if not is_stopped:
                            exit_price = min(open_p[i], tp)
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
                        
                    trades.append(net_pnl)
                    in_pos = False
                    pos_dir = None
                    tp = None
                    closed_this_bar = True
                else:
                    # Technical exit
                    tech_exit = (phase == 3 and h1_st_dir[i-1] == -1 if pos_dir == "long" else phase == 3 and h1_st_dir[i-1] == 1) or \
                                ((phase == 1 or phase == 2) and st_dir[i-1] == -1 if pos_dir == "long" else (phase == 1 or phase == 2) and st_dir[i-1] == 1)
                    if tech_exit:
                        exit_price = open_p[i]
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
                            
                        trades.append(net_pnl)
                        in_pos = False
                        pos_dir = None
                        tp = None
                        closed_this_bar = True
                    else:
                        # Update trailing SL
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
                                    
            # ENTRIES
            if not in_pos and not closed_this_bar and not cb_until and not cooldown_until:
                h1_c = h1_close[i-1]
                ma_v = h1_ma[i-1]
                
                trend_ok_long = (h1_c > ma_v) if trend_filter != "none" else True
                trend_ok_short = (h1_c < ma_v) if trend_filter != "none" else True
                
                adx_ok = (adx[i-1] > adx_threshold)
                
                entry_long = False
                entry_short = False
                
                if entry_signal == "supertrend":
                    entry_long = (st_dir[i-1] == 1)
                    entry_short = (st_dir[i-1] == -1)
                elif entry_signal == "rsi_pullback" and rsi is not None:
                    entry_long = (rsi[i-1] > rsi[i-2]) and (rsi[i-2] <= rsi_pullback_lower)
                    entry_short = (rsi[i-1] < rsi[i-2]) and (rsi[i-2] >= rsi_pullback_upper)
                
                if entry_long and trend_ok_long and adx_ok:
                    pos_dir = "long"
                elif entry_short and trend_ok_short and adx_ok:
                    pos_dir = "short"
                    
                if pos_dir is not None:
                    entry_price = open_p[i]
                    entry_time = t_curr
                    in_pos = True
                    phase = 1
                    
                    if sl_type == "supertrend":
                        sl = st_val[i-1]
                    else: # atr
                        sl = entry_price - sl_atr_mult * atr[i-1] if pos_dir == "long" else entry_price + sl_atr_mult * atr[i-1]
                    
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
        net_p = sum(trades)
        wins = [t for t in trades if t > 0]
        losses = [t for t in trades if t <= 0]
        pf = sum(wins) / abs(sum(losses)) if losses and sum(losses) != 0 else float('inf')
        win_rate = len(wins) / total_t if total_t > 0 else 0
        
        start_t = times[1000]
        end_t = times[-1]
        days = (end_t - start_t).total_seconds() / (24 * 3600)
        cagr = (equity / 1000.0) ** (365.25 / days) - 1
        
        return {
            "total_trades": total_t,
            "net_pnl": net_p,
            "win_rate": win_rate,
            "profit_factor": pf,
            "cagr": cagr,
            "max_dd": max_dd,
            "final_equity": equity
        }

    def run_portfolio(self, datasets: dict, configs: dict, risk_percent: float = 0.02) -> dict:
        """
        Runs the joint portfolio simulation for BTC, ETH, SOL, LINK, DOGE.
        """
        contracts = list(datasets.keys())
        
        # Unpack parameters into fast numpy arrays for each asset
        times = None
        n = 9999999
        
        highs = {}
        lows = {}
        closes = {}
        opens = {}
        st_vals = {}
        st_dirs = {}
        h1_st_vals = {}
        h1_st_dirs = {}
        h1_closes = {}
        adxs = {}
        rsis = {}
        atrs = {}
        h1_mas = {}
        
        face_values = {}
        slippages = {}
        
        for contract in contracts:
            df = datasets[contract]
            face_value, slippage = self.get_contract_params(contract)
            face_values[contract] = face_value
            slippages[contract] = slippage
            
            highs[contract] = df['high'].values
            lows[contract] = df['low'].values
            closes[contract] = df['close'].values
            opens[contract] = df['open'].values
            st_vals[contract] = df['st_val'].values
            st_dirs[contract] = df['st_dir'].values
            h1_st_vals[contract] = df['h1_st_val'].values
            h1_st_dirs[contract] = df['h1_st_dir'].values
            h1_closes[contract] = df['h1_close'].values
            adxs[contract] = df['adx_aligned'].values
            
            rsis[contract] = df['rsi_30m'].values if 'rsi_30m' in df.columns else None
            atrs[contract] = df['atr_val'].values if 'atr_val' in df.columns else None
            
            cfg = configs[contract]
            trend_filter = cfg.get("trend_filter_1h", "ema")
            dema_period = cfg.get("dema_period", 150)
            if trend_filter == "ema":
                h1_mas[contract] = df[f'h1_ema_{dema_period}'].values
            elif trend_filter == "dema":
                h1_mas[contract] = df[f'h1_dema_{dema_period}'].values
            else:
                h1_mas[contract] = np.zeros(len(df))
                
            n = min(n, len(df))
            if times is None:
                times = df.index.to_pydatetime()
                
        initial_capital = 1000.0
        equity = initial_capital
        capital_history = []
        trades = []
        
        # Sizing and state maps
        in_pos = {c: False for c in contracts}
        pos_dir = {c: None for c in contracts}
        entry_price = {c: 0.0 for c in contracts}
        sl = {c: 0.0 for c in contracts}
        tp = {c: None for c in contracts}
        phase = {c: 0 for c in contracts}
        qty = {c: 0 for c in contracts}
        consecutive_losses = {c: 0 for c in contracts}
        cooldown_until = {c: None for c in contracts}
        entry_time = {c: None for c in contracts}
        
        cb_until = None
        
        for i in range(1000, n):
            t_curr = times[i]
            
            if cb_until and t_curr >= cb_until:
                cb_until = None
                
            # Compute current portfolio equity
            current_equity = equity
            for c in contracts:
                if cooldown_until[c] and t_curr >= cooldown_until[c]:
                    consecutive_losses[c] = 0
                    cooldown_until[c] = None
                if in_pos[c]:
                    pnl = (closes[c][i] - entry_price[c]) * qty[c] * face_values[c] if pos_dir[c] == "long" else (entry_price[c] - closes[c][i]) * qty[c] * face_values[c]
                    current_equity += pnl
                    
            capital_history.append((t_curr, current_equity))
            
            closed_this_bar = {c: False for c in contracts}
            
            # 1. EVALUATE EXITS
            for c in contracts:
                if in_pos[c]:
                    is_stopped = False
                    is_tp_hit = False
                    exit_price = sl[c]
                    exit_reason = "stop_loss"
                    
                    if pos_dir[c] == "long":
                        if lows[c][i] <= sl[c]:
                            is_stopped = True
                            exit_price = min(opens[c][i], sl[c])
                        if tp[c] is not None and highs[c][i] >= tp[c]:
                            is_tp_hit = True
                            if not is_stopped:
                                exit_price = max(opens[c][i], tp[c])
                                exit_reason = "take_profit"
                    else: # short
                        if highs[c][i] >= sl[c]:
                            is_stopped = True
                            exit_price = max(opens[c][i], sl[c])
                        if tp[c] is not None and lows[c][i] <= tp[c]:
                            is_tp_hit = True
                            if not is_stopped:
                                exit_price = min(opens[c][i], tp[c])
                                exit_reason = "take_profit"
                                
                    if is_stopped or (is_tp_hit and exit_reason == "take_profit"):
                        actual_exit = exit_price - slippages[c] if pos_dir[c] == "long" else exit_price + slippages[c]
                        pnl = (actual_exit - entry_price[c]) * qty[c] * face_values[c] if pos_dir[c] == "long" else (entry_price[c] - actual_exit) * qty[c] * face_values[c]
                        fee = (entry_price[c] + actual_exit) * qty[c] * face_values[c] * self.fee_rate
                        net_pnl = pnl - fee
                        
                        equity += net_pnl
                        if net_pnl < 0:
                            consecutive_losses[c] += 1
                            if consecutive_losses[c] >= 3:
                                cooldown_until[c] = t_curr + timedelta(hours=48)
                        else:
                            consecutive_losses[c] = 0
                        if equity <= 350.0:
                            cb_until = t_curr + timedelta(days=7)
                            
                        trades.append({
                            "Symbol": c,
                            "Net PnL": net_pnl,
                            "Fee": fee
                        })
                        in_pos[c] = False
                        pos_dir[c] = None
                        tp[c] = None
                        closed_this_bar[c] = True
                    else:
                        # Technical exit
                        tech_exit = (phase[c] == 3 and h1_st_dirs[c][i-1] == -1 if pos_dir[c] == "long" else phase[c] == 3 and h1_st_dirs[c][i-1] == 1) or \
                                    ((phase[c] == 1 or phase[c] == 2) and st_dirs[c][i-1] == -1 if pos_dir[c] == "long" else (phase[c] == 1 or phase[c] == 2) and st_dirs[c][i-1] == 1)
                        if tech_exit:
                            exit_price = opens[c][i]
                            actual_exit = exit_price - slippages[c] if pos_dir[c] == "long" else exit_price + slippages[c]
                            pnl = (actual_exit - entry_price[c]) * qty[c] * face_values[c] if pos_dir[c] == "long" else (entry_price[c] - actual_exit) * qty[c] * face_values[c]
                            fee = (entry_price[c] + actual_exit) * qty[c] * face_values[c] * self.fee_rate
                            net_pnl = pnl - fee
                            
                            equity += net_pnl
                            if net_pnl < 0:
                                consecutive_losses[c] += 1
                                if consecutive_losses[c] >= 3:
                                    cooldown_until[c] = t_curr + timedelta(hours=48)
                            else:
                                consecutive_losses[c] = 0
                            if equity <= 350.0:
                                cb_until = t_curr + timedelta(days=7)
                                
                            trades.append({
                                "Symbol": c,
                                "Net PnL": net_pnl,
                                "Fee": fee
                            })
                            in_pos[c] = False
                            pos_dir[c] = None
                            tp[c] = None
                            closed_this_bar[c] = True
                        else:
                            # Update trailing stop loss
                            is_long = (pos_dir[c] == "long")
                            act_risk = current_equity * risk_percent
                            if 350.0 <= current_equity <= 500.0:
                                act_risk = 10.0
                            buf_u = act_risk * 1.0
                            
                            locked_price = entry_price[c] + (buf_u / (qty[c] * face_values[c])) if is_long else entry_price[c] - (buf_u / (qty[c] * face_values[c]))
                            st_30 = st_vals[c][i-1]
                            st_1h = h1_st_vals[c][i-1]
                            
                            is_surv = st_30 < entry_price[c] if is_long else st_30 > entry_price[c]
                            if is_surv:
                                phase[c] = 1
                                sl[c] = max(st_30, sl[c]) if is_long else min(st_30, sl[c])
                            else:
                                is_hr = st_1h > locked_price if is_long else st_1h < locked_price
                                if is_hr:
                                    phase[c] = 3
                                    sl[c] = max(st_1h, sl[c]) if is_long else min(st_1h, sl[c])
                                else:
                                    phase[c] = 2
                                    cand = st_30
                                    if is_long:
                                        if st_30 > locked_price: cand = locked_price
                                        sl[c] = max(cand, sl[c])
                                    else:
                                        if st_30 < locked_price: cand = locked_price
                                        sl[c] = min(cand, sl[c])

            # 2. EVALUATE ENTRIES
            for c in contracts:
                if not in_pos[c] and not closed_this_bar[c] and not cb_until and not cooldown_until[c]:
                    cfg = configs[c]
                    trend_filter = cfg.get("trend_filter_1h", "ema")
                    adx_threshold = cfg.get("adx_threshold", 25.0)
                    tp_ratio = cfg.get("tp_ratio", 5.0)
                    entry_signal = cfg.get("entry_signal", "supertrend")
                    rsi_pullback_lower = cfg.get("rsi_pullback_lower", 40.0)
                    rsi_pullback_upper = cfg.get("rsi_pullback_upper", 60.0)
                    sl_type = cfg.get("sl_type", "supertrend")
                    sl_atr_mult = cfg.get("sl_atr_mult", 2.5)
                    
                    h1_c = h1_closes[c][i-1]
                    ma_v = h1_mas[c][i-1]
                    
                    trend_ok_long = (h1_c > ma_v) if trend_filter != "none" else True
                    trend_ok_short = (h1_c < ma_v) if trend_filter != "none" else True
                    
                    adx_ok = (adxs[c][i-1] > adx_threshold)
                    
                    entry_long = False
                    entry_short = False
                    
                    if entry_signal == "supertrend":
                        entry_long = (st_dirs[c][i-1] == 1)
                        entry_short = (st_dirs[c][i-1] == -1)
                    elif entry_signal == "rsi_pullback" and rsis[c] is not None:
                        entry_long = (rsis[c][i-1] > rsis[c][i-2]) and (rsis[c][i-2] <= rsi_pullback_lower)
                        entry_short = (rsis[c][i-1] < rsis[c][i-2]) and (rsis[c][i-2] >= rsi_pullback_upper)
                    
                    if entry_long and trend_ok_long and adx_ok:
                        pos_dir[c] = "long"
                    elif entry_short and trend_ok_short and adx_ok:
                        pos_dir[c] = "short"
                        
                    if pos_dir[c] is not None:
                        entry_price[c] = opens[c][i]
                        entry_time[c] = t_curr
                        in_pos[c] = True
                        phase[c] = 1
                        
                        if sl_type == "supertrend":
                            sl[c] = st_vals[c][i-1]
                        else: # atr
                            sl[c] = entry_price[c] - sl_atr_mult * atrs[c][i-1] if pos_dir[c] == "long" else entry_price[c] + sl_atr_mult * atrs[c][i-1]
                        
                        act_risk = current_equity * risk_percent
                        if 350.0 <= current_equity <= 500.0:
                            act_risk = 10.0
                        sl_d = abs(entry_price[c] - sl[c])
                        if sl_d > 0:
                            qty[c] = int(min(act_risk / (sl_d * face_values[c]), (current_equity * 5.0) / (entry_price[c] * face_values[c])))
                            if qty[c] <= 0: qty[c] = 1
                            if tp_ratio is not None:
                                tp[c] = entry_price[c] + tp_ratio * sl_d if pos_dir[c] == "long" else entry_price[c] - tp_ratio * sl_d
                            else:
                                tp[c] = None
                        else:
                            qty[c] = 1
                            tp[c] = None
                            
        # Calculate final stats
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
        
        start_t = times[1000]
        end_t = times[-1]
        days = (end_t - start_t).total_seconds() / (24 * 3600)
        cagr = (equity / initial_capital) ** (365.25 / days) - 1
        
        # Sharpe ratio (daily returns)
        df_cap.set_index("timestamp", inplace=True)
        df_daily = df_cap["equity"].resample("D").last().ffill()
        df_daily_ret = df_daily.pct_change().dropna()
        daily_vol = df_daily_ret.std()
        daily_mean = df_daily_ret.mean()
        sharpe = (daily_mean / daily_vol) * np.sqrt(365.25) if daily_vol != 0 else 0.0
        
        return {
            "total_trades": total_t,
            "win_rate": win_rate,
            "profit_factor": pf,
            "cagr": cagr,
            "max_dd": max_dd,
            "sharpe": sharpe,
            "final_equity": equity
        }


def run_optimizer():
    contracts = ["BTC_USDT", "ETH_USDT", "SOL_USDT", "LINK_USDT", "DOGE_USDT"]
    datasets = {}
    
    print("=" * 80)
    print("🚀 PRECOMPUTING INDICATORS FOR 5-ASSET 5-YEAR HISTORY (UPGRADED)")
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
        df_30m['rsi_30m'] = calculate_rsi(df_30m['close'], 14)
        
        # 1H indicators
        st_res_1h = calculate_supertrend(df_1h, 10, 3.0)
        df_1h['st_val'] = st_res_1h['supertrend']
        df_1h['st_dir'] = st_res_1h['direction']
        df_1h['adx'] = calculate_adx(df_1h, 16)
        
        for p in [150, 200]:
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
        for p in [150, 200]:
            rename_cols[f'dema_{p}'] = f'h1_dema_{p}'
            rename_cols[f'ema_{p}'] = f'h1_ema_{p}'
            
        df_1h_aligned = df_1h_aligned.reset_index().rename(columns=rename_cols)
        
        # Merge
        df_30m = df_30m.reset_index()
        df_30m['timestamp'] = df_30m['timestamp'].astype('datetime64[ns]')
        df_1h_aligned['timestamp'] = df_1h_aligned['timestamp'].astype('datetime64[ns]')
        
        merge_cols = ['timestamp', 'h1_st_val', 'h1_st_dir', 'h1_adx', 'h1_close']
        for p in [150, 200]:
            merge_cols.extend([f'h1_dema_{p}', f'h1_ema_{p}'])
            
        df_merged = pd.merge_asof(
            df_30m,
            df_1h_aligned[merge_cols],
            on='timestamp',
            direction='backward'
        ).rename(columns={'h1_adx': 'adx_aligned'})
        
        df_merged.set_index('timestamp', inplace=True)
        datasets[contract] = df_merged
        
    sim = FastSimulator5Asset()
    
    # 1. Single Asset Optimization Sweep
    print("\n" + "=" * 80)
    print("🔍 RUNNING SINGLE-ASSET STRATEGY SWEEPS (UPGRADED SPACE, 5-YEAR CYCLE)")
    print("=" * 80)
    
    top_configs = {}
    
    for contract in contracts:
        print(f"\nSweeping configurations for {contract}...")
        df_merged = datasets[contract]
        
        configs = []
        # Generate configurations:
        # A. SuperTrend Breakout
        for tf_filter in ["ema", "dema", "none"]:
            for ma_period in [150, 200]:
                for tp in [4.0, 5.0, 6.0, 8.0, 10.0]:
                    for adx_t in [25.0, 30.0]:
                        configs.append({
                            "entry_signal": "supertrend",
                            "trend_filter_1h": tf_filter,
                            "dema_period": ma_period,
                            "tp_ratio": tp,
                            "adx_threshold": adx_t,
                            "sl_type": "supertrend"
                        })
                        
        # B. RSI Pullback
        for tf_filter in ["ema", "dema"]:
            for ma_period in [150, 200]:
                for tp in [3.0, 4.0, 5.0, 6.0]:
                    for rsi_low, rsi_high in [(40.0, 60.0), (45.0, 55.0)]:
                        for adx_t in [20.0, 25.0]:
                            for sl_atr in [2.0, 2.5, 3.0]:
                                configs.append({
                                    "entry_signal": "rsi_pullback",
                                    "trend_filter_1h": tf_filter,
                                    "dema_period": ma_period,
                                    "tp_ratio": tp,
                                    "adx_threshold": adx_t,
                                    "rsi_pullback_lower": rsi_low,
                                    "rsi_pullback_upper": rsi_high,
                                    "sl_type": "atr",
                                    "sl_atr_mult": sl_atr
                                })
                        
        print(f"Generated {len(configs)} configuration candidates. Running fast simulations...")
        
        best_configs = []
        for cfg in configs:
            res = sim.run_single(df_merged, contract, cfg)
            cagr = res["cagr"]
            max_dd = abs(res["max_dd"])
            
            # Keep all configurations (no filtering) so we can sort them and get the absolute best
            cfg_result = cfg.copy()
            cfg_result["metrics"] = res
            best_configs.append(cfg_result)
                
        # Sort by CAGR
        best_configs = sorted(best_configs, key=lambda x: x["metrics"]["cagr"], reverse=True)
        top_configs[contract] = best_configs[:5]  # Save top 5 configs
        
        best_one = best_configs[0]
        print(f"  ✅ Best Config for {contract}:")
        print(f"     Signal: {best_one.get('entry_signal')}, Filter: {best_one['trend_filter_1h']} ({best_one['dema_period']}), TP: {best_one['tp_ratio']}R, SL: {best_one.get('sl_type')} (mult: {best_one.get('sl_atr_mult', 'N/A')})")
        print(f"     CAGR: {best_one['metrics']['cagr']*100:+.2f}%, Max DD: {best_one['metrics']['max_dd']*100:.2f}%, PF: {best_one['metrics']['profit_factor']:.2f}")
            
    # 2. Portfolio Sizing & Asset Combination Sweep
    print("\n" + "=" * 80)
    print("💼 RUNNING JOINT PORTFOLIO OPTIMIZATIONS (ASSET COMBINATIONS & SIZING)")
    print("=" * 80)
    
    # We take the Rank 1 config for each asset
    portfolio_configs = {}
    for contract in contracts:
        portfolio_configs[contract] = top_configs[contract][0]
        
    print("Selected Optimal Configs for each Asset:")
    for c in contracts:
        cfg = portfolio_configs[c]
        print(f"  - {c}: Signal={cfg.get('entry_signal')}, Filter={cfg['trend_filter_1h']}_{cfg['dema_period']}, TP={cfg['tp_ratio']}R, SL={cfg.get('sl_type')}")
        
    # Generate all combinations of contracts of size 2 to 5 that include BTC_USDT
    other_contracts = [c for c in contracts if c != "BTC_USDT"]
    all_combinations = []
    for r in range(1, 5):
        for comb in itertools.combinations(other_contracts, r):
            all_combinations.append(["BTC_USDT"] + list(comb))
            
    print(f"\nGenerated {len(all_combinations)} portfolio asset combinations containing BTC_USDT.")
    
    portfolio_sweep_results = []
    
    for comb in all_combinations:
        comb_str = "+".join([c.split("_")[0] for c in comb])
        print(f"\nTesting combination: {comb_str}")
        
        # Sub-datasets and sub-configs
        sub_datasets = {c: datasets[c] for c in comb}
        sub_configs = {c: portfolio_configs[c] for c in comb}
        
        for r_size in [0.0035, 0.005, 0.0075, 0.01, 0.0125, 0.015, 0.02]:
            res = sim.run_portfolio(sub_datasets, sub_configs, risk_percent=r_size)
            cagr = res["cagr"]
            max_dd = abs(res["max_dd"])
            pf = res["profit_factor"]
            sharpe = res["sharpe"]
            
            print(f"  Risk: {r_size*100:5.2f}% | CAGR: {cagr*100:+7.2f}% | Max DD: {max_dd*100:6.2f}% | Sharpe: {sharpe:5.2f} | Equity: ${res['final_equity']:.2f}")
            
            portfolio_sweep_results.append({
                "assets": comb_str,
                "risk_size_pct": r_size * 100,
                "cagr_pct": cagr * 100,
                "max_dd_pct": max_dd * 100,
                "profit_factor": pf,
                "sharpe": sharpe,
                "final_equity": res["final_equity"],
                "total_trades": res["total_trades"],
                "win_rate_pct": res["win_rate"] * 100
            })
        
    # Save results to JSON file
    final_output = {
        "single_asset_top_configs": top_configs,
        "portfolio_risk_sweep": portfolio_sweep_results
    }
    
    filepath = os.path.join(RESULTS_DIR, "optimal_5y_portfolio.json")
    with open(filepath, "w") as f:
        json.dump(final_output, f, indent=4)
        
    print("\n" + "=" * 80)
    print(f"🎉 Optimization Completed! Detailed JSON saved to: backtest/results/optimal_5y_portfolio.json")
    print("=" * 80)


if __name__ == "__main__":
    run_optimizer()
