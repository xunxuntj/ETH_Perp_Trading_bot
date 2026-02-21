# 🧪 测试和验证指南

本文档说明如何测试和验证 ETH SuperTrend Trading Bot 的各个功能模块。

## 📋 测试概述

项目包含 9 个测试模块，覆盖策略、执行、持仓管理等核心功能：

| 测试文件 | 用途 | 运行时间 |
|---------|------|--------|
| `test_strategy_logic.py` | 进场/平仓信号逻辑 | < 1s |
| `test_position_state.py` | 持仓状态管理 | < 1s |
| `test_stop_loss_integration.py` | 止损计算和追踪 | < 1s |
| `test_trading_executor.py` | 交易执行模块 | 1-2s |
| `test_gate_api.py` | Gate.io API 连接 | 2-5s |
| `test_kline_completion.py` | K线数据完整性 | 3-5s |
| `test_cooldown_optimization.py` | 冷静期机制 | < 1s |
| `test_locked_logic.py` | 锁利期逻辑 | < 1s |
| `simulate_gate_client.py` | 模拟 Gate 客户端 | 辅助工具 |

---

## 🚀 快速开始

### 前置准备

```bash
# 1. 克隆仓库
git clone https://github.com/yourusername/eth-trading-bot.git
cd eth-trading-bot

# 2. 安装依赖
pip3 install -r requirements.txt

# 3. 安装测试依赖（如果不在 requirements.txt 中）
pip3 install pytest pytest-cov
```

### 运行所有测试

```bash
# 运行所有单元测试
pytest tests/ -v

# 运行所有测试并显示覆盖率
pytest tests/ -v --cov=. --cov-report=html

# 运行特定测试文件
pytest tests/test_strategy_logic.py -v
```

---

## 📊 逐个测试模块

### 1. 策略逻辑测试 (`test_strategy_logic.py`)

**用途**: 验证进场和平仓信号的计算逻辑

**关键测试项**:
- ✅ 双向分析 (long/short)
- ✅ 1H 趋势过滤 + 30m 入场时机
- ✅ DEMA200 确认
- ✅ 反手逻辑
- ✅ 无信号状态

**运行**:

```bash
pytest tests/test_strategy_logic.py -v
```

**预期输出**:

```
test_strategy_logic.py::test_signal_open_long PASSED
test_strategy_logic.py::test_signal_open_short PASSED
test_strategy_logic.py::test_signal_close PASSED
test_strategy_logic.py::test_signal_reverse PASSED
test_strategy_logic.py::test_no_signal PASSED

====== 5 passed in 0.42s ======
```

**失败排查**:

| 错误 | 原因 | 解决 |
|------|------|------|
| DEMA 值为 None | K线不足 | 确保获取 1000+ 根 K线 |
| ST 值错误 | 计算参数错误 | 检查 SUPERTREND_PERIOD/MULTIPLIER |
| Signal 总是 None | 指标库问题 | 重新安装 pandas/numpy |

---

### 2. 持仓状态测试 (`test_position_state.py`)

**用途**: 验证持仓信息的持久化和读取

**关键测试项**:
- ✅ 状态文件创建/读写
- ✅ JSON 序列化/反序列化
- ✅ 状态完整性检查
- ✅ 多次更新一致性

**运行**:

```bash
pytest tests/test_position_state.py -v
```

**文件操作**:

```bash
# 查看持仓状态文件
cat trading_state.json

# 文件示例
{
    "symbol": "ETH_USDT",
    "position": "long",
    "entry_price": 2500.0,
    "entry_time": "2026-02-21T10:30:00Z",
    "stop_loss": 2450.0,
    "phase": "survival",
    "quantity": 10.0,
    "contract_id": "123456789"
}
```

---

### 3. 止损集成测试 (`test_stop_loss_integration.py`)

**用途**: 验证止损计算、追踪、调整的完整流程

**关键测试项**:
- ✅ 初始止损计算 (SuperTrend 下轨)
- ✅ 止损收紧检测
- ✅ "生存期 → 锁利期" 转换
- ✅ "锁利期 → 换轨期" 转换
- ✅ 止损条件单执行

**运行**:

```bash
pytest tests/test_stop_loss_integration.py -v

# 显示详细输出
pytest tests/test_stop_loss_integration.py -v -s
```

**调试输出**:

```
[持仓信息]
价格: 2500, 止损: 2450, 浮盈: 50 USDT
阶段: survival (30m ST 托管)

[止损调整]
30m ST 下轨变化: 2450 → 2460
新止损: 2460 (收紧 10 点)
状态: ✅ 已调整

[阶段转换检测]
浮盈 (50) >= 缓冲 (1) → 进入锁利期
```

