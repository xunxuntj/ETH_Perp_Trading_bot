# ⚙️ 配置参数完整指南

本文档详细说明所有配置参数的含义、用途、推荐值及调整建议。所有配置通过环境变量和 `config.py` 管理。

## 🔐 API 凭证配置

### GATE_API_KEY
- **类型**: String
- **必需**: ✅ 是
- **环境变量**: `GATE_API_KEY`
- **含义**: Gate.io 交易所 API 密钥
- **获取方式**:
  1. 登录 [Gate.io](https://www.gate.io)
  2. 进入 Account → API Management
  3. Create New Key
  4. 选择 API Type → "Classic"
  5. 权限:
     - ✅ `Spot` 和 `Futures` 读取权限
     - ✅ `Spot` 和 `Futures` 交易权限
     - ✅ `IP Restriction`: 限制您的 IP（推荐）
  6. 复制 Key
- **示例**: `a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6`
- **注意**: 
  - 不要在代码中硬编码
  - 不要提交到 Git
  - 定期轮换 API Key

### GATE_API_SECRET
- **类型**: String
- **必需**: ✅ 是
- **环境变量**: `GATE_API_SECRET`
- **含义**: Gate.io 交易所 API 密钥对应的密钥
- **获取方式**: 与 GATE_API_KEY 同时生成，创建后保存到安全位置
- **示例**: `q7w8e9r0t1y2u3i4o5p6a7s8d9f0g1h2`
- **注意**: 此密钥泄露将导致账户被盗，请妥善保管

---

## 📊 交易对配置

### SYMBOL
- **类型**: String
- **默认值**: `ETH_USDT`
- **环境变量**: 不支持（在 config.py 中修改）
- **含义**: 交易对符号，用于 REST API 查询行情
- **可选值**: 
  - `ETH_USDT` - ETH/USDT（推荐）
  - `BTC_USDT` - BTC/USDT（需自行测试）
- **建议**: 保持 `ETH_USDT`，其他币种需验证指标参数

### CONTRACT
- **类型**: String
- **默认值**: `ETH_USDT`
- **环境变量**: 不支持（在 config.py 中修改）
- **含义**: 永续合约交易对代码
- **注意**: 与 SYMBOL 保持一致

---

## 📈 技术指标参数

### SUPERTREND_PERIOD
- **类型**: Integer
- **默认值**: `10`
- **环境变量**: 不支持（在 config.py 中修改）
- **含义**: SuperTrend 指标计算周期（K线根数）
- **范围**: 5-20
- **说明**:
  - 越小 → 信号越灵敏（但噪声增加）
  - 越大 → 信号越稳定（但反应延迟）
- **建议**: 保持 `10`（已优化验证）
- **用途**: 计算上轨/下轨，判断趋势方向

### SUPERTREND_MULTIPLIER
- **类型**: Float
- **默认值**: `3.0`
- **环境变量**: 不支持（在 config.py 中修改）
- **含义**: SuperTrend 的 ATR 倍数
- **范围**: 2.0-4.0
- **说明**:
  - 越小 → 止损更紧（风险增加）
  - 越大 → 止损越宽（盈利空间受限）
- **建议**: 保持 `3.0`（已优化验证）
- **公式**: `上轨 = 中轨 + ATR × SUPERTREND_MULTIPLIER`

### DEMA_PERIOD
- **类型**: Integer
- **默认值**: `200`
- **环境变量**: 不支持（在 config.py 中修改）
- **含义**: 双指数移动平均线（DEMA）计算周期（K线根数）
- **范围**: 100-300
- **说明**:
  - DEMA 使用 1000 根K线历史数据计算（精度 99.99% 与 TradingView 对齐）
  - 用于识别长期趋势方向
- **建议**: 保持 `200`（已优化验证）
- **用途**: 入场前过滤，确认趋势方向

---

## 🎯 交易杠杆配置

### LEVERAGE
- **类型**: Integer
- **默认值**: `10`
- **环境变量**: 不支持（在 config.py 中修改）
- **含义**: 杠杆倍数（仅在持有合约时生效）
- **范围**: 1-125 (根据交易所支持)
- **说明**:
  - `10` 表示 10 倍杠杆
  - 杠杆越高 → 所需保证金越少 → 风险越大
- **建议**: 
  - 新手: 5-10 倍
  - 中级: 10-15 倍
  - 高级: 15-20 倍
- **注意**: 杠杆过高易爆仓，请根据风险承受能力调整

---

## 💰 风险管理配置

### RISK_MODE
- **类型**: String
- **默认值**: `"fixed"`
- **环境变量**: `RISK_MODE`
- **含义**: 单笔交易风险计算模式
- **可选值**:
  - `"fixed"` - 固定金额风险
  - `"percent"` - 账户百分比风险
- **说明**:
  - **fixed 模式**: 每笔交易风险金额固定，独立于账户规模
  - **percent 模式**: 风险金额随账户余额动态变化
- **推荐**:
  - 账户 > 500 USDT: `percent` 模式
  - 账户 ≤ 500 USDT: `fixed` 模式
- **示例**:
  ```bash
  export RISK_MODE="fixed"  # 固定金额模式
  ```

### RISK_FIXED_AMOUNT
- **类型**: Float
- **默认值**: `10` USDT
- **环境变量**: `RISK_FIXED_AMOUNT`
- **含义**: 固定风险模式下单笔交易的风险金额
- **范围**: 1-1000 USDT
- **说明**:
  - 开仓时，止损点数 × 合约数 = 此金额（或更少）
  - 若风险超过此金额，则减少仓位
- **建议**:
  - 初级账户 (< 500U): 5-10 USDT
  - 中级账户 (500-2000U): 10-20 USDT
  - 高级账户 (> 2000U): 20-50 USDT
- **示例**:
  ```bash
  export RISK_FIXED_AMOUNT="10"
  ```

### RISK_PERCENT
- **类型**: Float (0.0 - 1.0)
- **默认值**: `0.02` (2%)
- **环境变量**: `RISK_PERCENT`
- **含义**: 百分比风险模式下单笔交易风险占账户的百分比
- **范围**: 0.01 (1%) - 0.05 (5%)
- **说明**:
  - 账户风险 = 当前账户 × RISK_PERCENT
  - 账户增长时风险自动增加，亏损时风险自动减少
- **建议**:
  - 保守型: 0.01 (1%)
  - 平衡型: 0.02 (2%)
  - 激进型: 0.03-0.05 (3-5%)
- **示例**:
  ```bash
  export RISK_PERCENT="0.02"  # 2%
  ```

---

## 🛡️ 熔断和冷静期配置

### CIRCUIT_BREAKER_EQUITY
- **类型**: Float
- **默认值**: `350` USDT
- **环境变量**: 不支持（在 config.py 中修改）
- **含义**: 账户本金熔断阈值
- **说明**:
  - 当账户余额 ≤ 此值时，系统停止交易（熔断）
  - 为账户保留基本资金，防止完全爆零
- **建议**:
  - 小账户 (< 1000U): 200-300 USDT
  - 中等账户 (1000-5000U): 300-500 USDT
  - 大账户 (> 5000U): 500-1000 USDT
- **工作原理**:
  ```
  如 CIRCUIT_BREAKER_EQUITY = 350:
  账户余额 500U → 继续交易
  账户余额 350U → 继续交易
  账户余额 349U → ❌ 熔断，停止交易
  ```

### MAX_CONSECUTIVE_LOSSES
- **类型**: Integer
- **默认值**: `3`
- **环境变量**: 不支持（在 config.py 中修改）
- **含义**: 连续亏损次数触发冷静期
- **范围**: 2-10
- **说明**:
  - 连续 N 次止损触发后，自动冷静 48 小时
  - 冷静期间仅发信号，不执行交易
  - 目的: 避免持续亏损加重资金损失
- **建议**:
  - 保守型: 2-3 次
  - 平衡型: 3-4 次
  - 激进型: 4-5 次
- **冷静期规则表**:
  ```
  连续1-2次止损 → 继续交易
  连续3次止损   → 冷静 48 小时 ⏳
  冷静期内止损  → 冷静时间重置为 48 小时
  冷静期结束    → 恢复正常交易
  ```

---

## 📍 锁利缓冲配置

### LOCK_PROFIT_BUFFER
- **类型**: Float
- **默认值**: `1` USDT
- **环境变量**: `LOCK_PROFIT_BUFFER`
- **含义**: 锁利期的保底盈利金额
- **范围**: 0.5-5 USDT
- **说明**:
  - 当头寸进入"锁利期"后，止损被锁定在某个位置
  - 即使立即平仓，也能保证获得最少此金额的盈利
  - 这是风险管理的"安全垫"
- **建议**:
  - 保守型: 0.5-1 USDT
  - 平衡型: 1-2 USDT
  - 激进型: 2-5 USDT
- **示例**:
  ```
  入场价: 2500 USDT
  LOCK_PROFIT_BUFFER = 1 USDT
  止损价: 2499 USDT （入场价 - 1）
  → 即使立即止损，也赚 1 USDT
  ```

---

## 🚀 自动交易开关

### ENABLE_AUTO_TRADING
- **类型**: Boolean (`true` / `false`)
- **默认值**: `"false"`
- **环境变量**: `ENABLE_AUTO_TRADING`
- **含义**: 是否启用自动交易（执行真实订单）
- **说明**:
  - `false` (默认): **模拟模式** - 仅计算信号，不执行交易
  - `true`: **自动交易模式** - 自动执行开仓、止损调整、平仓
- **建议流程**:
  ```
  第1阶段: ENABLE_AUTO_TRADING=false (1-2周)
    ↓ 验证信号准确性
  第2阶段: 小资金 + ENABLE_AUTO_TRADING=true
    ↓ 验证执行逻辑
  第3阶段: 正常资金 + ENABLE_AUTO_TRADING=true
  ```
- **示例**:
  ```bash
  export ENABLE_AUTO_TRADING="true"
  ```

---

## 🔧 交易执行配置

### AUTO_SET_STOP_LOSS
- **类型**: Boolean (`true` / `false`)
- **默认值**: `"true"`
- **环境变量**: `AUTO_SET_STOP_LOSS`
- **含义**: 开仓时是否自动设置止损单
- **说明**:
  - `true` (默认): 开仓时自动在 Gate.io 创建止损单
  - `false`: 手动管理止损（不推荐）
- **工作原理**:
  ```
  开多单 → 自动设置卖出止损单 (条件单)
  开空单 → 自动设置买入止损单 (条件单)
  ```
- **建议**: 保持 `true`（风险保护）
- **示例**:
  ```bash
  export AUTO_SET_STOP_LOSS="true"
  ```

### STOP_LOSS_MODE
- **类型**: String
- **默认值**: `"tight_only"`
- **环境变量**: `STOP_LOSS_MODE`
- **含义**: 止损调整模式
- **可选值**:
  - `"tight_only"` - 仅收紧不放松
  - `"both"` - 既可收紧也可放松
- **说明**:
  - **tight_only**: SuperTrend 变化时，新止损若更紧则执行，若更松则忽略
  - **both**: SuperTrend 变化时，无论新止损更紧还是更松都会执行
- **推荐**: `"tight_only"` （风险更低，符合"逐浪上升"策略）
- **示例**:
  ```bash
  export STOP_LOSS_MODE="tight_only"
  ```

### CLOSE_MODE
- **类型**: String
- **默认值**: `"market"`
- **环境变量**: `CLOSE_MODE`
- **含义**: 平仓订单类型
- **可选值**:
  - `"market"` - 市价单（立即成交，可能滑点）
  - `"limit"` - 限价单（可能不成交，但价格更优）
- **说明**:
  - **market**: 快速平仓，确保执行，但价格可能不理想（滑点风险）
  - **limit**: 防滑点，但行情不利时可能无法平仓
- **推荐**: `"market"`（优先确保平仓）
- **示例**:
  ```bash
  export CLOSE_MODE="market"
  ```

---

## 📨 通知配置

### NOTIFY_DETAILS
- **类型**: Boolean (`true` / `false`)
- **默认值**: `"true"`
- **环境变量**: `NOTIFY_DETAILS`
- **含义**: Telegram 通知中是否包含详细日志
- **说明**:
  - `true` (默认): 发送完整的信号分析日志
  - `false`: 仅发送简要信息
- **在模拟模式下的表现**:
  ```
  true:  📊 完整日志 - SuperTrend 值、DEMA、止损计算等
  false: 🎯 简要通知 - "开多信号" / "持仓调整" 等
  ```
- **建议**: 
  - 测试阶段: `true`（便于排查问题）
  - 生产环节: `false`（消息清晰简洁）
- **示例**:
  ```bash
  export NOTIFY_DETAILS="true"
  ```

---

## 💾 状态文件配置

### STATE_FILE
- **类型**: String
- **默认值**: `"trading_state.json"`
- **环境变量**: `STATE_FILE`
- **含义**: 本地交易状态文件路径
- **说明**:
  - 存储当前持仓信息（入场价、止损、阶段等）
  - 脚本每次运行时读取并更新
  - 用于跨运行间的状态同步
- **文件位置**:
  - 默认: 项目根目录
  - 自定义: `export STATE_FILE="/path/to/state.json"`
- **内容示例**:
  ```json
  {
    "symbol": "ETH_USDT",
    "position": "long",
    "entry_price": 2500,
    "stop_loss": 2450,
    "phase": "survival",
    "entry_time": "2026-02-21T10:30:00Z"
  }
  ```

---

## 📋 完整配置示例

### 示例 1: 保守型小账户（< 500 USDT）

```bash
# API 配置
export GATE_API_KEY="your_key_here"
export GATE_API_SECRET="your_secret_here"

# 风险管理
export RISK_MODE="fixed"
export RISK_FIXED_AMOUNT="5"
export LEVERAGE="5"  # config.py 中修改

# 冷静期
# config.py: MAX_CONSECUTIVE_LOSSES = 2
# config.py: CIRCUIT_BREAKER_EQUITY = 200

# 交易执行
export ENABLE_AUTO_TRADING="false"  # 先验证
export AUTO_SET_STOP_LOSS="true"
export STOP_LOSS_MODE="tight_only"

# 通知
export NOTIFY_DETAILS="true"
```

### 示例 2: 平衡型中等账户（500-2000 USDT）

```bash
# API 配置
export GATE_API_KEY="your_key_here"
export GATE_API_SECRET="your_secret_here"

# 风险管理
export RISK_MODE="percent"
export RISK_PERCENT="0.02"
export LEVERAGE="10"  # config.py 中修改

# 冷静期
# config.py: MAX_CONSECUTIVE_LOSSES = 3
# config.py: CIRCUIT_BREAKER_EQUITY = 400

# 交易执行
export ENABLE_AUTO_TRADING="true"
export AUTO_SET_STOP_LOSS="true"
export STOP_LOSS_MODE="tight_only"

# 通知
export NOTIFY_DETAILS="false"
```

### 示例 3: 激进型大账户（> 2000 USDT）

```bash
# API 配置
export GATE_API_KEY="your_key_here"
export GATE_API_SECRET="your_secret_here"

# 风险管理
export RISK_MODE="percent"
export RISK_PERCENT="0.03"
export LEVERAGE="15"  # config.py 中修改

# 冷静期
# config.py: MAX_CONSECUTIVE_LOSSES = 4
# config.py: CIRCUIT_BREAKER_EQUITY = 800

# 交易执行
export ENABLE_AUTO_TRADING="true"
export AUTO_SET_STOP_LOSS="true"
export STOP_LOSS_MODE="tight_only"

# 通知
export NOTIFY_DETAILS="false"
```

---

## 🔍 配置检查清单

在启动自动交易前，请检查：

- [ ] API Key 和 Secret 正确且有完整权限
- [ ] 风险模式和金额符合账户规模
- [ ] 熔断阈值设置合理
- [ ] ENABLE_AUTO_TRADING 在测试后再设为 true
- [ ] Telegram 配置正确（见 DEPLOYMENT.md）
- [ ] 本地已运行至少 1 周验证信号
- [ ] 理解风险管理规则和各个参数含义

---

## ⚠️ 常见配置错误

| 错误 | 原因 | 解决 |
|------|------|------|
| 交易亏损过多 | 杠杆过高或风险金额设置过大 | 降低 LEVERAGE 和 RISK 参数 |
| 频繁熔断 | CIRCUIT_BREAKER_EQUITY 设置过高 | 合理调降熔断阈值或优化交易逻辑 |
| 收不到通知 | NOTIFY_DETAILS 不影响通知发送 | 检查 Telegram 配置（DEPLOYMENT.md） |
| 止损不变 | STOP_LOSS_MODE="both" 时可能忽略松动 | 改为 "tight_only" 或检查 ST 指标 |

---

## 📞 需要帮助？

- 查看 [QUICK_START.md](QUICK_START.md) - 快速开始指南
- 查看 [DEPLOYMENT.md](DEPLOYMENT.md) - 部署和运行指南
- 查看 [SIGNAL_LOGIC_QUICK_REFERENCE.md](SIGNAL_LOGIC_QUICK_REFERENCE.md) - 信号逻辑参考
