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
    USE_ADX, ADX_LENGTH, ADX_THRESHOLD, ADX_TIMEFRAME, TP_RATIO
)
from position_state import update_position_state, clear_position_state, load_position_state
from indicators import calculate_supertrend, calculate_dema, calculate_adx
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


def load_state() -> Position:
    """加载辅助状态（仅交易计数和连续亏损）"""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r') as f:
                data = json.load(f)
                return Position(
                    trade_count=data.get('trade_count', 0),
                    consecutive_losses=data.get('consecutive_losses', 0),
                    last_processed_30m_bar_ts=data.get('last_processed_30m_bar_ts', 0),
                    last_processed_30m_bar_iso=data.get('last_processed_30m_bar_iso', "")
                )
        except:
            pass
    return Position()


def save_state(pos: Position):
    """保存辅助状态（仅交易计数和连续亏损）"""
    with open(STATE_FILE, 'w') as f:
        json.dump({
            'trade_count': pos.trade_count,
            'consecutive_losses': pos.consecutive_losses,
            'last_processed_30m_bar_ts': pos.last_processed_30m_bar_ts,
            'last_processed_30m_bar_iso': pos.last_processed_30m_bar_iso,
        }, f, indent=2)


def calculate_lock_threshold(entry_price: float, qty: int, is_long: bool, risk_amount: float = 1.0) -> float:
    """
    计算锁利阈值
    
    期望盈利 = risk_amount * LOCK_PROFIT_BUFFER (单位: USDT)
    """
    position_eth = qty * FACE_VALUE
    if position_eth == 0:
        return entry_price
    
    buffer_usdt = risk_amount * LOCK_PROFIT_BUFFER
    if is_long:
        return entry_price + buffer_usdt / position_eth
    else:
        return entry_price - buffer_usdt / position_eth


