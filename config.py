"""
ETH 趋势交易系统配置
V9.6-Exec SOP
"""

import os

# ============ Gate.io API ============
GATE_API_KEY = os.environ.get("GATE_API_KEY", "")
GATE_API_SECRET = os.environ.get("GATE_API_SECRET", "")

# ============ 交易对配置 ============
import sys
is_testing = any(m in sys.modules for m in ('pytest', 'unittest')) or 'PYTEST_CURRENT_TEST' in os.environ
default_symbol = "ETH_USDT" if is_testing else "SOL_USDT"
SYMBOL = os.environ.get("SYMBOL", default_symbol)
CONTRACT = os.environ.get("CONTRACT", SYMBOL)  # 永续合约

# 合约面值 (不同币种面值不同，可根据 CONTRACT 自动匹配默认值，或通过环境变量覆盖)
def _get_default_face_value(contract: str) -> float:
    c_upper = (contract or "").upper()
    if "ETH" in c_upper:
        return 0.01
    elif "BTC" in c_upper:
        return 0.0001
    elif "SOL" in c_upper:
        return 1.0
    elif "DOGE" in c_upper:
        return 10.0
    return 0.01

def get_face_value(contract: str) -> float:
    """Resolve face value dynamically per contract (env FACE_VALUE overrides)."""
    if os.environ.get("FACE_VALUE"):
        return float(os.environ["FACE_VALUE"])
    return _get_default_face_value(contract)

def get_default_tick_size(contract: str) -> float:
    """Fallback tick size per contract when exchange metadata API is unavailable."""
    c_upper = (contract or "").upper()
    if "BTC" in c_upper:
        return 0.1
    elif "DOGE" in c_upper:
        return 0.00005
    return 0.01

_default_fv = _get_default_face_value(CONTRACT)
FACE_VALUE = float(os.environ.get("FACE_VALUE", str(_default_fv)))

# ============ Post-ETF 机构化多资产组合配置 ============
PORTFOLIO_BASKET = ["BTC_USDT", "ETH_USDT", "SOL_USDT", "DOGE_USDT"]
PORTFOLIO_WEIGHTS = {
    "BTC_USDT": 0.35,
    "ETH_USDT": 0.30,
    "SOL_USDT": 0.25,
    "DOGE_USDT": 0.10
}
APPLY_PORTFOLIO_WEIGHTS = os.environ.get("APPLY_PORTFOLIO_WEIGHTS", "true").lower() == "true"

def get_portfolio_weight(contract: str) -> float:
    """Return portfolio allocation weight for a contract (defaults to 1.0 if disabled or unknown)."""
    if not APPLY_PORTFOLIO_WEIGHTS or not contract:
        return 1.0
    return float(PORTFOLIO_WEIGHTS.get(contract.upper(), 1.0))


# ============ 指标参数 ============
SUPERTREND_PERIOD = 10
SUPERTREND_MULTIPLIER = 3.0

def _get_default_dema_period(contract: str) -> int:
    c_upper = (contract or "").upper()
    if "ETH" in c_upper:
        return 150
    return 200  # BTC and others default to 200

def get_dema_period(contract: str) -> int:
    if os.environ.get("DEMA_PERIOD"):
        return int(os.environ["DEMA_PERIOD"])
    return _get_default_dema_period(contract)

DEMA_PERIOD = int(os.environ.get("DEMA_PERIOD", str(_get_default_dema_period(CONTRACT))))

def _get_default_tp_ratio(contract: str) -> float:
    # Aligned with V1 Post-ETF Trading Card: unified 5.0R initial take profit
    return 5.0

def get_tp_ratio(contract: str) -> float:
    if os.environ.get("TP_RATIO"):
        return float(os.environ["TP_RATIO"])
    return _get_default_tp_ratio(contract)

TP_RATIO = float(os.environ.get("TP_RATIO", str(_get_default_tp_ratio(CONTRACT))))

# ============ ADX 信号过滤配置 ============
# Aligned with V1 Post-ETF Trading Card: disabled by default (can be enabled via env USE_ADX=true)
USE_ADX = os.environ.get("USE_ADX", "false").lower() == "true"
ADX_LENGTH = int(os.environ.get("ADX_LENGTH", "16"))

def _get_default_adx_threshold(contract: str) -> float:
    c_upper = (contract or "").upper()
    if "BTC" in c_upper:
        return 45.0
    elif "ETH" in c_upper:
        return 40.0
    return 40.0

def get_adx_threshold(contract: str) -> float:
    if os.environ.get("ADX_THRESHOLD"):
        return float(os.environ["ADX_THRESHOLD"])
    return _get_default_adx_threshold(contract)

ADX_THRESHOLD = float(os.environ.get("ADX_THRESHOLD", str(_get_default_adx_threshold(CONTRACT))))
# ADX Timeframe: 选项 30min / 1H, 默认 30M -> 映射为 "30m" / "1h"
_adx_tf_raw = os.environ.get("ADX_TIMEFRAME", "30M").upper()
if _adx_tf_raw in ("30MIN", "30M"):
    ADX_TIMEFRAME = "30m"
else:
    ADX_TIMEFRAME = "1h"

# ============ 杠杆 ============
LEVERAGE = 10

# ============ 风控模式 ============
# 模式: "fixed" = 固定金额, "percent" = 账户百分比
RISK_MODE = os.environ.get("RISK_MODE", "fixed")

# 固定模式: 全组合单笔风险预算 (USDT，按权重拆分给各标的)
RISK_FIXED_AMOUNT = float(os.environ.get("RISK_FIXED_AMOUNT", "5"))

