# 三阶段止损逻辑 V2 - 快速参考

## 🎯 一图读懂新逻辑

```
┌─────────────────────────────────────────────────────────────────────┐
│                         持仓生命周期                                  │
└─────────────────────────────────────────────────────────────────────┘
                                 
                         ┌──────────────────┐
                         │    开仓执行       │
                         │(记录30m ST)      │
                         └────────┬─────────┘
                                  │
                    ┌─────────────▼──────────────┐
                    │  期望盈利 < LOCK_PROFIT_BUFFER  │
                    │      (默认 1 USDT)              │
                    └─────────────┬──────────────┘
                                  │
         ┌────────────────────────┴────────────────────────┐
         │                                                   │
    是(进入生存期)                                      否(满足条件)
         │                                                   │
    ┌────▼──────────┐                        ┌─────────────▼────────┐
    │ 🔵 生存期     │                        │  🟡 锁利期          │
    ├──────────────┤                        ├───────────────────────┤
    │止损: 30m ST  │                        │止损:locked_stop_loss │
    │变化: 跟随30m │                        │变化: 保持不变        │
    │            │                        │                     │
    │出场: 30m反向 │                        │监控: 1h ST          │
    └────┬──────────┘                        └──────────┬───────────┘
         │                                              │
         │ 30m反向                    1hST比locked_stop_loss更紧
         │ (平仓)                                  │
         │                                         │
         │                           ┌─────────────▼────────────┐
         │                           │  🟣 换轨期               │
         │                           ├──────────────────────────┤
         │                           │止损: 1h ST               │
         │                           │变化: 跟随1h ST           │
         │                           │                        │
         │                           │出场: 1h反向             │
         │                           └──────────┬──────────────┘
         │                                      │
         │                                   1h反向
         │                                   (平仓)
         │                                      │
         └──────────────────────────┬───────────┘
                                    │
                           ┌────────▼──────────┐
                           │  📊 平仓完成      │
                           │ (清除position_    │
                           │  state.json)      │
                           └───────────────────┘
```

---

## 📋 状态字段对照表

### position_state.json 中的字段含义

```json
{
  "long": {
    "phase": "LOCKED",
    // ↑ 当前阶段: SURVIVAL/LOCKED/HOURLY
    
    "stop_loss": 2000.5,
    // ↑ 当前止损（会变）
    // • 生存期: 跟随 30m ST
    // • 锁利期: = locked_stop_loss (不变)
    // • 换轨期: 跟随 1h ST
    
    "locked_stop_loss": 2024.83,
    // ↑ 【关键】锁利期止损（不会变）
    // • 【何时记录】首次进入 LOCKED 时
    // • 【用途】判断换轨条件: 1h ST vs locked_stop_loss
    
    "entry_price": 2062.17,
    // ↑ 开仓价格（从不变）
    
    "initial_30m_st": 2031.55,
    // ↑ 开仓时的 30m ST（从不变）
    // • 用于参考生存期的初始阈值
    
    "last_update": 1708462800
    // ↑ 最后更新时间戳
  }
}
```

---

## 🔄 三阶段切换矩阵

|从→到|生存期|锁利期|换轨期|
|---|---|---|---|
|**生存期**|✓ 停留|期望盈利≥1U|-|
|**锁利期**|向后退（不会）|✓ 停留|1hST更紧|
|**换轨期**|向后退（不会）|向后退（不会）|✓ 停留|

关键特性：
- ✅ **只进不退** - 一旦进入下一阶段，不会返回前一阶段
- ✅ **锁利可靠** - locked_stop_loss 一旦记录就冻结
- ✅ **换轨清晰** - 条件明确（1h ST vs locked_stop_loss）

---

## 🧮 计算示例

### 用户提供的案例

**开仓条件**
- 方向: 空单
- 入场价: $2062.17
- 仓位: 49 张 (= 0.49 ETH)
- 杠杆: 10x

**阶段推导**
| 时刻 | 30m ST | 1h ST | 期望盈利 | 判断 | 阶段 | 止损 | 备注 |
|------|--------|-------|---------|------|------|------|------|
| 0 | 2038.65 | 2050.99 | 11.52U | ≥1U? **YES** | LOCKED | 2038.65 | 记录locked_stop_loss=2038.65 |
| 3 | 2024.83 | 2044.95 | 18.30U | 在LOCKED中 | LOCKED | 2038.65 | 止损保持（不跟随30m ST） |
| 8 | 2024.83 | 2035.94 | 18.30U | 1h ST < 2038.65?**YES** | HOURLY | 2035.94 | 切换到换轨期 |
| 12 | 2024.83 | 2022.80 | 18.30U | 继续换轨 | HOURLY | 2022.80 | 止损跟随1h ST |

---

## 🔍 调试方法

### 查看状态变化

```bash
# 1. 查看 position_state.json
cat position_state.json | python -m json.tool

# 2. 启用调试日志
export GATE_DEBUG=1
python main.py
```

### 关键日志输出

```
[STRATEGY DEBUG] _infer_phase: expected_pnl_at_stop=11.52, LOCK_PROFIT_BUFFER=1.0
[STRATEGY DEBUG] 首次进入锁利期条件，记录 locked_stop_loss=2038.65
[STRATEGY DEBUG] Phase: LOCKED, recommended_stop=2038.65
[STRATEGY DEBUG] Phase: HOURLY, 1h_st=2035.94 > locked_stop_loss=2038.65
```

---

## ⚠️ 常见问题

### Q1: 为什么迟迟不进入锁利期？
**A**: 检查 `LOCK_PROFIT_BUFFER` 值
- 当前默认: 1 USDT（期望盈利≥1U即进入）
- 如果希望更保守，可设置为 10-15 USDT
```bash
export LOCK_PROFIT_BUFFER=15
python main.py
```

### Q2: 为什么locked_stop_loss和我期望的不一样？
**A**: locked_stop_loss 是首次进入LOCKED时的30m ST，取决于：
1. 当时的30m ST价格
2. LOCK_PROFIT_BUFFER的值（决定何时进入LOCKED）

### Q3: 锁利期内止损为什么不变？
**A**: 这是设计的核心 - 防止在获利充分后还继续追加风险。一旦进入锁利期：
- 不追随30m ST变化（可能是短期波动）
- 只看1h ST（更稳定的趋势）
- 直到1h ST更紧才切换

### Q4: 如何快速测试新逻辑？
**A**: 运行测试脚本
```bash
python tests/test_phase_logic_v2.py
```

---

## 📚 完整文档

| 文档 | 用途 |
|------|------|
| [TRADING_PHASE_LOGIC_V2.md](TRADING_PHASE_LOGIC_V2.md) | 完整的逻辑设计和实现说明 |
| [PHASE_LOGIC_V2_VERIFICATION.md](PHASE_LOGIC_V2_VERIFICATION.md) | 测试结果和调整指南 |
| [strategy.py](strategy.py#L176) | 核心实现 - _infer_phase() |
| [position_state.py](position_state.py#L25) | 状态管理 |
| [config.py](config.py#L44) | LOCK_PROFIT_BUFFER 配置 |

---

## 🚀 快速开始

### 1️⃣ 确认配置
```python
# config.py 第44行
LOCK_PROFIT_BUFFER = 1  # 根据需要调整（推荐 1-15）
```

### 2️⃣ 验证逻辑
```bash
python tests/test_phase_logic_v2.py
```

### 3️⃣ 正常运行
```bash
python main.py
```

### 4️⃣ 查看状态
```bash
cat position_state.json | python -m json.tool
```

---

**更新日期**: 2026-03-07  
**版本**: V2  
**状态**: ✅ 正式版
