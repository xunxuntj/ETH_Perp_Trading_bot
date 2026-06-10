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

def analyze_hybrid_details():
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

    # Run modified simulator that logs mode for each trade
    sim = FastSimulatorHybrid()
    
    # We will test ChopThresh = 60.0, Risk = 1.0%, TP = 1.5R, SL = 2.5xATR
    chop_threshold = 60.0
    mr_tp_ratio = 1.5
    mr_sl_atr = 2.5
    risk_percent = 0.01
    
    # Let's run a custom simulation loop to collect mode-specific trade details
    sub_datasets = {c: datasets[c] for c in active_contracts}
    sub_configs = {c: portfolio_configs[c] for c in active_contracts}
    
    # Run simulation
    contracts = active_contracts
    times = sub_datasets["BTC_USDT"].index.to_pydatetime()
    n = len(times)
    
    highs = {c: sub_datasets[c]['high'].values for c in contracts}
    lows = {c: sub_datasets[c]['low'].values for c in contracts}
    closes = {c: sub_datasets[c]['close'].values for c in contracts}
    opens = {c: sub_datasets[c]['open'].values for c in contracts}
    st_vals = {c: sub_datasets[c]['st_val'].values for c in contracts}
    st_dirs = {c: sub_datasets[c]['st_dir'].values for c in contracts}
    h1_st_vals = {c: sub_datasets[c]['h1_st_val'].values for c in contracts}
    h1_st_dirs = {c: sub_datasets[c]['h1_st_dir'].values for c in contracts}
    h1_closes = {c: sub_datasets[c]['h1_close'].values for c in contracts}
    adxs = {c: sub_datasets[c]['adx_aligned'].values for c in contracts}
    rsis = {c: sub_datasets[c]['rsi_30m'].values for c in contracts}
    atrs = {c: sub_datasets[c]['atr_val'].values for c in contracts}
    chops = {c: sub_datasets[c]['chop_aligned'].values for c in contracts}
    
    h1_mas = {}
    face_values = {}
    slippages = {}
    for c in contracts:
        face_value, slippage = sim.get_contract_params(c)
        face_values[c] = face_value
        slippages[c] = slippage
        cfg = sub_configs[c]
        trend_filter = cfg.get("trend_filter_1h", "ema")
        dema_period = cfg.get("dema_period", 200)
        if trend_filter == "ema":
            h1_mas[c] = sub_datasets[c][f'h1_ema_{dema_period}'].values
        elif trend_filter == "dema":
            h1_mas[c] = sub_datasets[c][f'h1_dema_{dema_period}'].values
        else:
            h1_mas[c] = np.zeros(n)

    initial_capital = 1000.0
    equity = initial_capital
    
    in_pos = {c: False for c in contracts}
    pos_dir = {c: None for c in contracts}
    pos_mode = {c: None for c in contracts}
    entry_price = {c: 0.0 for c in contracts}
    sl = {c: 0.0 for c in contracts}
    tp = {c: None for c in contracts}
    phase = {c: 0 for c in contracts}
    qty = {c: 0 for c in contracts}
    consecutive_losses = {c: 0 for c in contracts}
    cooldown_until = {c: None for c in contracts}
    entry_time = {c: None for c in contracts}
    
    cb_until = None
    detailed_trades = []
    
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
                        
                    detailed_trades.append({
                        "Symbol": c,
                        "Dir": pos_dir[c],
                        "Mode": pos_mode[c],
                        "EntryTime": entry_time[c],
                        "ExitTime": t_curr,
                        "EntryPrice": entry_price[c],
                        "ExitPrice": actual_exit,
                        "Net PnL": net_pnl,
                        "Reason": exit_reason
                    })
                    in_pos[c] = False
                    pos_dir[c] = None
                    pos_mode[c] = None
                    tp[c] = None
                    closed_this_bar[c] = True
                else:
                    if pos_mode[c] == "trending":
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
                                
                            detailed_trades.append({
                                "Symbol": c,
                                "Dir": pos_dir[c],
                                "Mode": pos_mode[c],
                                "EntryTime": entry_time[c],
                                "ExitTime": t_curr,
                                "EntryPrice": entry_price[c],
                                "ExitPrice": actual_exit,
                                "Net PnL": net_pnl,
                                "Reason": "tech_exit"
                            })
                            in_pos[c] = False
                            pos_dir[c] = None
                            pos_mode[c] = None
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

        # 2. EVALUATE ENTRIES
        for c in contracts:
            if not in_pos[c] and not closed_this_bar[c] and not cb_until and not cooldown_until[c]:
                chop_v = chops[c][i-1]
                is_choppy = chop_v > chop_threshold if not np.isnan(chop_v) else False
                
                if is_choppy:
                    rsi_curr = rsis[c][i-1]
                    rsi_prev = rsis[c][i-2]
                    entry_long = (rsi_prev <= 30.0) and (rsi_curr > rsi_prev)
                    entry_short = (rsi_prev >= 70.0) and (rsi_curr < rsi_prev)
                    
                    if entry_long:
                        pos_dir[c] = "long"
                    elif entry_short:
                        pos_dir[c] = "short"
                        
                    if pos_dir[c] is not None:
                        entry_price[c] = opens[c][i]
                        entry_time[c] = t_curr
                        in_pos[c] = True
                        pos_mode[c] = "choppy"
                        phase[c] = 1
                        
                        atr_val = atrs[c][i-1]
                        sl[c] = entry_price[c] - mr_sl_atr * atr_val if entry_long else entry_price[c] + mr_sl_atr * atr_val
                        sl_d = abs(entry_price[c] - sl[c])
                        act_risk = current_equity * risk_percent
                        if 350.0 <= current_equity <= 500.0:
                            act_risk = 10.0
                        if sl_d > 0:
                            qty[c] = int(min(act_risk / (sl_d * face_values[c]), (current_equity * 5.0) / (entry_price[c] * face_values[c])))
                            if qty[c] <= 0: qty[c] = 1
                            tp[c] = entry_price[c] + mr_tp_ratio * sl_d if entry_long else entry_price[c] - mr_tp_ratio * sl_d
                        else:
                            qty[c] = 1
                            tp[c] = None
                else:
                    cfg = sub_configs[c]
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
                        pos_mode[c] = "trending"
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

    # Print summary
    df_trades = pd.DataFrame(detailed_trades)
    if df_trades.empty:
        print("No trades taken.")
        return
        
    print(f"\nTotal Trades: {len(df_trades)}")
    print(f"Final Equity: ${equity:.2f}")
    
    for mode in ["trending", "choppy"]:
        mode_trades = df_trades[df_trades["Mode"] == mode]
        if mode_trades.empty:
            print(f"\nMode: {mode.upper()} - No trades")
            continue
            
        wins = mode_trades[mode_trades["Net PnL"] > 0]
        losses = mode_trades[mode_trades["Net PnL"] <= 0]
        total = len(mode_trades)
        wr = len(wins) / total
        net_profit = mode_trades["Net PnL"].sum()
        avg_pnl = mode_trades["Net PnL"].mean()
        
        print(f"\nMode: {mode.upper()}")
        print(f"  Trades: {total}")
        print(f"  Win Rate: {wr*100:.2f}%")
        print(f"  Total PnL: ${net_profit:.2f}")
        print(f"  Avg PnL: ${avg_pnl:.2f}")
        print(f"  Wins: {len(wins)} (avg: ${wins['Net PnL'].mean():.2f})")
        print(f"  Losses: {len(losses)} (avg: ${losses['Net PnL'].mean():.2f})")
        
        # Stop loss vs Take profit ratio
        reason_counts = mode_trades["Reason"].value_counts()
        print(f"  Exits: {dict(reason_counts)}")

if __name__ == "__main__":
    analyze_hybrid_details()
