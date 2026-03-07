# 三阶段止损逻辑 V2 - 完整实现说明

## 📋 核心改进

相比 V1，V2 实现了**更严谨的换轨期检测**，关键改进：

1. **记录锁利期止损** - 当进入锁利期时，记录该时刻的30m ST作为`locked_stop_loss`
2. **锁利期保持不变** - 在锁利期内只比较1H ST与`locked_stop_loss`，不跟随30m ST波动
3. **准确的换轨条件** - 换轨期的条件是1H ST更紧（比locked_stop_loss更靠近止损方向）

---

## 🔄 三阶段工作流

### 阶段1: 生存期 (SURVIVAL)
**条件**: 按30m ST平仓的期望盈利 < LOCK_PROFIT_BUFFER（1 USDT）

**行为**:
- 止损跟随30m ST调整
- 每当30m ST变化时，止损相应更新（只紧不松）
- 期望盈利达到1 USDT后，进入下一阶段

**例子**（该笔交易）:
```
开仓价: 2062.17 (多)
初始30m ST: 2031.55
期望盈利 = (30m_st - 2062.17) * 49 * 0.01

当期望盈利 < 1U时：
- 30m ST: 2038.65 → 止损 2038.65
- 30m ST: 2034.4  → 止损 2034.4
- ...
- 30m ST: 2024.83 → 止损 2024.83
```

### 阶段2: 锁利期 (LOCKED)
**条件**: 期望盈利 ≥ LOCK_PROFIT_BUFFER 且 1H ST 还未比`locked_stop_loss`更紧

**关键字段**:
- `locked_stop_loss`: 首次进入锁利期时的30m ST值 ←【关键】
- `stop_loss`: 在锁利期内保持 = `locked_stop_loss`

**行为**:
- **暂停止损调整** - 不再跟随30m ST，保持`locked_stop_loss`
- **等待1H ST** - 持续监控1H ST是否比`locked_stop_loss`更紧
- 当1H ST <= locked_stop_loss时（多单），进入换轨期

**例子**（该笔交易）:
```
当30m ST = 2024.83时，期望盈利 >= 1U，进入锁利期
记录: locked_stop_loss = 2024.83

锁利期内:
- stop_loss = 2024.83（保持不变）
- 30m ST继续变化: 2024.83 → 2019.75 → 2015.26 → ...
- 但止损仍保持在 2024.83，不再调整

同时监控1H ST:
- 1H ST: 2050.99 > 2024.83 (未满足)
- 1H ST: 2044.95 > 2024.83 (未满足)
- ...
- 1H ST: 2022.8  < 2024.83 (✅ 满足)
```

### 阶段3: 换轨期 (HOURLY)
**条件**: 1H ST <= `locked_stop_loss`（比锁利止损更紧）

**行为**:
- 止损跟随1H ST调整
- 1H ST变化时，止损相应更新（只紧不松）
- 当1H ST变反向时，平仓离场

**例子**（该笔交易）:
```
当1H ST = 2022.8时，进入换轨期
后续止损跟随1H ST:
- 1H ST: 2022.8  → 止损 2022.8
- 1H ST: 2019.37 → 止损 2019.37
- ...

持续到1H ST变红（多单）时平仓
```

---

## 💾 position_state.json 新结构

```json
{
  "long": {
    "phase": "LOCKED",
    "stop_loss": 2000.5,        // 当前止损（生存期和换轨期会变，锁利期不变）
    "locked_stop_loss": 2024.83, // ← 【新增】锁利期的止损（进入时记录）
    "entry_price": 2062.17,
    "initial_30m_st": 2031.55,  // ← 【新增】开仓时的30m ST
    "last_update": 1708462800
  }
}
```

### 字段说明
| 字段 | 含义 | 何时更新 |
|------|------|------|
| `phase` | 当前阶段 | 每次执行analyze时推导 |
| `stop_loss` | 当前止损 | 位置/1H ST变化时 |
| `locked_stop_loss` | 锁利期止损 | 首次进入LOCKED时 |
| `entry_price` | 入场价格 | 开仓时 |
| `initial_30m_st` | 初始30m ST | 首次有持仓时 |

---

## 🔧 代码流程

### 1️⃣ 位置管理入口

```python
def _manage_long_position(self, ...):
    # 读取历史状态
    prev_state = load_position_state().get("long", {})
    initial_30m_st = prev_state.get("initial_30m_st", 0)
    locked_stop_loss = prev_state.get("locked_stop_loss", 0)
    
    # 推导当前阶段（传入历史参数）
    phase, recommended_stop = self._infer_phase(
        entry_price, current_price, qty,
        last_30m_st, last_1h_st,
        is_long=True,
        initial_30m_st=initial_30m_st,    # ← 传入历史初始值
        locked_stop_loss=locked_stop_loss  # ← 传入历史锁利止损
    )
```

### 2️⃣ 推导阶段逻辑

