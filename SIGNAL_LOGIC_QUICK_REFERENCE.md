# V9.6 策略快速参考卡

## 🎯 核心信号规则（快速查询）

### 开仓条件（3 重过滤）
```
【开多】
✓ 1H ST 绿 (direction = 1)
✓ 1H 收盘 > 1H DEMA200
✓ 30m ST 绿 (direction = 1)

【开空】
✓ 1H ST 红 (direction = -1)
✓ 1H 收盘 < 1H DEMA200
✓ 30m ST 红 (direction = -1)
```

**代码位置:** [strategy.py L332-346](strategy.py#L332-L346)

---

## 📊 持仓管理三阶段动态切换

```
┌─────────────────────────────────────────┐
│ 入场                                     │
│ 浮盈 < 1U BUFFER                        │
└─────────────────────────────────────────┘
           ↓
    ┌──────────────┐
    │ 🔵 生存期     │
    ├──────────────┤
    │ 止损源:30m ST │
    │ 只紧不松     │
    └──────────────┘
           ↓
    ┌─────────────────────────────────┐
    │ 浮盈 ≥ 1U 且 1H ST 不够紧       │
    └─────────────────────────────────┘
           ↓
    ┌──────────────┐
    │ 🟡 锁利期     │
    ├──────────────┤
    │ 止损源:锁定  │
    │ (entry ± 1/pos) │
    └──────────────┘
           ↓
    ┌─────────────────────────────────┐
    │ 1H ST 比锁利阈值更紧           │
    └─────────────────────────────────┘
           ↓
    ┌──────────────┐
    │ 🟣 换轨期     │
    ├──────────────┤
    │ 止损源:1H ST │
    │ 只紧不松     │
    └──────────────┘
           ↓
    ┌─────────────────────────────────┐
    │ 1H ST 变色 → 平仓              │
    └─────────────────────────────────┘
```

**代码位置:** [strategy.py L164-192](strategy.py#L164-L192) (_infer_phase)

---

## 🛑 离场条件

| 阶段 | 方向 | 离场信号 |
|------|------|----------|
| **生存期** | 多 | 30m ST 变红 |
| **生存期** | 空 | 30m ST 变绿 |
| **锁利期** | 多 | 30m ST 变红 |
| **锁利期** | 空 | 30m ST 变绿 |
| **换轨期** | 多 | 1H ST 变红 |
| **换轨期** | 空 | 1H ST 变绿 |

**代码位置:** 
- [strategy.py L545-551](strategy.py#L545-L551) (多仓)
- [strategy.py L688-694](strategy.py#L688-L694) (空仓)

---

## 💰 仓位计算公式

```
第1步：计算止损距离
  sl_distance = |entry_price - stop_loss|

第2步：计算开仓张数（向下取整）
  qty = floor(risk_amount / sl_distance / FACE_VALUE)
  
  其中：
    risk_amount = 风险金额 (10U 固定 或 账户 × 2%)
    FACE_VALUE = 0.1 (每张对应 0.1 ETH)

第3步：计算相关指标
  position_eth = qty × FACE_VALUE
  position_value = position_eth × entry_price
  margin_required = position_value / LEVERAGE  (10x)
  actual_risk = qty × FACE_VALUE × sl_distance = risk_amount
```

**代码位置:** [strategy.py L119-135](strategy.py#L119-L135)

---

## 🔒 锁利阈值计算

```
【多仓】
  锁利阈值 = 入场价 + BUFFER / 仓位(ETH)
  
【空仓】
  锁利阈值 = 入场价 - BUFFER / 仓位(ETH)

其中 BUFFER = 1 USDT (可配置)
```

**示例：**
```
多仓例: 入场 2000, 使用 1 张 (0.1 ETH), BUFFER=1
  锁利阈值 = 2000 + 1/0.1 = 2000 + 10 = 2010
  含义: 只要止损达到 2010，平仓时至少赚 1U

空仓例: 入场 2000, 使用 1 张 (0.1 ETH), BUFFER=1
  锁利阈值 = 2000 - 1/0.1 = 2000 - 10 = 1990
  含义: 只要止损达到 1990，平仓时至少赚 1U
```

**代码位置:** [strategy.py L83-93](strategy.py#L83-L93)

---

## 🔍 1H ST "更紧"判断逻辑

```
【多仓】
  1H ST 更紧 = last_1h_st > lock_threshold
  含义: 1H ST 比锁利阈值更高（向上突破）

【空仓】
  1H ST 更紧 = last_1h_st < lock_threshold
  含义: 1H ST 比锁利阈值更低（向下突破）
```

**代码位置:** [strategy.py L148-151](strategy.py#L148-L151)

---

## 🚨 风险控制规则

### 熔断 (Circuit Breaker)
```
触发条件: 本金 ≤ 350 USDT
行为:     停手 1 周，不发出任何交易信号
状态:     返回 action:"circuit_breaker"
```

**代码:** [config.py L32](config.py#L32) + [strategy.py L284-292](strategy.py#L284-L292)

### 冷静期 (Cooldown)
```
触发条件: 连续 3 笔止损亏损
时长:     48 小时
行为:     停手 48 小时，不发出任何交易信号
状态:     返回 action:"cooldown"
```

**代码:** [strategy.py L293-318](strategy.py#L293-L318)

### 风险额 (Risk Per Trade)
```
模式1-固定: 每笔风险 = 10 USDT (固定)
模式2-百分比: 每笔风险 = 账户余额 × 2%

选择:     env: RISK_MODE="fixed" 或 "percent"
```

**代码:** [config.py L48-76](config.py#L48-L76)

---

## 📈 数据准确性保证

```
【K线获取】
  数量: 1000 根 (保证 DEMA 精度)
  周期: 1H + 30m 分别获取

【数据使用】
  使用: iloc[-2] (上一根"完整"K线)
  不使用: iloc[-1] (当前形成中的 K线)
  原因: 避免未收盘 K线影响信号

【技术指标】
  SuperTrend: 完全对齐 TradingView PineScript
  DEMA200:    精度 99.99% (差异仅 0.07 点)
```

**代码:** [strategy.py L225-246](strategy.py#L225-L246)

---

## 🔄 反手逻辑

```
【平仓时检查】
1. 是否满足反向方向的开仓条件？
   ✓ 1H ST 反向 + 价格反向 + 30m ST 反向

2. 是否处于冷静期？
   ✓ 不在冷静期才能反手

3. 检查完全 → 可反手，提示用户
   检查不全 → 只平仓

返回: action:"close_and_reverse_short/long" 或 "close"
```

**代码:** [strategy.py L766-825](strategy.py#L766-L825)

---

## 📋 信号 Action 类型速查表

| Action | 含义 | 下一步行动 |
|--------|------|----------|
| `open_long` | 满足开多条件 | 执行买入 |
| `open_short` | 满足开空条件 | 执行卖出 |
| `hold` | 持仓无变化 | 继续持仓 |
| `stop_updated` | 止损已调整 | 更新止损价 |
| `enter_locked` | 进入锁利期 | 锁定止损 |
| `switch_1h` | 切换至 1H 轨 | 更新止损参考 |
| `close` | 平仓信号 | 执行平仓 |
| `close_and_reverse_long` | 平空反手多 | 平仓 → 开多 |
| `close_and_reverse_short` | 平多反手空 | 平仓 → 开空 |
| `reverse_to_long` | 平空反手建议 | 提示反手 |
| `reverse_to_short` | 平多反手建议 | 提示反手 |
| `cooldown` | 冷静期中 | 等待 48h |
| `circuit_breaker` | 熔断触发 | 停手 1 周 |
| `none` | 无信号 | 继续观察 |

---

## 🔬 调试技巧

### 启用详细日志
```bash
export DEBUG=1
export GATE_DEBUG=1
export DEBUG_KLINE=1
```

### 查看 K线时间戳
```python
[DEBUG KLINE] 1H最后两根K线时间戳:
  iloc[-2] (上一根完整): 2026-02-21 15:00:00 close=2150.50
  iloc[-1] (当前形成中): 2026-02-21 16:00:00 close=2155.30
```

**说明:** 始终使用 `iloc[-2]`

---

## ⚙️ 配置速查

| 参数 | 默认值 | 作用 |
|------|--------|------|
| `SUPERTREND_PERIOD` | 10 | ST 周期 |
| `SUPERTREND_MULTIPLIER` | 3.0 | ST 乘数 |
| `DEMA_PERIOD` | 200 | DEMA 周期 |
| `LEVERAGE` | 10 | 杠杆倍数 |
| `LOCK_PROFIT_BUFFER` | 1 | 锁利保底盈利 (U) |
| `RISK_FIXED_AMOUNT` | 10 | 固定风险金额 (U) |
| `RISK_PERCENT` | 0.02 | 百分比风险 (2%) |
| `CIRCUIT_BREAKER_EQUITY` | 350 | 熔断阈值 (U) |
| `MAX_CONSECUTIVE_LOSSES` | 3 | 冷静期触发笔数 |
| `FACE_VALUE` | 0.1 | 每张合约面值 (ETH) |

**修改位置:** [config.py](config.py)

---

## 📞 常见问题排查

### Q: 为什么没有信号？
```
1. 检查账户状态: 是否熔断 (≤350U) 或冷静期？
2. 检查技术条件: 使用 DEBUG=1 查看 ST 方向和 DEMA 值
3. 检查 K线数据: DEBUG_KLINE=1 查看最后两根 K线
```

### Q: 止损为什么一直不变？
```
1. 检查阶段: 是否在锁利期内（止损应该锁定）
2. 检查 ST 方向: 30m ST 是否变色（应该离场而不是调整）
3. 查看浮盈: 如果浮盈还在增加，说明还未入锁利期
```

### Q: 反手为什么没有建议？
```
1. 检查条件: 1H ST + 价格 + 30m ST 是否都反向？
2. 检查冷静期: 是否正处于冷静期中？
3. 查看 action: 应该是 "close_and_reverse_*" 而不是 "close"
```

---

**更新时间:** 2026-02-21  
**版本:** V9.6-Exec SOP  
**检查状态:** ✅ 完全符合规范
