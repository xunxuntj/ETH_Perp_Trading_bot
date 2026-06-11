# Multi-Asset SuperTrend Portfolio Trading Bot (V10.0)

基于 SuperTrend V10.0 策略的 **BTC_USDT & ETH_USDT 双核心资产**量化合约交易系统。支持账户级别投资组合风险管理、资产动态调参、动态盈亏比控制与统一大盘报告。

[![GitHub Actions](https://img.shields.io/badge/GitHub%20Actions-Scheduled-blue)](https://github.com/features/actions)
[![Python](https://img.shields.io/badge/Python-3.11+-green)](https://python.org)
[![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)

---

## ✨ V10.0 核心功能与亮点

- 📈 **多币种组合并列交易 (BTC + ETH)**
  - 支持双核心标的在 GitHub Actions / 外部定时器中**并行独立轮询**。
  - 使用独立的数据库状态文件 (`trading_state_btc_usdt.json` / `trading_state_eth_usdt.json`) 避免状态污染。
- 🎯 **资产自适应调参 (Dynamic Adaptation)**
  - 自动识别合约交易对名称，切换最佳参数特征以贴合币种走势特性。
  - **BTC**: DEMA 200 确认，ADX ≥ 35 强趋势过滤，**22.0R 极限止盈**（捕捉宏观趋势）。
  - **ETH**: DEMA 150 确认，ADX ≥ 30 波动过滤，**5.0R 动态止盈**（防范利润冲高回吐）。
- 📊 **统一组合大盘报告 (Consolidated Daily Report)**
  - 取代原单币分立报告，输出包含账户组合总资金曲线（Portfolio Equity）以及 BTC / ETH 各自贡献度的三曲线互动折线图。
  - 提供多标的并排性能对比表，集中审计滑点税（Slippage Tax）与资金费率（Funding Fee）损耗。
  - 提供单页交互 HTML（支持 All/BTC/ETH 交易记录筛选），配合每日 Telegram 推送。
- 🛡️ **强化型资产风控官 (Risk Management)**
  - 支持固定风险金额（默认 5U）或账户比例风险（如 1.5%）的自适应仓位计算。
  - 账户连亏熔断暂停（连续 3 次亏损停手 48 小时）在多资产中并行运作。
  - 本金跌破 450U 自动触发熔断熔断停笔。
- 📺 **TradingView Pine 脚本同步仿真**
  - 内置 TradingView [仿真回测脚本](tradingview_strategy_v10_0.pine)，指标、止损、锁利与动态止盈机制与 Python 实盘逻辑 100% 对齐，支持自适应 Ticker 切换与 30m/1H 兼容。

---

## 📐 策略逻辑

### 入场与过滤机制

策略在 **信号周期**（30m 或 1H）上产生进出场信号，在 **高时区周期**（1H 或 4H）上做趋势与波动强度过滤。

| 标的 (Symbol) | 信号周期 | 高时区周期 | DEMA 过滤周期 | ADX 过滤阈值 | 动态止盈倍数 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **BTC_USDT** | 30m | 1H | 200 | 35.0 (30m) | **22.0R** |
| **ETH_USDT** | 30m | 1H | 150 | 30.0 (30m) | **5.0R** |

* **做多入场条件**：高时区 ST 呈绿线 ＋ 高时区收盘价 > DEMA ＋ 信号时区 ST 由红转绿 ＋ 信号时区 ADX > 阈值。
* **做空入场条件**：高时区 ST 呈红线 ＋ 高时区收盘价 < DEMA ＋ 信号时区 ST 由绿转红 ＋ 信号时区 ADX > 阈值。

### 动态 Take Profit (止盈) 机制
当仓位成交后，根据入场点与初始止损位（即入场时刻的信号周期 SuperTrend 线）计算一倍风险距离（$1\text{R}$）：
$$\text{sl\_dist} = |\text{entry\_price} - \text{initial\_30m\_st}|$$
* **做多限价止盈位**: $\text{entry\_price} + \text{TP\_RATIO} \times \text{sl\_dist}$
* **做空限价止盈位**: $\text{entry\_price} - \text{TP\_RATIO} \times \text{sl\_dist}$
*(BTC 放大至 22.0R 极限捕捉大牛市趋势，ETH 设定为 5.0R 防止深幅回调)*

### 3 阶段持仓管理
```
┌────────────────────────────────────────────────────────┐
│  生存期 (Survival Phase: 30m ST 托管)                    │
│  ├─ 止损: 跟随信号周期 ST，只紧不松                     │
│  └─ 触发锁利: 盘面利润达到 1R 的 lock_profit_buffer 比例  │
├────────────────────────────────────────────────────────┤
│  锁利期 (Lock Profit Phase: 锁定保底利润)                │
│  ├─ 止损: 锁死在保底利润位（入场价 ± 0.5R 缓冲利润）      │
│  └─ 触发换轨: 高时区 ST 指标价格超越锁利价位            │
├────────────────────────────────────────────────────────┤
│  换轨期 (Track Phase: 高时区 ST 托管)                    │
│  ├─ 止损: 换轨到大周期，跟随高时区 ST 价格移动，只紧不松 │
│  └─ 离场: 高时区 ST 发生趋势变色，或盘面触及动态限价止盈  │
└────────────────────────────────────────────────────────┘
```

---

## 🔧 核心参数与配置文件

参数可在 `config.py` 中查阅，也支持通过 GitHub Environment 环境变量进行灵活覆写。

| 环境变量 | 参数定义 | V10.0 推荐值 / 默认值 |
| :--- | :--- | :--- |
| `ENABLE_AUTO_TRADING` | 自动交易开关 | `false`（默认仅发 Telegram 信号，设为 `true` 执行实盘下单） |
| `RISK_MODE` | 仓位风险控制模式 | `"fixed"` (固定U模式) 或 `"percent"` (百分比复利模式) |
| `RISK_FIXED_AMOUNT` | 单笔固定风险额 | `5` (每单止损最大亏损 5 USDT) |
| `RISK_PERCENT` | 单笔百分比风险度 | `0.015` (1.5% 账户权益) |
| `CIRCUIT_BREAKER_EQUITY`| 本金熔断阈值 | `450` (账户金额 ≤ 450U 停止一切开仓) |
| `MAX_CONSECUTIVE_LOSSES`| 连亏熔断次数 | `3` (连续亏损 3 笔进入 48H 冷却休息期) |
| `LOCK_PROFIT_BUFFER` | 保底锁定系数 | `0.5` (达到解锁条件后锁死 0.5R 的风险利润) |
| `REPORT_START_TIME` | 报告默认初始日期 | `"2026-06-10 15:00"` (精确到小时，自动按 UTC+8 对齐) |

---

## 📂 项目结构

```
eth-trading-bot/
├── .github/workflows/
│   ├── trading.yml              # 双资产（BTC+ETH）并行交易核查工作流
│   ├── trading-external-trigger.yml  # 外部 API 触发专用工作流
│   └── report.yml               # 统一每日投资组合大盘报告工作流
├── templates/
│   ├── report_template.html     # 单资产评估模板（历史留存）
│   └── portfolio_report_template.html # 组合大盘三曲线交互报告模板 [NEW]
├── tests/                       # 单元与系统集成测试套件
│   ├── test_dynamic_config.py   # BTC/ETH 动态调参自适应测试
│   ├── test_strategy_logic.py   # 3阶段持仓止损与 TP 触发测试  
│   └── ...
├── config.py                    # 策略核心参数配置与自适应逻辑
├── gate_client.py               # Gate.io 全仓账户及合约交易 API 客户端
├── strategy.py                  # 策略核心决策逻辑（含 22.0R/5.0R 限价止盈控制）
├── execution_flow.py            # 单资产交易生命周期执行总控
├── generate_portfolio_report.py # 账户级组合报告生成引擎 [NEW]
├── tradingview_strategy_v10_0.pine # TradingView 双币自适应仿真脚本 [NEW]
├── requirements.txt             # 项目第三方依赖库
└── README.md                    # 本用户指南
```

---

## ⏱️ 快速启动

1. **环境准备**
   ```bash
   git clone https://github.com/yourusername/eth-trading-bot.git
   cd eth-trading-bot
   pip install -r requirements.txt
   ```

2. **环境变量注入 (开发环境测试)**
   ```bash
   export GATE_API_KEY="your_api_key"
   export GATE_API_SECRET="your_api_secret"
   export TELEGRAM_BOT_TOKEN="your_bot_token"
   export TELEGRAM_CHAT_ID="your_chat_id"
   
   # 本地测试单次运行 (模拟信号模式)
   $env:SYMBOL="BTC_USDT"; python main.py
   $env:SYMBOL="ETH_USDT"; python main.py
   ```

3. **离线运行测试报告**
   ```bash
   # 测试统一双币战报生成
   python scratch/test_portfolio_report.py
   ```

---

## 🛡️ 部署指南 (GitHub Actions 推荐)

1. **Fork 本仓库** 并进入 Settings -> Secrets and variables -> Actions。
2. 添加以下必需的 Repository Secrets：
   * `GATE_API_KEY`：您的 Gate.io API 密钥
   * `GATE_API_SECRET`：您的 Gate.io API 签名密钥
   * `TELEGRAM_BOT_TOKEN`：通知机器人的 Token
   * `TELEGRAM_CHAT_ID`：您的 Telegram 接收 Chat ID
3. 启用工作流：进入 Actions 页面，激活 **Generate Strategy Evaluation Report** 与 **ST Breakout Loop**，定时任务将完全托管运行。

---

## ⚠️ 免责声明

* 本项目仅供学习、模拟和技术研究使用，**不构成任何投资建议**。
* 加密货币合约交易具有极高的杠杆与清算风险，实盘交易前请务必使用小资金充分验证。
* 编写及维护团队对由于系统软件故障、API延迟、网络阻塞或服务器宕机造成的盈亏损失概不承担任何法律责任。
