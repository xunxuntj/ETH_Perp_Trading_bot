# 📡 系统架构和 API 参考

## 系统架构图

```
┌──────────────────────────────────────────────────────────────────┐
│                         ETH Trading System V9.6                  │
│                        (完整自动化交易)                          │
└──────────────────────────────────────────────────────────────────┘
                               ↓
                ┌──────────────────────────────┐
                │   main.py (入口脚本)        │
                │ - 初始化 ExecutionFlow      │
                │ - 调用完整流程              │
                │ - 发送通知                  │
                └──────────────────────────────┘
                               ↓
        ┌──────────────────────────────────────────┐
        │   ExecutionFlow (流程控制器)            │
        │ - 协调策略和执行                        │
        │ - 信号到交易的映射                      │
        │ - 状态管理                              │
        └──────────────────────────────────────────┘
               ↙                              ↖
    ┌────────────────────┐      ┌────────────────────┐
    │  strategy.py       │      │ trading_executor   │
    │ (信号分析)        │      │ (交易执行)        │
    │                   │      │                    │
    │ ✓ 开仓信号       │      │ ✓ 开仓            │
    │ ✓ 平仓信号       │      │ ✓ 调整止损        │
    │ ✓ 三阶段管理     │      │ ✓ 平仓            │
    │ ✓ 风控检查       │      │ ✓ 日志记录        │
    └────────────────────┘      └────────────────────┘
               ↓                         ↓
    ┌────────────────────────────────────────┐
    │      gate_client.py (API 客户端)      │
    │                                        │
    │  读取数据:                            │
    │  ✓ get_candlesticks(K线)             │
    │  ✓ get_positions(持仓)               │
    │  ✓ get_account(账户)                 │
    │                                        │
    │  执行交易:                            │
    │  ✓ create_order(下单)                │
    │  ✓ cancel_orders(取消)               │
    │  ✓ get_orders(查询)                  │
    └────────────────────────────────────────┘
               ↓
    ┌────────────────────┐
    │   Gate.io API      │
    │  (交易所)         │
    └────────────────────┘
               ↓
    ┌────────────────────┐
    │  Telegram API      │
    │  (通知)           │
    └────────────────────┘
```

---

## 核心模块对照表

| 模块 | 类/方法 | 功能 |
|------|--------|------|
| **strategy.py** | `TradingStrategy.analyze()` | 完整策略分析 |
| | `_infer_phase()` | 推导持仓阶段 |
| | `_manage_long_position()` | 多仓管理 |
| | `_manage_short_position()` | 空仓管理 |
| **trading_executor.py** | `TradeExecutor.open_long()` | 开多仓 |
| | `TradeExecutor.open_short()` | 开空仓 |
| | `TradeExecutor.adjust_stop_loss()` | 调整止损 |
| | `TradeExecutor.close_position()` | 平仓 |
| **execution_flow.py** | `ExecutionFlow.execute_strategy_and_trade()` | 完整流程 |
| | `_execute_by_action()` | 信号到交易映射 |
| **gate_client.py** | `GateClient.create_order()` | 下单 |
| | `GateClient.cancel_orders()` | 取消订单 |
| | `GateClient.get_candlesticks()` | 获取K线 |
| | `GateClient.get_positions()` | 获取持仓 |

---

## 数据流向图

### 开仓流程

```
分析信号
  ├─ 获取 1H K线 (1000根)
  ├─ 获取 30m K线 (1000根)
  ├─ 计算 ST 和 DEMA
  ├─ 过滤条件 (3重)
  │  ├─ 1H ST 颜色
  │  ├─ 1H 收盘价 vs DEMA
  │  └─ 30m ST 颜色
  ├─ 判断: 可以开多吗?
  │  └─ YES → 返回 open_long 信号
  └─ 执行开仓
     ├─ 下市价单 (数量 = 风险 / 止损距离)
     ├─ 设置止损条件单
     ├─ 记录日志
     └─ 推送通知
```

### 持仓管理流程

```
检测持仓变化
  ├─ 推导当前阶段
  │  ├─ 计算浮盈
  │  ├─ 对比锁利阈值
  │  └─ 确定: 生存期/锁利期/换轨期
  ├─ 检查离场条件
  │  ├─ 生存/锁利期: 30m ST 变色?
  │  └─ 换轨期: 1H ST 变色?
  ├─ 调整止损
  │  ├─ 计算新止损
  │  ├─ 验证方向 (仅收紧)
  │  ├─ 取消旧单
  │  └─ 创建新单
  └─ 返回: stop_updated / 或无变化
```

### 平仓流程

```
平仓信号
  ├─ 获取当前持仓
  ├─ 取消止损单 (防止自动触发)
  ├─ 下平仓单 (市价)
  ├─ 计算已实现盈亏
  ├─ 更新状态 (连续亏损)
  ├─ 检查冷静期触发
  ├─ 推送通知
  └─ 返回完毕
```

