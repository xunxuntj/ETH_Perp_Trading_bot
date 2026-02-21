# 止损调整流程可视化指南

## 🔄 止损调整完整流程图

```
【每 30 分钟执行一次】

                    ┌─────────────────────────────────────────┐
                    │     T[n] 时刻 - 定期分析              │
                    │   (GitHub Actions 每 30min 触发)       │
                    └─────────────────────────────────────────┘
                                      ↓
         ┌────────────────────────────────────────────────────┐
         │ 📥 从 Gate.io API 获取最新数据                      │
         ├────────────────────────────────────────────────────┤
         │ • 获取 1000 根 1H K线   → df_1h                   │
         │ • 获取 1000 根 30m K线  → df_30m                  │
         │ • 获取持仓信息          → position                │
         │ • 获取账户信息          → account                 │
         └────────────────────────────────────────────────────┘
                                      ↓
         ┌────────────────────────────────────────────────────┐
         │ 📊 计算技术指标                                     │
         ├────────────────────────────────────────────────────┤
         │ • SuperTrend(1H)        → st_1h                  │
         │ • SuperTrend(30m)       → st_30m                 │
         │ • DEMA200(1H)           → dema_1h                │
         └────────────────────────────────────────────────────┘
                                      ↓
         ┌────────────────────────────────────────────────────┐
         │ 🔍 检查持仓状态                                     │
         ├────────────────────────────────────────────────────┤
         │   has_position = API 查询持仓是否存在             │
         │                                                   │
         │   是 → 分为两路:                                 │
         │   ├─ 多仓? → _manage_long_position()          │
         │   └─ 空仓? → _manage_short_position()         │
         │                                                   │
         │   否 → 检查开仓条件 → 无持仓处理                  │
         └────────────────────────────────────────────────────┘
                                      ↓
                          多仓分支 / 空仓分支
                                      ↓
     ┌──────────────────────────────────────────────────────┐
     │ 🎯【第一步】_infer_phase() - 推导阶段和止损         │
     ├──────────────────────────────────────────────────────┤
     │                                                      │
     │  输入: entry_price, current_price, qty,             │
     │       last_30m_st, last_1h_st, is_long              │
     │                                                      │
     │  过程:                                              │
     │   1️⃣  计算浮盈 pnl                                 │
     │   2️⃣  计算锁利阈值 lock_threshold                  │
     │   3️⃣  判断阶段：                                   │
     │       if pnl < 1U:                                 │
     │           phase = "SURVIVAL"                       │
     │           recommended_stop = last_30m_st  ← 30m托管 │
     │       elif 1H ST > lock_threshold:                 │
     │           phase = "HOURLY"                         │
     │           recommended_stop = last_1h_st  ← 1H托管  │
     │       else:                                         │
     │           phase = "LOCKED"                         │
     │           recommended_stop = last_30m_st  ← 锁定   │
     │                                                      │
     │  输出: (phase, recommended_stop)                    │
     │                                                      │
     └──────────────────────────────────────────────────────┘
                                      ↓
     ┌──────────────────────────────────────────────────────┐
     │ ⚠️【第二步】检查离场条件                             │
     ├──────────────────────────────────────────────────────┤
     │  if (phase==HOURLY and ST变色) or                  │
     │     (phase in [SURVIVAL,LOCKED] and 30mST变色):    │
     │                                                      │
     │     exit_signal = True                             │
     │     → 调用 _close_with_reverse_check()  ← 平仓!   │
     │     → 返回平仓信号，结束                           │
     │                                                      │
     │  else:                                              │
     │     → 继续到第三步                                 │
     │                                                      │
     └──────────────────────────────────────────────────────┘
                                      ↓
     ┌──────────────────────────────────────────────────────┐
     │ 🔎【第三步】update_position_state() - 检测变化     │
     ├──────────────────────────────────────────────────────┤
     │                                                      │
     │  输入: direction, phase, stop_loss(=recommended_stop)│
     │                                                      │
     │  过程:                                              │
     │   1️⃣  从 position_state.json 读取前一次状态        │
     │       prev_stop_loss = prev_state['stop_loss']    │
     │                                                      │
     │   2️⃣  【关键检查】止损是否变化:                     │
     │       delta = |prev_stop_loss - recommended_stop|  │
     │                                                      │
     │       if delta > 0.01 USDT:                        │
     │           ✓ 检测到止损调整!                       │
     │           change_type = "stop_updated"            │
     │       else:                                         │
     │           change_type = ""                         │
     │                                                      │
     │   3️⃣  【优先检查】阶段是否变化 (优先级更高):       │
     │       if prev_phase != phase:                      │
     │           if phase=="LOCKED" and prev=="SURVIVAL":│
     │               change_type = "enter_locked"         │
     │           elif phase=="HOURLY":                    │
     │               change_type = "switch_1h"           │
     │                                                      │
     │   4️⃣  写回目标位置 position_state.json            │
     │       state[direction] = {                         │
     │           "phase": phase,                          │
     │           "stop_loss": recommended_stop,           │
     │           "entry_price": entry_price,              │
     │           "last_update": current_time              │
     │       }                                             │
     │                                                      │
     │  返回: (has_change, change_type)                   │
     │         其中 change_type 可能是:                    │
     │         • "stop_updated"     ← 止损调整             │
     │         • "enter_locked"     ← 进入锁利期           │
     │         • "switch_1h"        ← 切换至 1H 轨        │
     │         • "phase_changed"    ← 其他阶段变化         │
     │         • ""                 ← 无变化              │
     │                                                      │
     └──────────────────────────────────────────────────────┘
                                      ↓
     ┌──────────────────────────────────────────────────────┐
     │ 📤【第四步】根据 change_type 返回信号              │
     ├──────────────────────────────────────────────────────┤
     │                                                      │
     │  if change_type == "stop_updated":                │
     │      action = "stop_updated"  ✅ 止损已调整         │
     │      message = "⚠️  止损已调整\n..."               │
     │                                                      │
     │  elif change_type == "enter_locked":              │
     │      action = "enter_locked"  🟡 进入锁利期         │
     │      message = "🟡 已进入锁利期\n..."              │
     │                                                      │
     │  elif change_type == "switch_1h":                │
     │      action = "switch_1h"  🟣 切换至 1H 轨         │
     │      message = "🟣 已切换至小时线轨道\n..."        │
     │                                                      │
     │  else:                                              │
     │      action = "hold"  ✅ 继续持仓                  │
     │      message = "✅ 持仓中\n..."                    │
     │                                                      │
     │  返回 TradeResult(action, message, details)        │
     │                                                      │
     └──────────────────────────────────────────────────────┘
                                      ↓
                    ┌─────────────────────────────────────┐
                    │ 📨 推送信号 (Telegram + 日志)      │
                    │                                     │
                    │ action="stop_updated" → 发出通知   │
                    │ action="hold" → 日志记录            │
                    └─────────────────────────────────────┘
```

