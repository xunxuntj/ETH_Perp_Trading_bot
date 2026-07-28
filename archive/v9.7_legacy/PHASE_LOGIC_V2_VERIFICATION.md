# 三阶段止损逻辑 V2 - 实现验证报告

## ✅ 测试执行结果

已通过测试脚本验证了新的三阶段逻辑，使用了您提供的实际交易数据（空单，开仓价2062.17）。

### 测试数据
- **方向**: 空单
- **开仓价**: 2062.17
- **仓位**: 49张 × 0.01 ETH = 0.49 ETH
- **杠杆**: 10x
- **数据点**: 30m ST 21个，1h ST 16个

### 测试结果总结

| 事件 | 时刻 | 30m ST | 1h ST | 期望盈利 | 阶段 | 说明 |
|------|------|--------|-------|---------|------|------|
| 开仓 | 0 | 2038.65 | 2050.99 | 11.52U | LOCKED | 立即进入锁利期* |
| 锁利期 | 3-7 | 2024.83 | 2044.95 | 18.30U | LOCKED | 止损保持 2038.65 |
| 进入换轨 | 8 | 2024.83 | 2035.94 | 18.30U | HOURLY | 1h ST < 2038.65 |
| 换轨期 | 8-20 | - | 2019.37 | - | HOURLY | 止损跟随1h ST |

---

## ⚠️ 重要发现

### 1. 进入锁利期的时机与预期不符

**现象**: 在时刻 0（开盘第一根）就进入了锁利期，期望盈利只有 11.52U

**原因**: LOCK_PROFIT_BUFFER 设置值

当前配置 (config.py):
```python
LOCK_PROFIT_BUFFER = float(os.environ.get("LOCK_PROFIT_BUFFER", "1"))  # 1 USDT
```

**您的期望** (根据您的示例):
```
R = 15，期望盈利 >= 15U 才进入锁利期
```

### 2. locked_stop_loss 的值

**实现后的结果**:
- `locked_stop_loss = 2038.65`（首次进入LOCKED时的30m ST）

**您期望的结果**:
- `locked_stop_loss = 2024.83`（某个特定时刻的30m ST）

**原因**: 取决于 LOCK_PROFIT_BUFFER 的值
- 如果 LOCK_PROFIT_BUFFER = 1，在时刻 0 就满足
- 如果 LOCK_PROFIT_BUFFER = 15，需要等到时刻 3

---

## 🔧 需要您验证的配置

请检查并确认以下值是否正确：

### config.py
```python
# 第 44 行
LOCK_PROFIT_BUFFER = float(os.environ.get("LOCK_PROFIT_BUFFER", "1"))  # 1 USDT
```

**问题**: 这个值应该是多少？

根据您的交易案例：
- **入场**: 2062.17
- **仓位**: 49张
- **初始止损**: 2031.55（30m ST）
- **止损距离**: 30.62点
- **风险**: 30.62 × 49 × 0.01 = 15 USDT

建议:
- 如果您希望 **盈利 >= 15U 时才进入锁利期**，请设置 `LOCK_PROFIT_BUFFER = 15`
- 如果您希望 **更激进地进入锁利期**，可以设置 `LOCK_PROFIT_BUFFER = 10` 或其他值

---

## 📋 换轨条件验证

### 理论推导

对于空单：
- `locked_stop_loss` = 首次进入LOCKED时的30m ST
- **换轨条件**: 1h ST < `locked_stop_loss`（1h ST更低，即更紧）

### 测试验证

```
当 locked_stop_loss 由 LOCK_PROFIT_BUFFER=1 确定时：
  locked_stop_loss = 2038.65
  
在时刻 8：
  1h ST = 2035.94 < 2038.65
  ✓ 满足换轨条件，进入HOURLY
  
此后：
  - 时刻 12: 1h ST = 2022.80 < 2038.65 (继续HOURLY)
  - 时刻 14: 1h ST = 2019.37 < 2038.65 (继续HOURLY)
```

---

## 🎯 后续调整步骤

### 步骤 1: 确认 LOCK_PROFIT_BUFFER 值

