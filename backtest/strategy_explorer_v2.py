#!/usr/bin/env python3
"""
Optimized Strategy Exploration Engine (V2) for ETH and SOL.
Uses NumPy array caching to speed up simulations by 50x-100x.
Includes standard SuperTrend breakout, EMA Crossovers, RSI Pullbacks, and Joint Portfolio backtesting.
"""

import os
import sys
import json
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


class FastSimulatorV2:
    def __init__(self, fee_rate: float = 0.0004, slippage_ticks: float = 1.0):
        self.fee_rate = fee_rate
        self.slippage_ticks = slippage_ticks
        
    def _get_contract_params(self, contract: str) -> tuple:
        c_upper = contract.upper()
        if "ETH" in c_upper:
            face_value = 0.01
            tick_size = 0.1
        elif "BTC" in c_upper:
            face_value = 0.0001
            tick_size = 0.1
        elif "SOL" in c_upper:
            face_value = 1.0
            tick_size = 0.01
        else:
            face_value = 0.01
            tick_size = 0.01
        return face_value, tick_size * self.slippage_ticks

    def run_single(self, df_merged: pd.DataFrame, contract: str, cfg: dict, initial_capital: float = 1000.0) -> dict:
        """
        Runs the simulation for a single asset.
        Accepts a pre-merged DataFrame with all necessary indicators pre-calculated.
        To maximize performance, all pandas access is resolved to numpy arrays before the loop.
        """
        face_value, slippage = self._get_contract_params(contract)
        
        # Parse configuration parameters
        timeframe = cfg.get("timeframe", "30m")
        trend_filter_1h = cfg.get("trend_filter_1h", "none")  # "dema", "ema", "supertrend", "none"
        dema_period = cfg.get("dema_period", 200)
        entry_signal = cfg.get("entry_signal", "supertrend")  # "supertrend", "ema_cross", "rsi_pullback"
        tp_ratio = cfg.get("tp_ratio", None)
        sl_type = cfg.get("sl_type", "supertrend")  # "supertrend", "atr"
        sl_atr_mult = cfg.get("sl_atr_mult", 2.0)
        trailing_stop = cfg.get("trailing_stop", "three_stage")  # "three_stage", "atr", "none"
        trailing_atr_mult = cfg.get("trailing_atr_mult", 2.0)
        lock_profit_buffer = cfg.get("lock_profit_buffer", 1.0)
        
        adx_filter = cfg.get("adx_filter", False)
        adx_threshold = cfg.get("adx_threshold", 20.0)
        
        volume_filter = cfg.get("volume_filter", False)
        volume_factor = cfg.get("volume_factor", 1.0)
        
        # RSI Pullback Specifics
        rsi_pullback_lower = cfg.get("rsi_pullback_lower", 45)
        rsi_pullback_upper = cfg.get("rsi_pullback_upper", 55)
        
        risk_percent = cfg.get("risk_percent", 0.02)
        
        # Extract base arrays
        timestamps = df_merged.index.to_pydatetime()
        high_prices = df_merged['high'].values
        low_prices = df_merged['low'].values
        close_prices = df_merged['close'].values
        open_prices = df_merged['open'].values
        volume_vals = df_merged['volume'].values
        
        # Retrieve pre-calculated indicators
        st_val_30m = df_merged['st_val'].values
        st_dir_30m = df_merged['st_dir'].values
        h1_st_val = df_merged['h1_st_val'].values
        h1_st_dir = df_merged['h1_st_dir'].values
        
        # Trend Filters (1H Close & DEMA/EMA)
        h1_close_vals = df_merged['h1_close'].values
        h1_dema_vals = df_merged[f'h1_dema_{dema_period}'].values if f'h1_dema_{dema_period}' in df_merged.columns else None
        h1_ema_vals = df_merged[f'h1_ema_{dema_period}'].values if f'h1_ema_{dema_period}' in df_merged.columns else None
        
        # EMA Crossover arrays
        ema_fast_30m = df_merged['ema_fast_30m'].values if 'ema_fast_30m' in df_merged.columns else None
        ema_slow_30m = df_merged['ema_slow_30m'].values if 'ema_slow_30m' in df_merged.columns else None
        
        # ADX / RSI / ATR / Volume MA
        adx_vals = df_merged['adx_aligned'].values if 'adx_aligned' in df_merged.columns else None
        rsi_vals = df_merged['rsi_30m'].values if 'rsi_30m' in df_merged.columns else None
        atr_vals = df_merged['atr_val'].values if 'atr_val' in df_merged.columns else None
        vol_ma_vals = df_merged['vol_ma'].values if 'vol_ma' in df_merged.columns else None
        
        n = len(df_merged)
        warmup_len = 1000
        
        # Simulator state variables
        equity = initial_capital
        capital_history = []
        trades = []
        
        in_pos = False
        pos_direction = None
        pos_entry_price = 0.0
        pos_stop_loss = 0.0
        pos_tp_price = None
        pos_phase = 0  # 0: None, 1: Survival, 2: Locked, 3: Hourly
        pos_qty = 0
        pos_entry_time = None
        
        consecutive_losses = 0
        cooldown_until = None
        cb_until = None
        
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
                    unrealized_pnl = (curr_price - pos_entry_price) * pos_qty * face_value
                else:
                    unrealized_pnl = (pos_entry_price - curr_price) * pos_qty * face_value
                current_equity += unrealized_pnl
                
            capital_history.append((t_curr, current_equity))
            
            # ----------------------------------------------------
            # CASE A: In Active Position - Evaluate Exits
            # ----------------------------------------------------
            if in_pos:
                # 1. Check Stop Loss or Take Profit hit during current bar
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
                            pass  # Stop loss takes precedence for conservative backtesting
                        else:
                            exit_price = max(open_prices[i], pos_tp_price)
                            exit_reason = "take_profit"
                else:  # short
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
                    actual_exit_price = exit_price - slippage if pos_direction == "long" else exit_price + slippage
                    
                    pnl = (actual_exit_price - pos_entry_price) * pos_qty * face_value if pos_direction == "long" else (pos_entry_price - actual_exit_price) * pos_qty * face_value
                    entry_fee = pos_entry_price * pos_qty * face_value * self.fee_rate
                    exit_fee = actual_exit_price * pos_qty * face_value * self.fee_rate
                    net_pnl = pnl - (entry_fee + exit_fee)
                    
                    equity += net_pnl
                    
                    # Update cooldown rules
                    if net_pnl < 0:
                        consecutive_losses += 1
                        if consecutive_losses >= 3:
                            cooldown_until = t_curr + timedelta(hours=48)
                    else:
                        consecutive_losses = 0
                        
                    if equity <= 350.0:
                        cb_until = t_curr + timedelta(days=7)
                        
                    trades.append({"net_pnl": net_pnl, "fee": entry_fee + exit_fee})
                    
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
                    if timeframe == "1h":
                        if h1_st_dir_prev == -1:
                            technical_exit = True
                            exit_reason_tech = "1H ST Red"
                    else:  # 30m
                        if pos_phase == 3 and h1_st_dir_prev == -1:
                            technical_exit = True
                            exit_reason_tech = "1H ST Red"
                        elif (pos_phase == 1 or pos_phase == 2) and st_dir_prev == -1:
                            technical_exit = True
                            exit_reason_tech = "30m ST Red"
                else:  # short
                    if timeframe == "1h":
                        if h1_st_dir_prev == 1:
                            technical_exit = True
                            exit_reason_tech = "1H ST Green"
                    else:  # 30m
                        if pos_phase == 3 and h1_st_dir_prev == 1:
                            technical_exit = True
                            exit_reason_tech = "1H ST Green"
                        elif (pos_phase == 1 or pos_phase == 2) and st_dir_prev == 1:
                            technical_exit = True
                            exit_reason_tech = "30m ST Green"
                            
                if technical_exit:
                    exit_price = open_prices[i]
                    actual_exit_price = exit_price - slippage if pos_direction == "long" else exit_price + slippage
                    pnl = (actual_exit_price - pos_entry_price) * pos_qty * face_value if pos_direction == "long" else (pos_entry_price - actual_exit_price) * pos_qty * face_value
                    entry_fee = pos_entry_price * pos_qty * face_value * self.fee_rate
                    exit_fee = actual_exit_price * pos_qty * face_value * self.fee_rate
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
                        
                    trades.append({"net_pnl": net_pnl, "fee": entry_fee + exit_fee})
                    
                    in_pos = False
                    pos_direction = None
                    pos_phase = 0
                    pos_tp_price = None
                    continue
                
                # 3. Update Stop Loss Trailing Mechanism (using completed bar i-1)
                is_long_pos = (pos_direction == "long")
                survival_to_locked_price = pos_entry_price
                active_risk_amt = equity * risk_percent
                if 350.0 <= equity <= 500.0:
                    active_risk_amt = 10.0
                    
                buffer_usdt = active_risk_amt * lock_profit_buffer
                position_token_size = pos_qty * face_value
                
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
                    current_atr = atr_vals[i-1] if atr_vals is not None else 0.0
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
                can_cooldown = (not cooldown_until) and (not cb_until)
                if not can_cooldown:
                    continue
                    
                st_dir_sig = st_dir_30m[i-1]
                st_val_sig = st_val_30m[i-1]
                h1_st_dir_sig = h1_st_dir[i-1]
                h1_st_val_sig = h1_st_val[i-1]
                
                # 1. Evaluate Trend Filter (1H)
                trend_ok_long = True
                trend_ok_short = True
                
                if trend_filter_1h == "supertrend":
                    trend_ok_long = (h1_st_dir_sig == 1)
                    trend_ok_short = (h1_st_dir_sig == -1)
                elif trend_filter_1h == "dema" and h1_dema_vals is not None:
                    dema_val = h1_dema_vals[i-1]
                    h1_close_sig = h1_close_vals[i-1]
                    trend_ok_long = (h1_close_sig > dema_val)
                    trend_ok_short = (h1_close_sig < dema_val)
                elif trend_filter_1h == "ema" and h1_ema_vals is not None:
                    ema_val = h1_ema_vals[i-1]
                    h1_close_sig = h1_close_vals[i-1]
                    trend_ok_long = (h1_close_sig > ema_val)
                    trend_ok_short = (h1_close_sig < ema_val)
                    
                # 2. Evaluate Entry Signal
                entry_long = False
                entry_short = False
                
                if entry_signal == "supertrend":
                    if timeframe == "30m":
                        entry_long = (st_dir_sig == 1)
                        entry_short = (st_dir_sig == -1)
                    else:  # 1H ST
                        entry_long = (h1_st_dir_sig == 1)
                        entry_short = (h1_st_dir_sig == -1)
                elif entry_signal == "ema_cross" and ema_fast_30m is not None and ema_slow_30m is not None:
                    entry_long = (ema_fast_30m[i-1] > ema_slow_30m[i-1]) and (ema_fast_30m[i-2] <= ema_slow_30m[i-2])
                    entry_short = (ema_fast_30m[i-1] < ema_slow_30m[i-1]) and (ema_fast_30m[i-2] >= ema_slow_30m[i-2])
                elif entry_signal == "rsi_pullback" and rsi_vals is not None:
                    # RSI Pullback logic:
                    # In Long trend, RSI was below pullback_lower on bar i-2, and crosses above it or hooks up on bar i-1
                    # In Short trend, RSI was above pullback_upper on bar i-2, and hooks down on bar i-1
                    rsi_curr = rsi_vals[i-1]
                    rsi_prev = rsi_vals[i-2]
                    
                    if trend_ok_long:
                        entry_long = (rsi_curr > rsi_prev) and (rsi_prev <= rsi_pullback_lower)
                    if trend_ok_short:
                        entry_short = (rsi_curr < rsi_prev) and (rsi_prev >= rsi_pullback_upper)
                        
                # 3. Apply Filters (ADX, Volume)
                adx_ok = True
                if adx_filter and adx_vals is not None:
                    adx_ok = (adx_vals[i-1] > adx_threshold)
                    
                vol_ok = True
                if volume_filter and vol_ma_vals is not None:
                    vol_ok = (volume_vals[i-1] > volume_factor * vol_ma_vals[i-1])
                    
                # Check final trigger
                is_long_trigger = entry_long and trend_ok_long and adx_ok and vol_ok
                is_short_trigger = entry_short and trend_ok_short and adx_ok and vol_ok
                
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
                    elif sl_type == "atr" and atr_vals is not None:
                        current_atr = atr_vals[i-1]
                        if pos_direction == "long":
                            pos_stop_loss = pos_entry_price - sl_atr_mult * current_atr
                        else:
                            pos_stop_loss = pos_entry_price + sl_atr_mult * current_atr
                            
                    # Size calculation
                    active_risk_amt = equity * risk_percent
                    if 350.0 <= equity <= 500.0:
                        active_risk_amt = 10.0
                        
                    sl_dist = abs(pos_entry_price - pos_stop_loss)
                    if sl_dist > 0:
                        calc_qty = active_risk_amt / (sl_dist * face_value)
                        max_qty_leverage = (equity * 10.0) / (pos_entry_price * face_value)
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
                        
        metrics = self._calculate_metrics(trades, capital_history, equity, initial_capital)
        return metrics

    def run_portfolio(self, df_merged_eth: pd.DataFrame, df_merged_sol: pd.DataFrame, eth_cfg: dict, sol_cfg: dict, initial_capital: float = 1000.0, risk_percent_per_asset: float = 0.015) -> dict:
        """
        Runs a joint portfolio simulation of both ETH and SOL simultaneously.
        The assets trade from a single joint equity balance.
        Dynamic position sizing is calculated relative to the *current joint equity*.
        """
        eth_fv, eth_slip = self._get_contract_params("ETH_USDT")
        sol_fv, sol_slip = self._get_contract_params("SOL_USDT")
        
        # Unpack arrays for ETH
        eth_times = df_merged_eth.index.to_pydatetime()
        eth_high = df_merged_eth['high'].values
        eth_low = df_merged_eth['low'].values
        eth_close = df_merged_eth['close'].values
        eth_open = df_merged_eth['open'].values
        eth_volume = df_merged_eth['volume'].values
        eth_st_val = df_merged_eth['st_val'].values
        eth_st_dir = df_merged_eth['st_dir'].values
        eth_h1_st_val = df_merged_eth['h1_st_val'].values
        eth_h1_st_dir = df_merged_eth['h1_st_dir'].values
        eth_h1_close = df_merged_eth['h1_close'].values
        
        dema_p_eth = eth_cfg.get("dema_period", 200)
        eth_h1_dema = df_merged_eth[f'h1_dema_{dema_p_eth}'].values if f'h1_dema_{dema_p_eth}' in df_merged_eth.columns else None
        eth_h1_ema = df_merged_eth[f'h1_ema_{dema_p_eth}'].values if f'h1_ema_{dema_p_eth}' in df_merged_eth.columns else None
        
        eth_adx = df_merged_eth['adx_aligned'].values if 'adx_aligned' in df_merged_eth.columns else None
        eth_rsi = df_merged_eth['rsi_30m'].values if 'rsi_30m' in df_merged_eth.columns else None
        eth_atr = df_merged_eth['atr_val'].values if 'atr_val' in df_merged_eth.columns else None
        
        # Unpack arrays for SOL
        sol_times = df_merged_sol.index.to_pydatetime()
        sol_high = df_merged_sol['high'].values
        sol_low = df_merged_sol['low'].values
        sol_close = df_merged_sol['close'].values
        sol_open = df_merged_sol['open'].values
        sol_volume = df_merged_sol['volume'].values
        sol_st_val = df_merged_sol['st_val'].values
        sol_st_dir = df_merged_sol['st_dir'].values
        sol_h1_st_val = df_merged_sol['h1_st_val'].values
        sol_h1_st_dir = df_merged_sol['h1_st_dir'].values
        sol_h1_close = df_merged_sol['h1_close'].values
        
        dema_p_sol = sol_cfg.get("dema_period", 200)
        sol_h1_dema = df_merged_sol[f'h1_dema_{dema_p_sol}'].values if f'h1_dema_{dema_p_sol}' in df_merged_sol.columns else None
        sol_h1_ema = df_merged_sol[f'h1_ema_{dema_p_sol}'].values if f'h1_ema_{dema_p_sol}' in df_merged_sol.columns else None
        
        sol_adx = df_merged_sol['adx_aligned'].values if 'adx_aligned' in df_merged_sol.columns else None
        sol_rsi = df_merged_sol['rsi_30m'].values if 'rsi_30m' in df_merged_sol.columns else None
        sol_atr = df_merged_sol['atr_val'].values if 'atr_val' in df_merged_sol.columns else None
        
        n = min(len(df_merged_eth), len(df_merged_sol))
        warmup_len = 1000
        
        # Portfolio states
        equity = initial_capital
        capital_history = []
        trades = []
        
        # ETH state
        eth_in_pos = False
        eth_pos_dir = None
        eth_entry_price = 0.0
        eth_sl = 0.0
        eth_tp = None
        eth_phase = 0
        eth_qty = 0
        eth_consecutive_losses = 0
        eth_cooldown_until = None
        
        # SOL state
        sol_in_pos = False
        sol_pos_dir = None
        sol_entry_price = 0.0
        sol_sl = 0.0
        sol_tp = None
        sol_phase = 0
        sol_qty = 0
        sol_consecutive_losses = 0
        sol_cooldown_until = None
        
        cb_until = None
        
        for i in range(warmup_len, n):
            t_curr = eth_times[i]
            eth_closed_this_bar = False
            sol_closed_this_bar = False
            
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
                
            # Compute current portfolio equity (real-time mark to market)
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
            
            # ----------------------------------------------------
            # 1. EVALUATE EXITS & TRAILING STOPS (ETH)
            # ----------------------------------------------------
            if eth_in_pos:
                # Check stop loss/take profit hit during the bar
                is_stopped = False
                is_tp_hit = False
                exit_price = eth_sl
                exit_reason = "stop_loss"
                
                if eth_pos_dir == "long":
                    if eth_low[i] <= eth_sl:
                        is_stopped = True
                        exit_price = min(eth_open[i], eth_sl)
                    if eth_cfg.get("tp_ratio") is not None and eth_tp is not None and eth_high[i] >= eth_tp:
                        is_tp_hit = True
                        if not is_stopped:
                            exit_price = max(eth_open[i], eth_tp)
                            exit_reason = "take_profit"
                else:  # short
                    if eth_high[i] >= eth_sl:
                        is_stopped = True
                        exit_price = max(eth_open[i], eth_sl)
                    if eth_cfg.get("tp_ratio") is not None and eth_tp is not None and eth_low[i] <= eth_tp:
                        is_tp_hit = True
                        if not is_stopped:
                            exit_price = min(eth_open[i], eth_tp)
                            exit_reason = "take_profit"
                            
                if is_stopped or (is_tp_hit and exit_reason == "take_profit"):
                    actual_exit = exit_price - eth_slip if eth_pos_dir == "long" else exit_price + eth_slip
                    pnl = (actual_exit - eth_entry_price) * eth_qty * eth_fv if eth_pos_dir == "long" else (eth_entry_price - actual_exit) * eth_qty * eth_fv
                    fee = (eth_entry_price + actual_exit) * eth_qty * eth_fv * self.fee_rate
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
                        
                    trades.append({"net_pnl": net_pnl, "fee": fee, "contract": "ETH_USDT"})
                    eth_in_pos = False
                    eth_pos_dir = None
                    eth_tp = None
                    eth_closed_this_bar = True
                else:
                    # Check technical exits
                    tech_exit = False
                    if eth_pos_dir == "long":
                        if eth_cfg.get("timeframe") == "1h":
                            tech_exit = (eth_h1_st_dir[i-1] == -1)
                        else:
                            tech_exit = (eth_phase == 3 and eth_h1_st_dir[i-1] == -1) or ((eth_phase == 1 or eth_phase == 2) and eth_st_dir[i-1] == -1)
                    else:
                        if eth_cfg.get("timeframe") == "1h":
                            tech_exit = (eth_h1_st_dir[i-1] == 1)
                        else:
                            tech_exit = (eth_phase == 3 and eth_h1_st_dir[i-1] == 1) or ((eth_phase == 1 or eth_phase == 2) and eth_st_dir[i-1] == 1)
                            
                    if tech_exit:
                        exit_price = eth_open[i]
                        actual_exit = exit_price - eth_slip if eth_pos_dir == "long" else exit_price + eth_slip
                        pnl = (actual_exit - eth_entry_price) * eth_qty * eth_fv if eth_pos_dir == "long" else (eth_entry_price - actual_exit) * eth_qty * eth_fv
                        fee = (eth_entry_price + actual_exit) * eth_qty * eth_fv * self.fee_rate
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
                            
                        trades.append({"net_pnl": net_pnl, "fee": fee, "contract": "ETH_USDT"})
                        eth_in_pos = False
                        eth_pos_dir = None
                        eth_tp = None
                        eth_closed_this_bar = True
                    else:
                        # Update trailing SL
                        is_long = (eth_pos_dir == "long")
                        act_risk = current_equity * risk_percent_per_asset
                        if 350.0 <= current_equity <= 500.0:
                            act_risk = 10.0
                        buf_u = act_risk * eth_cfg.get("lock_profit_buffer", 1.0)
                        
                        if eth_cfg.get("trailing_stop", "three_stage") == "three_stage":
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
                        elif eth_cfg.get("trailing_stop") == "atr" and eth_atr is not None:
                            curr_atr = eth_atr[i-1]
                            cand_sl = eth_close[i-1] - eth_cfg.get("trailing_atr_mult", 2.0) * curr_atr if is_long else eth_close[i-1] + eth_cfg.get("trailing_atr_mult", 2.0) * curr_atr
                            eth_sl = max(cand_sl, eth_sl) if is_long else min(cand_sl, eth_sl)
                            
            # ----------------------------------------------------
            # 2. EVALUATE EXITS & TRAILING STOPS (SOL)
            # ----------------------------------------------------
            if sol_in_pos:
                # Check stop loss/take profit hit during the bar
                is_stopped = False
                is_tp_hit = False
                exit_price = sol_sl
                exit_reason = "stop_loss"
                
                if sol_pos_dir == "long":
                    if sol_low[i] <= sol_sl:
                        is_stopped = True
                        exit_price = min(sol_open[i], sol_sl)
                    if sol_cfg.get("tp_ratio") is not None and sol_tp is not None and sol_high[i] >= sol_tp:
                        is_tp_hit = True
                        if not is_stopped:
                            exit_price = max(sol_open[i], sol_tp)
                            exit_reason = "take_profit"
                else:  # short
                    if sol_high[i] >= sol_sl:
                        is_stopped = True
                        exit_price = max(sol_open[i], sol_sl)
                    if sol_cfg.get("tp_ratio") is not None and sol_tp is not None and sol_low[i] <= sol_tp:
                        is_tp_hit = True
                        if not is_stopped:
                            exit_price = min(sol_open[i], sol_tp)
                            exit_reason = "take_profit"
                            
                if is_stopped or (is_tp_hit and exit_reason == "take_profit"):
                    actual_exit = exit_price - sol_slip if sol_pos_dir == "long" else exit_price + sol_slip
                    pnl = (actual_exit - sol_entry_price) * sol_qty * sol_fv if sol_pos_dir == "long" else (sol_entry_price - actual_exit) * sol_qty * sol_fv
                    fee = (sol_entry_price + actual_exit) * sol_qty * sol_fv * self.fee_rate
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
                        
                    trades.append({"net_pnl": net_pnl, "fee": fee, "contract": "SOL_USDT"})
                    sol_in_pos = False
                    sol_pos_dir = None
                    sol_tp = None
                    sol_closed_this_bar = True
                else:
                    # Check technical exits
                    tech_exit = False
                    if sol_pos_dir == "long":
                        if sol_cfg.get("timeframe") == "1h":
                            tech_exit = (sol_h1_st_dir[i-1] == -1)
                        else:
                            tech_exit = (sol_phase == 3 and sol_h1_st_dir[i-1] == -1) or ((sol_phase == 1 or sol_phase == 2) and sol_st_dir[i-1] == -1)
                    else:
                        if sol_cfg.get("timeframe") == "1h":
                            tech_exit = (sol_h1_st_dir[i-1] == 1)
                        else:
                            tech_exit = (sol_phase == 3 and sol_h1_st_dir[i-1] == 1) or ((sol_phase == 1 or sol_phase == 2) and sol_st_dir[i-1] == 1)
                            
                    if tech_exit:
                        exit_price = sol_open[i]
                        actual_exit = exit_price - sol_slip if sol_pos_dir == "long" else exit_price + sol_slip
                        pnl = (actual_exit - sol_entry_price) * sol_qty * sol_fv if sol_pos_dir == "long" else (sol_entry_price - actual_exit) * sol_qty * sol_fv
                        fee = (sol_entry_price + actual_exit) * sol_qty * sol_fv * self.fee_rate
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
                            
                        trades.append({"net_pnl": net_pnl, "fee": fee, "contract": "SOL_USDT"})
                        sol_in_pos = False
                        sol_pos_dir = None
                        sol_tp = None
                        sol_closed_this_bar = True
                    else:
                        # Update trailing SL
                        is_long = (sol_pos_dir == "long")
                        act_risk = current_equity * risk_percent_per_asset
                        if 350.0 <= current_equity <= 500.0:
                            act_risk = 10.0
                        buf_u = act_risk * sol_cfg.get("lock_profit_buffer", 1.0)
                        
                        if sol_cfg.get("trailing_stop", "three_stage") == "three_stage":
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
                        elif sol_cfg.get("trailing_stop") == "atr" and sol_atr is not None:
                            curr_atr = sol_atr[i-1]
                            cand_sl = sol_close[i-1] - sol_cfg.get("trailing_atr_mult", 2.0) * curr_atr if is_long else sol_close[i-1] + sol_cfg.get("trailing_atr_mult", 2.0) * curr_atr
                            sol_sl = max(cand_sl, sol_sl) if is_long else min(cand_sl, sol_sl)
                            
            # ----------------------------------------------------
            # 3. EVALUATE ENTREIS (ETH)
            # ----------------------------------------------------
            if not eth_in_pos and not eth_closed_this_bar and not cb_until and not eth_cooldown_until:
                # Trend Filter
                trend_ok_long = True
                trend_ok_short = True
                
                eth_tfilter = eth_cfg.get("trend_filter_1h", "none")
                if eth_tfilter == "supertrend":
                    trend_ok_long = (eth_h1_st_dir[i-1] == 1)
                    trend_ok_short = (eth_h1_st_dir[i-1] == -1)
                elif eth_tfilter == "dema" and eth_h1_dema is not None:
                    dval = eth_h1_dema[i-1]
                    trend_ok_long = (eth_h1_close[i-1] > dval)
                    trend_ok_short = (eth_h1_close[i-1] < dval)
                elif eth_tfilter == "ema" and eth_h1_ema is not None:
                    eval_ = eth_h1_ema[i-1]
                    trend_ok_long = (eth_h1_close[i-1] > eval_)
                    trend_ok_short = (eth_h1_close[i-1] < eval_)
                    
                # Signal
                entry_long = False
                entry_short = False
                
                eth_esignal = eth_cfg.get("entry_signal", "supertrend")
                if eth_esignal == "supertrend":
                    if eth_cfg.get("timeframe") == "30m":
                        entry_long = (eth_st_dir[i-1] == 1)
                        entry_short = (eth_st_dir[i-1] == -1)
                    else:
                        entry_long = (eth_h1_st_dir[i-1] == 1)
                        entry_short = (eth_h1_st_dir[i-1] == -1)
                elif eth_esignal == "rsi_pullback" and eth_rsi is not None:
                    rsi_curr = eth_rsi[i-1]
                    rsi_prev = eth_rsi[i-2]
                    pullback_lower = eth_cfg.get("rsi_pullback_lower", 45)
                    pullback_upper = eth_cfg.get("rsi_pullback_upper", 55)
                    
                    if trend_ok_long:
                        entry_long = (rsi_curr > rsi_prev) and (rsi_prev <= pullback_lower)
                    if trend_ok_short:
                        entry_short = (rsi_curr < rsi_prev) and (rsi_prev >= pullback_upper)
                        
                # ADX filter
                adx_ok = True
                if eth_cfg.get("adx_filter", False) and eth_adx is not None:
                    adx_ok = (eth_adx[i-1] > eth_cfg.get("adx_threshold", 20.0))
                    
                if entry_long and trend_ok_long and adx_ok:
                    eth_pos_dir = "long"
                elif entry_short and trend_ok_short and adx_ok:
                    eth_pos_dir = "short"
                    
                if eth_pos_dir is not None:
                    eth_entry_price = eth_open[i]
                    eth_in_pos = True
                    eth_phase = 1
                    
                    if eth_cfg.get("sl_type") == "supertrend":
                        eth_sl = eth_st_val[i-1] if eth_cfg.get("timeframe") == "30m" else eth_h1_st_val[i-1]
                    else:
                        curr_atr = eth_atr[i-1] if eth_atr is not None else 0.0
                        mult = eth_cfg.get("sl_atr_mult", 2.0)
                        eth_sl = eth_entry_price - mult * curr_atr if eth_pos_dir == "long" else eth_entry_price + mult * curr_atr
                        
                    # Quantity
                    act_risk = current_equity * risk_percent_per_asset
                    if 350.0 <= current_equity <= 500.0:
                        act_risk = 10.0
                    sl_d = abs(eth_entry_price - eth_sl)
                    if sl_d > 0:
                        eth_qty = int(min(act_risk / (sl_d * eth_fv), (current_equity * 5.0) / (eth_entry_price * eth_fv)))
                        if eth_qty <= 0: eth_qty = 1
                        if eth_cfg.get("tp_ratio") is not None:
                            eth_tp = eth_entry_price + eth_cfg.get("tp_ratio") * sl_d if eth_pos_dir == "long" else eth_entry_price - eth_cfg.get("tp_ratio") * sl_d
                        else:
                            eth_tp = None
                    else:
                        eth_qty = 1
                        eth_tp = None
                        
            # ----------------------------------------------------
            # 4. EVALUATE ENTREIS (SOL)
            # ----------------------------------------------------
            if not sol_in_pos and not sol_closed_this_bar and not cb_until and not sol_cooldown_until:
                # Trend Filter
                trend_ok_long = True
                trend_ok_short = True
                
                sol_tfilter = sol_cfg.get("trend_filter_1h", "none")
                if sol_tfilter == "supertrend":
                    trend_ok_long = (sol_h1_st_dir[i-1] == 1)
                    trend_ok_short = (sol_h1_st_dir[i-1] == -1)
                elif sol_tfilter == "dema" and sol_h1_dema is not None:
                    dval = sol_h1_dema[i-1]
                    trend_ok_long = (sol_h1_close[i-1] > dval)
                    trend_ok_short = (sol_h1_close[i-1] < dval)
                elif sol_tfilter == "ema" and sol_h1_ema is not None:
                    eval_ = sol_h1_ema[i-1]
                    trend_ok_long = (sol_h1_close[i-1] > eval_)
                    trend_ok_short = (sol_h1_close[i-1] < eval_)
                    
                # Signal
                entry_long = False
                entry_short = False
                
                sol_esignal = sol_cfg.get("entry_signal", "supertrend")
                if sol_esignal == "supertrend":
                    if sol_cfg.get("timeframe") == "30m":
                        entry_long = (sol_st_dir[i-1] == 1)
                        entry_short = (sol_st_dir[i-1] == -1)
                    else:
                        entry_long = (sol_h1_st_dir[i-1] == 1)
                        entry_short = (sol_h1_st_dir[i-1] == -1)
                elif sol_esignal == "rsi_pullback" and sol_rsi is not None:
                    rsi_curr = sol_rsi[i-1]
                    rsi_prev = sol_rsi[i-2]
                    pullback_lower = sol_cfg.get("rsi_pullback_lower", 45)
                    pullback_upper = sol_cfg.get("rsi_pullback_upper", 55)
                    
                    if trend_ok_long:
                        entry_long = (rsi_curr > rsi_prev) and (rsi_prev <= pullback_lower)
                    if trend_ok_short:
                        entry_short = (rsi_curr < rsi_prev) and (rsi_prev >= pullback_upper)
                        
                # ADX filter
                adx_ok = True
                if sol_cfg.get("adx_filter", False) and sol_adx is not None:
                    adx_ok = (sol_adx[i-1] > sol_cfg.get("adx_threshold", 20.0))
                    
                if entry_long and trend_ok_long and adx_ok:
                    sol_pos_dir = "long"
                elif entry_short and trend_ok_short and adx_ok:
                    sol_pos_dir = "short"
                    
                if sol_pos_dir is not None:
                    sol_entry_price = sol_open[i]
                    sol_in_pos = True
                    sol_phase = 1
                    
                    if sol_cfg.get("sl_type") == "supertrend":
                        sol_sl = sol_st_val[i-1] if sol_cfg.get("timeframe") == "30m" else sol_h1_st_val[i-1]
                    else:
                        curr_atr = sol_atr[i-1] if sol_atr is not None else 0.0
                        mult = sol_cfg.get("sl_atr_mult", 2.0)
                        sol_sl = sol_entry_price - mult * curr_atr if sol_pos_dir == "long" else sol_entry_price + mult * curr_atr
                        
                    # Quantity
                    act_risk = current_equity * risk_percent_per_asset
                    if 350.0 <= current_equity <= 500.0:
                        act_risk = 10.0
                    sl_d = abs(sol_entry_price - sol_sl)
                    if sl_d > 0:
                        sol_qty = int(min(act_risk / (sl_d * sol_fv), (current_equity * 5.0) / (sol_entry_price * sol_fv)))
                        if sol_qty <= 0: sol_qty = 1
                        if sol_cfg.get("tp_ratio") is not None:
                            sol_tp = sol_entry_price + sol_cfg.get("tp_ratio") * sl_d if sol_pos_dir == "long" else sol_entry_price - sol_cfg.get("tp_ratio") * sl_d
                        else:
                            sol_tp = None
                    else:
                        sol_qty = 1
                        sol_tp = None
                        
        metrics = self._calculate_metrics(trades, capital_history, equity, initial_capital)
        return metrics

    def _calculate_metrics(self, trades: list, capital_history: list, final_equity: float, initial_capital: float) -> dict:
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
        
        # CAGR
        if len(capital_history) > 1:
            start_time = capital_history[0][0]
            end_time = capital_history[-1][0]
            duration_days = (end_time - start_time).total_seconds() / (24 * 3600)
            if duration_days > 0 and final_equity > 0:
                cagr = (final_equity / initial_capital) ** (365.25 / duration_days) - 1
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