---

## 📍 代码位置导航图

```
strategy.py
│
├── 【第1步】_infer_phase() ...................... L156-196
│   ├── 计算浮盈  pnl
│   ├── 计算锁利阈值  lock_threshold
│   └── 推导阶段 + 建议止损
│       ├── 🔵 生存期:   recommended_stop = 30m ST
│       ├── 🟡 锁利期:   recommended_stop = 30m ST (锁定)
│       └── 🟣 换轨期:   recommended_stop = 1H ST
│
├── 【第2/3/4步】_manage_long_position() ....... L551-665
│   ├── 调用 _infer_phase() 
│   ├── 检查离场条件
│   ├── 调用 update_position_state()
│   │   └─ position_state.py#L52-92
│   │      ├── 读取 prev_stop_loss
│   │      ├── 对比 |prev - current| > 0.01?
│   │      ├── 检查阶段变化
│   │      └── 写入 position_state.json
│   │
│   └── 返回 TradeResult
│       ├── action="stop_updated"   (止损调整) ← 核心!
│       ├── action="enter_locked"   (进入锁利期)
│       ├── action="switch_1h"      (切换 1H 轨)
│       └── action="hold"           (继续持仓)
│
├── 【第2/3/4步】_manage_short_position() ...... L677-765
│   └── 空仓逻辑 (对称)
│
├── analyze() ................................. L219-535
│   ├── 获取 API 数据
│   ├── 计算技术指标
│   ├── 检查持仓
│   ├── 调用 _manage_long_position() 或 _manage_short_position()
│   └── 返回最终信号
│
└── _close_with_reverse_check() ................ L826-895
    ├── 检查反手条件
    ├── 调用 clear_position_state()
    └── 返回平仓信号

position_state.json (缓存文件)
│
└── 存储格式:
    {
      "long": {
        "phase": "HOURLY",
        "stop_loss": 2015.00        ← 上一次的止损
        "entry_price": 2000.00,
        "last_update": 1708462800
      }
    }
```

---

## 🎯 止损调整的触发条件详解

### 触发条件检查表

