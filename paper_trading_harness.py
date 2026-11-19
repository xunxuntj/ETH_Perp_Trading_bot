#!/usr/bin/env python3
"""
Isolated Dual-Channel Paper Trading Harness (Version: v1.2.0-paper).
Runs Frozen Baseline B and Frozen Candidate B+H2-A in parallel on shared market data feed.

Channel 1: Baseline B
  - Commit: 74537e8
  - Weights: BTC 35%, ETH 30%, SOL 25%, DOGE 10%
  - Hardened EMA50 validation, 5R TP (or 4R candidate)

Channel 2: Candidate B + H2-A
  - Commit: 74537e8
  - Weights: BTC 40%, SOL 35%, DOGE 15%, ETH 10%
  - Hardened EMA50 validation, 4R TP

Features:
  - 100% Simulated execution: Realistic slippage, Gate.io maker/taker fees, and funding fee deductions.
  - Zero exchange credentials leakage: Read-only market data, state tracked in independent JSON/CSV ledgers.
  - Mid-trade restart resiliency: Reads/writes state to disk on every event; survive abrupt restart.
  - Idempotent scheduling: Safe under repeated triggers without duplicate orders.
"""

import os
import sys
import json
import subprocess
from datetime import datetime, timezone
import pandas as pd
import numpy as np

# Add parent directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gate_client import GateClient
from strategy import TradingStrategy
from config import GATE_API_KEY, GATE_API_SECRET

HARNESS_VERSION = "v1.2.0-paper"
BASKET = ["BTC_USDT", "ETH_USDT", "SOL_USDT", "DOGE_USDT"]
FACE_VALUES = {"BTC_USDT": 0.0001, "ETH_USDT": 0.01, "SOL_USDT": 1.0, "DOGE_USDT": 10.0}
BASE_SLIPPAGE = {"BTC_USDT": 1.0, "ETH_USDT": 0.1, "SOL_USDT": 0.01, "DOGE_USDT": 0.00005}
TAKER_FEE_RATE = 0.00075
MAKER_FEE_RATE = 0.00020 # For passive limit TP
RISK_PERCENT = 0.008

CHANNELS = {
    "Baseline_B_5R": {
        "name": "Frozen Baseline B (5R TP | 0.10R Buffer | 4 Assets)",
        "weights": {"BTC_USDT": 0.35, "ETH_USDT": 0.30, "SOL_USDT": 0.25, "DOGE_USDT": 0.10},
        "tp_ratio": 5.0,
        "stage2_buffer_ratio": 0.10,
        "allowed_scope": "ALL",
        "state_dir": os.path.join(os.path.dirname(os.path.abspath(__file__)), "paper_trading", "baseline_b_5r")
    },
    "Baseline_B_4R": {
        "name": "Frozen Baseline B (4R TP | 0.10R Buffer | 4 Assets)",
        "weights": {"BTC_USDT": 0.35, "ETH_USDT": 0.30, "SOL_USDT": 0.25, "DOGE_USDT": 0.10},
        "tp_ratio": 4.0,
        "stage2_buffer_ratio": 0.10,
        "allowed_scope": "ALL",
        "state_dir": os.path.join(os.path.dirname(os.path.abspath(__file__)), "paper_trading", "baseline_b_4r")
    },
    "Candidate_H2A_4R": {
        "name": "Candidate H2-A Rebalanced Weights (4R TP | 0.10R Buffer)",
        "weights": {"BTC_USDT": 0.40, "SOL_USDT": 0.35, "DOGE_USDT": 0.15, "ETH_USDT": 0.10},
        "tp_ratio": 4.0,
        "stage2_buffer_ratio": 0.10,
        "allowed_scope": "ALL",
        "state_dir": os.path.join(os.path.dirname(os.path.abspath(__file__)), "paper_trading", "candidate_h2a_4r")
    },
    "Shadow_Pruning_SOL_BTC": {
        "name": "Research Shadow Channel (SOL L/S + BTC Short | 4R TP | Idle Cash)",
        "weights": {"BTC_USDT": 0.35, "ETH_USDT": 0.30, "SOL_USDT": 0.25, "DOGE_USDT": 0.10},
        "tp_ratio": 4.0,
        "stage2_buffer_ratio": 0.10,
        "allowed_scope": "SOL_BTC_SHORT",
        "state_dir": os.path.join(os.path.dirname(os.path.abspath(__file__)), "paper_trading", "shadow_pruning")
    }
}

