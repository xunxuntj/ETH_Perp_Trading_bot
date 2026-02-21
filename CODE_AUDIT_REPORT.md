# 信号准确性代码逻辑审核报告

**审核日期:** 2026-02-21  
**审核内容:** 确认K线完整性、指标计算、信号判断的时序一致性

---

## 📋 需求检查表

### ✅ 需求1：代码每次运行都会获取最新行情信息做信号判断

**验证结果：正确** ✓

- `main.py:32` 每次执行都调用 `strategy.analyze()`
- `strategy.py:176-177` 在 `analyze()` 中获取最新数据：
  ```python
  df_30m = self.client.get_candlesticks(self.contract, "30m", 300)
  df_1h = self.client.get_candlesticks(self.contract, "1h", 300)
  ```
- `gate_client.py:48-71` 通过HTTP API实时获取数据

**结论：** 每次运行都获取最新行情 ✅


### ⚠️ 需求2：1h过滤 - 用最近一根完整K数据做判断

**存在待验证问题：**

当前代码使用 `iloc[-2]` 代表"最近一根完整K线"：

```python
# strategy.py:182-187
last_1h_close = df_1h['close'].iloc[-2]
last_1h_dema = dema_1h.iloc[-2]
last_1h_dir = int(st_1h['direction'].iloc[-2])
...
```

**问题：** 这取决于Gate.io API的返回格式

| API返回格式 | iloc[-1] | iloc[-2] | 当前代码 | 需要改? |
|-----------|---------|---------|--------|--------|
| 仅返回已完成K线 | ✅已完成最新K | ❌过旧K线 | ✅但不是最新的 | 需改为 `iloc[-1]` |
| 返回已完成KL+当前进行中的K | ❌进行中 | ✅已完成最新K | ✅正确 | 无需改 |

**需要的测试：** 运行 `test_kline_completion.py` 来确定API实际返回格式

**检查项：**
- [ ] 判断ST方向: `last_1h_dir = st_1h['direction'].iloc[-2]` → 基于已完成K线 ✓
- [ ] 判断收盘价位置: `last_1h_close > last_1h_dema` → 基于已完成K线 ✓  
- [ ] DEMA值: `last_1h_dema = dema_1h.iloc[-2]` → 该K线对应的DEMA值 ✓

---

### ⚠️ 需求3：30m - 用最近一根完整K判断ST方向，取ST数值计算开仓数量

**存在时序不一致问题：**

**代码片段：** `strategy.py:189-193`

```python
# 30m 用完整K线的数据判断
last_30m_dir = int(st_30m['direction'].iloc[-2])     # ← iloc[-2]
last_30m_st = st_30m['supertrend'].iloc[-2]          # ← iloc[-2]

# 但入场价格用实时价
current_price = df_30m['close'].iloc[-1]             # ← iloc[-1]
```

**导致的问题：**

#### 问题A：入场价格与信号源不一致

在开仓建议中（`strategy.py:320-329`）：

```python
return TradeResult(
    action="open_long",
    message=f"""...
📌 开多 {pos_info['qty']}张 @ {current_price:.2f}    # ← 实时价 (iloc[-1])
📌 设止损 @ {last_30m_st:.2f}                        # ← 完整K线的ST (iloc[-2])
...
""",
    details={
        "entry": current_price,                       # ← iloc[-1]
        "stop_loss": last_30m_st,                     # ← iloc[-2]
        ...
    }
)
```

**时序混淆：**
- ✅ 信号判断用完整K线: `last_30m_dir == 1` (已完成K线)
- ❌ 入场价格用实时价: `current_price = iloc[-1]` (进行中K线)
- ❌ 止损计算也基于实时价: `calculate_position_size(risk_amount, current_price, last_30m_st)`

**影响：** 
- 实际执行时入场价可能偏差5-50点
- 止损距离计算不准确
- 仓位大小 `qty = risk / sl_distance` 会被影响

#### 问题B：类似问题出现在持仓管理中

在 `_manage_long_position` 和 `_manage_short_position` 中（`strategy.py:447-448`）：