---

## API 接口总览

### trading_executor.TradeExecutor

#### `open_long(entry_price, stop_loss, qty)`
**功能:** 开多仓
**参数:**
- `entry_price: float` - 入场价格
- `stop_loss: float` - 止损价格
- `qty: int` - 张数

**返回:**
```python
{
    "success": bool,
    "order_id": str,
    "message": str,
    "details": {
        "order_id": str,
        "qty": int,
        "entry_price": float,
        "stop_loss": float,
        "stop_order_id": str,
        "dry_run": bool
    }
}
```

#### `open_short(entry_price, stop_loss, qty)`
**功能:** 开空仓（参数和返回同 `open_long`）

#### `adjust_stop_loss(direction, new_stop, qty, old_stop=None)`
**功能:** 调整止损
**参数:**
- `direction: str` - "long" / "short"
- `new_stop: float` - 新止损价格
- `qty: int` - 持仓张数
- `old_stop: float` - 旧止损价格（用于验证）

**返回:**
```python
{
    "success": bool,
    "message": str,
    "details": {
        "direction": str,
        "old_stop": float,
        "new_stop": float,
        "qty": int,
        "order_id": str
    }
}
```

#### `close_position(direction, qty, pnl=None, reason="signal")`
**功能:** 平仓
**参数:**
- `direction: str` - "long" / "short"
- `qty: int` - 张数
- `pnl: float` - 盈亏（可选）
- `reason: str` - 平仓原因标签

**返回:**
```python
{
    "success": bool,
    "order_id": str,
    "message": str,
    "details": {
        "order_id": str,
        "direction": str,
        "qty": int,
        "pnl": float,
        "reason": str,
        "dry_run": bool
    }
}
```

---

### gate_client.GateClient

#### `create_order(contract, size, price=None, reduce_only=False, text="")`
**功能:** 下单
**参数:**
- `contract: str` - 交易对（如 "ETH_USDT"）
- `size: int` - 数量（正=多, 负=空）
- `price: float` - 价格（None=市价）
- `reduce_only: bool` - 仅减仓
- `text: str` - 订单备注

**返回:** Gate.io API 返回的订单信息

#### `cancel_orders(contract, side=None, text="")`
**功能:** 取消订单
**参数:**
- `contract: str` - 交易对
- `side: str` - "buy"/"sell"/None
- `text: str` - 订单备注（过滤）

**返回:** 取消的订单列表

#### `get_orders(contract, status="open", limit=100)`
**功能:** 获取订单列表
**参数:**
- `contract: str` - 交易对
- `status: str` - "open"/"finished"
- `limit: int` - 限制数量

**返回:** 订单列表

#### `get_positions(contract)`
**功能:** 获取持仓
**返回:**
```python
{
    'size': int,              # 正=多, 负=空
    'entry_price': float,
    'mark_price': float,
    'liq_price': float,       # 清算价
    'unrealised_pnl': float,
    'leverage': int,
    'margin': float
}
```

#### `get_account()`
**功能:** 获取账户信息
**返回:**
```python
{
    'total': float,           # 本金
    'available': float,       # 可用
    'unrealised_pnl': float   # 未实现盈亏
}
```

#### `get_candlesticks(contract, interval="30m", limit=300)`
**功能:** 获取K线
**参数:**
- `contract: str` - 交易对
- `interval: str` - "1m", "5m", "15m", "30m", "1h", "4h", "1d"
- `limit: int` - 数量（最多 1000）

**返回:** pandas DataFrame (时间索引, OHLCV)

#### `get_ticker(contract)`
**功能:** 获取最新价格
**返回:**
```python
{
    'last': float,        # 最新价
    'mark_price': float
}
```

---

### execution_flow.ExecutionFlow

#### `execute_strategy_and_trade()`
**功能:** 执行完整的策略分析和交易流程
**返回:**
```python
{
    "strategy_action": str,           # 信号类型
    "trade_executed": bool,           # 是否执行了交易
    "trade_details": dict,
    "message": str
}
```

**strategy_action 可能的值:**
- `open_long` - 开多
- `open_short` - 开空
- `close` - 平仓
- `close_and_reverse_long` - 平+反手开多
- `close_and_reverse_short` - 平+反手开空
- `reverse_to_long` - 反手建议（开多）
- `reverse_to_short` - 反手建议（开空）
- `stop_updated` - 止损调整
- `enter_locked` - 进入锁利期
- `switch_1h` - 切换到 1H 轨道
- `hold` - 持仓中
- `none` - 无操作
- `circuit_breaker` - 熔断
- `cooldown` - 冷静期
- `error` - 错误

---

## 配置参数详解

### 指标参数