---

### 4. 交易执行测试 (`test_trading_executor.py`)

**用途**: 验证交易执行的各个阶段

**关键测试项**:
- ✅ 模拟开仓 (long/short)
- ✅ 条件止损单创建
- ✅ 止损单调整
- ✅ 平仓执行
- ✅ 错误处理

**运行**:

```bash
# 模拟模式测试 (无真实交易)
ENABLE_AUTO_TRADING=false pytest tests/test_trading_executor.py -v

# 需要 API 凭证的测试
export GATE_API_KEY="your_key"
export GATE_API_SECRET="your_secret"
pytest tests/test_trading_executor.py::test_execute_long -v
```

**关键参数**:

```python
# 测试配置
ENABLE_AUTO_TRADING = False  # 仅模拟，不执行真实交易
contract = "ETH_USDT"
leverage = 10
risk_amount = 10.0  # USDT
entry_price = 2500.0
```

---

### 5. Gate.io API 测试 (`test_gate_api.py`)

**用途**: 验证与 Gate.io 的 API 连接和数据获取

**前置条件**:
- ✅ GATE_API_KEY 和 GATE_API_SECRET 已配置
- ✅ 账户已开通永续合约
- ✅ 网络可访问 Gate.io

**运行**:

```bash
# 需要 API 凭证
export GATE_API_KEY="your_key"
export GATE_API_SECRET="your_secret"

pytest tests/test_gate_api.py -v

# 仅运行不需要交易权限的测试
pytest tests/test_gate_api.py::test_get_ticker -v
pytest tests/test_gate_api.py::test_get_klines -v
```

**关键测试项**:
- ✅ 行情获取 (ticker)
- ✅ K线获取 (klines)
- ✅ 账户查询 (account)
- ✅ 持仓查询 (positions)

**常见错误**:

```
❌ 错误: 401 Unauthorized
原因: API Key/Secret 错误或权限不足
解决: 验证 API 凭证，检查权限范围

❌ 错误: 403 Forbidden
原因: IP 不在白名单中
解决: Gate.io 账户设置中添加当前 IP

❌ 错误: Network timeout
原因: 网络连接问题或 Gate.io 故障
解决: 稍后重试或检查网络
```

---

### 6. K线完整性测试 (`test_kline_completion.py`)

**用途**: 验证 K线数据的完整性和时间戳准确性

**关键测试项**:
- ✅ K线数量完整 (应获取 1000+ 根)
- ✅ 时间间隔正确 (应为 30 分钟)
- ✅ 无缺失 K线
- ✅ 收盘价逻辑一致性

**运行**:

```bash
export GATE_API_KEY="your_key"
export GATE_API_SECRET="your_secret"

pytest tests/test_kline_completion.py -v -s
```

**输出示例**:

```
[1000 根 K线检查]
✅ 时间跨度: 2024-11-01 → 2026-02-21 (348 天)
✅ 实际根数: 1005 根
✅ 完整度: 99.9%
✅ 最后 K线: 2026-02-21 22:30:00 UTC
```

---

### 7. 冷静期机制测试 (`test_cooldown_optimization.py`)

**用途**: 验证连续亏损冷静期的触发和解除

**关键测试项**:
- ✅ 冷静期触发 (连续 3 次止损)
- ✅ 冷静期倒计时
- ✅ 冷静期自动解除
- ✅ 冷静期重置

**运行**:

```bash
pytest tests/test_cooldown_optimization.py -v
```

**场景模拟**:

```
初始状态: cooldown 已解除
首次止损: 记录
第二次止损: 记录
第三次止损: ⏳ 触发冷静期 48 小时
持续: 可继续模拟交易，但不执行
48 小时后: ✅ 自动恢复正常模式
```

---

### 8. 锁利期逻辑测试 (`test_locked_logic.py`)

**用途**: 验证锁利期认定和转换逻辑

**关键测试项**:
- ✅ 锁利条件检测
- ✅ 锁利阈值计算
- ✅ 从生存期进入锁利期
- ✅ 从锁利期进入换轨期

**运行**:

```bash
pytest tests/test_locked_logic.py -v -s
```

**流程验证**:

```
开仓价: 2500 USDT
缓冲: 1 USDT
锁利阈值: 2501 USDT (入场价 + 缓冲)

当前价: 2502, 浮盈: 2 USDT
检查: 2502 > 2501 → ✅ 进入锁利期

1H ST 下轨变化到 2495
检查: 2495 < 2501 → ✅ 进入换轨期
```

