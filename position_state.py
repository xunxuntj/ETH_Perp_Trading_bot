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
        "long": {"phase": "LOCKED", "stop_loss": 2000.5, "entry_price": 2010.0, "last_update": 1234567890},
        "short": {"phase": "SURVIVAL", "stop_loss": 2100.0, "entry_price": 2090.0, "last_update": 1234567890}
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
                         current_time: float) -> Tuple[bool, str]:
    """
    更新持仓状态，检测是否有变化
    
    返回: (has_change, change_type)
    change_type: "", "stop_updated", "enter_locked", "switch_1h", "phase_changed"
    """
    state = load_position_state()
    
    # 获取前一次的状态
    prev_state = state.get(direction, {})
    
    change_type = ""
    
    # 检查止损是否有变化 (差异超过 0.01)
    if prev_state and abs(prev_state.get('stop_loss', 0) - stop_loss) > 0.01:
        change_type = "stop_updated"
    
    # 检查阶段是否有变化
    prev_phase = prev_state.get('phase', '')
    if prev_phase and prev_phase != phase:
        # 进入锁利期
        if phase == "LOCKED" and prev_phase == "SURVIVAL":
            change_type = "enter_locked"
        # 切换到小时线
        elif phase == "HOURLY" and prev_phase in ["SURVIVAL", "LOCKED"]:
            change_type = "switch_1h"
        else:
            # 其他阶段变化
            change_type = "phase_changed"
    
    # 保存当前状态
    state[direction] = {
        "phase": phase,
        "stop_loss": stop_loss,
        "entry_price": entry_price,
        "last_update": current_time
    }
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
