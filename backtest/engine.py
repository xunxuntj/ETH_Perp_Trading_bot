#!/usr/bin/env python3
"""
Backtesting Simulation Engine for V9.7 Strategy
Matches the production strategy logic (triple filter, ADX, three-stage stop-loss).
"""

import os
import sys
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta

# Ensure parent directory is in path to import indicators
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from indicators import calculate_supertrend, calculate_dema, calculate_adx
from config import (
    SUPERTREND_PERIOD, SUPERTREND_MULTIPLIER, DEMA_PERIOD,
    ADX_LENGTH, ADX_THRESHOLD, ADX_TIMEFRAME, USE_ADX,
    LEVERAGE, CIRCUIT_BREAKER_EQUITY, MAX_CONSECUTIVE_LOSSES
)


class BacktestEngine:
    def __init__(self, contract: str, initial_capital: float = 1000.0, fee_rate: float = 0.0004, slippage_ticks: float = 1.0):
        self.contract = contract
        self.initial_capital = initial_capital
        self.fee_rate = fee_rate
        
        # Determine base coin parameters
        self.face_value = self._get_face_value(contract)
        self.tick_size = self._get_tick_size(contract)
        self.slippage = slippage_ticks * self.tick_size
        
    def _get_face_value(self, contract: str) -> float:
        c_upper = contract.upper()
        if "ETH" in c_upper:
            return 0.01
        elif "BTC" in c_upper:
            return 0.0001
        elif "SOL" in c_upper:
            return 1.0
        elif "DOGE" in c_upper:
            return 10.0
        return 0.01

    def _get_tick_size(self, contract: str) -> float:
        c_upper = contract.upper()
        if "ETH" in c_upper or "BTC" in c_upper:
            return 0.1
        elif "SOL" in c_upper:
            return 0.01
        return 0.01

    def run(self, df_30m: pd.DataFrame, df_1h: pd.DataFrame, risk_mode: str = "fixed", 
            risk_amount: float = 10.0, risk_percent: float = 0.02, lock_profit_buffer: float = 1.0,
            adx_threshold: float = None, adx_length: int = None, adx_timeframe: str = None,
            dema_period: int = None, tp_ratio: float = None) -> dict:
        """
        Runs the backtest simulation over the K-line data.
        """
        active_adx_threshold = adx_threshold if adx_threshold is not None else ADX_THRESHOLD
        active_adx_length = adx_length if adx_length is not None else ADX_LENGTH
        active_adx_timeframe = adx_timeframe if adx_timeframe is not None else ADX_TIMEFRAME
        active_dema_period = dema_period if dema_period is not None else DEMA_PERIOD
        # 1. Compute Indicators
        # 30m Indicators
        df_30m = df_30m.copy()
        st_30m_res = calculate_supertrend(df_30m, SUPERTREND_PERIOD, SUPERTREND_MULTIPLIER)
        df_30m['st_val'] = st_30m_res['supertrend']
        df_30m['st_dir'] = st_30m_res['direction']
        
        if active_adx_timeframe == "30m":
            df_30m['adx'] = calculate_adx(df_30m, active_adx_length)
            
        # 1h Indicators
        df_1h = df_1h.copy()
        st_1h_res = calculate_supertrend(df_1h, SUPERTREND_PERIOD, SUPERTREND_MULTIPLIER)
        df_1h['st_val'] = st_1h_res['supertrend']
        df_1h['st_dir'] = st_1h_res['direction']
        if active_adx_timeframe == "1h":
            df_1h['adx'] = calculate_adx(df_1h, active_adx_length)
        df_1h['dema'] = calculate_dema(df_1h['close'], active_dema_period)
            
        # 2. Align 1H Indicators with 30m chart
        # Set 1H bar close time as the index for alignment to avoid lookahead bias.
        # Since df_1h index represents the START time of the 1H candle, the close time is start_time + 1 hour.
        df_1h_aligned = df_1h.copy()
        df_1h_aligned.index = df_1h_aligned.index + pd.Timedelta(hours=1)
        
        # Merge 1H indicators into 30m K-lines using merge_asof (backward match)
        # Note: Decision at 30m bar start time T[i] uses indicators completed at or before T[i].
        # So we align T[i] of 30m to the completed 1H indicators (timestamped at close time).
        df_30m = df_30m.reset_index()
        df_1h_aligned = df_1h_aligned.reset_index().rename(columns={
            'st_val': 'h1_st_val',
            'st_dir': 'h1_st_dir',
            'dema': 'h1_dema',
            'adx': 'h1_adx',
            'close': 'h1_close'
        })
        
        # Select columns to merge
        merge_cols = ['timestamp', 'h1_st_val', 'h1_st_dir', 'h1_dema', 'h1_close']
        if active_adx_timeframe == "1h":
            merge_cols.append('h1_adx')
            
        # Ensure timestamp columns have matching datatypes (datetime64[ns])
        df_30m['timestamp'] = df_30m['timestamp'].astype('datetime64[ns]')
        df_1h_aligned['timestamp'] = df_1h_aligned['timestamp'].astype('datetime64[ns]')
            
        merged = pd.merge_asof(
            df_30m,
            df_1h_aligned[merge_cols],
            on='timestamp',
            direction='backward'
        )
        
        # Set back timestamp as index
        merged.set_index('timestamp', inplace=True)
        
        # 3. Initialize Backtest State Variables
        equity = self.initial_capital
        capital_history = []
        trades = []
        
        # Position states
        in_pos = False
        pos_direction = None # "long" or "short"
        pos_entry_price = 0.0
        pos_stop_loss = 0.0
        pos_initial_30m_st = 0.0
        pos_locked_stop = 0.0
        pos_tp_price = None
        pos_phase = 0 # 0: None, 1: Survival, 2: Locked, 3: Hourly
        pos_qty = 0
        pos_entry_time = None
        
        # Safety rules
        consecutive_losses = 0
        cooldown_until = None
        cb_until = None
        
        # Warmup index: Skip first 1000 bars to let indicators (DEMA200, ADX) stabilize
        warmup_len = 1000
        
        # Iterate bar by bar
        timestamps = merged.index
        high_prices = merged['high'].values
        low_prices = merged['low'].values
        close_prices = merged['close'].values
        open_prices = merged['open'].values
        
        st_val_30m = merged['st_val'].values
        st_dir_30m = merged['st_dir'].values
        
        h1_st_val_aligned = merged['h1_st_val'].values
        h1_st_dir_aligned = merged['h1_st_dir'].values
        h1_dema_aligned = merged['h1_dema'].values
        h1_close_aligned = merged['h1_close'].values
        
        if active_adx_timeframe == "1h":
            adx_aligned = merged['h1_adx'].values
        else:
            adx_aligned = merged['adx'].values
            
        n = len(merged)
        
        for i in range(warmup_len, n):
            t_curr = timestamps[i]
            
            # Check cooldown or CB expiration
            if cooldown_until and t_curr >= cooldown_until:
                consecutive_losses = 0
                cooldown_until = None
                
            if cb_until and t_curr >= cb_until:
                cb_until = None
                
            # Current equity is capital + unrealized pnl of current position
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
            # CASE A: In Active Position - Evaluate SL Hit or Exit
            # ----------------------------------------------------
            if in_pos:
                # 1. Check if Stop Loss or Take Profit was hit during the current bar
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
                            # Both SL and TP hit in same bar, assume SL (conservative)
                            pass
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
                            # Both SL and TP hit in same bar, assume SL (conservative)
                            pass
                        else:
                            exit_price = min(open_prices[i], pos_tp_price)
                            exit_reason = "take_profit"
                        
                if is_stopped or (is_tp_hit and exit_reason == "take_profit"):
                    # Apply slippage (against our favor)
                    if pos_direction == "long":
                        actual_exit_price = exit_price - self.slippage
                    else:
                        actual_exit_price = exit_price + self.slippage
                        
                    # Calculate PNL
                    if pos_direction == "long":
                        pnl = (actual_exit_price - pos_entry_price) * pos_qty * self.face_value
                    else:
                        pnl = (pos_entry_price - actual_exit_price) * pos_qty * self.face_value
                        
                    # Apply fee
                    entry_fee = pos_entry_price * pos_qty * self.face_value * self.fee_rate
                    exit_fee = actual_exit_price * pos_qty * self.face_value * self.fee_rate
                    total_fee = entry_fee + exit_fee
                    net_pnl = pnl - total_fee
                    
                    equity += net_pnl
                    
                    # Update safety rules
                    if net_pnl < 0:
                        consecutive_losses += 1
                        if consecutive_losses >= MAX_CONSECUTIVE_LOSSES:
                            cooldown_until = t_curr + timedelta(hours=48)
                    else:
                        consecutive_losses = 0
                        
                    # Check circuit breaker
                    if equity <= CIRCUIT_BREAKER_EQUITY:
                        cb_until = t_curr + timedelta(days=7)
                        
                    trades.append({
                        "entry_time": pos_entry_time,
                        "exit_time": t_curr,
                        "direction": pos_direction,
                        "qty": pos_qty,
                        "entry_price": pos_entry_price,
                        "exit_price": actual_exit_price,
                        "exit_reason": exit_reason,
                        "pnl": pnl,
                        "fee": total_fee,
                        "net_pnl": net_pnl,
                        "equity": equity
                    })
                    
                    # Reset position state
                    in_pos = False
                    pos_direction = None
                    pos_phase = 0
                    pos_tp_price = None
                    continue
                
                # 2. Check if Technical Exit Condition was met (evaluated at the close of last K-line, index i-1)
                # Note: Signal checked at bar start T[i] uses indicators completed at T[i-1]
                st_dir_prev = st_dir_30m[i-1]
                h1_st_dir_prev = h1_st_dir_aligned[i-1]
                
                technical_exit = False
                exit_reason = ""
                
                if pos_direction == "long":
                    if pos_phase == 3 and h1_st_dir_prev == -1:
                        technical_exit = True
                        exit_reason = "1H ST Red"
                    elif (pos_phase == 1 or pos_phase == 2) and st_dir_prev == -1:
                        technical_exit = True
                        exit_reason = "30m ST Red"
                else: # short
                    if pos_phase == 3 and h1_st_dir_prev == 1:
                        technical_exit = True
                        exit_reason = "1H ST Green"
                    elif (pos_phase == 1 or pos_phase == 2) and st_dir_prev == 1:
                        technical_exit = True
                        exit_reason = "30m ST Green"
                        
                if technical_exit:
                    # Exit at the open of current bar (which is the close of previous bar)
                    exit_price = open_prices[i]
                    
                    # Apply slippage
                    if pos_direction == "long":
                        actual_exit_price = exit_price - self.slippage
                    else:
                        actual_exit_price = exit_price + self.slippage
                        
                    # Calculate PNL
                    if pos_direction == "long":
                        pnl = (actual_exit_price - pos_entry_price) * pos_qty * self.face_value
                    else:
                        pnl = (pos_entry_price - actual_exit_price) * pos_qty * self.face_value
                        
                    # Apply fee
                    entry_fee = pos_entry_price * pos_qty * self.face_value * self.fee_rate
                    exit_fee = actual_exit_price * pos_qty * self.face_value * self.fee_rate
                    total_fee = entry_fee + exit_fee
                    net_pnl = pnl - total_fee
                    
                    equity += net_pnl
                    
                    # Update safety rules
                    if net_pnl < 0:
                        consecutive_losses += 1
                        if consecutive_losses >= MAX_CONSECUTIVE_LOSSES:
                            cooldown_until = t_curr + timedelta(hours=48)
                    else:
                        consecutive_losses = 0
                        
                    # Check circuit breaker
                    if equity <= CIRCUIT_BREAKER_EQUITY:
                        cb_until = t_curr + timedelta(days=7)
                        
                    trades.append({
                        "entry_time": pos_entry_time,
                        "exit_time": t_curr,
                        "direction": pos_direction,
                        "qty": pos_qty,
                        "entry_price": pos_entry_price,
                        "exit_price": actual_exit_price,
                        "exit_reason": exit_reason,
                        "pnl": pnl,
                        "fee": total_fee,
                        "net_pnl": net_pnl,
                        "equity": equity
                    })
                    
                    # Check if we can REVERSE immediately
                    # Get indicators for reversal signal (from completed bar i-1)
                    st_dir_sig = st_dir_30m[i-1]
                    h1_st_dir_sig = h1_st_dir_aligned[i-1]
                    h1_close_sig = h1_close_aligned[i-1]
                    h1_dema_sig = h1_dema_aligned[i-1]
                    adx_sig = adx_aligned[i-1]
                    
                    adx_ok = (not USE_ADX) or (adx_sig > active_adx_threshold)
                    can_cooldown = (not cooldown_until) and (not cb_until)
                    
                    can_reverse = False
                    if pos_direction == "long":
                        # Can reverse to short?
                        if can_cooldown and h1_st_dir_sig == -1 and h1_close_sig < h1_dema_sig and st_dir_sig == -1 and adx_ok:
                            can_reverse = True
                    else: # short
                        # Can reverse to long?
                        if can_cooldown and h1_st_dir_sig == 1 and h1_close_sig > h1_dema_sig and st_dir_sig == 1 and adx_ok:
                            can_reverse = True
                            
                    if can_reverse:
                        # Setup new reversed position at current open
                        pos_direction = "short" if pos_direction == "long" else "long"
                        pos_entry_price = open_prices[i]
                        pos_initial_30m_st = st_val_30m[i-1]
                        pos_stop_loss = pos_initial_30m_st
                        pos_locked_stop = 0.0
                        pos_phase = 1 # Survival
                        pos_entry_time = t_curr
                        
                        # Size calculation
                        # Risk Amount
                        if risk_mode == "percent":
                            active_risk_amt = equity * risk_percent
                            if 350.0 <= equity <= 500.0:
                                active_risk_amt = 10.0 # Conservative mode cap
                        else:
                            active_risk_amt = risk_amount
                            
                        sl_dist = abs(pos_entry_price - pos_stop_loss)
                        if sl_dist > 0:
                            calc_qty = active_risk_amt / (sl_dist * self.face_value)
                            # Leverage safety cap
                            max_qty_leverage = (equity * LEVERAGE) / (pos_entry_price * self.face_value)
                            pos_qty = int(min(calc_qty, max_qty_leverage))
                            if pos_qty <= 0:
                                pos_qty = 1
                                
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
                            
                        # Set in_pos to True (stays active)
                        in_pos = True
                    else:
                        in_pos = False
                        pos_direction = None
                        pos_phase = 0
                        pos_tp_price = None
                        
                    continue
                
                # 3. Update Stop Loss Trailing Mechanism (using completed bar i-1)
                # Run the V2 three-stage logic to trail stop loss for next bar
                is_long_pos = (pos_direction == "long")
                
                # Define prices
                survival_to_locked_price = pos_entry_price
                
                # Dynamic risk calculation for lock threshold
                if risk_mode == "percent":
                    active_risk_amt = equity * risk_percent
                    if 350.0 <= equity <= 500.0:
                        active_risk_amt = 10.0
                else:
                    active_risk_amt = risk_amount
                    
                buffer_usdt = active_risk_amt * lock_profit_buffer
                position_token_size = pos_qty * self.face_value
                
                if is_long_pos:
                    locked_to_hourly_price = pos_entry_price + (buffer_usdt / position_token_size)
                else:
                    locked_to_hourly_price = pos_entry_price - (buffer_usdt / position_token_size)
                    
                st_30m_val = st_val_30m[i-1]
                st_1h_val = h1_st_val_aligned[i-1]
                
                # Phase 1 Check: Survival
                is_survival = st_30m_val < survival_to_locked_price if is_long_pos else st_30m_val > survival_to_locked_price
                
                if is_survival:
                    pos_phase = 1
                    # Tighten stop
                    if is_long_pos:
                        pos_stop_loss = max(st_30m_val, pos_stop_loss)
                    else:
                        pos_stop_loss = min(st_30m_val, pos_stop_loss)
                else:
                    # Phase 3 Check: Hourly Track
                    is_hourly = st_1h_val > locked_to_hourly_price if is_long_pos else st_1h_val < locked_to_hourly_price
                    if is_hourly:
                        pos_phase = 3
                        # Tighten stop
                        if is_long_pos:
                            pos_stop_loss = max(st_1h_val, pos_stop_loss)
                        else:
                            pos_stop_loss = min(st_1h_val, pos_stop_loss)
                    else:
                        # Phase 2 Check: Locked
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
            
            # ----------------------------------------------------
            # CASE B: No Position - Check Entry Conditions
            # ----------------------------------------------------
            else:
                # decision made at T[i] using indicators completed at T[i-1]
                st_dir_sig = st_dir_30m[i-1]
                st_val_sig = st_val_30m[i-1]
                h1_st_dir_sig = h1_st_dir_aligned[i-1]
                h1_dema_sig = h1_dema_aligned[i-1]
                h1_close_sig = h1_close_aligned[i-1]
                adx_sig = adx_aligned[i-1]
                
                adx_ok = (not USE_ADX) or (adx_sig > active_adx_threshold)
                can_cooldown = (not cooldown_until) and (not cb_until)
                
                if can_cooldown:
                    # Check Long entry
                    if h1_st_dir_sig == 1 and h1_close_sig > h1_dema_sig and st_dir_sig == 1 and adx_ok:
                        pos_direction = "long"
                        pos_entry_price = open_prices[i]
                        pos_initial_30m_st = st_val_sig
                        pos_stop_loss = pos_initial_30m_st
                        pos_locked_stop = 0.0
                        pos_phase = 1
                        pos_entry_time = t_curr
                        in_pos = True
                        
                    # Check Short entry
                    elif h1_st_dir_sig == -1 and h1_close_sig < h1_dema_sig and st_dir_sig == -1 and adx_ok:
                        pos_direction = "short"
                        pos_entry_price = open_prices[i]
                        pos_initial_30m_st = st_val_sig
                        pos_stop_loss = pos_initial_30m_st
                        pos_locked_stop = 0.0
                        pos_phase = 1
                        pos_entry_time = t_curr
                        in_pos = True
                        
                    if in_pos:
                        # Calculate quantity
                        if risk_mode == "percent":
                            active_risk_amt = equity * risk_percent
                            if 350.0 <= equity <= 500.0:
                                active_risk_amt = 10.0
                        else:
                            active_risk_amt = risk_amount
                            
                        sl_dist = abs(pos_entry_price - pos_stop_loss)
                        if sl_dist > 0:
                            calc_qty = active_risk_amt / (sl_dist * self.face_value)
                            # Leverage safety cap
                            max_qty_leverage = (equity * LEVERAGE) / (pos_entry_price * self.face_value)
                            pos_qty = int(min(calc_qty, max_qty_leverage))
                            if pos_qty <= 0:
                                pos_qty = 1
                                
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
                            
        # 4. Generate Backtest Metrics
        metrics = self._calculate_metrics(trades, capital_history, equity)
        return {
            "metrics": metrics,
            "trades": trades,
            "capital_history": capital_history
        }

    def _calculate_metrics(self, trades: list, capital_history: list, final_equity: float) -> dict:
        total_trades = len(trades)
        if total_trades == 0:
            return {
                "total_trades": 0,
                "win_rate": 0.0,
                "total_pnl": 0.0,
                "profit_factor": 0.0,
                "max_drawdown": 0.0,
                "annualized_return": 0.0,
                "final_equity": final_equity
            }
            
        df_trades = pd.DataFrame(trades)
        wins = df_trades[df_trades['net_pnl'] > 0]
        losses = df_trades[df_trades['net_pnl'] <= 0]
        
        win_count = len(wins)
        loss_count = len(losses)
        win_rate = win_count / total_trades
        
        total_pnl = df_trades['net_pnl'].sum()
        total_fee = df_trades['fee'].sum()
        
        total_gains = wins['net_pnl'].sum()
        total_losses = abs(losses['net_pnl'].sum())
        profit_factor = total_gains / total_losses if total_losses > 0 else float('inf')
        
        # Max Drawdown
        df_cap = pd.DataFrame(capital_history, columns=['timestamp', 'equity'])
        df_cap['running_max'] = df_cap['equity'].cummax()
        df_cap['drawdown'] = (df_cap['equity'] - df_cap['running_max']) / df_cap['running_max']
        max_dd = df_cap['drawdown'].min()
        
        # Sharpe ratio (based on trade net returns)
        trade_returns = df_trades['net_pnl'] / self.initial_capital
        std_ret = trade_returns.astype(float).std()
        sharpe = (trade_returns.astype(float).mean() / std_ret * np.sqrt(365 * 48 / total_trades)) if std_ret > 0 and total_trades > 1 else 0
        
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
            "win_count": win_count,
            "loss_count": loss_count,
            "win_rate": win_rate,
            "total_pnl": total_pnl,
            "total_fee": total_fee,
            "profit_factor": None if np.isinf(profit_factor) else profit_factor,
            "max_drawdown": max_dd,
            "annualized_return": cagr,
            "sharpe_ratio": sharpe,
            "final_equity": final_equity,
            "avg_pnl": df_trades['net_pnl'].mean(),
            "avg_win": wins['net_pnl'].mean() if win_count > 0 else 0.0,
            "avg_loss": losses['net_pnl'].mean() if loss_count > 0 else 0.0
        }
