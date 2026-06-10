#!/usr/bin/env python3
"""
Weekly EMA Macro Regime Filter Portfolio Simulation (5-Year).
Compares the performance of the weekly macro regime filter model against a pure trend-following benchmark.
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


class FastWeeklyRegimeSimulator:
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
            face_value = 100.0
            slippage = 0.00005
        else:
            face_value = 1.0
            slippage = 0.01
        return face_value, slippage

    def run_portfolio_weekly_regime(self, datasets: dict, configs: dict, 
                                   use_filter: bool, weekly_ema_period: int, 
                                   bull_risk: float, bear_risk: float) -> dict:
        """
        Runs the joint portfolio simulation with Weekly EMA regime filter.
        If use_filter is False, runs standard benchmark (all assets traded at bull_risk).
        If use_filter is True:
          - Altcoins (SOL, LINK, DOGE) disabled if weekly close < weekly EMA.
          - BTC/ETH risk reduced to bear_risk if weekly close < weekly EMA.
        """
        contracts = list(datasets.keys())
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
        weekly_closes = {}
        weekly_emas = {}
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
            rsis[contract] = df['rsi_30m'].values
            atrs[contract] = df['atr_val'].values
            
            # Weekly aligned columns
            weekly_closes[contract] = df['weekly_close_aligned'].values
            weekly_emas[contract] = df[f'weekly_ema_{weekly_ema_period}_aligned'].values
            
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
        
        # Position states
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
                            
                            # Sizing depends on the regime when entered
                            # Let's find out what the risk was: we can recalculate it
                            # Or we can just use the current regime. Let's use the current equity risk.
                            # First, check if filter is enabled and if it's bear regime
                            w_close = weekly_closes[c][i-1]
                            w_ema = weekly_emas[c][i-1]
                            is_bear = w_close < w_ema if (not np.isnan(w_close) and not np.isnan(w_ema)) else False
                            
                            trade_risk = bull_risk
                            if use_filter and is_bear:
                                trade_risk = bear_risk
                                
                            act_risk = current_equity * trade_risk
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
                    # Determine Weekly EMA Regime
                    w_close = weekly_closes[c][i-1]
                    w_ema = weekly_emas[c][i-1]
                    is_bear = w_close < w_ema if (not np.isnan(w_close) and not np.isnan(w_ema)) else False
                    
                    if use_filter and is_bear:
                        # Bear regime filter active
                        if c in ["SOL_USDT", "LINK_USDT", "DOGE_USDT"]:
                            # Disable altcoins entirely
                            continue
                        else:
                            # Restrict BTC and ETH to bear_risk
                            current_risk = bear_risk
                    else:
                        current_risk = bull_risk
                        
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
                    elif entry_signal == "rsi_pullback":
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
                        
                        act_risk = current_equity * current_risk
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
                                
        # Calculate statistics
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


def run_weekly_regime_backtest():
    contracts = ["BTC_USDT", "ETH_USDT", "SOL_USDT", "LINK_USDT", "DOGE_USDT"]
    datasets = {}
    
    print("=" * 80)
    print("🚀 PRECOMPUTING INDICATORS FOR WEEKLY REGIME SWEEPS (5-YEAR)")
    print("=" * 80)
    
    # Load optimal configs
    optimal_file = os.path.join(RESULTS_DIR, "optimal_5y_portfolio.json")
    if os.path.exists(optimal_file):
        with open(optimal_file, "r") as f:
            opt_data = json.load(f)
        single_configs = opt_data.get("single_asset_top_configs", {})
        portfolio_configs = {c: single_configs[c][0] for c in contracts}
    else:
        portfolio_configs = {
            "BTC_USDT": {"entry_signal": "supertrend", "trend_filter_1h": "ema", "dema_period": 200, "tp_ratio": 10.0, "adx_threshold": 25.0, "sl_type": "supertrend"},
            "ETH_USDT": {"entry_signal": "supertrend", "trend_filter_1h": "ema", "dema_period": 200, "tp_ratio": 5.0, "adx_threshold": 30.0, "sl_type": "supertrend"},
            "SOL_USDT": {"entry_signal": "supertrend", "trend_filter_1h": "ema", "dema_period": 200, "tp_ratio": 5.0, "adx_threshold": 30.0, "sl_type": "supertrend"},
            "LINK_USDT": {"entry_signal": "rsi_pullback", "trend_filter_1h": "dema", "dema_period": 150, "tp_ratio": 6.0, "adx_threshold": 25.0, "rsi_pullback_lower": 40.0, "rsi_pullback_upper": 60.0, "sl_type": "atr", "sl_atr_mult": 3.0},
            "DOGE_USDT": {"entry_signal": "supertrend", "trend_filter_1h": "dema", "dema_period": 200, "tp_ratio": 10.0, "adx_threshold": 25.0, "sl_type": "supertrend"}
        }

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
        
        # Weekly Resampling (close price)
        df_weekly = df_1h.resample('W').agg({
            'close': 'last'
        }).dropna()
        
        for p in [10, 20, 30]:
            df_weekly[f'ema_{p}'] = calculate_ema(df_weekly['close'], p)
            
        # Shift weekly index by 1 day (Sunday midnight to Monday midnight) to prevent lookahead bias
        # Weekly close of week ending Sunday D is fully available starting Monday D+1
        df_weekly_shifted = df_weekly.copy()
        df_weekly_shifted.index = df_weekly_shifted.index + pd.Timedelta(days=1)
        
        # Rename weekly columns
        rename_cols_weekly = {'close': 'weekly_close_aligned'}
        for p in [10, 20, 30]:
            rename_cols_weekly[f'ema_{p}'] = f'weekly_ema_{p}_aligned'
        df_weekly_shifted = df_weekly_shifted.reset_index().rename(columns=rename_cols_weekly)
        
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
        
        # Merge Daily CHOP and 1H data
        df_30m = df_30m.reset_index()
        df_30m['timestamp'] = df_30m['timestamp'].astype('datetime64[ns]')
        df_1h_aligned['timestamp'] = df_1h_aligned['timestamp'].astype('datetime64[ns]')
        df_weekly_shifted['timestamp'] = df_weekly_shifted['timestamp'].astype('datetime64[ns]')
        
        merge_cols = ['timestamp', 'h1_st_val', 'h1_st_dir', 'h1_adx', 'h1_close']
        for p in [150, 200]:
            merge_cols.extend([f'h1_dema_{p}', f'h1_ema_{p}'])
            
        df_merged = pd.merge_asof(
            df_30m,
            df_1h_aligned[merge_cols],
            on='timestamp',
            direction='backward'
        ).rename(columns={'h1_adx': 'adx_aligned'})
        
        # Merge weekly alignment columns
        weekly_merge_cols = ['timestamp', 'weekly_close_aligned']
        for p in [10, 20, 30]:
            weekly_merge_cols.append(f'weekly_ema_{p}_aligned')
            
        df_merged = pd.merge_asof(
            df_merged,
            df_weekly_shifted[weekly_merge_cols],
            on='timestamp',
            direction='backward'
        )
        
        df_merged.set_index('timestamp', inplace=True)
        datasets[contract] = df_merged
        
    sim = FastWeeklyRegimeSimulator()
    
    print("\n" + "=" * 80)
    print("💼 SWEEPING WEEKLY EMA REGIME-FILTERED PORTFOLIO CONFIGURATIONS")
    print("=" * 80)
    
    # We will test running on full 5-asset portfolio (since that is the main candidate for Weekly filter)
    # Asset list: BTC, ETH, SOL, LINK, DOGE
    results = []
    
    # Sweep:
    # - use_filter: True (Weekly EMA filter active), False (Benchmark without filter)
    # - weekly_ema_period: 10, 20, 30 weeks
    # - bull_risk: 1.0% (0.01), 1.5% (0.015), 2.0% (0.02)
    # - bear_risk: 0.25% (0.0025), 0.5% (0.005)
    
    # First run benchmark sweeps (use_filter = False)
    print("--- BENCHMARK RUNS (No Weekly EMA Filter) ---")
    for b_risk in [0.01, 0.015, 0.02]:
        res = sim.run_portfolio_weekly_regime(
            datasets, portfolio_configs,
            use_filter=False,
            weekly_ema_period=20, # dummy value, has no effect
            bull_risk=b_risk,
            bear_risk=0.0,
            )
        cagr = res["cagr"]
        max_dd = abs(res["max_dd"])
        sharpe = res["sharpe"]
        print(f"  BENCHMARK | Risk: {b_risk*100:5.2f}% | CAGR: {cagr*100:+7.2f}% | Max DD: {max_dd*100:6.2f}% | Sharpe: {sharpe:.2f} | Final: ${res['final_equity']:.2f}")
        results.append({
            "type": "BENCHMARK",
            "weekly_ema_period": 0,
            "bull_risk_pct": b_risk * 100,
            "bear_risk_pct": 0.0,
            "cagr_pct": cagr * 100,
            "max_dd_pct": max_dd * 100,
            "sharpe": sharpe,
            "final_equity": res["final_equity"],
            "total_trades": res["total_trades"]
        })
        
    print("\n--- FILTERED RUNS (Weekly EMA Filter Active) ---")
    for ema_p in [10, 20, 30]:
        for b_risk in [0.01, 0.015, 0.02]:
            for bear_r in [0.0025, 0.005]:
                res = sim.run_portfolio_weekly_regime(
                    datasets, portfolio_configs,
                    use_filter=True,
                    weekly_ema_period=ema_p,
                    bull_risk=b_risk,
                    bear_risk=bear_r
                )
                cagr = res["cagr"]
                max_dd = abs(res["max_dd"])
                sharpe = res["sharpe"]
                print(f"  FILTERED  | EMA Period: {ema_p:2d}w | BullRisk: {b_risk*100:5.2f}% | BearRisk: {bear_r*100:5.2f}% | CAGR: {cagr*100:+7.2f}% | Max DD: {max_dd*100:6.2f}% | Sharpe: {sharpe:.2f} | Final: ${res['final_equity']:.2f}")
                results.append({
                    "type": "FILTERED",
                    "weekly_ema_period": ema_p,
                    "bull_risk_pct": b_risk * 100,
                    "bear_risk_pct": bear_r * 100,
                    "cagr_pct": cagr * 100,
                    "max_dd_pct": max_dd * 100,
                    "sharpe": sharpe,
                    "final_equity": res["final_equity"],
                    "total_trades": res["total_trades"]
                })
                
    # Save sweep results
    filepath = os.path.join(RESULTS_DIR, "weekly_regime_sweep.json")
    with open(filepath, "w") as f:
        json.dump(results, f, indent=4)
        
    print("\n" + "=" * 80)
    print(f"🎉 Weekly Regime Backtests Completed! Results saved to: backtest/results/weekly_regime_sweep.json")
    print("=" * 80)


if __name__ == "__main__":
    run_weekly_regime_backtest()
