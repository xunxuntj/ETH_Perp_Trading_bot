"""
持仓状态管理模块
用于跟踪持仓的阶段变化和止损更新，生成相应的通知
"""

import os
import json
from typing import Optional, Tuple
from dataclasses import dataclass


from config import CONTRACT

POSITION_STATE_FILE = "position_state.json" if CONTRACT == "ETH_USDT" else f"position_state_{CONTRACT.lower()}.json"


def get_position_state_filename(contract: str = "ETH_USDT") -> str:
    c_lower = (contract or "ETH_USDT").lower()
    if c_lower == "eth_usdt" and not os.environ.get("POSITION_STATE_FILE"):
        return "position_state.json"
    return os.environ.get("POSITION_STATE_FILE") or f"position_state_{c_lower}.json"


@dataclass
class PositionStateInfo:
    """持仓状态信息"""
    direction: str  # "long" 或 "short"
    phase: str  # "SURVIVAL", "LOCKED", "HOURLY"
    stop_loss: float  # 止损价格
    entry_price: float  # 入场价格
    last_update: float  # 最后更新时间戳


def load_position_state(contract: str = "ETH_USDT") -> dict:
    """
    加载持仓状态文件
    """
    filename = get_position_state_filename(contract)
    if os.path.exists(filename):
        try:
            with open(filename, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"⚠️  加载持仓状态文件失败 ({filename}): {e}")
            return {}
    return {}


def save_position_state(state: dict, contract: str = "ETH_USDT"):
    """保存持仓状态"""
    filename = get_position_state_filename(contract)
    try:
        with open(filename, 'w') as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        print(f"⚠️  保存持仓状态文件失败 ({filename}): {e}")


def update_position_state(direction: str, phase: str, stop_loss: float, entry_price: float, 
                         current_time: float, initial_30m_st: float = 0, 
                         locked_stop_loss: float = 0, contract: str = "ETH_USDT") -> Tuple[bool, str]:
    """
    更新持仓状态，检测是否有变化
    """
    state = load_position_state(contract)
    
    # 获取前一次的状态
    prev_state = state.get(direction, {})
    prev_phase = prev_state.get('phase', '')
    current_phase_upper = str(phase).upper()
    prev_phase_upper = str(prev_phase).upper()
    prev_stop_loss = prev_state.get('stop_loss', 0)
    prev_locked_stop_loss = prev_state.get('locked_stop_loss', 0)
    prev_initial_30m_st = prev_state.get('initial_30m_st', 0)
    
    change_type = ""
    
    # 新持仓：记录初始30m ST
    if not prev_state:
        change_type = "new_position"
    # 检查阶段变化：SURVIVAL → LOCKED
    elif current_phase_upper == "LOCKED" and prev_phase_upper == "SURVIVAL":
        change_type = "enter_locked"
    # 检查阶段变化：LOCKED/SURVIVAL → HOURLY
    elif current_phase_upper == "HOURLY" and prev_phase_upper in ["SURVIVAL", "LOCKED"]:
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
    save_position_state(state, contract=contract)
    
    return (change_type != ""), change_type


def clear_position_state(direction: str, contract: str = "ETH_USDT"):
    """清除指定方向的持仓状态（平仓时调用）"""
    state = load_position_state(contract)
    if direction in state:
        del state[direction]
    save_position_state(state, contract=contract)


def clear_all_position_state(contract: str = "ETH_USDT"):
    """清除所有持仓状态"""
    filename = get_position_state_filename(contract)
    try:
        if os.path.exists(filename):
            os.remove(filename)
    except Exception as e:
        print(f"⚠️  清除持仓状态文件失败 ({filename}): {e}")