```python
SUPERTREND_PERIOD = 10           # SuperTrend 周期
SUPERTREND_MULTIPLIER = 3.0     # SuperTrend 倍数
DEMA_PERIOD = 200               # DEMA 周期
```

### 风控参数

```python
LEVERAGE = 10                   # 杠杆倍数
LOCK_PROFIT_BUFFER = 1          # 锁利缓冲 (USDT)
CIRCUIT_BREAKER_EQUITY = 350    # 熔断线 (USDT)
MAX_CONSECUTIVE_LOSSES = 3      # 冷静期触发次数
```

### 交易参数

```python
ENABLE_AUTO_TRADING = False     # 自动交易开关
AUTO_SET_STOP_LOSS = True       # 自动设止损
STOP_LOSS_MODE = "tight_only"   # "tight_only" = 仅收紧
CLOSE_MODE = "market"           # "market" = 市价平仓
```

### 风险控制参数

```python
RISK_MODE = "fixed"             # "fixed" 或 "percent"
RISK_FIXED_AMOUNT = 10          # 固定风险 (USDT)
RISK_PERCENT = 0.02             # 百分比风险 (2%)
```

---

## 状态转移图

### 订单状态

```
未开仓
  ↓
[开仓条件满足]
  ↓
发送开仓单 → 市价立即成交
  ↓
[设置止损条件单]
  ↓
已开仓，监控止损
  ├─ 止损被触发 → [平仓]
  ├─ 触发离场信号 → [平仓]
  └─ 继续持仓 → [调整止损或进入下一阶段]
```

### 持仓阶段转移

```
无持仓
  ↓
[开仓信号]
  ↓
生存期 (浮盈 < 1U)
  │ ├─ 止损: 30m ST
  │ ├─ 离场: 30m ST 变色
  │ └─ → 锁利期 (浮盈 ≥ 1U)
  ↓
锁利期 (已锁利, 1H ST ≤ 阈值)
  │ ├─ 止损: 锁定不动
  │ ├─ 离场: 30m ST 变色
  │ └─ → 换轨期 (1H ST 比阈值更紧)
  ↓
换轨期 (1H ST > 阈值 for 多)
  │ ├─ 止损: 1H ST (动态)
  │ ├─ 离场: 1H ST 变色
  │ └─ → 平仓
  ↓
无持仓
```

---

## 日志格式

### execution_log.json

```json
[
  {
    "timestamp": "2026-02-21T23:30:00.123456+00:00",
    "action": "OPEN_LONG",
    "message": "✅ [模拟] 开多 1张 @ 2000.00",
    "details": {
      "order_id": "sim_long_1234567890",
      "qty": 1,
      "entry_price": 2000.00,
      "stop_loss": 1995.00,
      "stop_order_id": "sim_stop_1234567891",
      "dry_run": true
    }
  },
  {
    "timestamp": "2026-02-21T23:35:00.234567+00:00",
    "action": "ADJUST_STOP",
    "message": "✅ [模拟] 多仓止损调整 1995.00 → 2002.00",
    "details": {
      "direction": "long",
      "old_stop": 1995.00,
      "new_stop": 2002.00,
      "qty": 1,
      "dry_run": true
    }
  },
  {
    "timestamp": "2026-02-21T23:40:00.345678+00:00",
    "action": "CLOSE",
    "message": "✅ [模拟] 平多 1张 盈亏 +50.00U",
    "details": {
      "order_id": "sim_close_1234567892",
      "direction": "long",
      "qty": 1,
      "pnl": 50.00,
      "reason": "signal",
      "dry_run": true
    }
  }
]
```

---

## 错误处理

### 常见异常

| 异常 | 原因 | 处理 |
|------|------|------|
| 401 Unauthorized | API Key/Secret 错误 | 检查凭证 |
| 429 Too Many Requests | 请求过于频繁 | 降低频率/重试 |
| 500 Server Error | 交易所服务器问题 | 等待刷新/重试 |
| Network Timeout | 网络连接超时 | 检查网络/重试 |
| Invalid Order | 订单参数错误 | 检查参数 |
| Insufficient Margin | 保证金不足 | 降低风险额度 |

### 异常处理流程

```
执行操作
  ↓
[异常捕获]
  ↓
记录日志
  ↓
发送告警
  ↓
继续监控或者停止
```

---

## 性能优化建议

### 数据查询优化
- K 线缓存: 使用 1000 根 K 线，减少 API 调用
- 批量查询: 一次获取 1H 和 30m 数据
- 异步执行: 使用 asyncio 并发调用

### 交易执行优化
- 市价执行: 市价单立即成交，减少滑点
- 条件止损: 使用交易所条件单，自动执行
- 批量操作: 同时创建开仓和止损单

### 成本优化
- 手续费: 使用 Maker 订单降低成本
- 杠杆: 合理使用 10 倍杠杆
- 频率: 30 分钟执行一次，减少 API 调用

---

**文档更新:** 2026-02-21
