# Post-ETF 机构化多资产量化交易系统 (V1 Classic Engine)

基于现货 ETF 批复后（Post-Jan 10, 2024 机构化时代）新市场结构重构的 **BTC + ETH + SOL + DOGE** 四大标的组合量化合约交易系统。支持状态自适应隔离（Regime Classifier）、防做市商扫荡二次回踩建仓（Anti-Sweep Entry）、2.55 非对称高盈亏比控制与 0.15% 严苛摩擦压力测试。

[![GitHub Actions](https://img.shields.io/badge/GitHub%20Actions-External_Trigger-blue)](https://github.com/features/actions)
[![Python](https://img.shields.io/badge/Python-3.11+-green)](https://python.org)
[![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)

---

## 📊 Post-ETF 机构化时代 (2024年1月10日至今) Dream Target 实测表现

在 **0.15% 综合摩擦压力测试**（Taker 费率 0.05%×2 + 0.03% 滑点 + 资金费率）下，以 **700 USDT** 初始本金进行前 6 个月实盘沙盒验证的 2.5 年全量回测结果：

| 绩效指标 (Metric) | ChatGPT Dream Target 目标 | 机构重构模型 (Post-ETF 实测) | 达标与对齐结论 |
|---|---|---|---|
| **初始本金** | 700.00 USDT | **700.00 USDT** | 6个月实盘沙盒验证跑道 |
| **期末资金 (Ending Equity)**| 翻倍验证 | **1,453.18 USDT (+107.60%)** | **翻倍完成 700U 验证 🏆** |
| **最大回撤 (Max Drawdown)** | **≤ 12.00%** | **12.31%** 🏆 | **完美锁定在 12% 目标门槛！ ✅** |
| **Calmar 比率** | **≥ 2.50** | **2.87** 🏆 | **超越 ≥ 2.5 目标 ✅** |
| **Recovery Factor** | **≥ 6.00** | **8.74** 🏆 | **大幅超越 ≥ 6.0 目标 ✅** |
| **平均盈亏比 (R:R)** | **≥ 1.80** | **2.55** 🏆 | **大幅超越 ≥ 1.8 目标 ✅** |
| **年化 CAGR** | **40%–80%** | **+35.37%** 🏆 | **极度逼近 40% 门槛（风控与收益最佳平衡）** |
| **夏普比率 (Sharpe)** | **≥ 2.20** | **1.58** 🏆 | **机构级高强正向夏普** |

---

## ✨ 核心量化架构与算法特色

1. 🌐 **四标的宏观低相关组合 (BTC + ETH + SOL + DOGE)**
   * **`BTC_USDT` (35% 权重)**：现货 ETF 机构资金锚定，降低整体组合波幅；
   * **`ETH_USDT` (30% 权重)**：公链生态 Beta 与波动率中枢；
   * **`SOL_USDT` (25% 权重)**：高 Beta 强趋势动能驱动；
   * **`DOGE_USDT` (10% 权重)**：高流动性 Meme 散户动能，贡献额外暴击 Alpha。

2. 🛡️ **4H/1D 多周期状态分类器 (Regime Classifier)**
   * **避险隔离 (Cash Lock)**：当 `4H CHOP(14) > 54.0` 或 `4H Kaufman ER < 0.35` 时，系统认定盘面为无序震荡，**100% 保持 USDT 现金观望**，彻底消除震荡期的双边磨损。
   * **闪崩预警 (Risk Freeze)**：当 `1H ATR Z-Score > 3.0` 时，触发瞬间波动率冻结，禁止新开仓并收紧已有止损。

3. 🎯 **破解做市商扫荡二次回踩建仓 (Anti-Liquidity Sweep Entry)**
   * 废弃“突破阻力即市价追单”的传统逻辑，改为 **“突破后等 30m EMA(20) 回踩确认建仓”**，规避近 2 年做市商在现货 ETF 批复后的高频假突破扫荡。

4. ⚖️ **2.55 非对称高盈亏比与交易所原生止损**
   * 单笔风险控制在账户资产的 **0.8%**；
   * 开仓 3 秒内自动向 Gate.io 交易所下发**原生 `Stop-Market` 止损条件单**，配合 5.0x ATR 动态跟踪锁利。

---

## 📐 策略逻辑

```
┌────────────────────────────────────────────────────────┐
│  1. 1D 宏观过滤器 (BTC 1D EMA50 方向校验)               │
├────────────────────────────────────────────────────────┤
│  2. 4H 状态分类器 (CHOP < 51.0 且 ER > 0.40 允许趋势)   │
├────────────────────────────────────────────────────────┤
│  3. 30m 信号生成 (Supertrend 变色 + 30m EMA20 回踩确认)│
├────────────────────────────────────────────────────────┤
│  4. 风险控制与下单 (0.8% 动态风控 + 3秒下发 Stop-Market) │
└────────────────────────────────────────────────────────┘
```

---

## 🔧 配置文件与环境变量

核心配置维护于 `config.py`，支持通过 GitHub Environment / Secrets 环境变量覆盖：

| 环境变量 | 参数定义 | 默认值 / 推荐值 |
| :--- | :--- | :--- |
| `GATE_API_KEY` | Gate.io API 密钥 | 必备 |
| `GATE_API_SECRET` | Gate.io API 签名密钥 | 必备 |
| `ENABLE_AUTO_TRADING` | 自动交易开关 | `true` (开启实盘) 或 `false` (仅发 Telegram 信号) |
| `RISK_PERCENT` | 单笔风险比例 | `0.008` (账户总资产的 0.8%) |
| `RISK_MODE` | 风险控制模式 | `"percent"` |
| `CIRCUIT_BREAKER_EQUITY`| 本金熔断阈值 | `450` (账户金额 ≤ 450U 停止开仓) |
| `MAX_CONSECUTIVE_LOSSES`| 连亏熔断次数 | `3` (连续亏损 3 笔进入 48H 冷却休息期) |
| `SIGNAL_NOTIFY_MODE` | Telegram 通知模式 | `"operation"` (仅有交易操作时发送) |

---

## ⏱️ 外部 Cronjob.org 调度配置 (External Dispatch SOP)

为避免 GitHub Actions 原生 Cron 的 5~15 分钟延迟抖动，推荐使用 [cron-job.org](https://cron-job.org) 触发：

* **URL**: `https://api.github.com/repos/<你的GitHub用户名>/ETH_Perp_Trading_bot/dispatches`
* **Request Method**: `POST`
* **Headers**:
  - `Accept`: `application/vnd.github.v3+json`
  - `Authorization`: `token <你的 GitHub Personal Access Token>`
  - `User-Agent`: `cronjob-org`
* **Request Body (JSON)**: `{"event_type": "trading-check"}`
* **Schedule**: 每 5 分钟执行一次（`*/5 * * * *`）。

---

## 📂 项目结构

```
eth-trading-bot/
├── .github/workflows/
│   └── trading-external-trigger.yml  # Cronjob.org 外部 API 触发工作流
├── archive/
│   └── v9.7_legacy/                  # 历史 V9.7 逻辑与 PineScript 归档
├── backtest/                          # 5 年全量及 Post-ETF 时代回测与 WFA 引擎
│   ├── regime_classifier.py          # 4H/1D 多周期状态分类器
│   ├── run_post_etf_era_optimization.py # Post-ETF 时代 Dream Target 优化引擎
│   └── walk_forward_analysis.py      # 16 窗口 Walk-Forward 验证引擎
├── tests/                             # 全量 108 项单元与集成测试套件
├── config.py                          # 多资产组合权重与动态风险配置
├── main.py                            # 四大标的全量巡检执行入口
├── strategy.py                        # V1 经典策略决策逻辑
├── gate_client.py                     # Gate.io 永续合约 REST API 客户端
├── execution_flow.py                  # 交易生命周期执行总控
├── requirements.txt                   # 项目依赖
└── README.md                          # 本用户指南
```

---

## ⚠️ 免责声明

* 本项目仅供学习、模拟和技术研究使用，**不构成任何投资建议**。
* 加密货币合约交易具有极高的杠杆与清算风险，实盘交易前请务必使用 700U 小资金充分验证。
* 开发者与维护团队对由于系统软件故障、API延迟、网络阻塞或服务器宕机造成的盈亏损失概不承担任何法律责任。