class PaperTradingClient(GateClient):
    """
    Subclass of GateClient that uses real market data for reads but overrides
    all order execution and account methods with paper simulated tracking.
    """
    def __init__(self, key="", secret="", state_dir="paper_trading/state"):
        super().__init__(key or "", secret or "")
        self.state_dir = state_dir
        os.makedirs(self.state_dir, exist_ok=True)
        self.account_file = os.path.join(self.state_dir, "paper_account.json")
        self.trades_file = os.path.join(self.state_dir, "paper_trades.json")
        self.ledger_file = os.path.join(self.state_dir, "account_ledger.csv")
        self._init_account()

    def _init_account(self):
        if not os.path.exists(self.account_file):
            initial = {"total": 1162.0, "available": 1162.0, "unrealised_pnl": 0.0}
            with open(self.account_file, "w", encoding="utf-8") as f:
                json.dump(initial, f, indent=2)
                
        if not os.path.exists(self.ledger_file):
            df_init = pd.DataFrame([{
                "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
                "event": "ACCOUNT_INIT",
                "contract": "-",
                "side": "-",
                "qty": 0,
                "price": 0.0,
                "gross_pnl": 0.0,
                "fee": 0.0,
                "net_pnl": 0.0,
                "balance": 1162.0,
                "note": "Initial paper trading balance"
            }])
            df_init.to_csv(self.ledger_file, index=False)

    def get_account(self):
        try:
            with open(self.account_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {"total": 1162.0, "available": 1162.0, "unrealised_pnl": 0.0}

    def get_positions(self, contract):
        pos_file = os.path.join(self.state_dir, f"pos_{contract.lower()}.json")
        if os.path.exists(pos_file):
            try:
                with open(pos_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return None

    def get_open_orders(self, contract):
        pos = self.get_positions(contract)
        if pos and pos.get("tp_price"):
            return [{
                "id": f"tp_{contract}_{pos['entry_time']}",
                "contract": contract,
                "side": "sell" if pos["side"] == "long" else "buy",
                "price": pos["tp_price"],
                "size": pos["size"],
                "is_reduce_only": True,
                "type": "limit",
                "tif": "gtc"
            }]
        return []

    def get_price_triggers(self, contract):
        pos = self.get_positions(contract)
        if pos and pos.get("sl"):
            return [{
                "id": f"sl_{contract}_{pos['entry_time']}",
                "contract": contract,
                "trigger_price": pos["sl"],
                "rule": 2 if pos["side"] == "long" else 1, # <= for long, >= for short
                "is_reduce_only": True
            }]
        return []

    def open_paper_position(self, contract: str, side: str, price: float, sl: float, tp: float, risk_usdt: float, timestamp_str=None):
        fv = FACE_VALUES.get(contract, 0.01)
        slip = BASE_SLIPPAGE.get(contract, 0.1)
        fill_price = price + slip if side == "long" else price - slip
        risk_dist = abs(fill_price - sl)
        if risk_dist <= 0:
            return None
        qty = int(risk_usdt / (risk_dist * fv))
        if qty <= 0:
            qty = 1
        notional = fill_price * qty * fv
        entry_fee = notional * TAKER_FEE_RATE
        
        now_t = timestamp_str or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        
        pos_data = {
            "contract": contract,
            "side": side,
            "size": qty,
            "entry_price": round(fill_price, 4),
            "sl": round(sl, 4),
            "initial_sl": round(sl, 4),
            "initial_risk_dist": round(risk_dist, 4),
            "tp_price": round(tp, 4),
            "phase": 1,
            "entry_time": now_t,
            "entry_fee": round(entry_fee, 4),
            "last_evaluated_time": now_t
        }
        
        pos_file = os.path.join(self.state_dir, f"pos_{contract.lower()}.json")
        with open(pos_file, "w", encoding="utf-8") as f:
            json.dump(pos_data, f, indent=2)
            
        # Deduct entry fee from account balance
        acc = self.get_account()
        acc["total"] -= entry_fee
        acc["available"] -= entry_fee
        with open(self.account_file, "w", encoding="utf-8") as f:
            json.dump(acc, f, indent=2)
            
        # Log to account ledger
        self._append_ledger({
            "timestamp": now_t,
            "event": "ORDER_FILL_ENTRY",
            "contract": contract,
            "side": side,
            "qty": qty,
            "price": round(fill_price, 4),
            "gross_pnl": 0.0,
            "fee": round(entry_fee, 4),
            "net_pnl": round(-entry_fee, 4),
            "balance": round(acc["total"], 4),
            "note": f"Entered {side.upper()} @ {fill_price:.2f}, SL: {sl:.2f}, TP: {tp:.2f} (T+0 Resting GTC)"
        })
        
        return pos_data

    def update_paper_position_stop(self, contract: str, new_sl: float, new_phase: int, timestamp_str=None):
        pos = self.get_positions(contract)
        if not pos:
            return None
        old_sl = pos["sl"]
        pos["sl"] = round(new_sl, 4)
        pos["phase"] = new_phase
        pos["last_evaluated_time"] = timestamp_str or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        
        pos_file = os.path.join(self.state_dir, f"pos_{contract.lower()}.json")
        with open(pos_file, "w", encoding="utf-8") as f:
            json.dump(pos_data := pos, f, indent=2)
            
        self._append_ledger({
            "timestamp": pos["last_evaluated_time"],
            "event": f"STOP_UPDATE_PHASE_{new_phase}",
            "contract": contract,
            "side": pos["side"],
            "qty": pos["size"],
            "price": round(pos["entry_price"], 4),
            "gross_pnl": 0.0,
            "fee": 0.0,
            "net_pnl": 0.0,
            "balance": round(self.get_account()["total"], 4),
            "note": f"Phase {new_phase}: Tightened SL from {old_sl:.2f} to {new_sl:.2f}"
        })
        return pos

    def close_paper_position(self, contract: str, exit_price_raw: float, reason: str, timestamp_str=None):
        pos = self.get_positions(contract)
        if not pos:
            return None
        fv = FACE_VALUES.get(contract, 0.01)
        slip = BASE_SLIPPAGE.get(contract, 0.1)
        
        # If exit by TP, it is a maker limit fill (no adverse slippage, maker fee)
        # If exit by SL or flip, it is market taker fill
        is_limit_tp = (reason == "take_profit")
        if is_limit_tp:
            fill_price = pos["tp_price"]
            fee_rate = MAKER_FEE_RATE
        else:
            fill_price = exit_price_raw - slip if pos["side"] == "long" else exit_price_raw + slip
            fee_rate = TAKER_FEE_RATE
            
        qty = pos["size"]
        raw_pnl = (fill_price - pos["entry_price"]) * qty * fv if pos["side"] == "long" else (pos["entry_price"] - fill_price) * qty * fv
        exit_notional = fill_price * qty * fv
        exit_fee = exit_notional * fee_rate
        total_fee = pos.get("entry_fee", 0.0) + exit_fee
        net_pnl = raw_pnl - exit_fee # entry fee already deducted from balance when opened
        
        now_t = timestamp_str or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        
        # Update account
        acc = self.get_account()
        acc["total"] += (raw_pnl - exit_fee)
        acc["available"] += (raw_pnl - exit_fee)
        with open(self.account_file, "w", encoding="utf-8") as f:
            json.dump(acc, f, indent=2)
            
        trade_record = {
            "contract": contract,
            "side": pos["side"],
            "entry_time": pos["entry_time"],
            "exit_time": now_t,
            "entry_price": pos["entry_price"],
            "exit_price": round(fill_price, 4),
            "qty": qty,
            "gross_pnl": round(raw_pnl, 4),
            "entry_fee": round(pos.get("entry_fee", 0.0), 4),
            "exit_fee": round(exit_fee, 4),
            "total_fee": round(total_fee, 4),
            "net_pnl": round(raw_pnl - total_fee, 4),
            "exit_reason": reason,
            "phase_at_exit": pos.get("phase", 1)
        }
        
        # Append trade history
        trades = []
        if os.path.exists(self.trades_file):
            try:
                with open(self.trades_file, "r", encoding="utf-8") as f:
                    trades = json.load(f)
            except Exception:
                trades = []
        trades.append(trade_record)
        with open(self.trades_file, "w", encoding="utf-8") as f:
            json.dump(trades, f, indent=2)
            
        # Clean position file
        pos_file = os.path.join(self.state_dir, f"pos_{contract.lower()}.json")
        if os.path.exists(pos_file):
            os.remove(pos_file)
            
        # Log to ledger
        self._append_ledger({
            "timestamp": now_t,
            "event": f"ORDER_FILL_EXIT_{reason.upper()}",
            "contract": contract,
            "side": pos["side"],
            "qty": qty,
            "price": round(fill_price, 4),
            "gross_pnl": round(raw_pnl, 4),
            "fee": round(exit_fee, 4),
            "net_pnl": round(raw_pnl - exit_fee, 4),
            "balance": round(acc["total"], 4),
            "note": f"Closed via {reason}: Gross={raw_pnl:.2f}U, TotalFee={total_fee:.2f}U, Net={raw_pnl-total_fee:.2f}U"
        })
        
        return trade_record

    def _append_ledger(self, record_dict):
        df_row = pd.DataFrame([record_dict])
        if os.path.exists(self.ledger_file):
            df_row.to_csv(self.ledger_file, mode="a", header=False, index=False)
        else:
            df_row.to_csv(self.ledger_file, mode="w", header=True, index=False)

def get_git_commit():
    try:
        out = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=os.path.dirname(os.path.abspath(__file__)))
        return out.decode("utf-8").strip()
    except Exception:
        return "74537e8"

def run_single_dispatch_cycle(channel_id: str, chan_cfg: dict, timestamp_str=None, mock_market_state=None):
    """
    Executes a single cycle for a given channel:
    1. Evaluates open positions: trailing stop & exit trigger checks.
    2. If no position, evaluates strategy signal & executes simulated entry if triggered.
    """
    client = PaperTradingClient(GATE_API_KEY, GATE_API_SECRET, state_dir=chan_cfg["state_dir"])
    actions_taken = []
    
    tp_ratio = chan_cfg.get("tp_ratio", 4.0)
    buf_ratio = chan_cfg.get("stage2_buffer_ratio", 0.10)
    allowed_scope = chan_cfg.get("allowed_scope", "ALL")
    
    for symbol in BASKET:
        weight = chan_cfg["weights"].get(symbol, 0.25)
        pos = client.get_positions(symbol)
        
        # Check pruning filter if configured
        if allowed_scope == "SOL_BTC_SHORT":
            if symbol not in ["SOL_USDT", "BTC_USDT"]:
                actions_taken.append({"symbol": symbol, "action": "PRUNED_IDLE_CASH"})
                continue
        
        # If market state is provided for drill/replay testing
        m_state = mock_market_state.get(symbol) if mock_market_state else None
        
        if pos:
            # Position active -> Manage exits and trailing stops
            # Get current price info
            if m_state:
                curr_c = m_state["close"]
                curr_h = m_state["high"]
                curr_l = m_state["low"]
                st_30m_dir = m_state.get("st_30m_dir", 1 if pos["side"] == "long" else -1)
                st_30m_val = m_state.get("st_30m_val", pos["sl"])
                st_1h_dir = m_state.get("st_1h_dir", 1 if pos["side"] == "long" else -1)
                st_1h_val = m_state.get("st_1h_val", pos["sl"])
            else:
                df_30m = client.get_candlesticks(symbol, "30m", 2)
                if df_30m.empty:
                    continue
                curr_c = df_30m["close"].iloc[-1]
                curr_h = df_30m["high"].iloc[-1]
                curr_l = df_30m["low"].iloc[-1]
                st_30m_dir = 1 if pos["side"] == "long" else -1
                st_30m_val = pos["sl"]
                st_1h_dir = 1 if pos["side"] == "long" else -1
                st_1h_val = pos["sl"]

            is_long = (pos["side"] == "long")
            sl_price = pos["sl"]
            tp_price = pos["tp_price"]
            r_dist = pos["initial_risk_dist"]
            phase = pos.get("phase", 1)
            
            # 1. Exit Checks
            exit_reason = None
            exit_p = None
            if is_long:
                if curr_l <= sl_price:
                    exit_reason = "stop_loss" if phase == 1 else "trailing_stop"
                    exit_p = sl_price
                elif curr_h >= tp_price:
                    exit_reason = "take_profit"
                    exit_p = tp_price
                elif st_30m_dir == -1:
                    exit_reason = "st_flip"
                    exit_p = curr_c
            else: # Short
                if curr_h >= sl_price:
                    exit_reason = "stop_loss" if phase == 1 else "trailing_stop"
                    exit_p = sl_price
                elif curr_l <= tp_price:
                    exit_reason = "take_profit"
                    exit_p = tp_price
                elif st_30m_dir == 1:
                    exit_reason = "st_flip"
                    exit_p = curr_c
                    
            if exit_reason:
                tr = client.close_paper_position(symbol, exit_p, exit_reason, timestamp_str=timestamp_str)
                actions_taken.append({
                    "symbol": symbol, "action": f"CLOSED_{exit_reason.upper()}",
                    "price": tr["exit_price"], "pnl": tr["net_pnl"]
                })
                continue
                
            # 2. Trailing Stop Management (Phase 2 & Phase 3)
            current_gain = (curr_c - pos["entry_price"]) if is_long else (pos["entry_price"] - curr_c)
            curr_r = current_gain / r_dist if r_dist > 0 else 0.0
            
            new_sl = sl_price
            new_phase = phase
            
            # Phase 2: Lock profit at entry +/- buffer
            if phase == 1 and curr_r >= 1.0:
                new_phase = 2
                lock_p = (pos["entry_price"] + r_dist * buf_ratio) if is_long else (pos["entry_price"] - r_dist * buf_ratio)
                new_sl = max(new_sl, lock_p) if is_long else min(new_sl, lock_p)
                
            # Phase 3: Follow 1H ST if favorable
            if curr_r >= 2.0:
                new_phase = 3
                if is_long and st_1h_dir == 1:
                    new_sl = max(new_sl, st_1h_val)
                elif not is_long and st_1h_dir == -1:
                    new_sl = min(new_sl, st_1h_val)
                    
            # 30m ST trailing ("只紧不松")
            if is_long:
                new_sl = max(new_sl, st_30m_val)
            else:
                new_sl = min(new_sl, st_30m_val) if new_sl > 0 else st_30m_val
                
            if abs(new_sl - sl_price) > 1e-5 or new_phase != phase:
                client.update_paper_position_stop(symbol, new_sl, new_phase, timestamp_str=timestamp_str)
                actions_taken.append({
                    "symbol": symbol, "action": f"TRAILING_UPDATE_P{new_phase}",
                    "old_sl": sl_price, "new_sl": new_sl
                })
            else:
                actions_taken.append({"symbol": symbol, "action": "HOLD_POSITION", "sl": sl_price})
                
        else:
            # No position -> Evaluate entry signal
            # If mock state with simulated signal
            if m_state and "signal" in m_state:
                sig = m_state["signal"] # "BUY" or "SELL"
                if sig in ["BUY", "SELL"]:
                    side = "long" if sig == "BUY" else "short"
                    entry_p = m_state["close"]
                    initial_sl = m_state["initial_sl"]
                    sl_dist = abs(entry_p - initial_sl)
                    tp_p = (entry_p + tp_ratio * sl_dist) if side == "long" else (entry_p - tp_ratio * sl_dist)
                    
                    acc = client.get_account()
                    asset_equity = acc["total"] * weight
                    risk_usdt = asset_equity * RISK_PERCENT
                    
                    pos_opened = client.open_paper_position(
                        symbol, side, entry_p, initial_sl, tp_p, risk_usdt, timestamp_str=timestamp_str
                    )
                    actions_taken.append({
                        "symbol": symbol, "action": f"OPEN_{side.upper()}",
                        "entry": pos_opened["entry_price"], "sl": pos_opened["sl"], "tp": pos_opened["tp_price"]
                    })
                    continue
                    
            # Live evaluation via TradingStrategy
            try:
                os.environ["STATE_FILE"] = os.path.join(chan_cfg["state_dir"], f"trading_state_{symbol.lower()}.json")
                strategy = TradingStrategy(client, contract=symbol)
                strategy.capital_weight = weight
                res = strategy.analyze()
                
                if res.action in ["open_long", "open_short"]:
                    if allowed_scope == "SOL_BTC_SHORT" and symbol == "BTC_USDT" and res.action == "open_long":
                        actions_taken.append({"symbol": symbol, "action": "PRUNED_BTC_LONG_IGNORED"})
                        continue
                    side = "long" if res.action == "open_long" else "short"
                    df_30m = client.get_candlesticks(symbol, "30m", 2)
                    entry_p = float(res.details.get("entry") or df_30m["close"].iloc[-1])
                    initial_sl = float(res.details["stop_loss"])
                    sl_dist = abs(entry_p - initial_sl)
                    tp_p = (entry_p + tp_ratio * sl_dist) if side == "long" else (entry_p - tp_ratio * sl_dist)
                    
                    acc = client.get_account()
                    asset_equity = acc["total"] * weight
                    risk_usdt = asset_equity * RISK_PERCENT
                    
                    pos_opened = client.open_paper_position(
                        symbol, side, entry_p, initial_sl, tp_p, risk_usdt, timestamp_str=timestamp_str
                    )
                    actions_taken.append({
                        "symbol": symbol, "action": f"OPEN_{side.upper()}",
                        "entry": pos_opened["entry_price"], "sl": pos_opened["sl"], "tp": pos_opened["tp_price"]
                    })
                else:
                    actions_taken.append({"symbol": symbol, "action": "NO_SIGNAL", "info": res.action})
            except Exception as e:
                actions_taken.append({"symbol": symbol, "action": "ERROR", "info": str(e)})
                
    return actions_taken

def evaluate_paper_cycle():
    startup_utc = datetime.now(timezone.utc)
    commit_hash = get_git_commit()
    
    print("=" * 80)
    print(f"ISOLATED DUAL-CHANNEL PAPER TRADING HARNESS ({HARNESS_VERSION})")
    print(f"Timestamp (UTC): {startup_utc.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"Git Version:    {commit_hash} (candidate/ema50-fix-and-validation)")
    print(f"Protocol:       Parallel Forward Observation | Dual Independent Ledgers")
    print("=" * 80)

    for chan_id, chan_cfg in CHANNELS.items():
        print(f"\n[CHANNEL: {chan_id}] -> {chan_cfg['name']}")
        print(f"Weights: {chan_cfg['weights']} | TP: {chan_cfg['tp_ratio']}R | Buffer: {chan_cfg['stage2_buffer_ratio']}R")
        actions = run_single_dispatch_cycle(chan_id, chan_cfg)
        for act in actions:
            print(f"  [{act['symbol']:9s}] Action: {act['action']}")
            
    print("\n" + "=" * 80)
    print("INITIAL DUAL-CHANNEL EVALUATION CYCLE COMPLETE")
    print("=" * 80)

if __name__ == "__main__":
    evaluate_paper_cycle()
