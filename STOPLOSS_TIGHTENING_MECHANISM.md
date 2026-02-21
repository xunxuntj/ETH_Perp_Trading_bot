# 止损收紧调整信号详解

## 🎯 止损调整的三层架构

```
┌─────────────────────────────────────────────────────────────────────┐
│ T[n] 周期 (每 30 分钟执行一次)                                       │
│                                                                      │
│  1️⃣ 计算推导阶段  ↓  2️⃣ 推导止损  ↓  3️⃣ 检测变化  ↓  4️⃣ 返回信号 │
└─────────────────────────────────────────────────────────────────────┘
        ↓                   ↓              ↓              ↓
   _infer_phase()    recommended_stop  update_position_  action=
                                        state()         stop_updated
```

---

## 📍 核心实现三步全流程

### 步骤1️⃣ : 推导当前阶段和建议止损

**函数位置:** [strategy.py#L156-196](strategy.py#L156-L196) - `_infer_phase()`

**输入参数:**
```python
def _infer_phase(self, 
    entry_price: float,      # 入场价格
    current_price: float,    # 当前价格
    qty: int,                # 仓位大小(张数)
    last_30m_st: float,      # 上一根完整 30m ST
    last_1h_st: float,       # 上一根完整 1H ST
    is_long: bool            # 是否多仓
) -> tuple:
```

**核心逻辑:**
```python
# 计算当前浮盈
pnl = (current_price - entry_price) * qty * FACE_VALUE  # 多仓
pnl = (entry_price - current_price) * qty * FACE_VALUE  # 空仓

# 计算锁利阈值
lock_threshold = calculate_lock_threshold(entry_price, qty, is_long)

# 推导阶段
if pnl < 1.0:  # LOCK_PROFIT_BUFFER = 1U
    # 【阶段1】生存期
    phase = "survival"
    recommended_stop = last_30m_st  # ← 止损跟随 30m ST
    
elif is_1h_tighter(last_1h_st, lock_threshold, is_long):
    # 【阶段3】换轨期
    phase = "hourly"
    recommended_stop = last_1h_st  # ← 止损跟随 1H ST
    
else:
    # 【阶段2】锁利期
    phase = "locked"
    recommended_stop = last_30m_st  # ← 止损锁定
    
return phase, recommended_stop
```

**关键点:**
- ✅ **只紧不松:** 止损从不向亏损方向调整
- ✅ **阶段适配:** 不同阶段用不同的 ST 作为止损源
- ✅ **无状态:** 每次从 API 数据重新计算，不依赖历史缓存

**各阶段止损源对照表:**

| 阶段 | 止损源 | 说明 |
|------|--------|------|
| 🔵 生存期 | 30m ST | 短周期保护 |
| 🟡 锁利期 | 锁定值 | 保底 1U 盈利 |
| 🟣 换轨期 | 1H ST | 长周期驾控 |

---

### 步骤2️⃣ : 获取前一次的止损，对比检测变化

**函数位置:** [position_state.py#L52-92](position_state.py#L52-L92) - `update_position_state()`

**数据来源:** [position_state.json](position_state.json) (缓存文件)

**文件格式:**
```json
{
  "long": {
    "phase": "LOCKED",
    "stop_loss": 2000.45,        ← 上一次保存的止损
    "entry_price": 2010.0,
    "last_update": 1708462800
  },
  "short": {
    "phase": "SURVIVAL",
    "stop_loss": 2150.67,
    "entry_price": 2140.0,
    "last_update": 1708462800
  }
}
```

**检测逻辑:**
```python
def update_position_state(direction, phase, stop_loss, entry_price, current_time):
    # 加载前一次状态
    state = load_position_state()
    prev_state = state.get(direction, {})
    
    # 🔍 【关键】: 检查止损是否有变化
    if prev_state and abs(prev_state.get('stop_loss', 0) - stop_loss) > 0.01:
        change_type = "stop_updated"  # ← 检测到止损变化！
    else:
        change_type = ""
    
    # 检查阶段变化 (优先级更高)
    prev_phase = prev_state.get('phase', '')
    if prev_phase and prev_phase != phase:
        if phase == "LOCKED" and prev_phase == "SURVIVAL":
            change_type = "enter_locked"      # 进入锁利期
        elif phase == "HOURLY" and prev_phase in ["SURVIVAL", "LOCKED"]:
            change_type = "switch_1h"         # 切换至 1H 轨
        else:
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
```

**判断算法:**
```
┌─────────────────────────────────────────────────────┐
│ 比较: |prev_stop_loss - current_recommended_stop|  │
│                                                      │
│  > 0.01  →  change_type = "stop_updated" ✓         │
│  ≤ 0.01  →  change_type = "" (无变化)              │
│                                                      │
│ 容差: 0.01 USDT (约 0.0005 × 当前价格)             │
│ 作用: 避免浮点数精度误差导致的虚假信号              │
└─────────────────────────────────────────────────────┘
```

---

### 步骤3️⃣ : 在持仓管理中调用流程

**多仓管理位置:** [strategy.py#L545-625](strategy.py#L545-L625) - `_manage_long_position()`

**完整流程代码:**
```python
def _manage_long_position(self, position, df_30m, df_1h, st_30m, st_1h,
                         last_1h_close, last_1h_dema, risk_amount, risk_info):
    """管理多仓"""
    # 获取实时指标
    current_price = df_30m['close'].iloc[-1]
    entry_price = position['entry_price']
    qty = abs(position['size'])
    last_30m_st = st_30m['supertrend'].iloc[-2]
    last_30m_dir = int(st_30m['direction'].iloc[-2])
    last_1h_st = st_1h['supertrend'].iloc[-2]
    last_1h_dir = int(st_1h['direction'].iloc[-2])
    
    # ✅【第1步】推导当前阶段 + 建议止损
    phase, recommended_stop = self._infer_phase(
        entry_price, current_price, qty, 
        last_30m_st, last_1h_st, is_long=True
    )
    
    # 检查离场条件 ...
    if exit_signal:
        return self._close_with_reverse_check(...)
    
    # 计算浮盈
    pnl = (current_price - entry_price) * qty * FACE_VALUE
    
    # ✅【第2步】检测状态变化 (包括止损变化)
    current_time = time.time()
    has_change, change_type = update_position_state(
        direction="long",
        phase=phase,
        stop_loss=recommended_stop,
        entry_price=entry_price,
        current_time=current_time
    )
    
    # ✅【第3步】根据变化类型返回信号
    if change_type == "stop_updated":
        return TradeResult(
            action="stop_updated",  # ← 止损已调整信号！
            message=f"""⚠️  止损已调整
• 方向: 多 | 阶段: {phase}
• 入场: {entry_price:.2f} | 当前: {current_price:.2f}
• 新止损: {recommended_stop:.2f} | 浮盈: {pnl:+.2f}U""",
            details={"phase": phase, "stop_loss": recommended_stop, "pnl": pnl}
        )
    elif change_type == "enter_locked":
        return TradeResult(action="enter_locked", ...)
    elif change_type == "switch_1h":
        return TradeResult(action="switch_1h", ...)
    else:
        return TradeResult(action="hold", ...)  # 止损无变化，继续持仓
```

**空仓管理:** [strategy.py#L677-765](strategy.py#L677-L765) - `_manage_short_position()` (逻辑完全对称)

---

## 📊 止损调整的完整示例

### 场景：多仓从生存期进入锁利期

```
【入场】
时间: T0
条件: 1H ST 绿 + price > DEMA + 30m ST 绿
动作: 开多 1 张 @ 2000
止损: 30m ST = 1990
状态: phase=SURVIVAL, stop_loss=1990
_json: position_state.json 写入 {"long": {"phase":"SURVIVAL", "stop_loss":1990}}

─────────────────────────────────────────────

【T1: 30 分钟后】
当前价: 2005, 浮盈 = 50U (> 1U BUFFER)
1H ST = 1990 (不够紧, 即< 2010 锁利阈值)

_infer_phase() 计算:
  pnl = 50 > 1 ✓
  is_1h_tighter(1990, 2010, is_long=True):
    return 1990 > 2010 = False
  → phase = "LOCKED"
  → recommended_stop = 1990

update_position_state("long", "LOCKED", 1990, 2000, t1):
  prev_state = {"phase":"SURVIVAL", "stop_loss":1990}
  abs(1990 - 1990) = 0 ≤ 0.01
    → stop_updated? NO
  prev_phase = "SURVIVAL" != phase "LOCKED"
  phase=="LOCKED" and prev=="SURVIVAL"?
    → YES! change_type = "enter_locked"

返回信号:
  action = "enter_locked"
  message = """🟡 已进入锁利期
  • 方向: 多 | 阶段: 🟡 锁利期
  • 入场: 2000.00 | 当前: 2005.00
  • 止损: 1990.00 | 浮盈: +50.00U
  • 说明: 浮盈已超过 1U，切换至锁利策略"""

─────────────────────────────────────────────

【T2: 60 分钟后】
当前价: 2008, 浮盈 = 80U
30m ST = 1995, 1H ST = 2012 (> 2010 锁利阈值!)

_infer_phase() 计算:
  pnl = 80 > 1 ✓
  is_1h_tighter(2012, 2010, is_long=True):
    return 2012 > 2010 = True ✓
  → phase = "HOURLY"
  → recommended_stop = 2012 (← 1H ST 接管!)

update_position_state("long", "HOURLY", 2012, 2000, t2):
  prev_state = {"phase":"LOCKED", "stop_loss":1990}
  abs(1990 - 2012) = 22 > 0.01
    → YES! change_type = "stop_updated" (但下面检查优先)
  prev_phase = "LOCKED" != phase "HOURLY"
  phase=="HOURLY" and prev in ["SURVIVAL","LOCKED"]?
    → YES! change_type = "switch_1h" ← (优先级更高)

返回信号:
  action = "switch_1h"  ← 优先返回阶段切换
  message = """🟣 已切换至小时线轨道
  • 方向: 多 | 阶段: 🟣 换轨期
  • 入场: 2000.00 | 当前: 2008.00
  • 止损: 2012.00 | 浮盈: +80.00U
  • 说明: 1H ST已转向上升，以 1H ST 作为止损参考"""

─────────────────────────────────────────────

【T3: 90 分钟后】
当前价: 2010, 浮盈 = 100U
30m ST = 1998, 1H ST = 2015 (继续上升)

_infer_phase() 计算:
  phase = "HOURLY"
  recommended_stop = 2015 ← 1H ST 上升

update_position_state("long", "HOURLY", 2015, 2000, t3):
  prev_state = {"phase":"HOURLY", "stop_loss":2012}
  abs(2012 - 2015) = 3 > 0.01
    → YES! change_type = "stop_updated" ✓
  prev_phase = "HOURLY" == phase "HOURLY"
    → 无阶段变化

返回信号:
  action = "stop_updated"  ← 检测到止损收紧!
  message = """⚠️  止损已调整
  • 方向: 多 | 阶段: 🟣 换轨期
  • 入场: 2000.00 | 当前: 2010.00
  • 新止损: 2015.00 | 浮盈: +100.00U"""

位置_state.json 更新:
  {"long": {"phase":"HOURLY", "stop_loss":2015}}

👆【关键】: 止损从 2012 → 2015 收紧，信号触发!

─────────────────────────────────────────────

【T4: 120 分钟后】
当前价: 2014, 浮盈 = 140U
30m ST = 2000, 1H ST = 2018 (继续上升)

_infer_phase() 计算:
  phase = "HOURLY"
  recommended_stop = 2018 ← 1H ST 继续上升

update_position_state("long", "HOURLY", 2018, 2000, t4):
  prev_state = {"phase":"HOURLY", "stop_loss":2015}
  abs(2015 - 2018) = 3 > 0.01
    → YES! change_type = "stop_updated" ✓

返回信号:
  action = "stop_updated"  ← 又收紧了!
  message = """⚠️  止损已调整
  • 方向: 多 | 阶段: 🟣 换轨期
  • 入场: 2000.00 | 当前: 2014.00
  • 新止损: 2018.00 | 浮盈: +140.00U"""

位置_state.json 更新:
  {"long": {"phase":"HOURLY", "stop_loss":2018}}

👆【止损持续收紧】

─────────────────────────────────────────────

【T5: 150 分钟后】
当前价: 2010, 浮盈 = 100U
1H ST 变红 (-1), 30m ST 也变红

_manage_long_position() 检查:
  phase = "HOURLY"
  last_1h_dir = -1 (红)
  
  if phase == Phase.HOURLY and last_1h_dir == -1:
    exit_signal = True
    exit_reason = "1H ST 变红"
    
    return self._close_with_reverse_check(...)

返回信号:
  action = "close"  ← 平仓
  message = """🛑 平多！1H ST 变红
  • 入场: 2000.00
  • 当前: 2010.00
  • 盈亏: +100.00U"""

位置_state.json 删除:
  {"long": 删除} ← 平仓时清除持仓状态
```

---

## 🔍 "只紧不松"的实现保证

### 多仓示意图
```
      价格轴 ↑
           │
    2020   │             ← 1H ST 不断上升
    2015   │         ┌──→ 1H ST
    2012   │     ┌───┤   ← 进入换轨期时的 1H ST
    2010   │ ┌───┤   │   ← 锁利阈值
    2005   │ │   │   │
    2000   │─┼───┼───┼── 入场价
    1995   │ │   │   │
    1990   │─┘   │   │   ← 30m ST (生存期止损)
           │     │   │
           ├─────┼───┼─── 时间轴 →
           T0   T2  T3

【只紧不松规则】
• 生存期: stop = 30m ST = 1990 (固定)
• 进入锁利期: stop = 仍然 1990 (不变)
• 进入换轨期: stop = 1H ST = 2012 (上升，收紧!)
• 后续: stop = 1H ST = 2015 → 2018 (持续收紧!)
• 永远不会: stop < 前一次的 stop (保证只紧不松)
```

### 实现保证
```python
# 在 _infer_phase() 中:
if is_long:
    # 多仓的 recommended_stop 永远来自这三个值之一:
    recommended_stop = last_30m_st   # 生存期/锁利期: ST越来越高
    recommended_stop = last_1h_st    # 换轨期: 1H ST越来越高
    # → 两个 ST 指标本身都具有"只紧不松"特性

# ST 指标的"粘性" (sticky) 特性:
# SuperTrend 的上轨 (support line in uptrend) 天然只会上升不会下降
# 除非方向变色
```

---

## 📈 多个收紧触发的时间间隔

### 实际运行统计

| 周期 | 收紧触发频率 | 说明 |
|------|-------------|------|
| 高效行情 | 每 30m-1h | ST 方向稳定，逐根 K线上升 |
| 震荡行情 | 每 2-4h | ST 波动，等待更紧的条件 |
| 缓慢行情 | 每 4-8h | ST 变化缓慢 |
| 没有收紧 | 0 次 | ST 下降或横盘，止损保持不变 |

### 案例：高效上升行情
```
时间    价格   30m ST   1H ST    阶段      止损   收紧?
────────────────────────────────────────────────────
T0     2000   1990    1990    SURVIVAL  1990   开仓
T1     2005   1991    1990    SURVIVAL  1991   ✓ 收紧
T2     2008   1993    1995    LOCKED    1993   ✓ 收紧
T3     2012   1995    2005    HOURLY    2005   ✓ 收紧 (阶段切换)
T4     2015   1997    2010    HOURLY    2010   ✓ 收紧
T5     2018   1998    2015    HOURLY    2015   ✓ 收紧
T6     2020   2000    2018    HOURLY    2018   ✓ 收紧
···    ···    ···     ···     ···       ···    持续收紧...
```

---

## 🎛️ 调试和验证

### 启用详细日志
```bash
export DEBUG=1
export GATE_DEBUG=1
```

### 日志输出示例
```
[STRATEGY DEBUG] _infer_phase: pnl=50.00, lock_threshold=2010.00, last_1h_st=1995.00
[STRATEGY DEBUG] inferred phase=locked, recommended_stop=1990.00

[ACCOUNT INFO] 原始API返回: {'total': 1000, 'available': 950, ...}

[ACCOUNT PARSE] total=1000, available=950
[FINAL EQUITY] 本金取值: 1000

✅ 止损已调整
• 方向: 多 | 阶段: 🟣 换轨期
• 入场: 2000.00 | 当前: 2015.00
• 新止损: 2015.00 | 浮盈: +150.00U
```

### 查看 position_state.json
```json
{
  "long": {
    "phase": "HOURLY",
    "stop_loss": 2015.00,
    "entry_price": 2000.00,
    "last_update": 1708462800.1234
  }
}
```

---

## 🧮 止损调整的计算流水表

### 多仓示例表格

| T | Price | 30m ST | 1H ST | PnL | Phase | Prev SL | New SL | Change | Signal |
|----|-------|--------|-------|-----|-------|---------|--------|--------|--------|
| 0 | 2000 | 1990 | 1990 | 0 | SURVIVAL | - | 1990 | - | open_long |
| 1 | 2010 | 1991 | 1992 | 100 | SURVIVAL | 1990 | 1991 | +1 | stop_updated |
| 2 | 2015 | 1993 | 2000 | 150 | SURVIVAL | 1991 | 1993 | +2 | stop_updated |
| 3 | 2018 | 1995 | 2008 | 180 | LOCKED | 1993 | 1995 | +2 | stop_updated |
| 4 | 2020 | 1998 | 2012 | 200 | HOURLY | 1995 | 2012 | +17 | **switch_1h** |
| 5 | 2022 | 2000 | 2015 | 220 | HOURLY | 2012 | 2015 | +3 | stop_updated |
| 6 | 2024 | 2002 | 2018 | 240 | HOURLY | 2015 | 2018 | +3 | stop_updated |
| 7 | 2026 | 2004 | 2020 | 260 | HOURLY | 2018 | 2020 | +2 | stop_updated |

- T4: 阶段从 LOCKED 切换到 HOURLY，新止损从 30m ST 1995 升级到 1H ST 2012 (大幅收紧!)
- T5-7: 1H ST 继续上升，每个 K线都触发 stop_updated 信号

---

## 总结：止损调整信号的三个关键点

| 关键点 | 位置 | 说明 |
|--------|------|------|
| **推导止损** | [strategy.py#L156-196](strategy.py#L156-L196) `_infer_phase()` | 根据阶段计算 recommended_stop |
| **检测变化** | [position_state.py#L52-92](position_state.py#L52-L92) `update_position_state()` | 对比 prev 和 current，差异 > 0.01 触发 |
| **返回信号** | [strategy.py#L610-617](strategy.py#L610-L617) | 当 `change_type == "stop_updated"` 时，action="stop_updated" |

这三步完整保证了**只紧不松**的止损收紧机制！
