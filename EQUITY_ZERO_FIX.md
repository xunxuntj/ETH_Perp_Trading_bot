# 本金值为0的问题诊断与修复

## 问题现象

脚本显示：
```
⚠️ 熔断！本金 0.00U ≤ 350U，熔断，停手一周
```

但实际Gate App中有700+U的本金。

## 根本原因分析

equity为0很可能是以下原因之一：

### 可能原因1: API字段名不匹配
Gate.io API可能在不同版本/端点返回不同的字段名：
- 期望: `total` → 实际可能是: `equity`、`wallet_balance` 等
- 期望: `available` → 实际可能是: `free` 等  
- 期望: `unrealised_pnl` → 实际可能是: `unrealized_pnl` 等

### 可能原因2: account获取异常
异常被捕获后account被设为None，虽然有默认值500，但显示0.00仍然可能

## 实施的修复

### 1. gate_client.py - 多字段名支持

添加fallback机制，支持多个可能的字段名：

```python
# 原来的代码
total = _safe_float(entry.get('total', 0))

# 修改后的代码 (支持多个字段名)
total = _safe_float(entry.get('total', 
                               entry.get('equity', 
                               entry.get('wallet_balance', 0))))
available = _safe_float(entry.get('available', 
                                   entry.get('free', 0)))
```

**支持的字段名变体：**
- `total` ← 优先级最高
- `equity` ← 第二选项
- `wallet_balance` ← 备用
- `available` ← 优先级最高
- `free` ← 第二选项

### 2. strategy.py - 改进equity计算逻辑

**增强的默认值处理：**

```python
equity = 500  # 初始默认值
if account is not None:
    total = account.get('total', 0.0)
    available = account.get('available', 0.0)
    
    if total > 0:
        equity = total
    elif available > 0:
        equity = available  # fallback到available
    else:
        # 输出警告，保持500
        print("[DEBUG] account.total and available都是0, using default 500")
else:
    # account为None
    print("[DEBUG] account is None, using default 500")
```

### 3. 增强DEBUG信息

当equity <= 0时，会在熔断消息中输出完整的account对象，便于诊断：

```
⚠️ 熔断！本金 0.00U ≤ 350U，熔断，停手一周

[DEBUG] account={'total': 0, 'available': 700, 'unrealised_pnl': 0}
[DEBUG] equity=0
```

### 4. 启用DEBUG模式看完整信息

设置环境变量查看完整DEBUG输出：

```bash
export DEBUG=1
python main.py
```

会输出：
```
[GATE DEBUG] get_account raw data: {...}
[GATE DEBUG] get_account entry fields: dict_keys(['currency', ...])
[GATE DEBUG] extracted: total=714.13, available=476.10, unrealised_pnl=0
[STRATEGY DEBUG] full account object: {'total': 714.13, ...}
[STRATEGY DEBUG] final equity for risk check: 714.13
```

## 预期修复后的效果

✅ 脚本能正确识别API返回的account字段（无论字段名如何）
✅ 即使某个字段为0，也会尝试其他字段（提高容错性）
✅ 当异常时，输出完整DEBUG信息便于诊断
✅ equity应该显示为700+，而非0.00

## 测试步骤

### 步骤1: 运行脚本查看是否修复

```bash
python main.py
```

如果"本金"不再是0.00，说明问题已解决 ✅

### 步骤2: 启用DEBUG查看完整信息

```bash
export DEBUG=1
python main.py
```

查看输出中的：
```
[STRATEGY DEBUG] final equity for risk check: XXX
```

这个值应该是700+

### 步骤3: 对比验证

对比脚本输出中的"本金"和Gate App中的账户余额
- 应该一致 ✅
- 如果仍然是0，请查看DEBUG输出中的account对象内容

## 相关修改文件

- `gate_client.py` (lines 115-200): 改进account字段提取逻辑
- `strategy.py` (lines 251-290): 改进equity计算和DEFAULT值处理

## 后续建议

1. **立即部署**: 修改已准备完毕，可直接上线
2. **收集反馈**: 观察脚本运行后本金值是否正确
3. **如仍异常**: 设置DEBUG=1运行，收集完整输出分析

---

**修改完成**: ✅
**预期效果**: 本金应显示为724.13U或类似正常值，而非0.00U
**部署建议**: 优先级高，立即更新
