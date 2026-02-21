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
    LOCK_PROFIT_BUFFER
)
from position_state import update_position_state, clear_position_state
from indicators import calculate_supertrend, calculate_dema
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


# 合约面值（每张对应的 ETH），用于仓位/盈亏计算。测试套件使用 0.01
FACE_VALUE = 0.1


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
                    consecutive_losses=data.get('consecutive_losses', 0)
                )
        except:
            pass
    return Position()


def save_state(pos: Position):
    """保存辅助状态（仅交易计数和连续亏损）"""
    with open(STATE_FILE, 'w') as f:
        json.dump({
            'trade_count': pos.trade_count,
            'consecutive_losses': pos.consecutive_losses
        }, f, indent=2)


def calculate_lock_threshold(entry_price: float, qty: int, is_long: bool) -> float:
    """
    计算锁利阈值
    
    空单: 止损 ≤ 入场 - Buffer / 仓位(ETH)
    多单: 止损 ≥ 入场 + Buffer / 仓位(ETH)
    """
    position_eth = qty * FACE_VALUE
    if position_eth == 0:
        return entry_price
    
    if is_long:
        return entry_price + LOCK_PROFIT_BUFFER / position_eth
    else:
        return entry_price - LOCK_PROFIT_BUFFER / position_eth


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