| 条件 | 代码位置 | 检查方式 | 例子 |
|------|---------|---------|------|
| **止损 > 0.01** | [position_state.py#L69](position_state.py#L69) | `abs(prev - current) > 0.01` | 从 1990 → 1991 触发 ✓ |
| **浮盈 < 1U → ≥ 1U** | [position_state.py#L72-77](position_state.py#L72-L77) | 相邻两次阶段的变化 | SURVIVAL → LOCKED 触发 ✓ |
| **1H ST 更紧** | [position_state.py#L75-77](position_state.py#L75-L77) | 阶段变化为 HOURLY | LOCKED → HOURLY 触发 ✓ |

### 优先级规则

```
if 止损有变化 (delta > 0.01):
    change_type = "stop_updated"
    
if 阶段有变化:  ← 【优先级更高】
    if SURVIVAL → LOCKED:
        change_type = "enter_locked"  ← 覆盖 stop_updated
    elif * → HOURLY:
        change_type = "switch_1h"     ← 覆盖 stop_updated
```

**原因:** 阶段变化包含更多信息，应该优先返回

---

## 📊 实际执行时的数据流

### 示例数据链路

```
【T4 时刻】
API 查询返回:
{
  "position": {"entry_price": 2000, "size": 1, ...},
  "price": 2020,
  "st_1h": 2012,
  "st_30m": 1998,
  "st_1h_dir": 1,
  "st_30m_dir": 1
}

↓ 进入 _manage_long_position()

_infer_phase(2000, 2020, 1, 1998, 2012, is_long=True):
  pnl = (2020 - 2000) * 1 * 0.1 = 200 > 1  ✓ 不是生存期
  lock_threshold = 2000 + 1/0.1 = 2010
  is_1h_tighter(2012, 2010, True):
    return 2012 > 2010 = True ✓ 1H ST 更紧!
  → phase="HOURLY", recommended_stop=2012
  
↓ 不是离场信号 (ST 未变色)

update_position_state("long", "HOURLY", 2012, 2000, t4):
  prev_state = {"phase":"LOCKED", "stop_loss":1995, ...}
  
  abs(1995 - 2012) = 17 > 0.01  ✓ 止损调整!
  change_type = "stop_updated"
  
  但是: prev_phase="LOCKED" != phase="HOURLY"
  且 phase=="HOURLY" and prev_phase in ["SURVIVAL","LOCKED"]
  → change_type = "switch_1h"  ← 优先!
  
  写入 position_state.json:
  state["long"] = {"phase":"HOURLY", "stop_loss":2012, ...}

↓ 返回信号

if change_type == "switch_1h":
  action = "switch_1h"
  
  message = """🟣 已切换至小时线轨道
  • 方向: 多 | 阶段: 🟣 换轨期
  • 入场: 2000.00 | 当前: 2020.00
  • 止损: 2012.00 | 浮盈: +200.00U
  • 说明: 1H ST已转向上升，以 1H ST 作为止损参考"""
  
  details = {"phase":"HOURLY", "stop_loss":2012.00, "pnl":200.00}

↓ 推送 Telegram (+ 日志)

【信号已发出】
```

---

## 🔬 调试命令速查

### 查看实时止损状态

**方法1: 查看日志**
```bash
export DEBUG=1
python main.py 2>&1 | grep -E "stop|STRATEGY"
```

**输出示例:**
```
[STRATEGY DEBUG] _infer_phase: pnl=200.00, lock_threshold=2010.00, last_1h_st=2012.00
[STRATEGY DEBUG] inferred phase=hourly, recommended_stop=2012.00
⚠️  止损已调整
• 方向: 多 | 阶段: 🟣 换轨期
• 新止损: 2012.00 | 浮盈: +200.00U
```

**方法2: 查看缓存文件**
```bash
cat position_state.json | jq .
```

**输出示例:**
```json
{
  "long": {
    "phase": "HOURLY",
    "stop_loss": 2012.0,
    "entry_price": 2000.0,
    "last_update": 1708462800.123
  }
}
```

**方法3: 实时 grep 止损调整**
```bash
python main.py 2>&1 | grep "stop_updated\|止损已调整"
```

---

## ⚙️ 参数调优指南

### 止损容差值 (Tolerance)

**当前值:** 0.01 USDT

```python
# position_state.py#L69
if abs(prev_stop_loss - recommended_stop) > 0.01:  ← 阈值
    change_type = "stop_updated"
```

**调整建议:**

| 容差值 | 特点 | 适用场景 |
|---------|------|---------|
| **0.01** | 频繁触发 | 小资金账户、高频交易 |
| **0.1** | 中等触发 | 普通账户 (推荐) |
| **0.5** | 低频触发 | 大资金账户、减少干扰 |
| **1.0** | 很低频 | 极高稳定性需求 |

**修改方式:**
```python
# position_state.py L69
if abs(prev_state.get('stop_loss', 0) - stop_loss) > 0.1:  # 改为 0.1
    change_type = "stop_updated"
```

---

## 🎓 总结：三个关键实现

| 关键实现 | 位置 | 作用 |
|---------|------|------|
| **1. 推导止损** | `_infer_phase()` | 根据阶段计算 recommended_stop |
| **2. 检测变化** | `update_position_state()` | 对比前后止损，差异 > 0.01 |
| **3. 返回信号** | `if change_type == "stop_updated"` | 返回 action="stop_updated" |

**组合起来:**
```python
recommended_stop = _infer_phase(...)        # 第1步
has_change, change_type = update_position_state(  # 第2步
    direction, phase, recommended_stop, ...
)
if change_type == "stop_updated":           # 第3步
    return TradeResult(action="stop_updated", ...)
```

这就是整个止损收紧机制的完整实现！
