"""
交易策略逻辑
V9.6-Exec SOP 实现
"""

import json
import os
import time
from datetime import datetime, timezone
from typing import Optional
from dataclasses import dataclass, asdict
from enum import Enum

import pandas as pd

from config import (
    SUPERTREND_PERIOD, SUPERTREND_MULTIPLIER, DEMA_PERIOD,
    MAX_CONSECUTIVE_LOSSES, STATE_FILE,
    LEVERAGE, CIRCUIT_BREAKER_EQUITY, get_risk_amount,
    LOCK_PROFIT_BUFFER, FACE_VALUE,
    USE_ADX, ADX_LENGTH, ADX_THRESHOLD, ADX_TIMEFRAME, TP_RATIO, RISK_PERCENT,
    get_face_value, get_tp_ratio, get_adx_threshold, get_dema_period, get_default_tick_size
)

from position_state import update_position_state, clear_position_state, load_position_state
from indicators import calculate_supertrend, calculate_dema, calculate_adx, calculate_atr
from gate_client import GateClient


class Phase(Enum):
    """持仓阶段"""
    NONE = "none"           # 无持仓
    SURVIVAL = "survival"   # 阶段1: 生存期 (30m托管)
    LOCKED = "locked"       # 阶段2: 锁利期 (被动保本)
    HOURLY = "hourly"       # 阶段3: 换轨期 (1H托管)


class Direction(Enum):
    """方向"""
    LONG = "long"
    SHORT = "short"
    NONE = "none"


@dataclass
class Position:
    """持仓状态 - 仅用于记录辅助信息，不缓存持仓关键数据（阶段、止损等都从 API 推导）"""
    trade_count: int = 0             # 交易计数
    consecutive_losses: int = 0      # 连续亏损次数
    last_processed_30m_bar_ts: int = 0   # 去重: 最近一次已处理的30m已收盘K线时间戳
    last_processed_30m_bar_iso: str = ""  # 去重: 最近一次已处理的30m已收盘K线时间


# 合约面值（每张对应的代币数量），用于仓位/盈亏计算。由 config 模块提供


@dataclass
class TradeResult:
    """
    交易结果
    
    关键参考文档（见项目根目录）:
    • DEMA_ROOT_CAUSE_FIXED.md: DEMA精度优化说明（1000根K线，99.99%精度）
    • GATEIO_API_KLINE_GUIDE.md: K线获取和处理指南
    • README.md: 完整的策略规则和参数说明
    """
    action: str                      # open_long/open_short/close/adjust_sl/switch_1h/hold/none
    message: str
    details: dict = None


def get_state_filename(contract: str = "SOL_USDT") -> str:
    c_lower = (contract or "SOL_USDT").lower()
    if c_lower == "eth_usdt" and not os.environ.get("STATE_FILE"):
        return "trading_state.json"
    return os.environ.get("STATE_FILE") or f"trading_state_{c_lower}.json"


def load_state(contract: str = "SOL_USDT") -> Position:
    """加载辅助状态（仅交易计数和连续亏损）"""
    filename = get_state_filename(contract)
    if os.path.exists(filename):
        try:
            with open(filename, 'r') as f:
                data = json.load(f)
                return Position(
                    trade_count=data.get('trade_count', 0),
                    consecutive_losses=data.get('consecutive_losses', 0),
                    last_processed_30m_bar_ts=data.get('last_processed_30m_bar_ts', 0),
                    last_processed_30m_bar_iso=data.get('last_processed_30m_bar_iso', "")
                )
        except Exception:
            pass
    return Position()


def save_state(pos: Position, contract: str = "SOL_USDT"):
    """保存辅助状态（仅交易计数和连续亏损）"""
    filename = get_state_filename(contract)
    with open(filename, 'w') as f:
        json.dump({
            'trade_count': pos.trade_count,
            'consecutive_losses': pos.consecutive_losses,
            'last_processed_30m_bar_ts': pos.last_processed_30m_bar_ts,
            'last_processed_30m_bar_iso': pos.last_processed_30m_bar_iso,
        }, f, indent=2)



def calculate_lock_threshold(entry_price: float, qty: int, is_long: bool, risk_amount: float = 1.0,
                             face_value: Optional[float] = None) -> float:
    """
    计算锁利阈值
    
    期望盈利 = risk_amount * LOCK_PROFIT_BUFFER (单位: USDT)
    """
    fv = face_value if face_value is not None else FACE_VALUE
    position_eth = qty * fv
    if position_eth == 0:
        return entry_price
    
    buffer_usdt = risk_amount * LOCK_PROFIT_BUFFER
    if is_long:
        return entry_price + buffer_usdt / position_eth
    else:
        return entry_price - buffer_usdt / position_eth


def calculate_position_size(risk_amount: float, entry_price: float, stop_loss: float,
                            face_value: Optional[float] = None) -> dict:
    """
    计算开仓张数
    
    公式: Qty = R / |Entry - SL| / face_value (向下取整)
    """
    fv = face_value if face_value is not None else FACE_VALUE
    sl_distance = abs(entry_price - stop_loss)
    if sl_distance == 0 or risk_amount <= 0 or fv <= 0:
        return {"qty": 0, "sl_distance": 0, "position_eth": 0, 
                "position_value": 0, "margin_required": 0, "actual_risk": 0}
    
    qty = int(risk_amount / sl_distance / fv)  # 向下取整
    position_eth = qty * fv
    position_value = position_eth * entry_price
    margin_required = position_value / LEVERAGE
    actual_risk = qty * fv * sl_distance
    
    return {
        "qty": qty,
        "sl_distance": sl_distance,
        "position_eth": position_eth,
        "position_value": position_value,
        "margin_required": margin_required,
        "actual_risk": actual_risk
    }


def is_1h_tighter(last_1h_st: float, threshold: float, is_long: bool) -> bool:
    """判断上一完整 1H ST 是否比给定阈值更紧（多: 更高, 空: 更低）"""
    if is_long:
        return last_1h_st > threshold
    else:
        return last_1h_st < threshold


def tighten_stop_loss(candidate_stop: float, current_stop: float, is_long: bool) -> float:
    """对候选止损应用“只紧不松”原则。"""
    if current_stop <= 0:
        return candidate_stop

    if is_long:
        return max(candidate_stop, current_stop)
    return min(candidate_stop, current_stop)