def calculate_position_size(risk_amount: float, entry_price: float, stop_loss: float) -> dict:
    """
    计算开仓张数
    
    公式: Qty = R / |Entry - SL| / FACE_VALUE (向下取整)
    合约面值由常量 `FACE_VALUE` 指定
    
    返回: {
        "qty": 张数,
        "sl_distance": 止损距离,
        "position_eth": 仓位大小(ETH),
        "position_value": 仓位价值(U),
        "margin_required": 所需保证金(U),
        "actual_risk": 实际最大亏损(U)
    }
    """
    sl_distance = abs(entry_price - stop_loss)
    if sl_distance == 0:
        return {"qty": 0, "sl_distance": 0, "position_eth": 0, 
                "position_value": 0, "margin_required": 0, "actual_risk": 0}
    
    qty = int(risk_amount / sl_distance / FACE_VALUE)  # 向下取整
    position_eth = qty * FACE_VALUE
    position_value = position_eth * entry_price
    margin_required = position_value / LEVERAGE
    actual_risk = qty * FACE_VALUE * sl_distance
    
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
        save_state(self.state)

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

    def _infer_phase(self, entry_price: float, current_price: float, qty: int, 
                     last_30m_st: float, last_1h_st: float, is_long: bool,
                     initial_30m_st: float = 0, locked_stop_loss: float = 0,
                     prev_stop_loss: float = 0, risk_amount: float = 1.0) -> tuple:
        """
        从当前数据推导阶段（三阶段逻辑）- 完全无缓存直接动态计算
        
        返回: (phase, recommended_stop_loss)
        
        逻辑：
        【阶段1 - 生存期】30m ST 未达到开仓价
            止损跟随 30m ST，只紧不松
        
        【阶段3 - 换轨期】1H ST 已经比锁利阈值更紧
            止损跟随 1H ST，只紧不松
            
        【阶段2 - 锁利期】30m ST已达到开仓价，但 1H ST 未比锁利阈值更紧
            如果 30m ST 已经比锁利阈值更紧，则锁定为锁利阈值；否则跟随 30m ST。
            均应用“只紧不松”原则。
        """
        # 三阶段切换价只依赖当前持仓：成本价 + 仓位大小
        survival_to_locked_price = entry_price
        locked_to_hourly_price = calculate_lock_threshold(entry_price, qty, is_long, risk_amount)

        if (os.getenv('GATE_DEBUG') or os.getenv('DEBUG')):
            print(
                f"[STRATEGY DEBUG] _infer_phase: entry={entry_price:.2f}, 30m_ST={last_30m_st:.2f}, "
                f"1h_ST={last_1h_st:.2f}, current_stop={prev_stop_loss:.2f}, "
                f"survival_to_locked={survival_to_locked_price:.2f}, locked_to_hourly={locked_to_hourly_price:.2f}, "
                f"LOCK_PROFIT_BUFFER={LOCK_PROFIT_BUFFER}"
            )

        # 【阶段1 - 生存期】：30m ST 未达到开仓价
        if is_long:
            is_survival = last_30m_st < survival_to_locked_price
        else:
            is_survival = last_30m_st > survival_to_locked_price

        if is_survival:
            phase = Phase.SURVIVAL.value
            recommended_stop = tighten_stop_loss(last_30m_st, prev_stop_loss, is_long)
            if (os.getenv('GATE_DEBUG') or os.getenv('DEBUG')):
                print(
                    f"[STRATEGY DEBUG] Phase: SURVIVAL, 30m_ST={last_30m_st:.2f} has not reached "
                    f"entry={survival_to_locked_price:.2f}, recommended_stop={recommended_stop:.2f}"
                )
            return phase, recommended_stop

        # 到这里说明已过生存期，可触发保本或锁利

        # 【阶段3 - 换轨期】：1H ST 已越过锁利切换价（比锁利止损更紧）
        if is_long:
            is_hourly = last_1h_st > locked_to_hourly_price
        else:
            is_hourly = last_1h_st < locked_to_hourly_price

        if is_hourly:
            phase = Phase.HOURLY.value
            recommended_stop = tighten_stop_loss(last_1h_st, prev_stop_loss, is_long)
            if (os.getenv('GATE_DEBUG') or os.getenv('DEBUG')):
                print(
                    f"[STRATEGY DEBUG] Phase: HOURLY, 1H_ST={last_1h_st:.2f} crossed locked_to_hourly={locked_to_hourly_price:.2f}, "
                    f"recommended_stop={recommended_stop:.2f}"
                )
            return phase, recommended_stop

        # 【阶段2 - 锁利期】：已达保本，且 1H ST 尚未越过锁利价
        phase = Phase.LOCKED.value
        # 如果 30m ST 已经超过锁利切换价，则锁在锁利价上，不再随 30m ST 波动
        if is_long:
            if last_30m_st > locked_to_hourly_price:
                candidate_stop = locked_to_hourly_price
            else:
                candidate_stop = last_30m_st
        else:
            if last_30m_st < locked_to_hourly_price:
                candidate_stop = locked_to_hourly_price
            else:
                candidate_stop = last_30m_st

        recommended_stop = tighten_stop_loss(candidate_stop, prev_stop_loss, is_long)
        if (os.getenv('GATE_DEBUG') or os.getenv('DEBUG')):
            print(
                f"[STRATEGY DEBUG] Phase: LOCKED, 30m_ST={last_30m_st:.2f}, candidate_stop={candidate_stop:.2f}, "
                f"entry={entry_price:.2f}, locked_to_hourly={locked_to_hourly_price:.2f}, recommended_stop={recommended_stop:.2f}"
            )
        return phase, recommended_stop

    def __init__(self, client: GateClient, contract: str = "SOL_USDT"):
        self.client = client
        self.contract = contract
        self.state = load_state()
    
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
        # 获取数据 (使用1000根K线以获得最优DEMA精度)
        # 注: DEMA需要足够的历史数据才能准确计算
        # 测试结果: 1000根K线DEMA值1925.71, 与TradingView 1925.64相差仅0.07 (差异<0.01%)
        df_30m = self.client.get_candlesticks(self.contract, "30m", 1000)
        df_1h = self.client.get_candlesticks(self.contract, "1h", 1000)

        # 去重保护：同一根30m已收盘K线只处理一次，避免高频调度重复执行动作
        signal_bar = df_30m.index[-2]
        signal_bar_ts = int(signal_bar.value // 10**9)
        signal_bar_iso = signal_bar.strftime('%Y-%m-%d %H:%M:%S')

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

        def finalize(result: TradeResult) -> TradeResult:
            # 只有真正执行了分析流程才标记，防止同一根K线重复执行
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
        dema_1h = calculate_dema(df_1h['close'], DEMA_PERIOD)
        
        # 计算 ADX (使用配置的时间周期和周期长度)
        df_adx_source = df_30m if ADX_TIMEFRAME == "30m" else df_1h
        adx_series = calculate_adx(df_adx_source, ADX_LENGTH)
        last_adx = adx_series.iloc[-2]
        adx_is_trending = (not USE_ADX) or (last_adx > ADX_THRESHOLD)
        
        # 1H 数据 (上一根完整K线 = iloc[-2])
        last_1h_close = df_1h['close'].iloc[-2]
        last_1h_dema = dema_1h.iloc[-2]
        last_1h_dir = int(st_1h['direction'].iloc[-2])
        prev_1h_dir = int(st_1h['direction'].iloc[-3])
        last_1h_st = st_1h['supertrend'].iloc[-2]
        
        # 30m 数据 (上一根完整K线 = iloc[-2])
        last_30m_dir = int(st_30m['direction'].iloc[-2])
        last_30m_st = st_30m['supertrend'].iloc[-2]
        
        current_price = df_30m['close'].iloc[-1]
        
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

        # ==== 风控与冷静期对账逻辑 ====
        # 检测本地状态里记录的持仓是否已在交易所被平仓（例如触及交易所止损条件单）
        try:
            pos_state = load_position_state()
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
                        
                        # 尝试从平仓历史获取真实 PnL 和平仓时间
                        try:
                            closes = self.client.get_position_closes(self.contract, limit=5)
                            if closes:
                                # 寻找最符合当前平仓的记录 (一般为最近的一笔)
                                last_close = closes[0]
                                pnl = last_close.get('pnl', 0.0)
                                close_time = datetime.fromtimestamp(last_close.get('time', 0), tz=timezone.utc)
                                
                                from cooldown import record_trade_result
                                record_trade_result(pnl, close_time)
                                print(f"[RECONCILE] 成功记录已平仓交易：PnL={pnl:+.2f}U, 时间={close_time.strftime('%Y-%m-%d %H:%M:%S UTC')}")
                            else:
                                print("[RECONCILE] 未获取到交易所平仓历史记录")
                        except Exception as close_err:
                            print(f"[RECONCILE ERROR] 获取或记录平仓历史失败: {close_err}")
                        
                        # 清除本地持仓状态
                        clear_position_state(dir_key)
                        print(f"[RECONCILE] 已清除本地 {dir_key} 仓位状态。")
        except Exception as state_err:
            print(f"[RECONCILE ERROR] 读取或处理本地持仓状态失败: {state_err}")


        # 计算账户本金（用于显示和风控判断）:
        # gate_client.get_account() 返回的 'total' 已经是处理后的结果:
        #   优先级: cross_available (全仓) > available (隔离) > total > equity
        # 这里直接使用即可
        equity = 500  # 默认值
        if account is not None:
            total = account.get('total', 0.0)
            available = account.get('available', 0.0)
            
            print(f"[ACCOUNT PARSE] total={total}, available={available}")
            
            if total > 0:
                equity = total
                print(f"[FINAL EQUITY] 本金取值: {equity}\n")
            else:
                print(f"[ACCOUNT WARNING] account.total为0，account={account}")
                equity = 500
        else:
            print(f"[ACCOUNT ERROR] account是None, 使用默认值500\n")
        
        # 风控检查
        risk = get_risk_amount(equity)
        
        if risk['status'] == 'circuit_breaker':
            # 如果equity异常（<=0），输出调试信息
            debug_msg = ""
            if equity <= 0:
                debug_msg = f"\n\n[DEBUG] account={account}\n[DEBUG] equity={equity}"
                print(f"[STRATEGY] WARNING: equity is {equity}, account={account}")
            
            return finalize(TradeResult(
                action="circuit_breaker",
                message=f"⚠️ 熔断！{risk['message']}，停手一周{debug_msg}",
                details={"equity": equity, "account": account}
            ))
        
        # 通过 API 检查连续亏损（从交易历史获取）
        from cooldown import check_cooldown
        cooldown = check_cooldown(self.client, self.contract)
        
        if cooldown.triggered:
            # 仅在首次进入冷静期时推送通知（should_notify=True）
            # 之后每30分钟的检查不再推送，避免重复信息轰炸
            
            if cooldown.should_notify:
                # 首次触发冷静期，发送通知
                action = "cooldown"
                message = f"⚠️ 冷静期已触发！\n{cooldown.details}"
            else:
                # 仍在冷静期，但已通知过，不再推送（避免重复）
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
        
        # 开仓条件检查
        # 开多: 1H绿 + 价格>DEMA + 30m绿 + ADX趋势过滤
        can_long = (last_1h_dir == 1 and 
                    last_1h_close > last_1h_dema and 
                    last_30m_dir == 1 and
                    adx_is_trending)
        
        # 开空: 1H红 + 价格<DEMA + 30m红 + ADX趋势过滤
        can_short = (last_1h_dir == -1 and 
                     last_1h_close < last_1h_dema and 
                     last_30m_dir == -1 and
                     adx_is_trending)
        
        # 1H 刚变色？（最佳入场点标记）
        h1_just_changed = prev_1h_dir != last_1h_dir
        
        # 判断当前持仓状态
        has_position = has_api_position
        is_long = has_position and position['size'] > 0
        is_short = has_position and position['size'] < 0
        
        # 构建过滤条件检查信息（试运行调试用）- 显示真实数据
        h1_st_color = "🟢绿" if last_1h_dir == 1 else "🔴红"
        h30m_st_color = "🟢绿" if last_30m_dir == 1 else "🔴红"
        
        # 开多条件信息
        if last_1h_close > last_1h_dema:
            dema_long = f"1H收盘 {last_1h_close:.2f} > DEMA {last_1h_dema:.2f} ✅"
        else:
            dema_long = f"1H收盘 {last_1h_close:.2f} < DEMA {last_1h_dema:.2f} ❌"
        
        # 开空条件信息
        if last_1h_close < last_1h_dema:
            dema_short = f"1H收盘 {last_1h_close:.2f} < DEMA {last_1h_dema:.2f} ✅"
        else:
            dema_short = f"1H收盘 {last_1h_close:.2f} > DEMA {last_1h_dema:.2f} ❌"
            
        adx_trend_symbol = '✅' if adx_is_trending else '❌'
        adx_info_line = f"• ADX ({ADX_TIMEFRAME.upper()}): {last_adx:.2f} (阈值: {ADX_THRESHOLD}) {adx_trend_symbol}\n"
        
        filter_info_long = (
            f"【过滤条件检查】\n"
            f"• 1H ST: {h1_st_color} {'✅' if last_1h_dir == 1 else '❌'}\n"
            f"• {dema_long}\n"
            f"• 30m ST: {h30m_st_color} {'✅' if last_30m_dir == 1 else '❌'}\n"
            f"{adx_info_line}"
        )
        
        filter_info_short = (
            f"【过滤条件检查】\n"
            f"• 1H ST: {h1_st_color} {'✅' if last_1h_dir == -1 else '❌'}\n"
            f"• {dema_short}\n"
            f"• 30m ST: {h30m_st_color} {'✅' if last_30m_dir == -1 else '❌'}\n"
            f"{adx_info_line}"
        )
        
        # ============ 无持仓: 检查开仓条件 ============
        if not has_position:
            if can_long:
                pos_info = calculate_position_size(risk_amount, current_price, last_30m_st)
                lock_threshold = calculate_lock_threshold(current_price, pos_info['qty'], is_long=True, risk_amount=risk_amount)
                timing = " ⚡最佳入场!" if h1_just_changed else ""
                
                return finalize(TradeResult(
                    action="open_long",
                    message=f"""🟢 开多信号！{timing}

━━━━━━━━━━ 技术指标 ━━━━━━━━━━
【1小时线】
• 1H ST: {last_1h_st:.2f} 🟢 绿 ✅
• 1H 收盘: {last_1h_close:.2f}
• 1H DEMA200: {last_1h_dema:.2f}
• 条件: {dema_long} ✅

【30分钟线】
• 30m ST: {last_30m_st:.2f} 🟢 绿 ✅

【ADX 过滤器】
• ADX ({ADX_TIMEFRAME.upper()}): {last_adx:.2f}
• 条件: ADX > {ADX_THRESHOLD} (启用: {'是' if USE_ADX else '否'}) ✅

━━━━━━━━━━ 行动 ━━━━━━━━━━
📌 开多 {pos_info['qty']}张 @ {current_price:.2f}
📌 设止损 @ {last_30m_st:.2f}

━━━━━━━━━━ 仓位计算 ━━━━━━━━━━
• 止损距离: {pos_info['sl_distance']:.2f}点
• 保证金: {pos_info['margin_required']:.2f}U ({LEVERAGE}x)
• 风险: {risk_info}
• 锁利阈值: {lock_threshold:.2f}""",
                    details={
                        "entry": current_price,
                        "stop_loss": last_30m_st,
                        "qty": pos_info['qty'],
                        "actual_risk": pos_info['actual_risk'],
                        "1h_st": last_1h_st,
                        "1h_close": last_1h_close,
                        "1h_dema": last_1h_dema,
                        "30m_st": last_30m_st,
                        "adx": last_adx
                    }
                ))
            
            elif can_short:
                pos_info = calculate_position_size(risk_amount, current_price, last_30m_st)
                lock_threshold = calculate_lock_threshold(current_price, pos_info['qty'], is_long=False, risk_amount=risk_amount)
                timing = " ⚡最佳入场!" if h1_just_changed else ""
                
                return finalize(TradeResult(
                    action="open_short",
                    message=f"""🔴 开空信号！{timing}

━━━━━━━━━━ 技术指标 ━━━━━━━━━━
【1小时线】
• 1H ST: {last_1h_st:.2f} 🔴 红 ✅
• 1H 收盘: {last_1h_close:.2f}
• 1H DEMA200: {last_1h_dema:.2f}
• 条件: {dema_short} ✅

【30分钟线】
• 30m ST: {last_30m_st:.2f} 🔴 红 ✅

【ADX 过滤器】
• ADX ({ADX_TIMEFRAME.upper()}): {last_adx:.2f}
• 条件: ADX > {ADX_THRESHOLD} (启用: {'是' if USE_ADX else '否'}) ✅

━━━━━━━━━━ 行动 ━━━━━━━━━━
📌 开空 {pos_info['qty']}张 @ {current_price:.2f}
📌 设止损 @ {last_30m_st:.2f}

━━━━━━━━━━ 仓位计算 ━━━━━━━━━━
• 止损距离: {pos_info['sl_distance']:.2f}点
• 保证金: {pos_info['margin_required']:.2f}U ({LEVERAGE}x)
• 风险: {risk_info}
• 锁利阈值: {lock_threshold:.2f}""",
                    details={
                        "entry": current_price,
                        "stop_loss": last_30m_st,
                        "qty": pos_info['qty'],
                        "actual_risk": pos_info['actual_risk'],
                        "1h_st": last_1h_st,
                        "1h_close": last_1h_close,
                        "1h_dema": last_1h_dema,
                        "30m_st": last_30m_st,
                        "adx": last_adx
                    }
                ))
            
            else:
                target_dir_str = "做多 🟢" if last_30m_dir == 1 else "做空 🔴"
                h1_st_expect = "🟢 绿" if last_30m_dir == 1 else "🔴 红"
                h1_st_check = "满足 ✅" if (last_30m_dir == 1 and last_1h_dir == 1) or (last_30m_dir == -1 and last_1h_dir == -1) else "阻断 ❌"
                
                dema_op = ">" if last_30m_dir == 1 else "<"
                dema_ok = (last_30m_dir == 1 and last_1h_close > last_1h_dema) or (last_30m_dir == -1 and last_1h_close < last_1h_dema)
                dema_check = "满足 ✅" if dema_ok else "阻断 ❌"
                
                adx_ok = (not USE_ADX) or (last_adx > ADX_THRESHOLD)
                adx_check = "满足 ✅" if adx_ok else ("过滤中 ❌" if USE_ADX else "已关闭 ⚠️")
                
                return finalize(TradeResult(
                    action="none",
                    message=f"""📊 无开仓信号

━━━━━━━━━━ 当前价格 ━━━━━━━━━━
• 价格: {current_price:.2f}

🎯 目标方向: {target_dir_str} (基于 30m ST)

━━━━━━━━━━ 过滤条件检查 ━━━━━━━━━━
• 1H ST 趋势过滤 (1H ST 应为 {h1_st_expect}, 实际为 {last_1h_st:.2f} {'🟢 绿' if last_1h_dir == 1 else '🔴 红'}): {h1_st_check}
• 1H DEMA 均线过滤 (收盘 {last_1h_close:.2f} {dema_op} DEMA {last_1h_dema:.2f}): {dema_check}
• ADX 动能过滤 (ADX {last_adx:.2f} > 阈值 {ADX_THRESHOLD}): {adx_check}

━━━━━━━━━━ 账户状态 ━━━━━━━━━━
• 本金: {equity:.2f}U
• 风险额: {risk_amount:.2f}U""",
                    details={
                        "price": current_price,
                        "1h_st": last_1h_st,
                        "1h_st_dir": last_1h_dir,
                        "1h_close": last_1h_close,
                        "1h_dema": last_1h_dema,
                        "30m_st": last_30m_st,
                        "30m_st_dir": last_30m_dir,
                        "adx": last_adx,
                        "equity": equity
                    }
                ))
        
        # ============ 已持多仓 ============
        if is_long:
            # 如果满足开空条件 → 提示平多反手
            if can_short:
                pnl = (current_price - position['entry_price']) * position['size'] * FACE_VALUE
                return finalize(TradeResult(
                    action="reverse_to_short",
                    message=f"🔄 平多反手开空！\n"
                            f"• 当前多仓入场: {position['entry_price']:.2f}\n"
                            f"• 当前价: {current_price:.2f}\n"
                            f"• 预计盈亏: {pnl:.2f}U\n"
                            f"• 新空仓止损: {last_30m_st:.2f}",
                    details={"pnl": pnl, "new_stop": last_30m_st}
                ))
            
            # 否则继续持有，检查止损调整
            return finalize(self._manage_long_position(
                position, df_30m, df_1h, st_30m, st_1h,
                last_1h_close, last_1h_dema, risk_amount, risk_info,
                last_adx=last_adx
            ))
        
        # ============ 已持空仓 ============
        if is_short:
            # 如果满足开多条件 → 提示平空反手
            if can_long:
                pnl = (position['entry_price'] - current_price) * abs(position['size']) * FACE_VALUE
                return finalize(TradeResult(
                    action="reverse_to_long",
                    message=f"🔄 平空反手开多！\n"
                            f"• 当前空仓入场: {position['entry_price']:.2f}\n"
                            f"• 当前价: {current_price:.2f}\n"
                            f"• 预计盈亏: {pnl:.2f}U\n"
                            f"• 新多仓止损: {last_30m_st:.2f}",
                    details={"pnl": pnl, "new_stop": last_30m_st}
                ))
            
            # 如果仍满足开空条件（已持空仓）→ 不提示，检查止损调整
            return finalize(self._manage_short_position(
                position, df_30m, df_1h, st_30m, st_1h,
                last_1h_close, last_1h_dema, risk_amount, risk_info,
                last_adx=last_adx
            ))
        
        return finalize(TradeResult(action="none", message="未知状态"))
    
    def _manage_long_position(self, position, df_30m, df_1h, st_30m, st_1h,
                               last_1h_close, last_1h_dema, risk_amount, risk_info,
                               last_adx: float = None) -> TradeResult:
        """管理多仓（无状态，每次推导）"""
        # 兼容性处理：如果没有传入 last_adx，则动态计算
        if last_adx is None:
            if 'high' in df_30m.columns and 'low' in df_30m.columns:
                df_adx_source = df_30m if ADX_TIMEFRAME == "30m" else df_1h
                adx_series = calculate_adx(df_adx_source, ADX_LENGTH)
                last_adx = adx_series.iloc[-2]
            else:
                last_adx = 0.0
                
        adx_is_trending = (not USE_ADX) or (last_adx > ADX_THRESHOLD)

        current_price = df_30m['close'].iloc[-1]
        entry_price = position['entry_price']
        qty = abs(position['size'])
        last_30m_st = st_30m['supertrend'].iloc[-2]
        last_30m_dir = int(st_30m['direction'].iloc[-2])
        last_1h_st = st_1h['supertrend'].iloc[-2]
        last_1h_dir = int(st_1h['direction'].iloc[-2])

        # 读取历史状态
        prev_state = load_position_state().get("long", {})
        prev_phase = prev_state.get("phase", "")
        prev_stop_loss = prev_state.get("stop_loss", 0)  # ← 记录旧止损，用于调整时验证
        live_stop_loss = self._get_live_stop_price()
        baseline_stop_loss = prev_stop_loss if prev_stop_loss > 0 else live_stop_loss
        initial_30m_st = prev_state.get("initial_30m_st", 0)
        locked_stop_loss = prev_state.get("locked_stop_loss", 0)
        
        # 首次开仓时记录 initial_30m_st
        if initial_30m_st <= 0:
            initial_30m_st = last_30m_st

        # 推导当前阶段和建议的止损，传入历史信息
        phase, recommended_stop = self._infer_phase(entry_price, current_price, qty, 
                                                      last_30m_st, last_1h_st, is_long=True,
                                                      initial_30m_st=initial_30m_st,
                                                      locked_stop_loss=locked_stop_loss,
                                                      prev_stop_loss=baseline_stop_loss)

        # 计算动态止盈价 (TP)
        tp_price = None
        if initial_30m_st > 0:
            sl_dist = abs(entry_price - initial_30m_st)
            tp_price = entry_price + TP_RATIO * sl_dist

        # 判断离场信号
        exit_signal = False
        exit_reason = ""
        if tp_price is not None and current_price >= tp_price:
            exit_signal = True
            exit_reason = f"止盈触发 @ {current_price:.2f} (目标: {tp_price:.2f})"
        elif phase == Phase.HOURLY.value and last_1h_dir == -1:
            exit_signal = True
            exit_reason = "1H ST 变红"
        elif phase in [Phase.SURVIVAL.value, Phase.LOCKED.value] and last_30m_dir == -1:
            exit_signal = True
            exit_reason = "30m ST 变红"

        if exit_signal:
            can_reverse = (last_1h_dir == -1 and 
                          last_1h_close < last_1h_dema and 
                          last_30m_dir == -1 and
                          adx_is_trending)
            
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
        pnl = (current_price - entry_price) * qty * FACE_VALUE
        lock_threshold = calculate_lock_threshold(entry_price, qty, is_long=True, risk_amount=risk_amount)

        # 检查持仓状态变化 (阶段和止损)
        current_time = time.time()
        
        has_change, change_type = update_position_state(
            direction="long",
            phase=phase,
            stop_loss=recommended_stop,
            entry_price=entry_price,
            current_time=current_time,
            initial_30m_st=initial_30m_st
        )

        # 无本地状态（例如定时任务无持久化）时，回退到交易所实时止损做差异判断
        if change_type == "new_position" and baseline_stop_loss > 0 and abs(baseline_stop_loss - recommended_stop) > 0.01:
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
            return TradeResult(
                action="stop_updated",
                message=f"""⚠️  止损已调整
• 方向: 多 | 阶段: {phase_names.get(phase)}
• 入场: {entry_price:.2f} | 当前: {current_price:.2f}
• 新止损: {recommended_stop:.2f} | 浮盈: {pnl:+.2f}U""",
                details={"phase": phase, "stop_loss": recommended_stop, "old_stop": baseline_stop_loss if baseline_stop_loss > 0 else None, "pnl": pnl}
            )
        elif change_type == "enter_locked":
            return TradeResult(
                action="enter_locked",
                message=f"""🟡 已进入锁利期
• 方向: 多 | 阶段: {phase_names.get(phase)}
• 入场: {entry_price:.2f} | 当前: {current_price:.2f}
• 止损: {recommended_stop:.2f} | 浮盈: {pnl:+.2f}U
• 说明: 30m ST已达到开仓价，进入锁利期跟随30m ST""",
                details={"phase": phase, "stop_loss": recommended_stop, "old_stop": prev_stop_loss if prev_stop_loss > 0 else None, "pnl": pnl}
            )
        elif change_type == "switch_1h":
            return TradeResult(
                action="switch_1h",
                message=f"""🟣 已切换至小时线轨道
• 方向: 多 | 阶段: {phase_names.get(phase)}
• 入场: {entry_price:.2f} | 当前: {current_price:.2f}
• 止损: {recommended_stop:.2f} | 浮盈: {pnl:+.2f}U
• 说明: 按30m ST平仓收益超过{LOCK_PROFIT_BUFFER}U，切换至1H ST跟踪""",
                details={"phase": phase, "stop_loss": recommended_stop, "old_stop": prev_stop_loss if prev_stop_loss > 0 else None, "pnl": pnl}
            )
        else:
            # 正常持仓，无状态变化
            tp_msg = f" | 止盈: {tp_price:.2f}" if tp_price else ""
            return TradeResult(
                action="hold",
                message=f"""✅ 持仓中
• 方向: 多 | 阶段: {phase_names.get(phase)}
• 入场: {entry_price:.2f} | 当前: {current_price:.2f}
• 止损: {recommended_stop:.2f}{tp_msg} | 浮盈: {pnl:+.2f}U

━━━━━━━━━━ 技术指标 ━━━━━━━━━━
【1小时线】
• 1H ST: {last_1h_st:.2f} {'🟢 绿' if last_1h_dir == 1 else '🔴 红'}
• 1H 收盘: {last_1h_close:.2f}
• 1H DEMA200: {last_1h_dema:.2f}

【30分钟线】
• 30m ST: {last_30m_st:.2f} {'🟢 绿' if last_30m_dir == 1 else '🔴 红'}

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
                                last_adx: float = None) -> TradeResult:
        """管理空仓（无状态，每次推导）"""
        # 兼容性处理：如果没有传入 last_adx，则动态计算
        if last_adx is None:
            if 'high' in df_30m.columns and 'low' in df_30m.columns:
                df_adx_source = df_30m if ADX_TIMEFRAME == "30m" else df_1h
                adx_series = calculate_adx(df_adx_source, ADX_LENGTH)
                last_adx = adx_series.iloc[-2]
            else:
                last_adx = 0.0
                
        adx_is_trending = (not USE_ADX) or (last_adx > ADX_THRESHOLD)

        current_price = df_30m['close'].iloc[-1]
        entry_price = position['entry_price']
        qty = abs(position['size'])
        last_30m_st = st_30m['supertrend'].iloc[-2]
        last_30m_dir = int(st_30m['direction'].iloc[-2])
        last_1h_st = st_1h['supertrend'].iloc[-2]
        last_1h_dir = int(st_1h['direction'].iloc[-2])

        # 读取历史状态
        prev_state = load_position_state().get("short", {})
        prev_phase = prev_state.get("phase", "")
        prev_stop_loss = prev_state.get("stop_loss", 0)  # ← 记录旧止损，用于调整时验证
        live_stop_loss = self._get_live_stop_price()
        baseline_stop_loss = prev_stop_loss if prev_stop_loss > 0 else live_stop_loss
        initial_30m_st = prev_state.get("initial_30m_st", 0)
        locked_stop_loss = prev_state.get("locked_stop_loss", 0)
        
        # 首次开仓时记录 initial_30m_st
        if initial_30m_st <= 0:
            initial_30m_st = last_30m_st

        # 推导当前阶段和建议的止损，传入历史信息
        phase, recommended_stop = self._infer_phase(entry_price, current_price, qty, 
                                                      last_30m_st, last_1h_st, is_long=False,
                                                      initial_30m_st=initial_30m_st,
                                                      locked_stop_loss=locked_stop_loss,
                                                      prev_stop_loss=baseline_stop_loss)

        # 计算动态止盈价 (TP)
        tp_price = None
        if initial_30m_st > 0:
            sl_dist = abs(entry_price - initial_30m_st)
            tp_price = entry_price - TP_RATIO * sl_dist

        # 判断离场信号
        exit_signal = False
        exit_reason = ""
        if tp_price is not None and current_price <= tp_price:
            exit_signal = True
            exit_reason = f"止盈触发 @ {current_price:.2f} (目标: {tp_price:.2f})"
        elif phase == Phase.HOURLY.value and last_1h_dir == 1:
            exit_signal = True
            exit_reason = "1H ST 变绿"
        elif phase in [Phase.SURVIVAL.value, Phase.LOCKED.value] and last_30m_dir == 1:
            exit_signal = True
            exit_reason = "30m ST 变绿"

        if exit_signal:
            can_reverse = (last_1h_dir == 1 and 
                          last_1h_close > last_1h_dema and 
                          last_30m_dir == 1 and
                          adx_is_trending)

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
        pnl = (entry_price - current_price) * qty * FACE_VALUE
        lock_threshold = calculate_lock_threshold(entry_price, qty, is_long=False, risk_amount=risk_amount)

        # 检查持仓状态变化 (阶段和止损)
        current_time = time.time()
        
        # 当进入LOCKED时，更新 locked_stop_loss
        has_change, change_type = update_position_state(
            direction="short",
            phase=phase,
            stop_loss=recommended_stop,
            entry_price=entry_price,
            current_time=current_time,
            initial_30m_st=initial_30m_st
        )

        # 无本地状态（例如定时任务无持久化）时，回退到交易所实时止损做差异判断
        if change_type == "new_position" and baseline_stop_loss > 0 and abs(baseline_stop_loss - recommended_stop) > 0.01:
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
            return TradeResult(
                action="stop_updated",
                message=f"""⚠️  止损已调整
• 方向: 空 | 阶段: {phase_names.get(phase)}
• 入场: {entry_price:.2f} | 当前: {current_price:.2f}
• 新止损: {recommended_stop:.2f} | 浮盈: {pnl:+.2f}U""",
                details={"phase": phase, "stop_loss": recommended_stop, "old_stop": baseline_stop_loss if baseline_stop_loss > 0 else None, "pnl": pnl}
            )
        elif change_type == "enter_locked":
            return TradeResult(
                action="enter_locked",
                message=f"""🟡 已进入锁利期
• 方向: 空 | 阶段: {phase_names.get(phase)}
• 入场: {entry_price:.2f} | 当前: {current_price:.2f}
• 止损: {recommended_stop:.2f} | 浮盈: {pnl:+.2f}U
• 说明: 30m ST已达到开仓价，进入锁利期跟随30m ST""",
                details={"phase": phase, "stop_loss": recommended_stop, "old_stop": prev_stop_loss if prev_stop_loss > 0 else None, "pnl": pnl}
            )
        elif change_type == "switch_1h":
            return TradeResult(
                action="switch_1h",
                message=f"""🟣 已切换至小时线轨道
• 方向: 空 | 阶段: {phase_names.get(phase)}
• 入场: {entry_price:.2f} | 当前: {current_price:.2f}
• 止损: {recommended_stop:.2f} | 浮盈: {pnl:+.2f}U
• 说明: 按30m ST平仓收益超过{LOCK_PROFIT_BUFFER}U，切换至1H ST跟踪""",
                details={"phase": phase, "stop_loss": recommended_stop, "old_stop": prev_stop_loss if prev_stop_loss > 0 else None, "pnl": pnl}
            )
        else:
            # 正常持仓，无状态变化
            tp_msg = f" | 止盈: {tp_price:.2f}" if tp_price else ""
            return TradeResult(
                action="hold",
                message=f"""✅ 持仓中
• 方向: 空 | 阶段: {phase_names.get(phase)}
• 入场: {entry_price:.2f} | 当前: {current_price:.2f}
• 止损: {recommended_stop:.2f}{tp_msg} | 浮盈: {pnl:+.2f}U

━━━━━━━━━━ 技术指标 ━━━━━━━━━━
【1小时线】
• 1H ST: {last_1h_st:.2f} {'🟢 绿' if last_1h_dir == 1 else '🔴 红'}
• 1H 收盘: {last_1h_close:.2f}
• 1H DEMA200: {last_1h_dema:.2f}

【30分钟线】
• 30m ST: {last_30m_st:.2f} {'🟢 绿' if last_30m_dir == 1 else '🔴 红'}

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
        record_trade_result(pnl)
        
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
            pos_info = calculate_position_size(risk_amount, current_price, reverse_stop)
            lock_threshold = calculate_lock_threshold(
                current_price, pos_info['qty'], 
                is_long=(reverse_direction == "long"),
                risk_amount=risk_amount
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
            clear_position_state(direction_key)
            
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
            clear_position_state(direction_key)
            
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
        record_trade_result(pnl)
        
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
        clear_position_state(direction_key)
        return result
    
    def _reset_state(self):
        """重置辅助状态（保留交易计数和连续亏损信息）"""
        save_state(self.state)
