"""
持仓状态管理模块
用于跟踪持仓的阶段变化和止损更新，生成相应的通知
"""

import os
import json
from typing import Optional, Tuple
from dataclasses import dataclass


POSITION_STATE_FILE = "position_state.json"


@dataclass
class PositionStateInfo:
    """持仓状态信息"""
    direction: str  # "long" 或 "short"
    phase: str  # "SURVIVAL", "LOCKED", "HOURLY"
    stop_loss: float  # 止损价格
    entry_price: float  # 入场价格
    last_update: float  # 最后更新时间戳


def load_position_state() -> dict:
    """
    加载持仓状态文件
    
    格式: {
        "long": {
            "phase": "LOCKED",                # 当前阶段: SURVIVAL/LOCKED/HOURLY
            "stop_loss": 2000.5,              # 当前止损
            "locked_stop_loss": 2024.83,      # 锁利期止损（进入锁利期时的30m ST）
            "entry_price": 2010.0,
            "initial_30m_st": 2031.55,        # 开仓时的初始30m ST（用于判断生存期）
            "last_update": 1234567890
        }
    }
    """
    if os.path.exists(POSITION_STATE_FILE):
        try:
            with open(POSITION_STATE_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"⚠️  加载持仓状态文件失败: {e}")
            return {}
    return {}


def save_position_state(state: dict):
    """保存持仓状态"""
    try:
        with open(POSITION_STATE_FILE, 'w') as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        print(f"⚠️  保存持仓状态文件失败: {e}")


def update_position_state(direction: str, phase: str, stop_loss: float, entry_price: float, 
                         current_time: float, initial_30m_st: float = 0, 
                         locked_stop_loss: float = 0) -> Tuple[bool, str]:
    """
    更新持仓状态，检测是否有变化
    
    参数:
        direction: "long" 或 "short"
        phase: 当前阶段 "SURVIVAL"/"LOCKED"/"HOURLY"
        stop_loss: 当前止损价格
        entry_price: 入场价格
        current_time: 当前时间戳
        initial_30m_st: 初始30m ST（入场时）- 仅在新持仓时需要
        locked_stop_loss: 锁利期止损 - 仅当从SURVIVAL进入LOCKED时需要更新
    
    返回: (has_change, change_type)
    change_type: "", "stop_updated", "enter_locked", "switch_1h", "new_position"
    """
    state = load_position_state()
    
    # 获取前一次的状态
    prev_state = state.get(direction, {})
    prev_phase = prev_state.get('phase', '')
    prev_stop_loss = prev_state.get('stop_loss', 0)
    prev_locked_stop_loss = prev_state.get('locked_stop_loss', 0)
    prev_initial_30m_st = prev_state.get('initial_30m_st', 0)
    
    change_type = ""
    
    # 新持仓：记录初始30m ST
    if not prev_state:
        change_type = "new_position"
    # 检查阶段变化：SURVIVAL → LOCKED
    elif phase == "LOCKED" and prev_phase == "SURVIVAL":
        change_type = "enter_locked"
    # 检查阶段变化：LOCKED/SURVIVAL → HOURLY
    elif phase == "HOURLY" and prev_phase in ["SURVIVAL", "LOCKED"]:
        change_type = "switch_1h"
    # 检查止损是否有变化（差异 > 0.01）
    elif abs(prev_stop_loss - stop_loss) > 0.01:
        change_type = "stop_updated"
    
    # 构建新状态
    new_state = {
        "phase": phase,
        "stop_loss": stop_loss,
        "entry_price": entry_price,
        "last_update": current_time
    }
    
    # 保留或更新 initial_30m_st（仅在新持仓时设置）
    if initial_30m_st > 0:
        new_state["initial_30m_st"] = initial_30m_st
    elif prev_initial_30m_st > 0:
        new_state["initial_30m_st"] = prev_initial_30m_st
    
    # 保留或更新 locked_stop_loss（仅当进入LOCKED或已经在LOCKED时更新）
    if locked_stop_loss > 0:
        new_state["locked_stop_loss"] = locked_stop_loss
    elif prev_locked_stop_loss > 0:
        new_state["locked_stop_loss"] = prev_locked_stop_loss
    
    # 保存当前状态
    state[direction] = new_state
    save_position_state(state)
    
    return (change_type != ""), change_type


def clear_position_state(direction: str):
    """清除指定方向的持仓状态（平仓时调用）"""
    state = load_position_state()
    if direction in state:
        del state[direction]
    save_position_state(state)


def clear_all_position_state():
    """清除所有持仓状态"""
    try:
        if os.path.exists(POSITION_STATE_FILE):
            os.remove(POSITION_STATE_FILE)
    except Exception as e:
        print(f"⚠️  清除持仓状态文件失败: {e}")
