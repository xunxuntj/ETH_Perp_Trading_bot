import os
import sys
import pandas as pd
import numpy as np
import json
from datetime import datetime, timedelta

# Ensure parent directory is in path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from indicators import (
    calculate_supertrend, calculate_dema, calculate_adx,
    calculate_ema, calculate_atr, calculate_rsi, calculate_chop
)

from backtest.test_hybrid_regime_5y import load_data, FastSimulatorHybrid

def analyze_filter_only():
    contracts = ["BTC_USDT", "ETH_USDT", "SOL_USDT", "LINK_USDT", "DOGE_USDT"]
    datasets = {}
    
    # Load optimal configs
    backtest_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backtest")
    optimal_file = os.path.join(backtest_dir, "results", "optimal_5y_portfolio.json")
    
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

    # Process indicators for BTC and ETH
    active_contracts = ["BTC_USDT", "ETH_USDT"]
    for contract in active_contracts:
        df_30m, df_1h = load_data(contract)
        if df_30m is None or df_1h is None:
            print(f"Missing data for {contract}")
            return
            
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
        
        # Daily CHOP
        df_daily = df_1h.resample('D').agg({
            'high': 'max', 'low': 'min', 'close': 'last', 'open': 'first'
        }).dropna()
        df_daily['chop'] = calculate_chop(df_daily, 14)
        
        # Shift Daily index by 1 day
        df_daily_shifted = df_daily.copy()
        df_daily_shifted.index = df_daily_shifted.index + pd.Timedelta(days=1)
        df_daily_shifted = df_daily_shifted.reset_index().rename(columns={'chop': 'chop_aligned'})
        
        for p in [150, 200]:
            df_1h[f'dema_{p}'] = calculate_dema(df_1h['close'], p)
            df_1h[f'ema_{p}'] = calculate_ema(df_1h['close'], p)
            
        # Align 1H to 30m
        df_1h_aligned = df_1h.copy()
        df_1h_aligned.index = df_1h_aligned.index + pd.Timedelta(hours=1)
        
        rename_cols = {
            'st_val': 'h1_st_val', 'st_dir': 'h1_st_dir', 'adx': 'h1_adx', 'close': 'h1_close'
        }
        for p in [150, 200]:
            rename_cols[f'dema_{p}'] = f'h1_dema_{p}'
            rename_cols[f'ema_{p}'] = f'h1_ema_{p}'
            
        df_1h_aligned = df_1h_aligned.reset_index().rename(columns=rename_cols)
        
        # Merge
        df_30m = df_30m.reset_index()
        df_30m['timestamp'] = df_30m['timestamp'].astype('datetime64[ns]')
        df_1h_aligned['timestamp'] = df_1h_aligned['timestamp'].astype('datetime64[ns]')
        df_daily_shifted['timestamp'] = df_daily_shifted['timestamp'].astype('datetime64[ns]')
        
        merge_cols = ['timestamp', 'h1_st_val', 'h1_st_dir', 'h1_adx', 'h1_close']
        for p in [150, 200]:
            merge_cols.extend([f'h1_dema_{p}', f'h1_ema_{p}'])
            
        df_merged = pd.merge_asof(
            df_30m, df_1h_aligned[merge_cols], on='timestamp', direction='backward'
        ).rename(columns={'h1_adx': 'adx_aligned'})
        
        df_merged = pd.merge_asof(
            df_merged, df_daily_shifted[['timestamp', 'chop_aligned']], on='timestamp', direction='backward'
        )
        df_merged.set_index('timestamp', inplace=True)
        datasets[contract] = df_merged

    sim = FastSimulatorHybrid()
    
    # We will test Filter-Only with different CHOP thresholds
    # When is_choppy is True, we simply don't trade.
    
    # Custom simulation function to test Filter-Only
    def run_filter_only(chop_threshold, risk_percent):
        contracts = active_contracts
        times = datasets["BTC_USDT"].index.to_pydatetime()
        n = len(times)
        
        highs = {c: datasets[c]['high'].values for c in contracts}
        lows = {c: datasets[c]['low'].values for c in contracts}
        closes = {c: datasets[c]['close'].values for c in contracts}
        opens = {c: datasets[c]['open'].values for c in contracts}
        st_vals = {c: datasets[c]['st_val'].values for c in contracts}
        st_dirs = {c: datasets[c]['st_dir'].values for c in contracts}
        h1_st_vals = {c: datasets[c]['h1_st_val'].values for c in contracts}
        h1_st_dirs = {c: datasets[c]['h1_st_dir'].values for c in contracts}
        h1_closes = {c: datasets[c]['h1_close'].values for c in contracts}
        adxs = {c: datasets[c]['adx_aligned'].values for c in contracts}
        atrs = {c: datasets[c]['atr_val'].values for c in contracts}
        chops = {c: datasets[c]['chop_aligned'].values for c in contracts}
        
        h1_mas = {}
        face_values = {}
        slippages = {}
        for c in contracts:
            face_value, slippage = sim.get_contract_params(c)
            face_values[c] = face_value
            slippages[c] = slippage
            cfg = portfolio_configs[c]
            trend_filter = cfg.get("trend_filter_1h", "ema")
            dema_period = cfg.get("dema_period", 200)
            if trend_filter == "ema":
                h1_mas[c] = datasets[c][f'h1_ema_{dema_period}'].values
            elif trend_filter == "dema":
                h1_mas[c] = datasets[c][f'h1_dema_{dema_period}'].values
            else:
                h1_mas[c] = np.zeros(n)

        initial_capital = 1000.0
        equity = initial_capital
        capital_history = []
        trades = []
        
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
            
            # Exits
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
                        fee = (entry_price[c] + actual_exit) * qty[c] * face_values[c] * sim.fee_rate
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
                            
                        trades.append({"Symbol": c, "Net PnL": net_pnl, "Fee": fee})
                        in_pos[c] = False
                        pos_dir[c] = None
                        tp[c] = None
                        closed_this_bar[c] = True
                    else:
                        # Tech exits for trending positions
                        tech_exit = (phase[c] == 3 and h1_st_dirs[c][i-1] == -1 if pos_dir[c] == "long" else phase[c] == 3 and h1_st_dirs[c][i-1] == 1) or \
                                    ((phase[c] == 1 or phase[c] == 2) and st_dirs[c][i-1] == -1 if pos_dir[c] == "long" else (phase[c] == 1 or phase[c] == 2) and st_dirs[c][i-1] == 1)
                        if tech_exit:
                            exit_price = opens[c][i]
                            actual_exit = exit_price - slippages[c] if pos_dir[c] == "long" else exit_price + slippages[c]
                            pnl = (actual_exit - entry_price[c]) * qty[c] * face_values[c] if pos_dir[c] == "long" else (entry_price[c] - actual_exit) * qty[c] * face_values[c]
                            fee = (entry_price[c] + actual_exit) * qty[c] * face_values[c] * sim.fee_rate
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
                                
                            trades.append({"Symbol": c, "Net PnL": net_pnl, "Fee": fee})
                            in_pos[c] = False
                            pos_dir[c] = None
                            tp[c] = None
                            closed_this_bar[c] = True
                        else:
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

            # Entries
            for c in contracts:
                if not in_pos[c] and not closed_this_bar[c] and not cb_until and not cooldown_until[c]:
                    chop_v = chops[c][i-1]
                    is_choppy = chop_v > chop_threshold if not np.isnan(chop_v) else False
                    
                    if is_choppy:
                        # FILTER OUT! Do not enter any trades.
                        continue
                        
                    # Standard Trending entries
                    cfg = portfolio_configs[c]
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
                        else:
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

        total_t = len(trades)
        if total_t == 0:
            return {"cagr": 0, "max_dd": 0, "final_equity": equity, "total_trades": 0}
            
        df_cap = pd.DataFrame(capital_history, columns=["timestamp", "equity"])
        df_cap["running_max"] = df_cap["equity"].cummax()
        df_cap["drawdown"] = (df_cap["equity"] - df_cap["running_max"]) / df_cap["running_max"]
        max_dd = df_cap["drawdown"].min()
        
        days = (times[-1] - times[1000]).total_seconds() / (24 * 3600)
        cagr = (equity / initial_capital) ** (365.25 / days) - 1
        
        return {
            "cagr": cagr,
            "max_dd": max_dd,
            "final_equity": equity,
            "total_trades": total_t
        }

    print("=" * 80)
    print("🧹 TESTING FILTER-ONLY REGIME SWEEPS (BTC+ETH)")
    print("=" * 80)
    for risk in [0.01, 0.015, 0.02]:
        print(f"\nRisk Level: {risk*100:.1f}%")
        # Benchmark (ChopThresh = 999.0, no filtering)
        bench = run_filter_only(999.0, risk)
        print(f"  Benchmark (No Filter): CAGR = {bench['cagr']*100:+.2f}%, Max DD = {bench['max_dd']*100:.2f}%, Final = ${bench['final_equity']:.2f}, Trades = {bench['total_trades']}")
        
        # Test Chop thresholds
        for thresh in [50.0, 52.5, 55.0, 57.5, 60.0, 62.5, 65.0]:
            res = run_filter_only(thresh, risk)
            print(f"  Chop Thresh {thresh:.1f}:     CAGR = {res['cagr']*100:+.2f}%, Max DD = {res['max_dd']*100:.2f}%, Final = ${res['final_equity']:.2f}, Trades = {res['total_trades']}")

if __name__ == "__main__":
    analyze_filter_only()