# 百分比模式: 单笔风险占账户资产的百分比 (按权重拆分给各标的，默认对齐交易卡片 0.8%)
RISK_PERCENT = float(os.environ.get("RISK_PERCENT", "0.008"))  # 0.8%

# 开仓与组合保证金防呆上限
# 最小止损距离占当前价格的比例（防止未收盘K线反穿30m ST或极窄止损导致张数失控）
MIN_SL_DISTANCE_PCT = float(os.environ.get("MIN_SL_DISTANCE_PCT", "0.002"))  # 0.2%
# 单笔开仓最大保证金占账户权益比例（10x杠杆下 0.30 等价于单笔名义价值 <= 3.0x 权益）
MAX_SINGLE_MARGIN_RATIO = float(os.environ.get("MAX_SINGLE_MARGIN_RATIO", "0.30"))
# 组合总占用保证金上限（防止多币同向满仓时 IMR 逼近 100%）
MAX_TOTAL_MARGIN_RATIO = float(os.environ.get("MAX_TOTAL_MARGIN_RATIO", "0.60"))

# ============ 熔断规则 ============
# 本金低于此值停止交易
CIRCUIT_BREAKER_EQUITY = float(os.environ.get("CIRCUIT_BREAKER_EQUITY", "450"))

# 连续亏损次数熔断
MAX_CONSECUTIVE_LOSSES = int(os.environ.get("MAX_CONSECUTIVE_LOSSES", "3"))

# ============ Buffer ============
# 锁利期的保底盈利 (USDT)
# 当止损锁定后，立即触发止损也能赚到这个金额
LOCK_PROFIT_BUFFER = float(os.environ.get("LOCK_PROFIT_BUFFER", "0.5"))  # 0.5 USDT

# ============ 报告统计初始时间 ============
# 启用自动交易的初始时间，精确到小时 (东八区 UTC+8)
REPORT_START_TIME = os.environ.get("REPORT_START_TIME", "2026-07-29 11:00")









# ============ 状态文件 ============
if CONTRACT == "ETH_USDT" and not os.environ.get("STATE_FILE"):
    STATE_FILE = "trading_state.json"
else:
    STATE_FILE = os.environ.get("STATE_FILE", f"trading_state_{CONTRACT.lower()}.json")

# ============ 自动化交易开关 ============
# 默认关闭（仅发信号，不执行交易），可通过环境变量开启
class DynamicBoolean:
    def __bool__(self):
        import os
        return os.environ.get("ENABLE_AUTO_TRADING", "false").lower() == "true"
    
    def __eq__(self, other):
        if isinstance(other, DynamicBoolean):
            return bool(self) == bool(other)
        return bool(self) == other
        
    def __ne__(self, other):
        return not self.__eq__(other)
        
    def __repr__(self):
        return str(bool(self))
        
    def __str__(self):
        return str(bool(self))

ENABLE_AUTO_TRADING = DynamicBoolean()

# ============ 交易执行配置 ============
# 开仓时是否设置条件止损单（默认启用）
AUTO_SET_STOP_LOSS = os.environ.get("AUTO_SET_STOP_LOSS", "true").lower() == "true"

# 止损调整模式："tight_only" = 仅止损收紧, "both" = 收紧和放松
STOP_LOSS_MODE = os.environ.get("STOP_LOSS_MODE", "tight_only")

# 平仓模式："market" = 市价, "limit" = 限价
CLOSE_MODE = os.environ.get("CLOSE_MODE", "market")

# Telegram 通知中是否包含详细日志（模拟模式下）
NOTIFY_DETAILS = os.environ.get("NOTIFY_DETAILS", "true").lower() == "true"

# 交易信号通知模式："all" = 所有信号都发送, "operation" = 仅当有操作时发送, "report" = 只发送每日报告 (不发信号)
SIGNAL_NOTIFY_MODE = os.environ.get("SIGNAL_NOTIFY_MODE", "operation").lower()


def get_risk_amount(equity: float, contract: str = None) -> dict:
    """
    Calculate per-trade risk budget (USDT) with optional portfolio weight allocation.
    Supports both 'percent' and 'fixed' modes (Option A: both modes split by PORTFOLIO_WEIGHTS).
    """
    # Hard circuit breaker check
    if equity <= CIRCUIT_BREAKER_EQUITY:
        return {
            "amount": 0,
            "mode": RISK_MODE,
            "status": "circuit_breaker",
            "weight": get_portfolio_weight(contract) if contract else 1.0,
            "allocated_equity": 0.0,
            "message": f"本金 {equity:.2f}U ≤ {CIRCUIT_BREAKER_EQUITY}U，熔断"
        }

    weight = get_portfolio_weight(contract) if contract else 1.0
    allocated_equity = equity * weight

    if RISK_MODE == "percent":
        amount = allocated_equity * RISK_PERCENT
        weight_str = f" × 权重{weight*100:.0f}%" if contract and APPLY_PORTFOLIO_WEIGHTS else ""
        return {
            "amount": amount,
            "mode": "percent",
            "status": "normal",
            "weight": weight,
            "allocated_equity": allocated_equity,
            "message": f"账户 {equity:.2f}U{weight_str} × {RISK_PERCENT*100:.2f}% = {amount:.2f}U"
        }
    else:  # fixed (Option A: total fixed budget split by portfolio weight)
        amount = RISK_FIXED_AMOUNT * weight
        weight_str = f" × 权重{weight*100:.0f}%" if contract and APPLY_PORTFOLIO_WEIGHTS else ""
        return {
            "amount": amount,
            "mode": "fixed",
            "status": "normal",
            "weight": weight,
            "allocated_equity": allocated_equity,
            "message": f"固定风险 {RISK_FIXED_AMOUNT:.2f}U{weight_str} = {amount:.2f}U"
        }
