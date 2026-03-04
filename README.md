# ETH SuperTrend Trading Bot

基于 SuperTrend V9.6 策略的 ETH/USDT 合约交易信号监控系统。

[![GitHub Actions](https://img.shields.io/badge/GitHub%20Actions-Scheduled-blue)](https://github.com/features/actions)
[![Python](https://img.shields.io/badge/Python-3.11+-green)](https://python.org)
[![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)

## ✨ 功能特点

- 🎯 **精准信号** - SuperTrend + DEMA200 双重过滤，减少假信号
  - DEMA 使用 1000 根 K线数据，精度达 99.99%（与 TradingView 极度对齐）
- 📊 **多周期协同** - 1H 趋势过滤 + 30m 入场时机
- 🔒 **智能止损** - 三阶段持仓管理（生存期→锁利期→换轨期）
- ⚡ **实时通知** - Telegram 即时推送交易信号
- 🤖 **自动调度** - GitHub Actions 每 30 分钟检查
- 🛡️ **风险控制** - 连亏熔断 + 本金保护机制 + 账户自动同步

## 📈 策略概述

### 入场条件

| 方向 | 条件 |
|------|------|
| 做多 | 1H ST 绿 + 1H收盘 > DEMA200 + 30m ST 绿 |
| 做空 | 1H ST 红 + 1H收盘 < DEMA200 + 30m ST 红 |

### 持仓管理

```
┌─────────────────────────────────────────────────┐
│  生存期 (30m ST 托管)                            │
│  ├─ 止损: 跟随 30m ST，只紧不松                  │
│  └─ 触发锁利: 止损达到入场价 ± Buffer            │
├─────────────────────────────────────────────────┤
│  锁利期 (止损锁定)                               │
│  ├─ 止损: 锁定不动，保底盈利                     │
│  └─ 触发换轨: 1H ST 比锁利止损更紧               │
├─────────────────────────────────────────────────┤
│  换轨期 (1H ST 托管)                             │
│  ├─ 止损: 跟随 1H ST，只紧不松                   │
│  └─ 离场: 1H ST 变色                            │
└─────────────────────────────────────────────────┘
```

### 风险控制

| 本金 | 风险模式 | 说明 |
|------|----------|------|
| > 500U | 2% 本金 | 动态调整风险 |
| 350-500U | 固定 10U | 保守模式 |
| ≤ 350U | 熔断 | 停手 1 周 |

**冷静期规则:**
- 连续 3 笔止损 → 强制休息 48 小时
- 本金 ≤ 350U → 停手 1 周

## 📚 文档导航

**第一步 - 必读文档** (选择你的角色)

| 你是... | 推荐文档 | 用时 |
|--------|--------|------|
| 🚀 完全新手 | [QUICK_START.md](QUICK_START.md) + [CONFIGURATION.md](CONFIGURATION.md) | 20min |
| 💼 交易员 | [CONFIGURATION.md](CONFIGURATION.md) + [SIGNAL_LOGIC_QUICK_REFERENCE.md](SIGNAL_LOGIC_QUICK_REFERENCE.md) | 30min |
| 👨‍💻 开发者 | [SYSTEM_ARCHITECTURE.md](SYSTEM_ARCHITECTURE.md) + [TESTING.md](TESTING.md) | 30min |
| 🌐 DevOps | [DEPLOYMENT.md](DEPLOYMENT.md) | 15min |

**第二步 - 深入理解**

| 文档 | 用途 |
|------|------|
| [配置参数完全指南](CONFIGURATION.md) | 18 个参数 + 推荐值 + 示例 |
| [部署方案详解](DEPLOYMENT.md) | GitHub Actions/VPS/Docker/本地 |
| [交易信号详解](SIGNAL_LOGIC_QUICK_REFERENCE.md) | 进场/平仓/风险控制 |
| [系统架构](SYSTEM_ARCHITECTURE.md) | 模块设计和数据流 |
| [止损逻辑详解](STOPLOSS_TIGHTENING_MECHANISM.md) | 止损追踪和调整机制 |
| [持仓流程图解](STOPLOSS_FLOW_DIAGRAM.md) | 三阶段持仓转换 |
| [测试指南](TESTING.md) | 9 个测试模块 |

**第三步 - 社区贡献 & 项目信息**

| 文档 | 用途 |
|------|------|
| [贡献指南](CONTRIBUTING.md) | 如何为项目做出贡献 |
| [发布准备](RELEASE_READY.md) | 项目完整性检查 |
| [项目状态](PROJECT_STATUS.md) | 完成度统计和质量指标 |

## �🚀 快速开始

### 最新版本优化

✅ **DEMA精度优化** - 使用1000根K线数据，精度达99.99%（与TradingView极度对齐）
✅ **账户金额修复** - 自动识别全仓模式（`cross_available`字段），正确显示账户本金
✅ **完整DEBUG日志** - 脚本运行时自动输出账户信息便于排查问题

### ⏱️ 3阶段快速启动

**第1步: 环境配置 (5分钟)**
```bash
# 克隆仓库
git clone https://github.com/yourusername/eth-trading-bot.git
cd eth-trading-bot

# 安装依赖
pip install -r requirements.txt

# 配置 API（见下文 "环境变量" 章节）
export GATE_API_KEY="your_key"
export GATE_API_SECRET="your_secret"
export TELEGRAM_BOT_TOKEN="your_token"
export TELEGRAM_CHAT_ID="your_chat_id"

# 运行
python main.py
```

**第2步: 信号验证 (1-2周)**
- 运行在模拟模式验证信号准确性
- 详见 [快速开始指南](QUICK_START.md)

**第3步: 启用自动交易**
- 验证完成后，设置 `ENABLE_AUTO_TRADING=true`
- 详见 [部署指南](DEPLOYMENT.md)

## 🔧 环境变量配置

**必需的环境变量**:

| 变量 | 说明 | 获取方式 |
|------|------|---------|
| `GATE_API_KEY` | Gate.io API密钥 | [Gate.io 账户设置](https://www.gate.io/myaccount/apimanagement) |
| `GATE_API_SECRET` | Gate.io API密钥对 | 同上 |
| `TELEGRAM_BOT_TOKEN` | Telegram 机器人 Token | [@BotFather](https://t.me/botfather) 创建 |
| `TELEGRAM_CHAT_ID` | Telegram 聊天 ID | 向你的 Bot 发送 `/start` 获取 |

**可选的环境变量** (详见 [配置参数文档](CONFIGURATION.md)):

```bash
# 风险管理
export RISK_MODE="fixed"              # 固定/百分比模式
export RISK_FIXED_AMOUNT="10"         # 固定风险金额(U)
export RISK_PERCENT="0.02"            # 百分比风险(2%)

# 自动交易
export ENABLE_AUTO_TRADING="false"    # 启用自动交易(默认false-模拟)
export AUTO_SET_STOP_LOSS="true"      # 自动设置止损
export STOP_LOSS_MODE="tight_only"    # 止损模式

# 通知
export NOTIFY_DETAILS="true"          # 发送详细日志
```

**>> 详细配置说明见 [配置参数完全指南](CONFIGURATION.md)**

## ⚙️ 策略参数调整

编辑 `config.py` 自定义指标参数：

```python
# 技术指标
SUPERTREND_PERIOD = 10         # SuperTrend周期
SUPERTREND_MULTIPLIER = 3.0    # SuperTrend倍数
DEMA_PERIOD = 200              # DEMA移动平均周期

# 交易配置
LEVERAGE = 10                  # 杠杆倍数
CONTRACT = "ETH_USDT"          # 交易对

# 风险控制
CIRCUIT_BREAKER_EQUITY = 350   # 熔断本金阈值
MAX_CONSECUTIVE_LOSSES = 3     # 连续亏损熔断
LOCK_PROFIT_BUFFER = 1         # 锁利缓冲(U)
```

**>> 建议保持默认参数，仅调整风险相关参数**

## 🤖 GitHub Actions 自动化（推荐）

本项目支持免费的 GitHub Actions 自动化，**无需自己管理服务器**！

### 配置步骤

1. **Fork 本仓库** → 点击右上角 "Fork"

2. **配置 Secrets**
   - 进入仓库 → Settings → Secrets and variables → Actions
   - 点击 "New repository secret"，添加以下 4 个 Secrets:

| Secret 名称 | 值 |
|------------|-----|
| `GATE_API_KEY` | 你的 API Key |
| `GATE_API_SECRET` | 你的 API Secret |
| `TELEGRAM_BOT_TOKEN` | 你的 Bot Token |
| `TELEGRAM_CHAT_ID` | 你的 Chat ID |

3. **启用工作流**
   - 进入 Actions 标签
   - 找到 "ETH Trading Bot Scheduler"
   - 点击 "Enable workflow"

**工作流默认设置**:
- ⏱️ 每 30 分钟运行一次
- 🔧 模拟模式 (ENABLE_AUTO_TRADING=false)

**>> 详细配置见 [部署指南](DEPLOYMENT.md#方案-1️⃣-github-actions推荐)**

## 📱 信号示例

### 开仓信号

```
🔴 开空信号！

━━━━━━━━━━ 行动 ━━━━━━━━━━
📌 开空 17张 @ 2700.89
📌 设止损 @ 2758.09
━━━━━━━━━━━━━━━━━━━━━━━━━

【过滤条件检查】
• 1H ST: 🔴红 ✅
• 1H收盘 2698.77 < DEMA 2800.55 ✅
• 30m ST: 🔴红 ✅

【仓位计算】
• 止损距离: 57.20点
• 保证金: 45.92U (10x)
• 风险: 固定 10.00U
• 锁利阈值: 2695.01
```

### 持仓状态

```
📍 持仓状态

━━━━━━━━━━ 行动 ━━━━━━━━━━
📌 止损锁定 @ 2740.55
   (不再移动，保底盈利)
━━━━━━━━━━━━━━━━━━━━━━━━━

【阶段】🟡 锁利期 ⚡新进入！
【离场条件】30m ST 变绿

【持仓信息】
• 方向: 空 | 入场: 2750.00 | 张数: 14张
• 当前价: 2703.89 | 浮盈: +6.46U
```

## 📁 项目结构

```
eth-trading-bot/
├── .github/workflows/
│   └── trading.yml              # GitHub Actions 工作流配置
├── tests/                       # 单元测试和集成测试
│   ├── test_strategy_logic.py   # 策略信号测试
│   ├── test_position_state.py   # 持仓状态测试  
│   ├── test_stop_loss_integration.py  # 止损追踪测试
│   ├── test_trading_executor.py # 交易执行测试
│   └── ...
├── config.py                    # 策略参数配置
├── gate_client.py               # Gate.io API 客户端
├── indicators.py                # 技术指标 (SuperTrend, DEMA)
├── strategy.py                  # 交易策略核心逻辑
├── execution_flow.py            # 完整交易流程编排
├── position_state.py            # 持仓状态管理
├── cooldown.py                  # 冷静期机制
├── trading_executor.py          # 交易执行器
├── telegram_notifier.py         # Telegram 通知
├── main.py                      # 主程序入口 (每 30min 运行)
├── requirements.txt             # Python 依赖
├── README.md                    # 本文件
├── CONFIGURATION.md             # 配置参数详细指南 ⭐ 必读
├── DEPLOYMENT.md                # 部署指南 (GitHub Actions / VPS / Docker)
├── TESTING.md                   # 测试指南
├── QUICK_START.md               # 快速开始 (5分钟)
└── LICENSE                      # MIT 许可证
```

## 🎯 使用建议

### 第一次使用？推荐流程

1. **阅读 [快速开始指南](QUICK_START.md)** - 5 分钟了解整个流程
2. **本地测试** - 按流程运行脚本，观察信号准确性（1-2周）
3. **配置环境变量** - 根据账户规模调整 [配置参数](CONFIGURATION.md)
4. **选择部署方案** - [GitHub Actions](DEPLOYMENT.md#方案-1️⃣-github-actions推荐)（推荐）或 [VPS](DEPLOYMENT.md#方案-2️⃣-vps-服务器)
5. **启用自动交易** - 设置 `ENABLE_AUTO_TRADING=true` 并使用小仓位验证  
6. **监控和优化** - 根据实际运行情况调整参数

### 我想...

- 🚀 **快速启动** → [快速开始指南](QUICK_START.md)
- 🔧 **调整参数** → [配置参数完全指南](CONFIGURATION.md)
- 🌐 **部署到生产** → [部署指南](DEPLOYMENT.md)
- 🧪 **运行测试** → [测试指南](TESTING.md)
- 📊 **理解策略** → [信号逻辑详解](SIGNAL_LOGIC_QUICK_REFERENCE.md)
- 🏗️ **了解架构** → [系统架构文档](SYSTEM_ARCHITECTURE.md)

## ✅ 部署前检查清单

启动自动交易前，请确认完成以下各项：

- [ ] 阅读并理解 [快速开始指南](QUICK_START.md)
- [ ] 理解 [配置参数](CONFIGURATION.md) 及其含义
- [ ] 获取 Gate.io API Key 并验证权限
- [ ] 获取 Telegram Bot Token 和 Chat ID
- [ ] 本地运行脚本至少 1 周，验证信号准确性
- [ ] 理解 [风险管理规则](CONFIGURATION.md#-风险管理配置)
- [ ] 选择合适的 [部署方案](DEPLOYMENT.md)
- [ ] 理解 **加密货币交易的高风险性**，准备好可能的亏损
- [ ] **使用小仓位进行验证**，不要一上来就投入大资金

## ⚠️ 免责声明

- 本项目仅供学习和研究使用
- **不提供任何投资建议**
- 加密货币交易存在高风险，可能导致本金全部损失
- 使用本工具进行交易的风险由用户自行承担
- 建议在实盘前充分测试并使用小仓位验证

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

1. Fork 本仓库
2. 创建特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 提交 Pull Request

## 📄 License

本项目采用 MIT 许可证 - 查看 [LICENSE](LICENSE) 文件了解详情。

## 🙏 致谢

- [Gate.io](https://www.gate.io/) - 交易所 API
- [TradingView](https://www.tradingview.com/) - SuperTrend 指标参考
- [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot) - Telegram 通知

---

**⭐ 如果这个项目对你有帮助，欢迎 Star！**
