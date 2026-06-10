import os
import sys
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# Ensure project directory is in path
sys.path.insert(0, r"c:\Users\Jason Zhang\OneDrive\6Career\100KProject\CryptoTrading\ETH_Perp_Trading_Bot\ETH_Perp_Trading_bot")

from indicators import (
    calculate_supertrend, calculate_dema, calculate_adx,
    calculate_ema, calculate_atr, calculate_rsi
)

DATA_DIR = r"c:\Users\Jason Zhang\OneDrive\6Career\100KProject\CryptoTrading\ETH_Perp_Trading_Bot\ETH_Perp_Trading_bot\backtest\data"

def load_data(contract: str) -> tuple:
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
            face_value = 100.0
            slippage = 0.00005
        else:
            face_value = 1.0
            slippage = 0.01
        return face_value, slippage

    def run_single(self, df_merged: pd.DataFrame, contract: str, cfg: dict) -> dict:
        face_value, slippage = self.get_contract_params(contract)
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
        rsi = df_merged['rsi_30m'].values if 'rsi_30m' in df_merged.columns else None
        atr = df_merged['atr_val'].values if 'atr_val' in df_merged.columns else None
        
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

def run_diagnostic():
    contracts = ["SOL_USDT", "LINK_USDT", "DOGE_USDT"]
    sim = FastSimulator5Asset()
    
    for contract in contracts:
        print(f"\n=======================================================")
        print(f"🔍 UPGRADED SWEEP ANALYSIS FOR {contract}")
        print(f"=======================================================")
        
        df_30m, df_1h = load_data(contract)
        if df_30m is None or df_1h is None:
            print(f"Missing data for {contract}")
            continue
            
        # Precompute indicators
        df_30m = df_30m.copy()
        df_1h = df_1h.copy()
        st_res = calculate_supertrend(df_30m, 10, 3.0)
        df_30m['st_val'] = st_res['supertrend']
        df_30m['st_dir'] = st_res['direction']
        df_30m['atr_val'] = calculate_atr(df_30m, 14)
        df_30m['rsi_30m'] = calculate_rsi(df_30m['close'], 14)
        
        st_res_1h = calculate_supertrend(df_1h, 10, 3.0)
        df_1h['st_val'] = st_res_1h['supertrend']
        df_1h['st_dir'] = st_res_1h['direction']
        df_1h['adx'] = calculate_adx(df_1h, 16)
        for p in [150, 200]:
            df_1h[f'dema_{p}'] = calculate_dema(df_1h['close'], p)
            df_1h[f'ema_{p}'] = calculate_ema(df_1h['close'], p)
            
        df_1h_aligned = df_1h.copy()
        df_1h_aligned.index = df_1h_aligned.index + pd.Timedelta(hours=1)
        rename_cols = {'st_val': 'h1_st_val', 'st_dir': 'h1_st_dir', 'adx': 'h1_adx', 'close': 'h1_close'}
        for p in [150, 200]:
            rename_cols[f'dema_{p}'] = f'h1_dema_{p}'
            rename_cols[f'ema_{p}'] = f'h1_ema_{p}'
        df_1h_aligned = df_1h_aligned.reset_index().rename(columns=rename_cols)
        
        df_30m = df_30m.reset_index()
        df_30m['timestamp'] = df_30m['timestamp'].astype('datetime64[ns]')
        df_1h_aligned['timestamp'] = df_1h_aligned['timestamp'].astype('datetime64[ns]')
        
        merge_cols = ['timestamp', 'h1_st_val', 'h1_st_dir', 'h1_adx', 'h1_close']
        for p in [150, 200]:
            merge_cols.extend([f'h1_dema_{p}', f'h1_ema_{p}'])
            
        df_merged = pd.merge_asof(df_30m, df_1h_aligned[merge_cols], on='timestamp', direction='backward').rename(columns={'h1_adx': 'adx_aligned'})
        df_merged.set_index('timestamp', inplace=True)
        
        # Run sweeps
        all_results = []
        # A. SuperTrend Breakout
        for tf_filter in ["ema", "dema", "none"]:
            for ma_period in [150, 200]:
                for tp in [4.0, 5.0, 6.0, 8.0, 10.0]:
                    for adx_t in [25.0, 30.0]:
                        cfg = {
                            "entry_signal": "supertrend",
                            "trend_filter_1h": tf_filter,
                            "dema_period": ma_period,
                            "tp_ratio": tp,
                            "adx_threshold": adx_t,
                            "sl_type": "supertrend"
                        }
                        res = sim.run_single(df_merged, contract, cfg)
                        all_results.append({"cfg": cfg, "res": res})
                        
        # B. RSI Pullback
        for tf_filter in ["ema", "dema"]:
            for ma_period in [150, 200]:
                for tp in [3.0, 4.0, 5.0, 6.0]:
                    for rsi_low, rsi_high in [(40.0, 60.0), (45.0, 55.0)]:
                        for adx_t in [20.0, 25.0]:
                            for sl_atr in [2.0, 2.5, 3.0]:
                                cfg = {
                                    "entry_signal": "rsi_pullback",
                                    "trend_filter_1h": tf_filter,
                                    "dema_period": ma_period,
                                    "tp_ratio": tp,
                                    "adx_threshold": adx_t,
                                    "rsi_pullback_lower": rsi_low,
                                    "rsi_pullback_upper": rsi_high,
                                    "sl_type": "atr",
                                    "sl_atr_mult": sl_atr
                                }
                                res = sim.run_single(df_merged, contract, cfg)
                                all_results.append({"cfg": cfg, "res": res})
                                
        # Sort by CAGR
        sorted_by_cagr = sorted(all_results, key=lambda x: x["res"]["cagr"], reverse=True)
        print("\nTOP 10 BY CAGR:")
        for idx, item in enumerate(sorted_by_cagr[:10]):
            cfg, res = item["cfg"], item["res"]
            sig = cfg.get("entry_signal")
            sl = cfg.get("sl_type")
            mult = cfg.get("sl_atr_mult", "N/A")
            print(f"  {idx+1:2d}. Signal: {sig:12s} | Filter: {cfg['trend_filter_1h']}_{cfg['dema_period']} | TP: {cfg['tp_ratio']}R | SL: {sl} ({mult}) | CAGR: {res['cagr']*100:+.2f}% | Max DD: {res['max_dd']*100:.2f}% | PF: {res['profit_factor']:.2f} | Final: ${res['final_equity']:.2f}")

if __name__ == "__main__":
    run_diagnostic()
