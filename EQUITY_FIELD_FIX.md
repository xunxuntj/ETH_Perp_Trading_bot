# 本金字段修正说明

## 问题

用户报告脚本显示的本金值与Gate App不符：
- 脚本显示: **476.10**U
- Gate App显示: **714.13**U  
- 差异: **238.03**U

## 根本原因

脚本使用了**错误的账户字段**：

在 `/workspaces/ETH_Perp_Trading_bot/strategy.py` 第251行，代码使用了：
```python
equity = account.get('available', 0.0)  # ❌ 错误：可用余额（已扣除保证金）
```

而应该使用：
```python
equity = account.get('total', 0.0)  # ✅ 正确：账户总资金
```

## API返回字段说明

Gate.io API `/api/v4/futures/usdt/accounts` 返回三个字段：

| 字段 | 含义 | 示例 |
|------|------|------|
| `total` | **账户总资金** | 714.13U（与Gate App显示一致）|
| `available` | **可用余领余额** | 476.10U（已扣除占用保证金）|
| `unrealised_pnl` | **未平仓盈亏** | - |

**差异分析：**
```
total (714.13) = available (476.10) + 占用保证金 (238.03)
                          ↑                     ↑
                    脚本错误地显示           目前持仓的保证金
```

## 修改内容

### 文件: strategy.py 

**位置**: 第246-255行

**修改前**:
```python
if account:
    equity = account.get('available', 0.0)
    if has_api_position:
        equity += account.get('unrealised_pnl', 0.0)
else:
    equity = 500
```

**修改后**:
```python
if account:
    equity = account.get('total', 0.0)
else:
    equity = 500
```

**注释更新**:
```
# 计算账户本金（用于显示和风控判断）:
# API返回三个字段:
#   - total: 账户总资金 (与Gate App显示一致)
#   - available: 可用余额 (已扣除已占用保证金)
#   - unrealised_pnl: 未平仓盈亏
# 使用 `total` 作为本金 (与Gate App同步)
```

## 修改后的预期行为

✅ **脚本现在显示的本金**: 714.13U（与Gate App一致）
✅ **仍然会根据本金进行风控判断**: 使用总资金计算风险额
✅ **账户状态信息更准确**: 显示的本金与Gate App实时同步

## 风控影响

原来的逻辑：`available + unrealised_pnl` （仅考虑可用余额+浮盈）
现在的逻辑：`total` （账户总资金，包含所有资金)

**改进**：
- 风控判断更准确（基于实际账户资金）
- 不会因为占用保证金而低估账户规模

## 验证步骤

1. **运行脚本**:
```bash
python main.py
```

2. **检查输出**:
查看脚本输出中的 `【账户状态】→ 本金:` 行
应该显示: `• 本金: 714.13U`（与Gate App一致）

3. **对比验证**:
登录Gate App → 期货账户 → 查看账户权益/总资金
应与脚本输出完全相同 ✅

## 受影响的代码部分

- `strategy.py` 第457行: `• 本金: {equity:.2f}U` 
  - 现在显示的是账户总资金而非仅可用余额

## 相关文件

- `gate_client.py`:  `get_account()` 方法返回 `total` 字段（已有此字段）
- `strategy.py`: 使用 `equity` 变量的所有位置会自动用新值

## 后续建议

无需其他修改，修改已完成并可直接部署。

---

**修改状态**: ✅ 完成
**测试状态**: 等待用户在真实环境验证
**部署建议**: 立即部署（改进准确性，无副作用）