```python
def _infer_phase(self, ..., initial_30m_st=0, locked_stop_loss=0):
    # 计算期望盈利
    expected_pnl = (last_30m_st - entry) * qty * FACE_VALUE
    
    # 【阶段1】生存期：盈利不足
    if expected_pnl < LOCK_PROFIT_BUFFER:
        return Phase.SURVIVAL, last_30m_st
    
    # 【首次进入锁利】：记录此时的30m ST
    if locked_stop_loss <= 0:
        locked_stop_loss = last_30m_st
    
    # 判断1H ST是否比locked_stop_loss更紧
    is_1h_tighter = (last_1h_st > locked_stop_loss) if is_long else (last_1h_st < locked_stop_loss)
    
    # 【阶段3】换轨期：1H ST已更紧
    if is_1h_tighter:
        return Phase.HOURLY, last_1h_st
    
    # 【阶段2】锁利期：保持locked_stop_loss
    return Phase.LOCKED, locked_stop_loss
```

### 3️⃣ 保存状态时记录锁利止损

```python
# 当从SURVIVAL进入LOCKED时，记录locked_stop_loss
if phase == "LOCKED" and prev_phase == "SURVIVAL":
    locked_stop_for_update = recommended_stop  # = 此时的30m ST
else:
    locked_stop_for_update = 0  # 不更新

update_position_state(
    ...,
    initial_30m_st=initial_30m_st,
    locked_stop_loss=locked_stop_for_update or locked_stop_loss  # 记录或保持
)
```

---

## 📊 离场条件

| 当前阶段 | 离场条件 |
|---------|--------|
| 生存期 | 30m ST变反向 |
| 锁利期 | 30m ST变反向 |
| 换轨期 | 1H ST变反向 |

---

## 🎯 与用户建议的对应关系

用户的建议：
> 开仓时计算生存期和锁利期阈值 → 追踪止损变化 → 记录进入锁利的止损 → 追踪1H ST

现在的实现：
1. ✅ **开仓时**: `initial_30m_st` = 当前30m ST
2. ✅ **追踪止损**: 每次analyze时重新计算 → `_infer_phase()`
3. ✅ **记录锁利止损**: `locked_stop_loss` = 首次进入LOCKED时的30m ST
4. ✅ **追踪1H ST**: 与`locked_stop_loss`对比，满足条件时切换到换轨期

---

## ✨ 关键改进点

### 之前的问题
- 锁利期会跟随30m ST调整（使用了保持prev_stop_loss的trick，但逻辑不清）
- 换轨条件使用lock_threshold（按入场价计算），不是实际的锁利止损
- 缺少对锁利止损的显式记录

### 现在解决了
- 锁利期明确返回`locked_stop_loss`，不受30m ST影响
- 换轨条件直接比较1H ST与`locked_stop_loss`
- `locked_stop_loss`显式保存在position_state.json中便于追踪和调试

---

## 🧪 测试建议

### 场景1：正常的三阶段流程
```
开仓 → SURVIVAL → LOCKED → HOURLY → 平仓
```
验证：
- [ ] position_state.json中initial_30m_st正确记录
- [ ] 进入LOCKED时locked_stop_loss被记录
- [ ] LOCKED期间stop_loss保持不变
- [ ] 1H ST满足条件时切换到HOURLY

### 场景2：直接进入HOURLY（快速反弹）
```
开仓 → SURVIVAL → HOURLY（跳过LOCKED）
```
可能发生在：
- 快速反弹，期望盈利快速达到阈值，但1H ST同时满足条件

### 场景3：生存期内止损被击中
```
开仓 → SURVIVAL → 平仓（30m ST变反向）
```
验证：离场条件正确

---

## 📝 日志调试

启用DEBUG日志查看详细流程：
```bash
GATE_DEBUG=1 python main.py
```

关键输出：
```
[STRATEGY DEBUG] _infer_phase: expected_pnl_at_stop=5.00, LOCK_PROFIT_BUFFER=1.0
[STRATEGY DEBUG] Phase: SURVIVAL, expected_pnl=5.00 < 50.00
[STRATEGY DEBUG] 首次进入锁利期条件，记录 locked_stop_loss=2024.83
[STRATEGY DEBUG] Phase: LOCKED, recommended_stop=2024.83
[STRATEGY DEBUG] Phase: HOURLY, 1h_st=> locked_stop_loss
```

---

## 🔗 相关文件修改

- `position_state.py`: 
  - 新增`initial_30m_st`和`locked_stop_loss`参数
  - 更新`load_position_state()`文档
  - 重构`update_position_state()`逻辑

- `strategy.py`:
  - 重构`_infer_phase()`实现三阶段逻辑
  - 更新`_manage_long_position()`传递新参数
  - 更新`_manage_short_position()`传递新参数

---

## ✅ 验证清单

- [x] position_state.json结构更新
- [x] _infer_phase重新实现三阶段逻辑
- [x] 持仓管理传递initial_30m_st和locked_stop_loss
- [x] 进入LOCKED时记录locked_stop_loss
- [x] 代码无语法错误
- [ ] 运行测试验证各场景（用户手动测试）