```python
last_30m_st = st_30m['supertrend'].iloc[-2]   # ← 完整K线
last_1h_st = st_1h['supertrend'].iloc[-2]     # ← 完整K线

# [后面代码中]
current_price = df_30m['close'].iloc[-1]      # ← 这行在哪? 需确认是否一致
```

要检查持仓管理时是否也有相同的时序问题。

---

## 🔧 建议修复

### 方案一：统一使用已完成K线（推荐）

如果Gate.io API返回：最后一根是**进行中的K线**，当前代码正确；  
如果Gate.io API返回：最后一根也**已完成**，需改造：

```python
# strategy.py 改造建议
# 第一步：检查K线是否包含当前进行中的K线
def get_completed_klines(df, interval_minutes):
    """确保返回的都是已完成K线"""
    last_time = df.index[-1]
    now = pd.Timestamp.now(tz='UTC')
    
    # 如果最后一根K线时间距现在 < 周期→说明包含进行中的K
    minutes_ago = (now - last_time).total_seconds() / 60
    
    if minutes_ago < interval_minutes:
        # 最后一根是进行中的K，去掉它
        return df[:-1]  # 返回已完成的K
    else:
        # 最后一根已完成
        return df

# 改造analyze()方法
def analyze(self) -> TradeResult:
    df_30m = self.client.get_candlesticks(...)
    df_1h = self.client.get_candlesticks(...)
    
    # 确保都是已完成的K线
    df_30m = get_completed_klines(df_30m, 30)
    df_1h = get_completed_klines(df_1h, 60)
    
    # 所有指标都用最新的完整K线 iloc[-1]
    last_1h_close = df_1h['close'].iloc[-1]
    last_1h_dema = dema_1h.iloc[-1]
    last_30m_dir = int(st_30m['direction'].iloc[-1])
    last_30m_st = st_30m['supertrend'].iloc[-1]
    
    # 入场价也用完整K线
    current_price = df_30m['close'].iloc[-1]
    
    # 这样信号源和入场价就统一了！
```

### 方案二：保持现状但明确注释

如果经过测试确认API返回的最后一根就是进行中的K线，当前 `iloc[-2]` 是对的，但需要：

1. **添加显式注释** 说明为什么用 `iloc[-2]`
2. **完整性检查** 确保所有地方都用 `iloc[-2]` 代表"最新完整K线"

```python
# ✅ 改造前：模糊不清
last_30m_st = st_30m['supertrend'].iloc[-2]

# ✅ 改造后：清晰明确
# 注意：get_candlesticks() 返回的最后一根是当前进行中的K线
# 因此 iloc[-1] 是进行中的K，iloc[-2] 是最新已完成的K线
completed_30m_st = st_30m['supertrend'].iloc[-2]
```

---

## 🧪 立即测试步骤

### 步骤1：确认API返回格式

```bash
python test_kline_completion.py
```

**在非K线整点时运行**（如 14:35, 15:27 等），观察输出判断：
- 最后一根K线是 ✅已完成 还是 📊进行中？

### 步骤2：验证指标计算

如果需要，运行单元测试：

```bash
pytest test_strategy_logic.py -v
```

检查：
- [ ] ST方向判断是否准确
- [ ] DEMA值计算是否正确
- [ ] 仓位计算是否一致

### 步骤3：实盘对比

在实际部署前：
1. 记录某个时刻的信号
2. 对比手动在K线图上的判断
3. 验证ST值、DEMA值是否匹配

---

## 📌 总结

| 需求 | 状态 | 问题 |
|-----|------|------|
| 每次获取最新行情 | ✅完全正确 | 无 |
| 1h用最新完整K + DEMA | ⚠️基本正确 | 需确认API返回格式 |
| 30m仅判断ST方向 | ✅逻辑正确 | 但入场价格与信号源时序不一致❌ |

**最可能的问题根源：** 入场价格、止损距离计算使用的是 `iloc[-1]`（可能是进行中的K线），而信号源用的是 `iloc[-2]`（已完成K线），导致时序混乱。

**建议优先处理:** 运行 `test_kline_completion.py` 确认API格式，然后统一所有逻辑使用同一个时序源。