def run_optimizer():
    print("=" * 80)
    print("🚀 STRATEGY EXPLORER V2 - CACHED NUMPY OPTIMIZATION & PORTFOLIO SEARCH")
    print("=" * 80)
    
    contracts = ["ETH_USDT", "SOL_USDT"]
    datasets = {}
    
    # 1. Load Data and Compute Indicators
    for contract in contracts:
        df_30m, df_1h = load_data(contract)
        if df_30m is None or df_1h is None:
            print(f"Skipping {contract} - data not found. Run downloader first.")
            continue
            
        print(f"📊 Pre-computing indicators for {contract}...")
        df_30m = df_30m.copy()
        df_1h = df_1h.copy()
        
        # 30m base
        st_res_30m = calculate_supertrend(df_30m, 10, 3.0)
        df_30m['st_val'] = st_res_30m['supertrend']
        df_30m['st_dir'] = st_res_30m['direction']
        
        df_30m['ema_fast_30m'] = calculate_ema(df_30m['close'], 12)
        df_30m['ema_slow_30m'] = calculate_ema(df_30m['close'], 26)
        df_30m['rsi_30m'] = calculate_rsi(df_30m['close'], 14)
        df_30m['atr_val'] = calculate_atr(df_30m, 14)
        df_30m['vol_ma'] = df_30m['volume'].rolling(window=20).mean()
        
        # 1H base
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
        
        # Merge
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
        datasets[contract] = df_merged

    sim = FastSimulatorV2()

    # 2. Run Single Asset Sweeps for RSI Pullback & Standard Trend
    results = {}
    
    for contract in contracts:
        df_merged = datasets[contract]
        print(f"\n🔍 Sweeping single-asset configurations for {contract}...")
        
        configs = []
        # Build configuration list
        # We sweep RSI pullbacks, standard SuperTrend entries, and various SL/TP ratios
        for entry in ["supertrend", "rsi_pullback"]:
            for tf_1h in ["dema", "ema", "supertrend", "none"]:
                for dema_p in [100, 150, 200]:
                    for tp in [None, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0]:
                        for risk in [0.01, 0.015, 0.02, 0.025]:
                            for adx_t in [20.0, 25.0, 30.0]:
                                if entry == "rsi_pullback":
                                    # test different pullback thresholds
                                    for bounds in [(40, 60), (45, 55)]:
                                        configs.append({
                                            "timeframe": "30m",
                                            "entry_signal": entry,
                                            "trend_filter_1h": tf_1h,
                                            "dema_period": dema_p,
                                            "tp_ratio": tp,
                                            "risk_percent": risk,
                                            "adx_filter": True,
                                            "adx_threshold": adx_t,
                                            "sl_type": "atr",
                                            "sl_atr_mult": 2.5,
                                            "trailing_stop": "atr",
                                            "trailing_atr_mult": 2.5,
                                            "rsi_pullback_lower": bounds[0],
                                            "rsi_pullback_upper": bounds[1]
                                        })
                                else:
                                    configs.append({
                                        "timeframe": "30m",
                                        "entry_signal": entry,
                                        "trend_filter_1h": tf_1h,
                                        "dema_period": dema_p,
                                        "tp_ratio": tp,
                                        "risk_percent": risk,
                                        "adx_filter": True,
                                        "adx_threshold": adx_t,
                                        "sl_type": "supertrend",
                                        "trailing_stop": "three_stage",
                                        "lock_profit_buffer": 1.0
                                    })
                                    
        print(f"Generated {len(configs)} configs for {contract}. Running sweep...")
        
        best_single_configs = []
        
        for idx, cfg in enumerate(configs):
            metrics = sim.run_single(df_merged, contract, cfg)
            cagr = metrics["annualized_return"]
            max_dd = abs(metrics["max_drawdown"])
            
            # Record config with metrics summary
            cfg["metrics"] = {
                "total_trades": metrics["total_trades"],
                "win_rate": f"{metrics['win_rate']*100:.1f}%",
                "total_pnl": metrics["total_pnl"],
                "annualized_return_pct": f"{cagr*100:+.1f}%",
                "max_drawdown_pct": f"{max_dd*100:.1f}%",
                "profit_factor": metrics["profit_factor"],
                "final_equity": metrics["final_equity"]
            }
            
            # We track configs that have good metrics (CAGR > 20% or Max DD < 75%)
            if cagr >= 0.20 and max_dd <= 0.75:
                best_single_configs.append(cfg)
                
            if (idx + 1) % 1000 == 0:
                print(f"Processed {idx + 1}/{len(configs)} configs...")
                
        # Sort by CAGR
        best_single_configs = sorted(best_single_configs, key=lambda x: x["metrics"]["total_pnl"], reverse=True)
        results[contract] = best_single_configs[:50]  # save top 50
        print(f"Completed {contract} sweep! Found {len(best_single_configs)} configs meeting baseline filters.")

    # 3. Run Joint Portfolio Sweeps
    # Let's cross-simulate the top performing single asset strategies in a shared portfolio.
    print("\n💼 Running Joint Portfolio Simulation Sweeps (shared equity)...")
    portfolio_results = []
    
    # We take top 15 configs for ETH and top 15 configs for SOL, and run them jointly
    top_eth_configs = results["ETH_USDT"][:15]
    top_sol_configs = results["SOL_USDT"][:15]
    
    print(f"Cross-testing {len(top_eth_configs)} ETH configs with {len(top_sol_configs)} SOL configs...")
    
    count = 0
    for eth_cfg in top_eth_configs:
        for sol_cfg in top_sol_configs:
            # We test different asset-level risk percentages (1.0%, 1.5%, 2.0%)
            for r_pct in [0.01, 0.015, 0.02]:
                metrics = sim.run_portfolio(
                    df_merged_eth=datasets["ETH_USDT"],
                    df_merged_sol=datasets["SOL_USDT"],
                    eth_cfg=eth_cfg,
                    sol_cfg=sol_cfg,
                    initial_capital=1000.0,
                    risk_percent_per_asset=r_pct
                )
                
                cagr = metrics["annualized_return"]
                max_dd = abs(metrics["max_drawdown"])
                pf = metrics["profit_factor"]
                
                portfolio_results.append({
                    "cagr": cagr,
                    "max_dd": max_dd,
                    "profit_factor": pf,
                    "risk_percent": r_pct,
                    "eth_cfg": eth_cfg,
                    "sol_cfg": sol_cfg,
                    "metrics": {
                        "total_trades": metrics["total_trades"],
                        "win_rate": f"{metrics['win_rate']*100:.1f}%",
                        "total_pnl": metrics["total_pnl"],
                        "annualized_return_pct": f"{cagr*100:+.1f}%",
                        "max_drawdown_pct": f"{max_dd*100:.1f}%",
                        "final_equity": metrics["final_equity"],
                        "profit_factor": pf
                    }
                })
                
                # Check if we meet target: CAGR > 300% and Max DD < 25%
                if cagr >= 3.0 and max_dd <= 0.25:
                    print(f"🏆 WINNER PORTFOLIO FOUND! PnL={metrics['total_pnl']:+.2f}U, CAGR={cagr*100:+.1f}%, Max DD={max_dd*100:.1f}%, PF={pf:.2f}, Risk={r_pct*100}%")
                    
                count += 1
                if count % 100 == 0:
                    print(f"Processed {count} portfolio combinations...")
                    
    # Sort portfolio results by CAGR, and secondary by Profit Factor
    portfolio_results = sorted(portfolio_results, key=lambda x: x["cagr"], reverse=True)
    
    # Save top 50 portfolio results and top 50 single-asset results
    final_output = {
        "joint_portfolio_top_50": portfolio_results[:50],
        "eth_single_top_50": results["ETH_USDT"],
        "sol_single_top_50": results["SOL_USDT"]
    }
    
    filepath = os.path.join(RESULTS_DIR, "optimal_strategies_v2.json")
    with open(filepath, "w") as f:
        json.dump(final_output, f, indent=4)
        
    print(f"\n✅ Exploration V2 finished! Results saved to: backtest/results/optimal_strategies_v2.json")
    
    # Print the top 3 portfolio results
    print("\n🏆 TOP 3 PORTFOLIO CONFIGURATIONS:")
    for i, res in enumerate(portfolio_results[:3]):
        print(f"\nRank #{i+1}:")
        print(f"  Annualized Return (CAGR): {res['metrics']['annualized_return_pct']}")
        print(f"  Max Drawdown: -{res['metrics']['max_drawdown_pct']}")
        print(f"  Profit Factor: {res['metrics']['profit_factor']:.2f}")
        print(f"  Asset Risk Size: {res['risk_percent']*100}%")
        print(f"  ETH Entry: {res['eth_cfg']['entry_signal']}, HTF Filter: {res['eth_cfg']['trend_filter_1h']}, TP Ratio: {res['eth_cfg']['tp_ratio']}")
        print(f"  SOL Entry: {res['sol_cfg']['entry_signal']}, HTF Filter: {res['sol_cfg']['trend_filter_1h']}, TP Ratio: {res['sol_cfg']['tp_ratio']}")
    print("=" * 80)


if __name__ == "__main__":
    run_optimizer()