class TradingStrategy:

    def _mark_processed_30m_bar(self, bar_ts: int, bar_iso: str):
        """记录本次已处理的30m已收盘K线，用于高频调度去重。"""
        self.state.last_processed_30m_bar_ts = bar_ts
        self.state.last_processed_30m_bar_iso = bar_iso
        save_state(self.state, self.contract)


    def _get_live_stop_price(self) -> float:
        """从交易所当前 open 的 price_orders 中提取止损触发价。"""
        try:
            orders = self.client.get_price_orders(contract=self.contract, status="open", limit=100)
            if not orders:
                return 0.0

            # 只取 reduce_only + auto_size=close 的持仓止损单
            for order in orders:
                initial = order.get("initial", {})
                is_reduce_only = initial.get("reduce_only")
                if is_reduce_only is None:
                    is_reduce_only = initial.get("is_reduce_only")

                if not (is_reduce_only and str(initial.get("auto_size", "")).lower() == "close"):
                    continue

                price = order.get("trigger", {}).get("price")
                if price is None:
                    continue

                try:
                    return float(price)
                except Exception:
                    continue

            return 0.0
        except Exception:
            return 0.0

    def _get_tick_size(self) -> float:
        """获取当前合约的价格单位 (order_price_round)"""
        try:
            contract_info = self.client.get_futures_contract(settle="usdt", contract=self.contract)
            return float(contract_info.get("order_price_round", "0.01"))
        except Exception:
            # 发生异常时根据合约名称给出安全的默认值
            return get_default_tick_size(self.contract)

    def _round_price(self, price: float) -> float:
        """根据合约价格单位对价格进行舍入"""
        if price is None:
            return None
        tick_size = self._get_tick_size()
        rounded = round(price / tick_size) * tick_size
        tick_str = f"{tick_size:.10f}".rstrip('0')
        decimals = len(tick_str.split('.')[1]) if '.' in tick_str else 0
        return round(rounded, decimals)

    def _infer_phase(self, entry_price: float, current_price: float, qty: int, 
                     last_30m_st: float, last_1h_st: float, is_long: bool,
                     initial_30m_st: float = 0, locked_stop_loss: float = 0,
                     prev_stop_loss: float = 0, risk_amount: float = 1.0,
                     prev_phase: str = "", face_value: Optional[float] = None) -> tuple:
        """
        Three-stage trailing stop state machine aligned with V1 Post-ETF Trading Card:
        - Stage 1 (SURVIVAL): Floating profit < 1.0R -> Trail 30m SuperTrend (tighten only).
        - Stage 2 (LOCKED): Floating profit >= 1.0R (or already unlocked) -> Force stop to
          entry +/- LOCK_PROFIT_BUFFER * R (default 0.5R), tighten only.
        - Stage 3 (HOURLY): Stage 2 unlocked AND 1H SuperTrend surpasses lock price ->
          Switch to 1H SuperTrend (tighten only, never looser than lock price).
        """
        fv = face_value if face_value is not None else get_face_value(self.contract)

        # Resolve initial 1R price distance
        if initial_30m_st and initial_30m_st > 0 and abs(entry_price - initial_30m_st) > 0:
            r_dist = abs(entry_price - initial_30m_st)
        elif qty > 0 and fv > 0 and risk_amount > 0:
            r_dist = risk_amount / (qty * fv)
        else:
            r_dist = 0.0

        # Compute floating profit in R multiples
        current_gain = (current_price - entry_price) if is_long else (entry_price - current_price)
        current_r = (current_gain / r_dist) if r_dist > 0 else 0.0

        # Lock profit price: entry +/- LOCK_PROFIT_BUFFER * R (default 0.5R)
        if r_dist > 0:
            lock_price = (entry_price + LOCK_PROFIT_BUFFER * r_dist) if is_long else (entry_price - LOCK_PROFIT_BUFFER * r_dist)
        else:
            lock_price = calculate_lock_threshold(entry_price, qty, is_long, risk_amount, face_value=fv)

        prev_phase_lower = str(prev_phase or "").lower()
        already_unlocked = prev_phase_lower in (Phase.LOCKED.value, Phase.HOURLY.value)
        reached_1r = current_r >= 1.0
        # Also allow unlock if prev_stop_loss already crossed lock_price (restart resilience)
        stop_already_locked = (
            prev_stop_loss > 0 and (
                (is_long and prev_stop_loss >= lock_price) or
                (not is_long and prev_stop_loss <= lock_price)
            )
        )
        is_unlocked = already_unlocked or reached_1r or stop_already_locked

        if os.getenv('GATE_DEBUG') or os.getenv('DEBUG'):
            print(
                f"[STRATEGY DEBUG] _infer_phase: entry={entry_price:.4f}, curr={current_price:.4f}, "
                f"r_dist={r_dist:.4f}, curr_R={current_r:.2f}R, lock_price={lock_price:.4f}, "
                f"30m_ST={last_30m_st:.4f}, 1h_ST={last_1h_st:.4f}, prev_stop={prev_stop_loss:.4f}, "
                f"prev_phase={prev_phase_lower}, is_unlocked={is_unlocked}"
            )

        # 【Stage 1 - SURVIVAL】: Not yet unlocked (floating profit < 1.0R)
        if not is_unlocked:
            phase = Phase.SURVIVAL.value
            recommended_stop = tighten_stop_loss(last_30m_st, prev_stop_loss, is_long)
            return phase, recommended_stop

        # 【Stage 3 - HOURLY】: Unlocked AND 1H ST has surpassed lock_price
        if is_1h_tighter(last_1h_st, lock_price, is_long):
            phase = Phase.HOURLY.value
            candidate_stop = tighten_stop_loss(last_1h_st, lock_price, is_long)
            recommended_stop = tighten_stop_loss(candidate_stop, prev_stop_loss, is_long)
            return phase, recommended_stop

        # 【Stage 2 - LOCKED】: Unlocked (>= 1.0R), force stop to lock_price (tighten only)
        phase = Phase.LOCKED.value
        recommended_stop = tighten_stop_loss(lock_price, prev_stop_loss, is_long)
        return phase, recommended_stop

    def _reconstruct_initial_30m_st(self, is_long: bool, entry_price: float, last_30m_st: float) -> float:
        """
        当本地状态丢失时，从 Gate.io 成交历史中重建仓位开仓时的初始 30m ST。
        """
        try:
            print(f"[RECONSTRUCT] 尝试从 Gate.io API 成交历史中恢复 {self.contract} {'多' if is_long else '空'}仓的初始 30m ST...")
            trades = self.client.get_my_trades(self.contract, limit=20)
            if not trades:
                print(f"[RECONSTRUCT WARNING] 未获取到成交记录。回退使用当前 30m ST: {last_30m_st:.2f}")
                return last_30m_st

            # 寻找与当前持仓方向相符且最近的开仓/加仓成交
            matched_trade = None
            for t in trades:
                trade_is_long = t['size'] > 0
                if trade_is_long == is_long:
                    # 取最近的一笔匹配交易作为近似入场点
                    matched_trade = t
                    break

            if not matched_trade:
                print(f"[RECONSTRUCT WARNING] 未找到匹配的成交记录。回退使用当前 30m ST: {last_30m_st:.2f}")
                return last_30m_st

            entry_time = matched_trade['time']
            trade_dt = datetime.fromtimestamp(entry_time, tz=timezone.utc).replace(tzinfo=None)
            print(f"[RECONSTRUCT] 找到匹配成交：价格={matched_trade['price']:.2f}, 数量={matched_trade['size']}, 时间={datetime.fromtimestamp(entry_time, tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")

            # 获取当时 30m 蜡烛线（300根大概覆盖最近 6 天）
            df_30m = self.client.get_candlesticks(self.contract, "30m", 300)
            if df_30m.empty:
                print(f"[RECONSTRUCT WARNING] 获取蜡烛线失败。回退使用当前 30m ST: {last_30m_st:.2f}")
                return last_30m_st

            # 计算 SuperTrend
            st_df = calculate_supertrend(df_30m, SUPERTREND_PERIOD, SUPERTREND_MULTIPLIER)
            
            # index 代表 K 线开始时间。所以信号收盘完成时间是 index + 30m
            # 因此要找：index + 30m <= entry_time 的最后一个
            signal_close_times = st_df.index + pd.Timedelta(minutes=30)
            valid_candles = st_df[signal_close_times <= trade_dt]

            if not valid_candles.empty:
                reconstructed_st = valid_candles['supertrend'].iloc[-1]
                print(f"[RECONSTRUCT SUCCESS] 成功恢复初始 30m ST = {reconstructed_st:.2f} (原当前值={last_30m_st:.2f})")
                return reconstructed_st
            else:
                print(f"[RECONSTRUCT WARNING] 成交时间超出 K 线缓存范围。回退使用当前 30m ST: {last_30m_st:.2f}")
                return last_30m_st

        except Exception as e:
            print(f"[RECONSTRUCT ERROR] 恢复初始 30m ST 异常: {e}。回退使用当前 30m ST: {last_30m_st:.2f}")
            return last_30m_st

    def __init__(self, client: GateClient, contract: str = "SOL_USDT"):
        self.client = client
        self.contract = contract
        self.state = load_state(contract)

    
    def analyze(self) -> TradeResult:
        """
        主分析函数
        
        策略规则（详见README.md）:
        - 做多: 1H ST绿 + 1H收盘 > DEMA200 + 30m ST绿
        - 做空: 1H ST红 + 1H收盘 < DEMA200 + 30m ST红
        
        持仓管理三阶段（详见GATEIO_API_KLINE_GUIDE.md）:
        1. 生存期: 止损跟随 30m ST
        2. 锁利期: 止损锁定不动，保底盈利
        3. 换轨期: 止损跟随 1H ST
        
        返回交易建议
        """
        # Resolve per-contract dynamic parameters (avoids static global leakage in multi-asset runs)
        contract_fv = get_face_value(self.contract)
        contract_tp_ratio = get_tp_ratio(self.contract)
        contract_dema_period = get_dema_period(self.contract)
        contract_adx_threshold = get_adx_threshold(self.contract)

        # 获取数据 (使用1000根K线以获得最优DEMA精度)
        df_30m = self.client.get_candlesticks(self.contract, "30m", 1000)
        df_1h = self.client.get_candlesticks(self.contract, "1h", 1000)

        # 记录本次 30m 已收盘 K 线时间戳（用于无持仓新开仓去重）
        signal_bar = df_30m.index[-2]
        signal_bar_ts = int(signal_bar.value // 10**9)
        signal_bar_iso = signal_bar.strftime('%Y-%m-%d %H:%M:%S')

        def finalize(result: TradeResult, mark_bar: bool = True) -> TradeResult:
            if mark_bar:
                self._mark_processed_30m_bar(signal_bar_ts, signal_bar_iso)
            return result
        
        # DEBUG: 记录K线时间戳和数据
        if os.getenv('DEBUG_KLINE'):
            print(f"[DEBUG KLINE] 1H最后两根K线时间戳:")
            print(f"  iloc[-2] (上一根完整): {df_1h.index[-2]} close={df_1h['close'].iloc[-2]:.2f}")
            print(f"  iloc[-1] (当前形成中): {df_1h.index[-1]} close={df_1h['close'].iloc[-1]:.2f}")
            print(f"[DEBUG KLINE] 30m最后K线时间: {df_30m.index[-1]}")
        
        # 计算指标 (使用已收盘的K线)
        st_30m = calculate_supertrend(df_30m, SUPERTREND_PERIOD, SUPERTREND_MULTIPLIER)
        st_1h = calculate_supertrend(df_1h, SUPERTREND_PERIOD, SUPERTREND_MULTIPLIER)
        dema_1h = calculate_dema(df_1h['close'], contract_dema_period)
        
        # 4H与1D周期数据重采样 (用于 V1 Post-ETF 机构化状态分类器)
        from indicators import calculate_chop, calculate_kaufman_er, calculate_atr_zscore, calculate_ema
        agg_dict = {'high': 'max', 'low': 'min', 'close': 'last'}
        if 'open' in df_1h.columns:
            agg_dict['open'] = 'first'
        if 'volume' in df_1h.columns:
            agg_dict['volume'] = 'sum'

        df_4h = df_1h.resample('4h').agg(agg_dict).dropna()

        chop_series_4h = calculate_chop(df_4h, 14)
        er_series_4h = calculate_kaufman_er(df_4h, 10)
        atr_z_series_1h = calculate_atr_zscore(df_1h, 14, 100)
        atr_series_1h = calculate_atr(df_1h, 14)
        ema20_series_30m = calculate_ema(df_30m['close'], 20)

        # V1 Post-ETF 机构化状态分类器判定: 严密日线 EMA50 计算与数据质量校验 (双重 1D 宏观过滤 + 安全降级)
        from daily_ema_validator import validate_and_extract_daily_ema50
        
        # 决策时刻严格取当前 30m 收盘时刻 (即当前 K 线开始形成的时刻)
        decision_time = df_30m.index[-1]
        if getattr(decision_time, 'tzinfo', None) is None:
            decision_time = decision_time.replace(tzinfo=timezone.utc)
        else:
            decision_time = decision_time.astimezone(timezone.utc)

        # 1. 获取并校验标的日线数据
        macro_filter_available = True
        macro_diag_msg = ""
        try:
            df_sym_1d = self.client.get_candlesticks(self.contract, "1d", 200)
            is_valid_sym, last_1d_close, last_1d_ema50, msg_sym = validate_and_extract_daily_ema50(df_sym_1d, decision_time, min_warmup_bars=150)
            if is_valid_sym:
                macro_1d_dir = 1 if last_1d_close >= last_1d_ema50 else -1
            else:
                macro_filter_available = False
                macro_1d_dir = 0
                macro_diag_msg += f"[{self.contract} 1D不可用: {msg_sym}] "
        except Exception as e:
            macro_filter_available = False
            macro_1d_dir = 0
            macro_diag_msg += f"[{self.contract} 1D获取异常: {e}] "

        # 2. 获取并校验 BTC 大盘日线数据 (严格双重同向校验)
        if self.contract.upper() == "BTC_USDT":
            btc_macro_1d_dir = macro_1d_dir
        else:
            try:
                df_btc_1d = self.client.get_candlesticks("BTC_USDT", "1d", 200)
                is_valid_btc, last_btc_close, last_btc_ema50, msg_btc = validate_and_extract_daily_ema50(df_btc_1d, decision_time, min_warmup_bars=150)
                if is_valid_btc:
                    btc_macro_1d_dir = 1 if last_btc_close >= last_btc_ema50 else -1
                else:
                    macro_filter_available = False
                    btc_macro_1d_dir = 0
                    macro_diag_msg += f"[BTC 1D不可用: {msg_btc}] "
            except Exception as e:
                macro_filter_available = False
                btc_macro_1d_dir = 0
                macro_diag_msg += f"[BTC 1D获取异常: {e}] "

        if not macro_filter_available:
            print(f"[MACRO FILTER PAUSE] ⚠️ 日线数据质量校验未通过，已安全暂停新开仓: {macro_diag_msg}")

        last_chop_4h = float(chop_series_4h.iloc[-2]) if len(chop_series_4h) >= 2 else 50.0
        last_er_4h = float(er_series_4h.iloc[-2]) if len(er_series_4h) >= 2 else 0.5
        last_atr_z_1h = float(atr_z_series_1h.iloc[-2]) if len(atr_z_series_1h) >= 2 else 0.0
        last_1h_atr = float(atr_series_1h.iloc[-2]) if len(atr_series_1h) >= 2 and pd.notna(atr_series_1h.iloc[-2]) else 0.0

        # Anti-sweep confirmation strictly uses the last CLOSED 30m candle (iloc[-2])
        last_30m_close = float(df_30m['close'].iloc[-2])
        last_ema20_30m = float(ema20_series_30m.iloc[-2])

        # 计算 ADX (默认关闭以对齐 V1 交易卡片，支持通过 USE_ADX=true 开启)
        df_adx_source = df_30m if ADX_TIMEFRAME == "30m" else df_1h
        adx_series = calculate_adx(df_adx_source, ADX_LENGTH)
        last_adx = float(adx_series.iloc[-2]) if pd.notna(adx_series.iloc[-2]) else 0.0
        # Respect module-level ADX_THRESHOLD if patched in tests; otherwise use contract-specific threshold
        eff_adx_threshold = ADX_THRESHOLD if os.environ.get("ADX_THRESHOLD") else (
            ADX_THRESHOLD if ADX_THRESHOLD not in (40.0, 45.0) else contract_adx_threshold
        )
        adx_is_trending = (not USE_ADX) or (last_adx > eff_adx_threshold)

        # 1H 数据 (上一根完整K线 = iloc[-2])
        last_1h_close = float(df_1h['close'].iloc[-2])
        last_1h_dema = float(dema_1h.iloc[-2])
        last_1h_dir = int(st_1h['direction'].iloc[-2])
        prev_1h_dir = int(st_1h['direction'].iloc[-3])
        last_1h_st = float(st_1h['supertrend'].iloc[-2])
        
        # 30m 数据 (上一根完整K线 = iloc[-2])
        last_30m_dir = int(st_30m['direction'].iloc[-2])
        last_30m_st = float(st_30m['supertrend'].iloc[-2])

        current_price = float(df_30m['close'].iloc[-1])
        
        # 获取账户和持仓
        try:
            account = self.client.get_account()
            # 总是打印account信息便于调试
            print(f"\n[ACCOUNT INFO] 原始API返回: {account}")
        except Exception as e:
            print(f"[ERROR] get_account() failed: {e}")
            account = None

        try:
            position = self.client.get_positions(self.contract)
        except Exception as e:
            if os.getenv('DEBUG'):
                print(f"[STRATEGY DEBUG] get_positions() failed: {e}")
            position = None

        # 检查持仓状态（无缓存依赖）
        has_api_position = position is not None and position.get('size', 0) != 0

        # 无持仓时的残留遗留挂单防护清理 (Orphan Order Sanitization)
        if not has_api_position:
            try:
                open_limit_orders = self.client.get_orders(self.contract, status="open")
                open_price_orders = self.client.get_price_orders(self.contract, status="open")
                if open_limit_orders or open_price_orders:
                    print(f"\n[ORPHAN CLEANUP] 检测到 [{self.contract}] 无持仓但存在残留订单 (普通单: {len(open_limit_orders)}, 触发单: {len(open_price_orders)})，进行强制清理...")
                    self.client.cancel_orders(contract=self.contract)
                    self.client.cancel_price_orders(contract=self.contract)
                    print(f"[ORPHAN CLEANUP] ✅ 成功清理 [{self.contract}] 残留挂单，确保盘面干净。")
            except Exception as orphan_err:
                print(f"[ORPHAN CLEANUP WARNING] 清理 [{self.contract}] 残留挂单异常: {orphan_err}")

        # ==== 风控与冷静期对账逻辑 ====
        # 检测本地状态里记录的持仓是否已在交易所被平仓（例如触及交易所止损条件单）
        try:
            pos_state = load_position_state(self.contract)
            for dir_key in ["long", "short"]:
                if dir_key in pos_state:
                    still_exists = False
                    if has_api_position and position is not None:
                        if dir_key == "long" and position.get('size', 0) > 0:
                            still_exists = True
                        elif dir_key == "short" and position.get('size', 0) < 0:
                            still_exists = True
                    
                    if not still_exists:
                        # 仓位已平仓（多半是触及交易所止损触发单）
                        print(f"\n[RECONCILE] 检测到本地记录的 {dir_key} 仓位已在交易所平仓。开始提取平仓信息...")
                        
                        # 尝试从平仓历史获取真实 PnL 和平仓时间（校验方向与时间，防旧记录误计）
                        try:
                            closes = self.client.get_position_closes(self.contract, limit=5)
                            if closes:
                                last_pos_update = float(pos_state.get(dir_key, {}).get("last_update", 0) or 0)
                                matched_close = None
                                for c in closes:
                                    c_side = str(c.get('side', '')).lower()
                                    c_time = int(c.get('time', 0) or 0)
                                    if c_side and c_side != dir_key:
                                        continue
                                    # Allow small clock skew (1800s) relative to last_update if recorded
                                    if last_pos_update > 0 and c_time > 0 and c_time < (last_pos_update - 1800):
                                        continue
                                    matched_close = c
                                    break
                                if matched_close:
                                    pnl = matched_close.get('pnl', 0.0)
                                    close_time = datetime.fromtimestamp(matched_close.get('time', 0), tz=timezone.utc)
                                    from cooldown import record_trade_result
                                    record_trade_result(pnl, close_time, contract=self.contract)
                                    print(f"[RECONCILE] 成功记录已平仓交易：PnL={pnl:+.2f}U, 时间={close_time.strftime('%Y-%m-%d %H:%M:%S UTC')}")
                                else:
                                    print(f"[RECONCILE] 平仓历史中未找到匹配方向({dir_key})与时间的新平仓记录，跳过连亏计数")
                            else:
                                print("[RECONCILE] 未获取到交易所平仓历史记录")
                        except Exception as close_err:
                            print(f"[RECONCILE ERROR] 获取或记录平仓历史失败: {close_err}")
                        
                        # 清除本地持仓状态
                        clear_position_state(dir_key, contract=self.contract)

                        print(f"[RECONCILE] 已清除本地 {dir_key} 仓位状态。")
                        
                        # 清除交易所上所有未成交的止盈限价单和止损条件单
                        try:
                            self.client.cancel_orders(contract=self.contract)
                            self.client.cancel_price_orders(contract=self.contract)
                            print(f"[RECONCILE] 已成功清理交易所残留挂单（如限价止盈单及触发单）")
                        except Exception as cancel_err:
                            print(f"[RECONCILE WARNING] 清理交易所挂单失败: {cancel_err}")
        except Exception as state_err:
            print(f"[RECONCILE ERROR] 读取或处理本地持仓状态失败: {state_err}")



        # 计算账户本金（Fail-Closed：API 失败或返回 <= 0 时绝不回退 500U 绕过熔断）
        account_available = False
        equity = 0.0
        if account is not None and isinstance(account, dict):
            total = float(account.get('total', 0.0) or 0.0)
            available = float(account.get('available', 0.0) or 0.0)
            print(f"[ACCOUNT PARSE] total={total}, available={available}")
            if total > 0:
                equity = total
                account_available = True
                print(f"[FINAL EQUITY] 本金取值: {equity}\n")
            else:
                print(f"[ACCOUNT WARNING] account.total <= 0，启用 Fail-Closed 保护（暂停新开仓），account={account}")
        else:
            print(f"[ACCOUNT ERROR] account获取失败(None)，启用 Fail-Closed 保护（暂停新开仓）\n")

        # 检查永久熔断锁与账户熔断阈值
        from cooldown import check_cooldown, load_circuit_breaker_lock, activate_circuit_breaker_lock
        cb_lock = load_circuit_breaker_lock()
        is_circuit_broken = bool(cb_lock.get("locked"))
        cb_message = ""

        if account_available:
            risk = get_risk_amount(equity, contract=self.contract)
            if risk['status'] == 'circuit_breaker':
                is_circuit_broken = True
                activate_circuit_breaker_lock(equity=equity, reason=risk['message'])
                cb_message = f"🚨 永久熔断锁触发！{risk['message']}，已停止所有标的开仓（需人工设置 RESET_CIRCUIT_BREAKER=true 解锁）"
        else:
            risk = {"amount": 0.0, "mode": "unavailable", "status": "account_unavailable", "message": "账户余额获取失败"}

        if is_circuit_broken and not cb_message:
            cb_message = (
                f"🚨 永久熔断锁生效中！{cb_lock.get('reason', '')} "
                f"(触发于 {cb_lock.get('triggered_at', '未知')})，已停止所有标的开仓"
            )

        # 判断当前持仓状态
        has_position = has_api_position
        is_long = has_position and position['size'] > 0
        is_short = has_position and position['size'] < 0

        # V1 Post-ETF 机构化状态分类器判定
        is_risk = (last_atr_z_1h > 3.0)
        is_chop = (last_chop_4h > 54.0 or last_er_4h < 0.35)

        # 无持仓时的安全拦截：永久熔断 -> 账户异常 -> 30m K线去重 -> 冷静期
        if not has_position:
            if is_circuit_broken:
                return finalize(TradeResult(
                    action="circuit_breaker",
                    message=cb_message,
                    details={"equity": equity, "account": account, "permanent_lock": True}
                ))

            if not account_available:
                return TradeResult(
                    action="none",
                    message="⚠️ 账户余额 API 获取失败或为 0，已安全暂停新开仓（Fail-Closed 保护）",
                    details={"account_unavailable": True, "account": account}
                )

            # 去重保护：仅针对无持仓新开仓信号，同一根30m已收盘K线只分析一次
            if self.state.last_processed_30m_bar_ts == signal_bar_ts:
                return TradeResult(
                    action="hold",
                    message=f"⏭️ 去重保护：30m K线 {signal_bar_iso} 已处理，跳过本次重复执行",
                    details={
                        "dedup": True,
                        "signal_bar_ts": signal_bar_ts,
                        "signal_bar_iso": signal_bar_iso
                    }
                )

            cooldown = check_cooldown(self.client, self.contract)
            if cooldown.triggered:
                if cooldown.should_notify:
                    action = "cooldown"
                    message = f"⚠️ 冷静期已触发！\n{cooldown.details}"
                else:
                    action = "none"
                    message = f"⏸️ 冷静期中... {cooldown.details}"
                return finalize(TradeResult(
                    action=action,
                    message=message,
                    details={
                        "reason": cooldown.reason,
                        "cooldown_hours": cooldown.cooldown_hours,
                        "consecutive_losses": cooldown.consecutive_losses,
                        "can_trade_time": cooldown.can_trade_time.isoformat() if cooldown.can_trade_time else None,
                        "should_notify": cooldown.should_notify
                    }
                ))

        risk_amount = risk['amount']
        risk_info = risk['message']

        # 开多条件: 1D 标的+BTC双重看多 + 4H CHOP<51 + 4H ER>0.40 + 30m ST绿 + 已收盘30m EMA20踩实 + (可选ADX)
        can_long = (
            account_available and
            not is_circuit_broken and
            not is_risk and
            not is_chop and
            last_chop_4h < 51.0 and
            last_er_4h > 0.40 and
            macro_1d_dir == 1 and
            btc_macro_1d_dir == 1 and
            last_30m_dir == 1 and
            last_30m_close >= last_ema20_30m and
            adx_is_trending
        )
        
        # 开空条件: 1D 标的+BTC双重看空 + 4H CHOP<51 + 4H ER>0.40 + 30m ST红 + 已收盘30m EMA20踩实 + (可选ADX)
        can_short = (
            account_available and
            not is_circuit_broken and
            not is_risk and
            not is_chop and
            last_chop_4h < 51.0 and
            last_er_4h > 0.40 and
            macro_1d_dir == -1 and
            btc_macro_1d_dir == -1 and
            last_30m_dir == -1 and
            last_30m_close <= last_ema20_30m and
            adx_is_trending
        )

        # 1H 刚变色？（最佳入场点标记）
        h1_just_changed = prev_1h_dir != last_1h_dir
        
        # V1 Post-ETF 机构化状态分类器与过滤诊断
        macro_symbol = "🟢看多" if macro_1d_dir == 1 else ("🔴看空" if macro_1d_dir == -1 else "⚪不可用")
        btc_macro_symbol = "🟢看多" if btc_macro_1d_dir == 1 else ("🔴看空" if btc_macro_1d_dir == -1 else "⚪不可用")
        chop_pass = last_chop_4h < 51.0
        er_pass = last_er_4h > 0.40
        atr_z_pass = last_atr_z_1h <= 3.0
        ema20_long_pass = last_30m_close >= last_ema20_30m
        ema20_short_pass = last_30m_close <= last_ema20_30m

        adx_trend_symbol = '满足 ✅' if adx_is_trending else ('过滤中 ❌' if USE_ADX else '已关闭 ⚠️')
        adx_info_line = f"• ADX ({ADX_TIMEFRAME.upper()}): {last_adx:.2f} (阈值: {eff_adx_threshold}) {adx_trend_symbol}\n"

        filter_info_long = (
            f"━━━━━━━━━━ V1 状态分类器检查 ━━━━━━━━━━\n"
            f"• 1D 宏观趋势: 标的 {macro_symbol} / BTC {btc_macro_symbol} {'✅' if (macro_1d_dir == 1 and btc_macro_1d_dir == 1) else '❌'}\n"
            f"• 4H CHOP 维数: {last_chop_4h:.1f} (趋势带 < 51.0): {'✅' if chop_pass else '❌'}\n"
            f"• 4H Kaufman ER: {last_er_4h:.2f} (效率比 > 0.40): {'✅' if er_pass else '❌'}\n"
            f"• 1H ATR Z-Score: {last_atr_z_1h:.2f} (未触发闪崩 <= 3.0): {'✅' if atr_z_pass else '❌'}\n"
            f"• 30m EMA(20) 反扫荡确认 (已收盘): {'踩实 ✅' if ema20_long_pass else '未踩实 ❌'}\n"
            f"{adx_info_line}"
        )

        filter_info_short = (
            f"━━━━━━━━━━ V1 状态分类器检查 ━━━━━━━━━━\n"
            f"• 1D 宏观趋势: 标的 {macro_symbol} / BTC {btc_macro_symbol} {'✅' if (macro_1d_dir == -1 and btc_macro_1d_dir == -1) else '❌'}\n"
            f"• 4H CHOP 维数: {last_chop_4h:.1f} (趋势带 < 51.0): {'✅' if chop_pass else '❌'}\n"
            f"• 4H Kaufman ER: {last_er_4h:.2f} (效率比 > 0.40): {'✅' if er_pass else '❌'}\n"
            f"• 1H ATR Z-Score: {last_atr_z_1h:.2f} (未触发闪崩 <= 3.0): {'✅' if atr_z_pass else '❌'}\n"
            f"• 30m EMA(20) 反扫荡确认 (已收盘): {'踩实 ✅' if ema20_short_pass else '未踩实 ❌'}\n"
            f"{adx_info_line}"
        )

        
        # ============ 无持仓: 检查开仓条件 ============
        if not has_position:
            if can_long:
                rounded_st = self._round_price(last_30m_st)
                pos_info = calculate_position_size(risk_amount, current_price, rounded_st, face_value=contract_fv)
                if pos_info['qty'] <= 0:
                    return finalize(TradeResult(
                        action="none",
                        message=f"⚠️ 开多信号满足但计算张数为 0（风险额 {risk_amount:.2f}U 不足 1 张合约，止损距离 {pos_info['sl_distance']:.4f}），跳过开仓",
                        details={"entry": current_price, "stop_loss": rounded_st, "qty": 0, "risk_amount": risk_amount}
                    ))
                sl_dist = abs(current_price - rounded_st)
                lock_threshold = self._round_price(current_price + LOCK_PROFIT_BUFFER * sl_dist)
                timing = " ⚡最佳入场!" if h1_just_changed else ""
                tp_price = self._round_price(current_price + contract_tp_ratio * sl_dist)
                
                return finalize(TradeResult(
                    action="open_long",
                    message=f"""🟢 开多信号！{timing}

━━━━━━━━━━ V1 状态分类器指标 ━━━━━━━━━━
【1D 宏观与 4H 状态】
• 1D 宏观 (标的/BTC): {macro_symbol} / {btc_macro_symbol} ✅
• 4H CHOP 维数: {last_chop_4h:.1f} (< 51.0 趋势带) ✅
• 4H Kaufman ER: {last_er_4h:.2f} (> 0.40 效率比) ✅
• 1H ATR Z-Score: {last_atr_z_1h:.2f} (<= 3.0 未离群) ✅

【30m 信号与反扫荡 (已收盘)】
• 30m ST 轨线: {rounded_st:.4f} 🟢 绿 ✅
• 30m EMA(20): {last_ema20_30m:.4f} (收盘 {last_30m_close:.4f} 踩实 ✅)

【ADX 动能】
• ADX ({ADX_TIMEFRAME.upper()}): {last_adx:.2f} (启用: {'是' if USE_ADX else '否'}) ✅

━━━━━━━━━━ 行动 ━━━━━━━━━━
📌 开多 {pos_info['qty']}张 @ {current_price:.4f}
📌 设止损 @ {rounded_st:.4f}
📌 设限价止盈 ({contract_tp_ratio:.1f}R) @ {tp_price:.4f}

━━━━━━━━━━ 仓位计算 ━━━━━━━━━━
• 止损距离: {pos_info['sl_distance']:.4f}点
• 保证金: {pos_info['margin_required']:.2f}U ({LEVERAGE}x)
• 风险: {risk_info}
• 锁利目标 (0.5R): {lock_threshold:.4f}
• 限价止盈: {tp_price:.4f}""",
                    details={
                        "entry": current_price,
                        "stop_loss": rounded_st,
                        "qty": pos_info['qty'],
                        "actual_risk": pos_info['actual_risk'],
                        "1h_st": last_1h_st,
                        "1h_close": last_1h_close,
                        "1h_dema": last_1h_dema,
                        "30m_st": rounded_st,
                        "adx": last_adx,
                        "tp_price": tp_price
                    }
                ))
            
            elif can_short:
                rounded_st = self._round_price(last_30m_st)
                pos_info = calculate_position_size(risk_amount, current_price, rounded_st, face_value=contract_fv)
                if pos_info['qty'] <= 0:
                    return finalize(TradeResult(
                        action="none",
                        message=f"⚠️ 开空信号满足但计算张数为 0（风险额 {risk_amount:.2f}U 不足 1 张合约，止损距离 {pos_info['sl_distance']:.4f}），跳过开仓",
                        details={"entry": current_price, "stop_loss": rounded_st, "qty": 0, "risk_amount": risk_amount}
                    ))
                sl_dist = abs(current_price - rounded_st)
                lock_threshold = self._round_price(current_price - LOCK_PROFIT_BUFFER * sl_dist)
                timing = " ⚡最佳入场!" if h1_just_changed else ""
                tp_price = self._round_price(current_price - contract_tp_ratio * sl_dist)
                
                return finalize(TradeResult(
                    action="open_short",
                    message=f"""🔴 开空信号！{timing}

━━━━━━━━━━ V1 状态分类器指标 ━━━━━━━━━━
【1D 宏观与 4H 状态】
• 1D 宏观 (标的/BTC): {macro_symbol} / {btc_macro_symbol} ✅
• 4H CHOP 维数: {last_chop_4h:.1f} (< 51.0 趋势带) ✅
• 4H Kaufman ER: {last_er_4h:.2f} (> 0.40 效率比) ✅
• 1H ATR Z-Score: {last_atr_z_1h:.2f} (<= 3.0 未离群) ✅

【30m 信号与反扫荡 (已收盘)】
• 30m ST 轨线: {rounded_st:.4f} 🔴 红 ✅
• 30m EMA(20): {last_ema20_30m:.4f} (收盘 {last_30m_close:.4f} 踩实 ✅)

【ADX 动能】
• ADX ({ADX_TIMEFRAME.upper()}): {last_adx:.2f} (启用: {'是' if USE_ADX else '否'}) ✅

━━━━━━━━━━ 行动 ━━━━━━━━━━
📌 开空 {pos_info['qty']}张 @ {current_price:.4f}
📌 设止损 @ {rounded_st:.4f}
📌 设限价止盈 ({contract_tp_ratio:.1f}R) @ {tp_price:.4f}

━━━━━━━━━━ 仓位计算 ━━━━━━━━━━
• 止损距离: {pos_info['sl_distance']:.4f}点
• 保证金: {pos_info['margin_required']:.2f}U ({LEVERAGE}x)
• 风险: {risk_info}
• 锁利目标 (0.5R): {lock_threshold:.4f}
• 限价止盈: {tp_price:.4f}""",
                    details={
                        "entry": current_price,
                        "stop_loss": rounded_st,
                        "qty": pos_info['qty'],
                        "actual_risk": pos_info['actual_risk'],
                        "1h_st": last_1h_st,
                        "1h_close": last_1h_close,
                        "1h_dema": last_1h_dema,
                        "30m_st": rounded_st,
                        "adx": last_adx,
                        "tp_price": tp_price
                    }
                ))
            
            else:
                target_dir_str = "做多 🟢" if last_30m_dir == 1 else "做空 🔴"
                filter_text = filter_info_long if last_30m_dir == 1 else filter_info_short

                return finalize(TradeResult(
                    action="none",
                    message=f"""📊 无开仓信号

━━━━━━━━━━ 当前价格 ━━━━━━━━━━
• 价格: {current_price:.4f}

🎯 目标方向: {target_dir_str} (基于 30m ST)

{filter_text}
━━━━━━━━━━ 账户状态 ━━━━━━━━━━
• 本金: {equity:.2f}U
• 风险额: {risk_info}""",
                    details={
                        "price": current_price,
                        "1d_macro": macro_1d_dir,
                        "4h_chop": last_chop_4h,
                        "4h_er": last_er_4h,
                        "1h_atr_z": last_atr_z_1h,
                        "30m_st": last_30m_st,
                        "30m_st_dir": last_30m_dir,
                        "adx": last_adx,
                        "equity": equity
                    }
                ))

        
        # ============ 已持多仓（每次 5 分钟巡检实时监控，不受 30m 去重阻塞）============
        if is_long:
            return finalize(self._manage_long_position(
                position, df_30m, df_1h, st_30m, st_1h,
                last_1h_close, last_1h_dema, risk_amount, risk_info,
                last_adx=last_adx, can_reverse_short=can_short,
                is_risk=is_risk, last_1h_atr=last_1h_atr
            ), mark_bar=False)
        
        # ============ 已持空仓（每次 5 分钟巡检实时监控，不受 30m 去重阻塞）============
        if is_short:
            return finalize(self._manage_short_position(
                position, df_30m, df_1h, st_30m, st_1h,
                last_1h_close, last_1h_dema, risk_amount, risk_info,
                last_adx=last_adx, can_reverse_long=can_long,
                is_risk=is_risk, last_1h_atr=last_1h_atr
            ), mark_bar=False)

        
        return finalize(TradeResult(action="none", message="未知状态"))
    
    def _manage_long_position(self, position, df_30m, df_1h, st_30m, st_1h,
                               last_1h_close, last_1h_dema, risk_amount, risk_info,
                               last_adx: float = None, can_reverse_short: bool = False,
                               is_risk: bool = False, last_1h_atr: float = 0.0) -> TradeResult:
        """管理多仓（无状态，每次推导）"""
        contract_fv = get_face_value(self.contract)
        contract_tp_ratio = get_tp_ratio(self.contract)
        tick_size = self._get_tick_size()

        # 兼容性处理：如果没有传入 last_adx，则动态计算
        if last_adx is None:
            if 'high' in df_30m.columns and 'low' in df_30m.columns:
                df_adx_source = df_30m if ADX_TIMEFRAME == "30m" else df_1h
                adx_series = calculate_adx(df_adx_source, ADX_LENGTH)
                last_adx = adx_series.iloc[-2]
            else:
                last_adx = 0.0

        current_price = float(df_30m['close'].iloc[-1])
        entry_price = float(position['entry_price'])
        qty = abs(position['size'])
        last_30m_st = float(st_30m['supertrend'].iloc[-2])
        last_30m_dir = int(st_30m['direction'].iloc[-2])
        last_1h_st = float(st_1h['supertrend'].iloc[-2])
        last_1h_dir = int(st_1h['direction'].iloc[-2])

        # 读取历史状态并进行舍入以对齐交易所精度，防止浮点微小差异导致频繁调整止损
        prev_state = load_position_state(self.contract).get("long", {})

        prev_phase = prev_state.get("phase", "")
        prev_stop_loss = self._round_price(prev_state.get("stop_loss", 0))  # ← 记录旧止损，用于调整时验证
        live_stop_loss = self._round_price(self._get_live_stop_price())
        baseline_stop_loss = prev_stop_loss if prev_stop_loss > 0 else live_stop_loss
        initial_30m_st = self._round_price(prev_state.get("initial_30m_st", 0))
        locked_stop_loss = self._round_price(prev_state.get("locked_stop_loss", 0))
        
        # 首次开仓时记录 initial_30m_st，并对齐精度
        if initial_30m_st <= 0:
            initial_30m_st = self._round_price(self._reconstruct_initial_30m_st(is_long=True, entry_price=entry_price, last_30m_st=last_30m_st))

        # 推导当前阶段和建议的止损，传入历史信息
        phase, recommended_stop = self._infer_phase(entry_price, current_price, qty, 
                                                      last_30m_st, last_1h_st, is_long=True,
                                                      initial_30m_st=initial_30m_st,
                                                      locked_stop_loss=locked_stop_loss,
                                                      prev_stop_loss=baseline_stop_loss,
                                                      risk_amount=risk_amount,
                                                      prev_phase=prev_phase,
                                                      face_value=contract_fv)
        recommended_stop = self._round_price(recommended_stop)

        # Flash-crash risk freeze (1H ATR Z-Score > 3.0): tighten existing long stop close to market
        risk_tightened = False
        if is_risk and last_1h_atr > 0:
            emergency_sl = self._round_price(current_price - 0.5 * last_1h_atr)
            if emergency_sl < current_price:
                tightened_sl = tighten_stop_loss(emergency_sl, recommended_stop, is_long=True)
                if tightened_sl > recommended_stop + (tick_size - 1e-12):
                    recommended_stop = self._round_price(tightened_sl)
                    risk_tightened = True

        # 计算动态止盈价 (TP)并舍入
        tp_price = None
        if initial_30m_st > 0:
            sl_dist = abs(entry_price - initial_30m_st)
            tp_price = self._round_price(entry_price + contract_tp_ratio * sl_dist)

        # 判断离场信号
        exit_signal = False
        exit_reason = ""
        if tp_price is not None and current_price >= tp_price:
            exit_signal = True
            exit_reason = f"止盈触发 @ {current_price:.4f} (目标: {tp_price:.4f})"
        elif phase == Phase.HOURLY.value and last_1h_dir == -1:
            exit_signal = True
            exit_reason = "1H ST 变红"
        elif phase in [Phase.SURVIVAL.value, Phase.LOCKED.value] and last_30m_dir == -1:
            exit_signal = True
            exit_reason = "30m ST 变红"

        if exit_signal:
            can_reverse = can_reverse_short
            return self._close_with_reverse_check(
                position, entry_price, current_price, 
                is_long=True, reason=exit_reason,
                can_reverse=can_reverse, reverse_direction="short",
                reverse_stop=last_30m_st, risk_amount=risk_amount, risk_info=risk_info,
                last_1h_close=last_1h_close, last_1h_dema=last_1h_dema,
                last_1h_dir=last_1h_dir, last_30m_dir=last_30m_dir,
                last_adx=last_adx
            )

        # 计算浮盈
        pnl = (current_price - entry_price) * qty * contract_fv

        # 检查持仓状态变化 (阶段和止损，按合约 tick_size 感知)
        current_time = time.time()
        has_change, change_type = update_position_state(
            direction="long",
            phase=phase,
            stop_loss=recommended_stop,
            entry_price=entry_price,
            current_time=current_time,
            initial_30m_st=initial_30m_st,
            locked_stop_loss=recommended_stop if phase == Phase.LOCKED.value else locked_stop_loss,
            contract=self.contract,
            tick_size=tick_size
        )

        # 无本地状态（例如定时任务无持久化）时，回退到交易所实时止损做差异判断
        if change_type == "new_position" and baseline_stop_loss > 0 and abs(baseline_stop_loss - recommended_stop) > (tick_size - 1e-12):
            change_type = "stop_updated"
        
        # 如果交易所无实时止损单，且当前没有更高级的阶段切换事件，则强制设为 stop_updated 以补设止损单
        if live_stop_loss <= 0.0 and change_type not in ["enter_locked", "switch_1h"]:
            change_type = "stop_updated"

        # 返回阶段和止损信息
        phase_names = {
            Phase.SURVIVAL.value: "🔵 生存期",
            Phase.LOCKED.value: "🟡 锁利期",
            Phase.HOURLY.value: "🟣 换轨期"
        }
        phase_exit = {
            Phase.SURVIVAL.value: "30m ST 变红",
            Phase.LOCKED.value: "30m ST 变红",
            Phase.HOURLY.value: "1H ST 变红"
        }

        # 根据状态变化返回不同的 action
        if change_type == "stop_updated":
            risk_note = "\n• 原因: 🚨 闪崩冻结 (1H ATR Z>3.0) 触发紧急紧贴止损" if risk_tightened else ""
            return TradeResult(
                action="stop_updated",
                message=f"""⚠️  止损已调整
• 方向: 多 | 阶段: {phase_names.get(phase)}
• 入场: {entry_price:.4f} | 当前: {current_price:.4f}
• 新止损: {recommended_stop:.4f} | 浮盈: {pnl:+.2f}U{risk_note}""",
                details={"phase": phase, "stop_loss": recommended_stop, "old_stop": baseline_stop_loss if baseline_stop_loss > 0 else None, "pnl": pnl, "risk_tightened": risk_tightened}
            )
        elif change_type == "enter_locked":
            return TradeResult(
                action="enter_locked",
                message=f"""🟡 已进入保底锁利期
• 方向: 多 | 阶段: {phase_names.get(phase)}
• 入场: {entry_price:.4f} | 当前: {current_price:.4f}
• 止损: {recommended_stop:.4f} | 浮盈: {pnl:+.2f}U
• 说明: 账面浮盈达 1.0R，止损已强制提至入场价 +{LOCK_PROFIT_BUFFER}R 保底锁利""",
                details={"phase": phase, "stop_loss": recommended_stop, "old_stop": baseline_stop_loss if baseline_stop_loss > 0 else None, "pnl": pnl}
            )
        elif change_type == "switch_1h":
            return TradeResult(
                action="switch_1h",
                message=f"""🟣 已切换至小时线轨道
• 方向: 多 | 阶段: {phase_names.get(phase)}
• 入场: {entry_price:.4f} | 当前: {current_price:.4f}
• 止损: {recommended_stop:.4f} | 浮盈: {pnl:+.2f}U
• 说明: 1H ST 已超越 {LOCK_PROFIT_BUFFER}R 锁利位，切换至 1H ST 跟踪""",
                details={"phase": phase, "stop_loss": recommended_stop, "old_stop": baseline_stop_loss if baseline_stop_loss > 0 else None, "pnl": pnl}
            )
        else:
            # 正常持仓，无状态变化
            tp_msg = f" | 止盈: {tp_price:.4f}" if tp_price else ""
            return TradeResult(
                action="hold",
                message=f"""✅ 持仓中
• 方向: 多 | 阶段: {phase_names.get(phase)}
• 入场: {entry_price:.4f} | 当前: {current_price:.4f}
• 止损: {recommended_stop:.4f}{tp_msg} | 浮盈: {pnl:+.2f}U

━━━━━━━━━━ 技术指标 ━━━━━━━━━━
【1小时线】
• 1H ST: {last_1h_st:.4f} {'🟢 绿' if last_1h_dir == 1 else '🔴 红'}
• 1H 收盘: {last_1h_close:.4f}

【30分钟线】
• 30m ST: {last_30m_st:.4f} {'🟢 绿' if last_30m_dir == 1 else '🔴 红'}

• 离场条件: {phase_exit.get(phase)}""",
                details={
                    "phase": phase, 
                    "stop_loss": recommended_stop, 
                    "pnl": pnl,
                    "1h_st": last_1h_st,
                    "1h_close": last_1h_close,
                    "1h_dema": last_1h_dema,
                    "30m_st": last_30m_st
                }
            )

    
    def _manage_short_position(self, position, df_30m, df_1h, st_30m, st_1h,
                                last_1h_close, last_1h_dema, risk_amount, risk_info,
                                last_adx: float = None, can_reverse_long: bool = False,
                                is_risk: bool = False, last_1h_atr: float = 0.0) -> TradeResult:
        """管理空仓（无状态，每次推导）"""
        contract_fv = get_face_value(self.contract)
        contract_tp_ratio = get_tp_ratio(self.contract)
        tick_size = self._get_tick_size()

        # 兼容性处理：如果没有传入 last_adx，则动态计算
        if last_adx is None:
            if 'high' in df_30m.columns and 'low' in df_30m.columns:
                df_adx_source = df_30m if ADX_TIMEFRAME == "30m" else df_1h
                adx_series = calculate_adx(df_adx_source, ADX_LENGTH)
                last_adx = adx_series.iloc[-2]
            else:
                last_adx = 0.0

        current_price = float(df_30m['close'].iloc[-1])
        entry_price = float(position['entry_price'])
        qty = abs(position['size'])
        last_30m_st = float(st_30m['supertrend'].iloc[-2])
        last_30m_dir = int(st_30m['direction'].iloc[-2])
        last_1h_st = float(st_1h['supertrend'].iloc[-2])
        last_1h_dir = int(st_1h['direction'].iloc[-2])

        # 读取历史状态并进行舍入以对齐交易所精度，防止浮点微小差异导致频繁调整止损
        prev_state = load_position_state(self.contract).get("short", {})

        prev_phase = prev_state.get("phase", "")
        prev_stop_loss = self._round_price(prev_state.get("stop_loss", 0))  # ← 记录旧止损，用于调整时验证
        live_stop_loss = self._round_price(self._get_live_stop_price())
        baseline_stop_loss = prev_stop_loss if prev_stop_loss > 0 else live_stop_loss
        initial_30m_st = self._round_price(prev_state.get("initial_30m_st", 0))
        locked_stop_loss = self._round_price(prev_state.get("locked_stop_loss", 0))
        
        # 首次开仓时记录 initial_30m_st，并对齐精度
        if initial_30m_st <= 0:
            initial_30m_st = self._round_price(self._reconstruct_initial_30m_st(is_long=False, entry_price=entry_price, last_30m_st=last_30m_st))

        # 推导当前阶段和建议的止损，传入历史信息
        phase, recommended_stop = self._infer_phase(entry_price, current_price, qty, 
                                                      last_30m_st, last_1h_st, is_long=False,
                                                      initial_30m_st=initial_30m_st,
                                                      locked_stop_loss=locked_stop_loss,
                                                      prev_stop_loss=baseline_stop_loss,
                                                      risk_amount=risk_amount,
                                                      prev_phase=prev_phase,
                                                      face_value=contract_fv)
        recommended_stop = self._round_price(recommended_stop)

        # Flash-crash risk freeze (1H ATR Z-Score > 3.0): tighten existing short stop close to market
        risk_tightened = False
        if is_risk and last_1h_atr > 0:
            emergency_sl = self._round_price(current_price + 0.5 * last_1h_atr)
            if emergency_sl > current_price:
                tightened_sl = tighten_stop_loss(emergency_sl, recommended_stop, is_long=False)
                if tightened_sl < recommended_stop - (tick_size - 1e-12):
                    recommended_stop = self._round_price(tightened_sl)
                    risk_tightened = True

        # 计算动态止盈价 (TP)并舍入
        tp_price = None
        if initial_30m_st > 0:
            sl_dist = abs(entry_price - initial_30m_st)
            tp_price = self._round_price(entry_price - contract_tp_ratio * sl_dist)

        # 判断离场信号
        exit_signal = False
        exit_reason = ""
        if tp_price is not None and current_price <= tp_price:
            exit_signal = True
            exit_reason = f"止盈触发 @ {current_price:.4f} (目标: {tp_price:.4f})"
        elif phase == Phase.HOURLY.value and last_1h_dir == 1:
            exit_signal = True
            exit_reason = "1H ST 变绿"
        elif phase in [Phase.SURVIVAL.value, Phase.LOCKED.value] and last_30m_dir == 1:
            exit_signal = True
            exit_reason = "30m ST 变绿"

        if exit_signal:
            can_reverse = can_reverse_long
            return self._close_with_reverse_check(
                position, entry_price, current_price,
                is_long=False, reason=exit_reason,
                can_reverse=can_reverse, reverse_direction="long",
                reverse_stop=last_30m_st, risk_amount=risk_amount, risk_info=risk_info,
                last_1h_close=last_1h_close, last_1h_dema=last_1h_dema,
                last_1h_dir=last_1h_dir, last_30m_dir=last_30m_dir,
                last_adx=last_adx
            )

        # 计算浮盈
        pnl = (entry_price - current_price) * qty * contract_fv

        # 检查持仓状态变化 (阶段和止损，按合约 tick_size 感知)
        current_time = time.time()
        has_change, change_type = update_position_state(
            direction="short",
            phase=phase,
            stop_loss=recommended_stop,
            entry_price=entry_price,
            current_time=current_time,
            initial_30m_st=initial_30m_st,
            locked_stop_loss=recommended_stop if phase == Phase.LOCKED.value else locked_stop_loss,
            contract=self.contract,
            tick_size=tick_size
        )

        # 无本地状态（例如定时任务无持久化）时，回退到交易所实时止损做差异判断
        if change_type == "new_position" and baseline_stop_loss > 0 and abs(baseline_stop_loss - recommended_stop) > (tick_size - 1e-12):
            change_type = "stop_updated"
        
        # 如果交易所无实时止损单，且当前没有更高级的阶段切换事件，则强制设为 stop_updated 以补设止损单
        if live_stop_loss <= 0.0 and change_type not in ["enter_locked", "switch_1h"]:
            change_type = "stop_updated"

        # 返回阶段和止损信息
        phase_names = {
            Phase.SURVIVAL.value: "🔵 生存期",
            Phase.LOCKED.value: "🟡 锁利期",
            Phase.HOURLY.value: "🟣 换轨期"
        }
        phase_exit = {
            Phase.SURVIVAL.value: "30m ST 变绿",
            Phase.LOCKED.value: "30m ST 变绿",
            Phase.HOURLY.value: "1H ST 变绿"
        }

        # 根据状态变化返回不同的 action
        if change_type == "stop_updated":
            risk_note = "\n• 原因: 🚨 闪崩冻结 (1H ATR Z>3.0) 触发紧急紧贴止损" if risk_tightened else ""
            return TradeResult(
                action="stop_updated",
                message=f"""⚠️  止损已调整
• 方向: 空 | 阶段: {phase_names.get(phase)}
• 入场: {entry_price:.4f} | 当前: {current_price:.4f}
• 新止损: {recommended_stop:.4f} | 浮盈: {pnl:+.2f}U{risk_note}""",
                details={"phase": phase, "stop_loss": recommended_stop, "old_stop": baseline_stop_loss if baseline_stop_loss > 0 else None, "pnl": pnl, "risk_tightened": risk_tightened}
            )
        elif change_type == "enter_locked":
            return TradeResult(
                action="enter_locked",
                message=f"""🟡 已进入保底锁利期
• 方向: 空 | 阶段: {phase_names.get(phase)}
• 入场: {entry_price:.4f} | 当前: {current_price:.4f}
• 止损: {recommended_stop:.4f} | 浮盈: {pnl:+.2f}U
• 说明: 账面浮盈达 1.0R，止损已强制提至入场价 -{LOCK_PROFIT_BUFFER}R 保底锁利""",
                details={"phase": phase, "stop_loss": recommended_stop, "old_stop": baseline_stop_loss if baseline_stop_loss > 0 else None, "pnl": pnl}
            )
        elif change_type == "switch_1h":
            return TradeResult(
                action="switch_1h",
                message=f"""🟣 已切换至小时线轨道
• 方向: 空 | 阶段: {phase_names.get(phase)}
• 入场: {entry_price:.4f} | 当前: {current_price:.4f}
• 止损: {recommended_stop:.4f} | 浮盈: {pnl:+.2f}U
• 说明: 1H ST 已超越 {LOCK_PROFIT_BUFFER}R 锁利位，切换至 1H ST 跟踪""",
                details={"phase": phase, "stop_loss": recommended_stop, "old_stop": baseline_stop_loss if baseline_stop_loss > 0 else None, "pnl": pnl}
            )
        else:
            # 正常持仓，无状态变化
            tp_msg = f" | 止盈: {tp_price:.4f}" if tp_price else ""
            return TradeResult(
                action="hold",
                message=f"""✅ 持仓中
• 方向: 空 | 阶段: {phase_names.get(phase)}
• 入场: {entry_price:.4f} | 当前: {current_price:.4f}
• 止损: {recommended_stop:.4f}{tp_msg} | 浮盈: {pnl:+.2f}U

━━━━━━━━━━ 技术指标 ━━━━━━━━━━
【1小时线】
• 1H ST: {last_1h_st:.4f} {'🟢 绿' if last_1h_dir == 1 else '🔴 红'}
• 1H 收盘: {last_1h_close:.4f}

【30分钟线】
• 30m ST: {last_30m_st:.4f} {'🟢 绿' if last_30m_dir == 1 else '🔴 红'}

• 离场条件: {phase_exit.get(phase)}""",
                details={
                    "phase": phase, 
                    "stop_loss": recommended_stop, 
                    "pnl": pnl,
                    "1h_st": last_1h_st,
                    "1h_close": last_1h_close,
                    "1h_dema": last_1h_dema,
                    "30m_st": last_30m_st
                }
            )

    
    def _close_with_reverse_check(self, position, entry_price, current_price, 
                                   is_long: bool, reason: str,
                                   can_reverse: bool, reverse_direction: str,
                                   reverse_stop: float, risk_amount: float, risk_info: str,
                                   last_1h_close: float, last_1h_dema: float,
                                   last_1h_dir: int, last_30m_dir: int,
                                   last_adx: float = 0.0) -> TradeResult:
        """平仓并检查反手条件"""
        contract_fv = get_face_value(self.contract)
        qty = abs(position['size'])
        if is_long:
            pnl = (current_price - entry_price) * qty * contract_fv
        else:
            pnl = (entry_price - current_price) * qty * contract_fv
        
        if pnl < 0:
            self.state.consecutive_losses += 1
        else:
            self.state.consecutive_losses = 0
        
        # 记录交易结果（用于冷静期计算）
        from cooldown import record_trade_result
        record_trade_result(pnl, contract=self.contract)

        
        direction = "多" if is_long else "空"
        
        # 构建平仓消息
        close_msg = (
            f"🛑 平{direction}！{reason}\n"
            f"• 入场: {entry_price:.2f}\n"
            f"• 当前: {current_price:.2f}\n"
            f"• 盈亏: {pnl:+.2f}U\n"
        )
        
        # 检查冷静期（平仓后才检查，因为这笔交易可能导致进入冷静期）
        from cooldown import check_cooldown
        cooldown = check_cooldown(self.client, self.contract)
        
        # 检查反手条件（需要同时满足技术条件 + 不在冷静期）
        if can_reverse and not cooldown.triggered:
            reverse_dir_cn = "多" if reverse_direction == "long" else "空"
            pos_info = calculate_position_size(risk_amount, current_price, reverse_stop, face_value=contract_fv)
            lock_threshold = calculate_lock_threshold(
                current_price, pos_info['qty'], 
                is_long=(reverse_direction == "long"),
                risk_amount=risk_amount,
                face_value=contract_fv
            )
            
            # 构建过滤条件信息 - 显示真实数据
            h1_st_color = "🟢绿" if last_1h_dir == 1 else "🔴红"
            h30m_st_color = "🟢绿" if last_30m_dir == 1 else "🔴红"
            adx_info = f"• ADX ({ADX_TIMEFRAME.upper()}): {last_adx:.2f} ✅\n"
            
            if reverse_direction == "long":
                filter_info = (
                    f"【反手开多条件检查】\n"
                    f"• 1H ST: {h1_st_color} ✅\n"
                    f"• 1H收盘 {last_1h_close:.2f} > DEMA {last_1h_dema:.2f} ✅\n"
                    f"• 30m ST: {h30m_st_color} ✅\n"
                    f"{adx_info}"
                )
            else:
                filter_info = (
                    f"【反手开空条件检查】\n"
                    f"• 1H ST: {h1_st_color} ✅\n"
                    f"• 1H收盘 {last_1h_close:.2f} < DEMA {last_1h_dema:.2f} ✅\n"
                    f"• 30m ST: {h30m_st_color} ✅\n"
                    f"{adx_info}"
                )
            
            reverse_msg = (
                f"\n🔄 可反手开{reverse_dir_cn}！\n"
                f"{filter_info}"
                f"【开仓建议】\n"
                f"• 入场价: {current_price:.2f}\n"
                f"• 止损价: {reverse_stop:.2f} (30m ST)\n"
                f"• 止损距离: {pos_info['sl_distance']:.2f}点\n"
                f"• 张数: {pos_info['qty']}张 ({pos_info['position_eth']:.2f} ETH)\n"
                f"• 保证金: {pos_info['margin_required']:.2f}U ({LEVERAGE}x)\n"
                f"• 风险: {risk_info}\n"
                f"• 锁利阈值: {lock_threshold:.2f}"
            )
            
            self._reset_state()
            # 清除旧持仓状态（平仓时调用，新持仓会在下一个周期生成新状态）
            direction_key = "long" if is_long else "short"
            clear_position_state(direction_key, contract=self.contract)
            
            return TradeResult(
                action=f"close_and_reverse_{reverse_direction}",
                message=close_msg + reverse_msg,
                details={
                    "pnl": pnl, 
                    "reason": reason,
                    "reverse": True,
                    "reverse_direction": reverse_direction,
                    "reverse_stop": reverse_stop,
                    "reverse_qty": pos_info['qty']
                }
            )
        else:
            # 只平仓，不反手
            self._reset_state()
            # 清除持仓状态（平仓时调用）
            direction_key = "long" if is_long else "short"
            clear_position_state(direction_key, contract=self.contract)

            
            # 区分不反手的原因
            if cooldown.triggered:
                no_reverse_reason = f"\n⚠️ 冷静期中，不可反手\n{cooldown.details}"
            elif not can_reverse:
                no_reverse_reason = "\n(技术条件不满足反手)"
            else:
                no_reverse_reason = ""
            
            return TradeResult(
                action="close",
                message=close_msg + no_reverse_reason,
                details={"pnl": pnl, "reason": reason, "reverse": False, "cooldown": cooldown.triggered}
            )
    
    def _close_position(self, position, entry_price, current_price, is_long: bool, reason: str) -> TradeResult:
        """平仓"""
        qty = abs(position['size'])
        if is_long:
            pnl = (current_price - entry_price) * qty * FACE_VALUE
        else:
            pnl = (entry_price - current_price) * qty * FACE_VALUE
        
        if pnl < 0:
            self.state.consecutive_losses += 1
        else:
            self.state.consecutive_losses = 0
        
        # 记录交易结果（用于冷静期计算）
        from cooldown import record_trade_result
        record_trade_result(pnl, contract=self.contract)

        
        direction = "多" if is_long else "空"
        direction_key = "long" if is_long else "short"
        
        result = TradeResult(
            action="close",
            message=f"🛑 平{direction}！{reason}\n"
                    f"• 入场: {entry_price:.2f}\n"
                    f"• 当前: {current_price:.2f}\n"
                    f"• 盈亏: {pnl:+.2f}U",
            details={"pnl": pnl, "reason": reason}
        )
        self._reset_state()
        # 清除持仓状态（平仓时调用）
        clear_position_state(direction_key, contract=self.contract)
        return result

    
    def _reset_state(self):
        """重置辅助状态（保留交易计数和连续亏损信息）"""
        save_state(self.state, contract=self.contract)