编辑 `config.py` 第 44 行，根据您的策略需求设置合适的值。

示例：改为 15 USDT
```bash
# 方式1: 修改config.py
LOCK_PROFIT_BUFFER = 15

# 方式2: 环境变量
export LOCK_PROFIT_BUFFER=15
python main.py
```

### 步骤 2: 重新运行测试

修改后重新运行测试脚本：
```bash
python tests/test_phase_logic_v2.py
```

观察新的输出，验证：
- `locked_stop_loss` 是否在您期望的时刻被记录
- 换轨条件是否按期望触发

### 步骤 3: 验证实际交易

在实际使用中，观察 `position_state.json` 文件：
```json
{
  "short": {
    "phase": "LOCKED",
    "stop_loss": 2038.65,
    "locked_stop_loss": 2038.65,
    "initial_30m_st": 2038.65,
    "entry_price": 2062.17,
    "last_update": 1708462800
  }
}
```

检查关键字段是否正确记录：
- [ ] `initial_30m_st` = 开仓时的30m ST
- [ ] `locked_stop_loss` = 进入LOCKED时的30m ST
- [ ] 在LOCKED期间 `stop_loss` 保持不变
- [ ] 进入HOURLY后 `stop_loss` 跟随1h ST更新

---

## 📊 三种配置场景

### 场景 A: LOCK_PROFIT_BUFFER = 1 (当前)

| 时刻 | 30m ST | 期望盈利 | 阶段 | 说明 |
|------|--------|---------|------|------|
| 0 | 2038.65 | 11.52U | LOCKED | ✓ 满足 |
| 3 | 2024.83 | 18.30U | LOCKED | 继续 |
| 8 | 2024.83 | 18.30U | HOURLY | 1h ST = 2035.94已满足条件 |

### 场景 B: LOCK_PROFIT_BUFFER = 15 (推荐?)

| 时刻 | 30m ST | 期望盈利 | 阶段 | 说明 |
|------|--------|---------|------|------|
| 0 | 2038.65 | 11.52U | SURVIVAL | 不满足 |
| 3 | 2024.83 | 18.30U | LOCKED | ✓ 满足，记录locked_stop_loss=2024.83 |
| 8 | 2024.83 | 18.30U | HOURLY | 1h ST = 2035.94 > 2024.83不满足 |
| 12 | 2024.83 | 18.30U | HOURLY | 1h ST = 2022.80 < 2024.83✓ 满足 |

### 场景 C: 完全跳过锁利期 (LOCK_PROFIT_BUFFER = 30+)

| 时刻 | 期望盈利 | 阶段 | 说明 |
|------|---------|------|------|
| 0-20 | < 30U | SURVIVAL | 永远不进入LOCKED |

---

## ✨ 新实现的优势

相比旧逻辑：

1. **明确的锁利止损记录** ✅
   - 旧: 模糊使用prev_stop_loss
   - 新: 显式保存 `locked_stop_loss`

2. **准确的换轨条件** ✅
   - 旧: 与 `lock_threshold`(按入场价)比较
   - 新: 与 `locked_stop_loss`(实际锁利价位)比较

3. **清晰的状态追踪** ✅
   - 旧: 缺少锁利期的明确标记
   - 新: position_state.json中保存完整信息

4. **三阶段逻辑清晰** ✅
   - 每个阶段的条件和行为明确定义
   - 便于调试和优化

---

## 🔗 相关文件

- [TRADING_PHASE_LOGIC_V2.md](TRADING_PHASE_LOGIC_V2.md) - 完整的三阶段逻辑文档
- [config.py](config.py) - L44: LOCK_PROFIT_BUFFER 配置
- [strategy.py](strategy.py) - _infer_phase() 实现
- [position_state.py](position_state.py) - 状态保存逻辑
- [tests/test_phase_logic_v2.py](tests/test_phase_logic_v2.py) - 测试脚本

---

## 📝 说明

> 本文档基于当前代码实现和测试结果生成。
> 您可能需要根据实际交易情况调整 LOCK_PROFIT_BUFFER 的值。
> 如有问题，请运行测试脚本并观察 position_state.json 的输出。
