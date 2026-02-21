"""
ETH 趋势交易系统配置
V9.6-Exec SOP
"""

import os

# ============ Gate.io API ============
GATE_API_KEY = os.environ.get("GATE_API_KEY", "")
GATE_API_SECRET = os.environ.get("GATE_API_SECRET", "")

# ============ 交易对配置 ============
SYMBOL = "ETH_USDT"
CONTRACT = "ETH_USDT"  # 永续合约

# ============ 指标参数 ============
SUPERTREND_PERIOD = 10
SUPERTREND_MULTIPLIER = 3.0
DEMA_PERIOD = 200

# ============ 杠杆 ============
LEVERAGE = 10

# ============ 风控模式 ============
# 模式: "fixed" = 固定金额, "percent" = 账户百分比
RISK_MODE = os.environ.get("RISK_MODE", "fixed")

# 固定模式: 单笔风险固定金额 (USDT)
RISK_FIXED_AMOUNT = float(os.environ.get("RISK_FIXED_AMOUNT", "10"))

# 百分比模式: 单笔风险占账户资产的百分比
RISK_PERCENT = float(os.environ.get("RISK_PERCENT", "0.02"))  # 2%

# ============ 熔断规则 ============
# 本金低于此值停止交易
CIRCUIT_BREAKER_EQUITY = 350

# 连续亏损次数熔断
MAX_CONSECUTIVE_LOSSES = 3

# ============ Buffer ============
# 锁利期的保底盈利 (USDT)
# 当止损锁定后，立即触发止损也能赚到这个金额
LOCK_PROFIT_BUFFER = float(os.environ.get("LOCK_PROFIT_BUFFER", "1"))  # 1 USDT

# ============ 状态文件 ============
STATE_FILE = os.environ.get("STATE_FILE", "trading_state.json")

# ============ 自动化交易开关 ============
# 默认关闭（仅发信号，不执行交易），可通过环境变量开启
ENABLE_AUTO_TRADING = os.environ.get("ENABLE_AUTO_TRADING", "false").lower() == "true"

# ============ 交易执行配置 ============
# 开仓时是否设置条件止损单（默认启用）
AUTO_SET_STOP_LOSS = os.environ.get("AUTO_SET_STOP_LOSS", "true").lower() == "true"

# 止损调整模式："tight_only" = 仅止损收紧, "both" = 收紧和放松
STOP_LOSS_MODE = os.environ.get("STOP_LOSS_MODE", "tight_only")

# 平仓模式："market" = 市价, "limit" = 限价
CLOSE_MODE = os.environ.get("CLOSE_MODE", "market")

# Telegram 通知中是否包含详细日志（模拟模式下）
NOTIFY_DETAILS = os.environ.get("NOTIFY_DETAILS", "true").lower() == "true"
# 打开时：发信号并执行交易（开仓、调止损、平仓）
ENABLE_AUTO_TRADING = os.environ.get("ENABLE_AUTO_TRADING", "false").lower() == "true"


def get_risk_amount(equity: float) -> dict:
    """
    根据配置计算单笔风险金额
    
    返回: {
        "amount": 风险金额,
        "mode": "fixed" 或 "percent",
        "status": "normal" / "circuit_breaker"
    }
    """
    # 熔断检查
    if equity <= CIRCUIT_BREAKER_EQUITY:
        return {
            "amount": 0,
            "mode": RISK_MODE,
            "status": "circuit_breaker",
            "message": f"本金 {equity:.2f}U ≤ {CIRCUIT_BREAKER_EQUITY}U，熔断"
        }
    
    if RISK_MODE == "percent":
        amount = equity * RISK_PERCENT
        return {
            "amount": amount,
            "mode": "percent",
            "status": "normal",
            "message": f"账户 {equity:.2f}U × {RISK_PERCENT*100:.1f}% = {amount:.2f}U"
        }
    else:  # fixed
        return {
            "amount": RISK_FIXED_AMOUNT,
            "mode": "fixed",
            "status": "normal",
            "message": f"固定风险 {RISK_FIXED_AMOUNT:.2f}U"
        }
