# ETH SuperTrend Trading Bot

基于 SuperTrend V9.6 策略的 ETH/USDT 合约交易信号监控系统。

[![GitHub Actions](https://img.shields.io/badge/GitHub%20Actions-Scheduled-blue)](https://github.com/features/actions)
[![Python](https://img.shields.io/badge/Python-3.11+-green)](https://python.org)
[![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)

## ✨ 功能特点

- 🎯 **精准信号** - SuperTrend + DEMA200 双重过滤，减少假信号
- 📊 **多周期协同** - 1H 趋势过滤 + 30m 入场时机
- 🔒 **智能止损** - 三阶段持仓管理（生存期→锁利期→换轨期）
- ⚡ **实时通知** - Telegram 即时推送交易信号
- 🤖 **自动调度** - GitHub Actions 每 30 分钟检查
- 🛡️ **风险控制** - 连亏熔断 + 本金保护机制

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

## � 文档导航

| 文档 | 用途 |
|------|------|
| [DEMA_QUICK_CHECKUP.md](DEMA_QUICK_CHECKUP.md) | **🔍 DEMA值差异快速排查** |
| [DEMA_DIAGNOSIS_REPORT.md](DEMA_DIAGNOSIS_REPORT.md) | 完整诊断报告和解决方案 |
| [DEMA_DIFFERENCE_DIAGNOSIS.md](DEMA_DIFFERENCE_DIAGNOSIS.md) | 详细诊断指南 |
| [LOGGING_ENHANCEMENT_GUIDE.md](LOGGING_ENHANCEMENT_GUIDE.md) | 日志系统说明 |
| [SIGNAL_FIX_GUIDE.md](SIGNAL_FIX_GUIDE.md) | 信号计算指南 |
| [STOP_LOSS_TRACKING_SOLUTION.md](STOP_LOSS_TRACKING_SOLUTION.md) | 止损追踪说明 |

## �🚀 快速开始

### 1. 克隆仓库

```bash
git clone https://github.com/yourusername/eth-trading-bot.git
cd eth-trading-bot
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 配置环境变量

```bash
export GATE_API_KEY="your_gate_api_key"
export GATE_API_SECRET="your_gate_api_secret"
export TELEGRAM_BOT_TOKEN="your_telegram_bot_token"
export TELEGRAM_CHAT_ID="your_telegram_chat_id"
```

### 4. 运行

```bash
python main.py
```

## ⚙️ 配置参数

编辑 `config.py` 自定义参数：

```python
# 交易对
CONTRACT = "ETH_USDT"

# SuperTrend 参数
SUPERTREND_PERIOD = 10
SUPERTREND_MULTIPLIER = 3.0

# DEMA 周期
DEMA_PERIOD = 200

# 杠杆倍数
LEVERAGE = 10

# 风险参数
FIXED_RISK_AMOUNT = 10.0      # 固定风险金额
RISK_PERCENT = 0.02           # 百分比风险 (2%)
CIRCUIT_BREAKER_EQUITY = 350  # 熔断本金阈值
MAX_CONSECUTIVE_LOSSES = 3    # 最大连续亏损次数
LOCK_PROFIT_BUFFER = 1.0      # 锁利缓冲 (U)
```

## 🔔 Telegram 通知设置

### 创建 Bot

1. 在 Telegram 中找到 [@BotFather](https://t.me/BotFather)
2. 发送 `/newbot` 创建新 Bot
3. 保存获得的 Bot Token

### 获取 Chat ID

1. 向你的 Bot 发送任意消息
2. 访问: `https://api.telegram.org/bot<TOKEN>/getUpdates`
3. 在返回的 JSON 中找到 `chat.id`

## 🤖 GitHub Actions 自动化

### 配置 Secrets

在仓库 **Settings → Secrets and variables → Actions** 添加：

| Secret | 说明 |
|--------|------|
| `GATE_API_KEY` | Gate.io API Key |
| `GATE_API_SECRET` | Gate.io API Secret |
| `TELEGRAM_BOT_TOKEN` | Telegram Bot Token |
| `TELEGRAM_CHAT_ID` | Telegram Chat ID |

### 调度频率

默认每 30 分钟运行一次（整点和半点）。

修改 `.github/workflows/trading.yml` 中的 cron 表达式可调整频率。

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
├── .github/
│   └── workflows/
│       └── trading.yml      # GitHub Actions 配置
├── config.py                # 策略参数配置
├── gate_client.py           # Gate.io API 客户端
├── indicators.py            # 技术指标 (SuperTrend, DEMA)
├── strategy.py              # 交易策略核心逻辑
├── cooldown.py              # 冷静期检查
├── telegram_notifier.py     # Telegram 通知
├── main.py                  # 主程序入口
├── requirements.txt         # Python 依赖
└── README.md
```

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