---

## 🧩 集成测试流程

### 步骤 1: 本地模拟测试

```bash
# 不需要 API 凭证
pytest tests/test_strategy_logic.py tests/test_position_state.py \
        tests/test_cooldown_optimization.py tests/test_locked_logic.py -v
```

### 步骤 2: 需要 API 的测试

```bash
# 需要 API 凭证
export GATE_API_KEY="your_key"
export GATE_API_SECRET="your_secret"

pytest tests/test_gate_api.py tests/test_kline_completion.py -v
```

### 步骤 3: 完整集成测试

```bash
# 运行所有测试并生成报告
pytest tests/ -v --cov=. --cov-report=html --cov-report=term

# 查看覆盖率报告
open htmlcov/index.html  # macOS
xdg-open htmlcov/index.html  # Linux
```

---

## ✅ 实际验证流程（推荐）

### Week 1: 策略验证阶段

```bash
# Day 1-3: 本地测试
pytest tests/test_strategy_logic.py -v
# 检查信号逻辑是否正确

# Day 4-5: API 连接测试
python3 main.py  # 模拟模式，ENABLE_AUTO_TRADING=false
# 检查是否能正常获取行情和计算指标

# Day 6-7: 持续监控
# 连续运行 7 天，观察信号准确性
# 记录每个信号和实际行情对比
```

### Week 2-3: 实盘验证（小资金）

```bash
# 启用自动交易，但使用小资金
export ENABLE_AUTO_TRADING="true"
export RISK_FIXED_AMOUNT="1"  # 每笔仅风险 1 USDT

# 运行 2-3 周，观察执行效果
python3 main.py

# 关键指标:
# - 实际成交价 vs 信号价差
# - 止损执行准确率
# - 持仓转换流畅性
```

### Week 4+: 平常运营

```bash
# 增加风险金额到正常水平
export RISK_FIXED_AMOUNT="10"

# 托管到 GitHub Actions 或 VPS
# 定期检查日志和利润
```

---

## 📈 测试性能指标

### 目标

| 指标 | 目标值 | 说明 |
|------|--------|------|
| 信号准确率 | > 60% | 信号实现利润和亏损的比例 |
| 平均赢利 | > 2 USDT | 单笔获利平均金额 |
| 平均亏损 | < 2 USDT | 单笔亏损平均金额 |
| 胜率 | > 50% | 盈利交易占比 |
| 盈亏比 | > 1:1 | 平均盈利 / 平均亏损 |

### 追踪

创建 `logs/performance.log` 用于记录:

```
2026-02-21 10:30 | OPEN_LONG | 2500 | Risk: 10 | SL: 2450
2026-02-21 11:00 | CLOSE_LONG | 2510 | P&L: +10
2026-02-21 11:30 | OPEN_SHORT | 2510 | Risk: 10 | SL: 2560
2026-02-21 12:00 | CLOSE_SHORT | 2505 | P&L: +5

总计: 15 USDT (2 笔交易)
胜率: 100% (2/2)
平均盈利: 7.5 USDT
```

---

## 🐛 调试技巧

### 启用详细日志

```python
# 在 main.py 中添加
import logging
logging.basicConfig(level=logging.DEBUG)
```

### 查看中间计算值

```bash
# 在 strategy.py 中添加 print 语句
print(f"1H ST: {st_1h}, 30m ST: {st_30m}, DEMA: {dema}")
print(f"Signal: {signal}, Action: {action}")
```

### 使用 Python REPL 调试

```bash
# 进入 Python 交互式环境
python3

# 导入并测试单个函数
from strategy import analyze_signal
from gate_client import GateClient
from config import GATE_API_KEY, GATE_API_SECRET

client = GateClient(GATE_API_KEY, GATE_API_SECRET)
klines_1h = client.get_klines("ETH_USDT", "1h")
klines_30m = client.get_klines("ETH_USDT", "30m")

signal = analyze_signal(klines_1h, klines_30m)
print(signal)
```

---

## 📊 持续集成 (CI)

项目支持 GitHub Actions CI/CD。查看运行状态：

```bash
# 本地查看工作流
cat .github/workflows/trading.yml

# 或在 GitHub 网页上 → Actions 标签查看运行历史
```

---

## 📚 相关文档

- [快速开始](QUICK_START.md) - 快速开始指南
- [部署指南](DEPLOYMENT.md) - 部署到不同环境
- [配置参数](CONFIGURATION.md) - 所有配置选项
- [信号逻辑](SIGNAL_LOGIC_QUICK_REFERENCE.md) - 交易信号详解