class TradingStrategy:

    def _infer_phase(self, entry_price: float, current_price: float, qty: int, 
                     last_30m_st: float, last_1h_st: float, is_long: bool) -> tuple:
        """
        从当前数据推导阶段（无状态）
        返回: (phase, recommended_stop_loss)
        """
        # 计算当前浮盈
        if is_long:
            pnl = (current_price - entry_price) * qty * FACE_VALUE
            current_st = last_30m_st
        else:
            pnl = (entry_price - current_price) * qty * FACE_VALUE
            current_st = last_30m_st

        # 计算锁利阈值
        lock_threshold = calculate_lock_threshold(entry_price, qty, is_long)

        if (os.getenv('GATE_DEBUG') or os.getenv('DEBUG')):
            print(f"[STRATEGY DEBUG] _infer_phase: pnl={pnl:.2f}, lock_threshold={lock_threshold:.2f}, last_1h_st={last_1h_st:.2f}")

        # 推导阶段逻辑
        if pnl < LOCK_PROFIT_BUFFER:
            # 生存期：跟随 30m ST，只紧不松
            phase = Phase.SURVIVAL.value
            if is_long:
                recommended_stop = last_30m_st  # 多仓：30m ST 为目标
            else:
                recommended_stop = last_30m_st  # 空仓：30m ST 为目标
        elif is_1h_tighter(last_1h_st, lock_threshold, is_long):
            # 换轨期：1H ST 比锁利阈值更紧
            phase = Phase.HOURLY.value
            recommended_stop = last_1h_st
        else:
            # 锁利期：浮盈 > buffer 但 1H ST 不够紧
            phase = Phase.LOCKED.value
            recommended_stop = last_30m_st  # 锁利时使用当前 30m ST 作为止损

        if (os.getenv('GATE_DEBUG') or os.getenv('DEBUG')):
            print(f"[STRATEGY DEBUG] inferred phase={phase}, recommended_stop={recommended_stop:.2f}")

        return phase, recommended_stop

    def __init__(self, client: GateClient, contract: str = "ETH_USDT"):
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
            
            return TradeResult(
                action="circuit_breaker",
                message=f"⚠️ 熔断！{risk['message']}，停手一周{debug_msg}",
                details={"equity": equity, "account": account}
            )
        
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
            
            return TradeResult(
                action=action,
                message=message,
                details={
                    "reason": cooldown.reason,
                    "cooldown_hours": cooldown.cooldown_hours,
                    "consecutive_losses": cooldown.consecutive_losses,
                    "can_trade_time": cooldown.can_trade_time.isoformat() if cooldown.can_trade_time else None,
                    "should_notify": cooldown.should_notify
                }
            )
        
        risk_amount = risk['amount']
        risk_info = risk['message']
        
        # 开仓条件检查
        # 开多: 1H绿 + 价格>DEMA + 30m绿
        can_long = (last_1h_dir == 1 and 
                    last_1h_close > last_1h_dema and 
                    last_30m_dir == 1)
        
        # 开空: 1H红 + 价格<DEMA + 30m红
        can_short = (last_1h_dir == -1 and 
                     last_1h_close < last_1h_dema and 
                     last_30m_dir == -1)
        
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
        
        filter_info_long = (
            f"【过滤条件检查】\n"
            f"• 1H ST: {h1_st_color} {'✅' if last_1h_dir == 1 else '❌'}\n"
            f"• {dema_long}\n"
            f"• 30m ST: {h30m_st_color} {'✅' if last_30m_dir == 1 else '❌'}\n"
        )
        
        filter_info_short = (
            f"【过滤条件检查】\n"
            f"• 1H ST: {h1_st_color} {'✅' if last_1h_dir == -1 else '❌'}\n"
            f"• {dema_short}\n"
            f"• 30m ST: {h30m_st_color} {'✅' if last_30m_dir == -1 else '❌'}\n"
        )
        
        # ============ 无持仓: 检查开仓条件 ============
        if not has_position:
            if can_long:
                pos_info = calculate_position_size(risk_amount, current_price, last_30m_st)
                lock_threshold = calculate_lock_threshold(current_price, pos_info['qty'], is_long=True)
                timing = " ⚡最佳入场!" if h1_just_changed else ""
                
                return TradeResult(
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
                        "30m_st": last_30m_st
                    }
                )
            
            elif can_short:
                pos_info = calculate_position_size(risk_amount, current_price, last_30m_st)
                lock_threshold = calculate_lock_threshold(current_price, pos_info['qty'], is_long=False)
                timing = " ⚡最佳入场!" if h1_just_changed else ""
                
                return TradeResult(
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
                        "30m_st": last_30m_st
                    }
                )
            
            else:
                return TradeResult(
                    action="none",
                    message=f"""📊 无开仓信号

━━━━━━━━━━ 当前价格 ━━━━━━━━━━
• 价格: {current_price:.2f}

━━━━━━━━━━ 技术指标 ━━━━━━━━━━
【1小时线】
• 1H ST: {last_1h_st:.2f} {'🟢 绿' if last_1h_dir == 1 else '🔴 红'}
• 1H 收盘: {last_1h_close:.2f}
• 1H DEMA200: {last_1h_dema:.2f}
• 条件: {dema_long if last_1h_close > last_1h_dema else dema_short}

【30分钟线】
• 30m ST: {last_30m_st:.2f} {'🟢 绿' if last_30m_dir == 1 else '🔴 红'}

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
                        "equity": equity
                    }
                )
        
        # ============ 已持多仓 ============
        if is_long:
            # 如果满足开空条件 → 提示平多反手
            if can_short:
                pnl = (current_price - position['entry_price']) * position['size'] * FACE_VALUE
                return TradeResult(
                    action="reverse_to_short",
                    message=f"🔄 平多反手开空！\n"
                            f"• 当前多仓入场: {position['entry_price']:.2f}\n"
                            f"• 当前价: {current_price:.2f}\n"
                            f"• 预计盈亏: {pnl:.2f}U\n"
                            f"• 新空仓止损: {last_30m_st:.2f}",
                    details={"pnl": pnl, "new_stop": last_30m_st}
                )
            
            # 否则继续持有，检查止损调整
            return self._manage_long_position(
                position, df_30m, df_1h, st_30m, st_1h,
                last_1h_close, last_1h_dema, risk_amount, risk_info
            )
        
        # ============ 已持空仓 ============
        if is_short:
            # 如果满足开多条件 → 提示平空反手
            if can_long:
                pnl = (position['entry_price'] - current_price) * abs(position['size']) * FACE_VALUE
                return TradeResult(
                    action="reverse_to_long",
                    message=f"🔄 平空反手开多！\n"
                            f"• 当前空仓入场: {position['entry_price']:.2f}\n"
                            f"• 当前价: {current_price:.2f}\n"
                            f"• 预计盈亏: {pnl:.2f}U\n"
                            f"• 新多仓止损: {last_30m_st:.2f}",
                    details={"pnl": pnl, "new_stop": last_30m_st}
                )
            
            # 如果仍满足开空条件（已持空仓）→ 不提示，检查止损调整
            return self._manage_short_position(
                position, df_30m, df_1h, st_30m, st_1h,
                last_1h_close, last_1h_dema, risk_amount, risk_info
            )
        
        return TradeResult(action="none", message="未知状态")
    
    def _manage_long_position(self, position, df_30m, df_1h, st_30m, st_1h,
                               last_1h_close, last_1h_dema, risk_amount, risk_info) -> TradeResult:
        """管理多仓（无状态，每次推导）"""
        current_price = df_30m['close'].iloc[-1]
        entry_price = position['entry_price']
        qty = abs(position['size'])
        last_30m_st = st_30m['supertrend'].iloc[-2]
        last_30m_dir = int(st_30m['direction'].iloc[-2])
        last_1h_st = st_1h['supertrend'].iloc[-2]
        last_1h_dir = int(st_1h['direction'].iloc[-2])

        # 推导当前阶段和建议的止损
        phase, recommended_stop = self._infer_phase(entry_price, current_price, qty, 
                                                      last_30m_st, last_1h_st, is_long=True)

        # 判断离场信号
        exit_signal = False
        exit_reason = ""
        if phase == Phase.HOURLY.value and last_1h_dir == -1:
            exit_signal = True
            exit_reason = "1H ST 变红"
        elif phase in [Phase.SURVIVAL.value, Phase.LOCKED.value] and last_30m_dir == -1:
            exit_signal = True
            exit_reason = "30m ST 变红"

        if exit_signal:
            can_reverse = (last_1h_dir == -1 and 
                          last_1h_close < last_1h_dema and 
                          last_30m_dir == -1)
            
            return self._close_with_reverse_check(
                position, entry_price, current_price, 
                is_long=True, reason=exit_reason,
                can_reverse=can_reverse, reverse_direction="short",
                reverse_stop=last_30m_st, risk_amount=risk_amount, risk_info=risk_info,
                last_1h_close=last_1h_close, last_1h_dema=last_1h_dema,
                last_1h_dir=last_1h_dir, last_30m_dir=last_30m_dir
            )

        # 计算浮盈
        pnl = (current_price - entry_price) * qty * FACE_VALUE
        lock_threshold = calculate_lock_threshold(entry_price, qty, is_long=True)

        # 检查持仓状态变化 (阶段和止损)
        current_time = time.time()
        has_change, change_type = update_position_state(
            direction="long",
            phase=phase,
            stop_loss=recommended_stop,
            entry_price=entry_price,
            current_time=current_time
        )

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
                details={"phase": phase, "stop_loss": recommended_stop, "pnl": pnl}
            )
        elif change_type == "enter_locked":
            return TradeResult(
                action="enter_locked",
                message=f"""🟡 已进入锁利期
• 方向: 多 | 阶段: {phase_names.get(phase)}
• 入场: {entry_price:.2f} | 当前: {current_price:.2f}
• 止损: {recommended_stop:.2f} | 浮盈: {pnl:+.2f}U
• 说明: 浮盈已超过 50U，切换至锁利策略""",
                details={"phase": phase, "stop_loss": recommended_stop, "pnl": pnl}
            )
        elif change_type == "switch_1h":
            return TradeResult(
                action="switch_1h",
                message=f"""🟣 已切换至小时线轨道
• 方向: 多 | 阶段: {phase_names.get(phase)}
• 入场: {entry_price:.2f} | 当前: {current_price:.2f}
• 止损: {recommended_stop:.2f} | 浮盈: {pnl:+.2f}U
• 说明: 1H ST已转向上升，以 1H ST 作为止损参考""",
                details={"phase": phase, "stop_loss": recommended_stop, "pnl": pnl}
            )
        else:
            # 正常持仓，无状态变化
            return TradeResult(
                action="hold",
                message=f"""✅ 持仓中
• 方向: 多 | 阶段: {phase_names.get(phase)}
• 入场: {entry_price:.2f} | 当前: {current_price:.2f}
• 止损: {recommended_stop:.2f} | 浮盈: {pnl:+.2f}U

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
                                last_1h_close, last_1h_dema, risk_amount, risk_info) -> TradeResult:
        """管理空仓（无状态，每次推导）"""
        current_price = df_30m['close'].iloc[-1]
        entry_price = position['entry_price']
        qty = abs(position['size'])
        last_30m_st = st_30m['supertrend'].iloc[-2]
        last_30m_dir = int(st_30m['direction'].iloc[-2])
        last_1h_st = st_1h['supertrend'].iloc[-2]
        last_1h_dir = int(st_1h['direction'].iloc[-2])

        # 推导当前阶段和建议的止损
        phase, recommended_stop = self._infer_phase(entry_price, current_price, qty, 
                                                      last_30m_st, last_1h_st, is_long=False)

        # 判断离场信号
        exit_signal = False
        exit_reason = ""
        if phase == Phase.HOURLY.value and last_1h_dir == 1:
            exit_signal = True
            exit_reason = "1H ST 变绿"
        elif phase in [Phase.SURVIVAL.value, Phase.LOCKED.value] and last_30m_dir == 1:
            exit_signal = True
            exit_reason = "30m ST 变绿"

        if exit_signal:
            can_reverse = (last_1h_dir == 1 and 
                          last_1h_close > last_1h_dema and 
                          last_30m_dir == 1)

            return self._close_with_reverse_check(
                position, entry_price, current_price,
                is_long=False, reason=exit_reason,
                can_reverse=can_reverse, reverse_direction="long",
                reverse_stop=last_30m_st, risk_amount=risk_amount, risk_info=risk_info,
                last_1h_close=last_1h_close, last_1h_dema=last_1h_dema,
                last_1h_dir=last_1h_dir, last_30m_dir=last_30m_dir
            )

        # 计算浮盈
        pnl = (entry_price - current_price) * qty * FACE_VALUE
        lock_threshold = calculate_lock_threshold(entry_price, qty, is_long=False)

        # 检查持仓状态变化 (阶段和止损)
        current_time = time.time()
        has_change, change_type = update_position_state(
            direction="short",
            phase=phase,
            stop_loss=recommended_stop,
            entry_price=entry_price,
            current_time=current_time
        )

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
                details={"phase": phase, "stop_loss": recommended_stop, "pnl": pnl}
            )
        elif change_type == "enter_locked":
            return TradeResult(
                action="enter_locked",
                message=f"""🟡 已进入锁利期
• 方向: 空 | 阶段: {phase_names.get(phase)}
• 入场: {entry_price:.2f} | 当前: {current_price:.2f}
• 止损: {recommended_stop:.2f} | 浮盈: {pnl:+.2f}U
• 说明: 浮盈已超过 50U，切换至锁利策略""",
                details={"phase": phase, "stop_loss": recommended_stop, "pnl": pnl}
            )
        elif change_type == "switch_1h":
            return TradeResult(
                action="switch_1h",
                message=f"""🟣 已切换至小时线轨道
• 方向: 空 | 阶段: {phase_names.get(phase)}
• 入场: {entry_price:.2f} | 当前: {current_price:.2f}
• 止损: {recommended_stop:.2f} | 浮盈: {pnl:+.2f}U
• 说明: 1H ST已转向下降，以 1H ST 作为止损参考""",
                details={"phase": phase, "stop_loss": recommended_stop, "pnl": pnl}
            )
        else:
            # 正常持仓，无状态变化
            return TradeResult(
                action="hold",
                message=f"""✅ 持仓中
• 方向: 空 | 阶段: {phase_names.get(phase)}
• 入场: {entry_price:.2f} | 当前: {current_price:.2f}
• 止损: {recommended_stop:.2f} | 浮盈: {pnl:+.2f}U

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
                                   last_1h_dir: int, last_30m_dir: int) -> TradeResult:
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
                is_long=(reverse_direction == "long")
            )
            
            # 构建过滤条件信息 - 显示真实数据
            h1_st_color = "🟢绿" if last_1h_dir == 1 else "🔴红"
            h30m_st_color = "🟢绿" if last_30m_dir == 1 else "🔴红"
            
            if reverse_direction == "long":
                filter_info = (
                    f"【反手开多条件检查】\n"
                    f"• 1H ST: {h1_st_color} ✅\n"
                    f"• 1H收盘 {last_1h_close:.2f} > DEMA {last_1h_dema:.2f} ✅\n"
                    f"• 30m ST: {h30m_st_color} ✅\n"
                )
            else:
                filter_info = (
                    f"【反手开空条件检查】\n"
                    f"• 1H ST: {h1_st_color} ✅\n"
                    f"• 1H收盘 {last_1h_close:.2f} < DEMA {last_1h_dema:.2f} ✅\n"
                    f"• 30m ST: {h30m_st_color} ✅\n"
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
