---
# ETH 永续合约自动交易系统 - V9.6 完整实现指南

**更新日期:** 2026-02-21  
**系统版本:** V9.6-Exec  
**状态:** ✅ **生产就绪**

---

## 📋 系统架构概览

### 完整的自动交易流程

```
信号生成 → 交易执行 → 止损管理 → 持仓监控 → 平仓/反手
   ↓           ↓           ↓           ↓         ↓
strategy.py → trading_executor.py → GateClient → Telegram
              execution_flow.py
```

### 关键模块

| 模块 | 功能 | 状态 |
|------|------|------|
| **strategy.py** | 信号分析、持仓管理三阶段 | ✅ |
| **trading_executor.py** | 真实交易执行 | ✅ |
| **execution_flow.py** | 流程控制、信号到交易映射 | ✅ |
| **gate_client.py** | 交易所 API 客户端 | ✅ |
| **main.py** | 入口脚本、完整控制 | ✅ |

---

## 🚀 快速开始

### 1️⃣ 环境配置

```bash
# 设置 API 凭证
export GATE_API_KEY="your_api_key"
export GATE_API_SECRET="your_api_secret"

# 设置 Telegram 通知
export TELEGRAM_BOT_TOKEN="your_bot_token"
export TELEGRAM_CHAT_ID="your_chat_id"

# 设置交易模式（关键！）
export ENABLE_AUTO_TRADING="false"  # 先用模拟模式测试
# 确认无误后改为
export ENABLE_AUTO_TRADING="true"   # 启用自动交易
```

### 2️⃣ 交易模式说明

#### 模式 1：信号模式（推荐首先使用）
```bash
export ENABLE_AUTO_TRADING="false"
python main.py
```
✅ 仅生成信号，**不执行交易**  
✅ 适合测试和验证信号逻辑  
⚠️ 所有交易均为模拟

#### 模式 2：自动交易模式（生产环境）
```bash
export ENABLE_AUTO_TRADING="true"
python main.py
```
🚀 **真实执行所有交易**  
⚠️ 确保 API 凭证正确和账户安全

### 3️⃣ 风险控制配置

```bash
# 固定风险金额模式（默认）
export RISK_MODE="fixed"
export RISK_FIXED_AMOUNT="10"      # 单笔风险 10 USDT

# 或使用百分比模式
export RISK_MODE="percent"
export RISK_PERCENT="0.02"         # 单笔风险 账户 2%

# 熔断保护
export CIRCUIT_BREAKER_EQUITY="350"  # 账户低于 350U 时停止交易

# 冷静期（连续亏损后）
export MAX_CONSECUTIVE_LOSSES="3"    # 连续亏损 3 次后进入冷静期
```

---

## 🔄 自动交易执行流程

### 流程图

```
START
  ↓
获取K线数据（1000根，1H + 30m）
  ↓
计算技术指标 (SuperTrend + DEMA200)
  ↓
检查账户状态、风控、冷静期
  ↓
YES ← 熔断/冷静期？ → NO
 ↓                    ↓
EXIT                 分析信号
                       ↓
                    +─────────────────────────┐
                    ↓                         ↓
                  无持仓                    有持仓
                    ↓                         ↓
            ┌─────────────────────┐   ┌──────────────┐
            ↓                     ↓   ↓              ↓
          开多信号？  开空信号？  管理多仓  管理空仓
            ↓           ↓         ↓           ↓
          执行        执行      检查离场    检查离场
          开多        开空      检查止损    检查止损
            ↓           ↓         ↓           ↓
        设置止损    设置止损    调整止损    调整止损
            ↓           ↓         ↓           ↓
        发送通知    发送通知    发送通知    发送通知
            ↓           ↓         ↓           ↓
            └─────────────────────────┘
                    ↓
                END
```

### 具体操作流程

#### 📊 开多仓流程（open_long）

```
1. 验证参数
   - 张数 > 0？
   - 止损价 < 入场价？

2. 下开仓单（市价）
   - 方向: 多
   - 大小: qty 张
   - 时效: 市价（IOC）

3. 设置止损条件单（可选）
   - 配置: AUTO_SET_STOP_LOSS=true
   - 反向: 卖出 qty 张
   - 价位: 30m ST (初始)
   - 时效: 良性取消（GTC）

4. 记录启动状态
   - 入场价、止损、数量
   - 锁利阈值、无状态推导

5. 推送 Telegram 通知
   - 入场价、止损、保证金需求
   - 风险额度
```

#### 🛑 平仓流程（close_position）

```
1. 验证持仓存在
   - 方向是多还是空？
   - 数量是多少？

2. 取消止损单（防止平仓后自动触发）
   - 查询所有 stop_loss 标签的订单
   - 全部取消

3. 下平仓单（市价）
   - 方向: 反向
   - 大小: qty 张
   - 时效: 市价（IOC）
   - reduce_only: true

4. 计算盈亏
   - 多仓: (平仓价 - 入场价) × 数量 × 面值
   - 空仓: (入场价 - 平仓价) × 数量 × 面值

5. 更新状态
   - 清除持仓状态
   - 更新连续亏损计数
   - 检查冷静期触发

6. 推送通知
```

#### ⚠️ 调整止损流程（adjust_stop_loss）

```
1. 验证新止损方向
   - 多仓: 新止损 >= 旧止损（仅收紧）
   - 空仓: 新止损 <= 旧止损（仅收紧）

2. 取消旧止损单
   - 查询 stop_loss 标签
   - 立即取消

3. 创建新止损单
   - 价位: 新止损
   - reduce_only: true

4. 记录调整
   - 旧止损 → 新止损
   - 阶段: 生存期/锁利期/换轨期
```

---

## 💡 开仓条件（三重过滤）

### 📈 开多条件

```
做多信号 = 1H ST 绿 AND 1H收盘 > DEMA200 AND 30m ST 绿

实现代码:
can_long = (last_1h_dir == 1) and \
           (last_1h_close > last_1h_dema) and \
           (last_30m_dir == 1)

技术指标数据源:
- last_1h_dir: 上一根完整 1H K线 ST 方向
- last_1h_close: 上一根完整 1H K线 收盘价
- last_1h_dema: 1000 根 K线 DEMA200 (99.99% 精度)
- last_30m_dir: 上一根完整 30m K线 ST 方向
```

### 📉 开空条件

```
做空信号 = 1H ST 红 AND 1H收盘 < DEMA200 AND 30m ST 红

实现代码:
can_short = (last_1h_dir == -1) and \
            (last_1h_close < last_1h_dema) and \
            (last_30m_dir == -1)
```

---

## 📍 持仓管理三阶段

### 阶段 1️⃣ 生存期（浮盈 < 1U）

**特点:** 新开仓，浮盈尚小，止损跟随 30m ST

| 属性 | 值 |
|------|-----|
| **触发条件** | 浮盈 < LOCK_PROFIT_BUFFER (1U) |
| **止损来源** | 30m ST（动态跟随） |
| **离场信号** | 30m ST 变色 |
| **转移条件** | 浮盈 ≥ 1U → 进入阶段2 |

```
例: 多仓 1 张入场 2000U
    当前价 2001U: 浮盈 = (2001-2000)×1×0.1 = 0.1U < 1U
    → 仍在生存期，止损 = 30m ST
```

### 阶段 2️⃣ 锁利期（浮盈 ≥ 1U，1H ST 不够紧）

**特点:** 浮盈达到buffer，止损锁定不动，保本意识强

| 属性 | 值 |
|------|-----|
| **触发条件** | 浮盈 ≥ 1U 且 1H ST ≤ 锁利阈值 |
| **止损来源** | 锁定在 `entry_price ± 1U / 仓位(ETH)` |
| **离场信号** | 30m ST 变色 |
| **转移条件** | 1H ST 比锁利阈值更紧 → 进入阶段3 |

```
例: 多仓 1 张入场 2000U
    锁利阈值 = 2000 + 1 / (1×0.1) = 2010U
    当浮盈 ≥ 1U 时进入
    → 止损 = 2010U (锁定)
    → 即使价格下跌到 2000U 仍能保本
```

### 阶段 3️⃣ 换轨期（1H ST 比锁利阈值更紧）

**特点:** 1H 趋势强势，止损跟随 1H ST

| 属性 | 值 |
|------|-----|
| **触发条件** | 1H ST > 锁利阈值（多）或 < 锁利阈值（空）|
| **止损来源** | 1H ST（动态跟随） |
| **离场信号** | 1H ST 变色 |
| **优势** | 趋势强劲，能够充分获利 |

```
例: 多仓 1 张
    锁利阈值 = 2010U
    当 1H ST = 2015U > 2010U 时
    → 进入换轨期
    → 止损 = 2015U (紧跟 1H ST)
    → 若 1H ST 继续上升到 2020U，止损自动提升
    → 1H ST 变红时平仓
```

---

## 🎯 交易信号总结

### 开仓信号

| 信号 | 条件 | 动作 |
|------|------|------|
| `open_long` | 1H绿+收盘>DEMA+30m绿 | 开多，设止损 |
| `open_short` | 1H红+收盘<DEMA+30m红 | 开空，设止损 |

### 持仓管理信号

| 信号 | 条件 | 动作 |
|------|------|------|
| `stop_updated` | 30m/1H ST 变动 | 调整止损 |
| `enter_locked` | 浮盈 ≥ 1U | 进入阶段2 |
| `switch_1h` | 1H ST 比锁利更紧 | 进入阶段3 |

### 平仓信号

| 信号 | 条件 | 动作 |
|------|------|------|
| `close` | 阶段1/2: 30m换色 / 阶段3: 1H换色 | 平仓 |
| `close_and_reverse_long` | 平多 + 反手开多 | 平多后立即开多 |
| `close_and_reverse_short` | 平空 + 反手开空 | 平空后立即开空 |
| `reverse_to_long` | 满足开多条件 | 建议反手（需确认） |
| `reverse_to_short` | 满足开空条件 | 建议反手（需确认） |

### 风控信号

| 信号 | 条件 | 动作 |
|------|------|------|
| `circuit_breaker` | 账户 ≤ 350U | 熔断，停止交易 |
| `cooldown` | 连续亏损 ≥ 3 次 | 冷静期，停止交易 |

---

## 🔧 自动交易启用指南

### 第1步：干运行模式（信号验证）

```bash
# .env 或命令行设置
export ENABLE_AUTO_TRADING="false"
export DEBUG="true"

# 运行 1-2 周，验证信号逻辑
python main.py

# 检查日志
tail -f execution_log.json
```

**验证项目:**
- ✅ 开仓信号是否准确
- ✅ 止损位置是否合理
- ✅ 持仓阶段切换是否正确
- ✅ 离场信号是否及时
- ✅ Telegram 通知是否正常

### 第2步：模拟盘测试（可选，更逼真）

```bash
# 如果交易所支持，使用模拟盘 API
# Gate.io 模拟盘: https://testnet.gateio.ws
export GATE_API_KEY="your_testnet_key"
export GATE_API_SECRET="your_testnet_secret"
export ENABLE_AUTO_TRADING="true"

python main.py
```

### 第3步：启用自动交易（生产环境）

```bash
# 确认一切就绪
export GATE_API_KEY="your_real_key"
export GATE_API_SECRET="your_real_secret"
export ENABLE_AUTO_TRADING="true"
export CIRCUIT_BREAKER_EQUITY="350"     # 保护
export MAX_CONSECUTIVE_LOSSES="3"       # 保护
export RISK_FIXED_AMOUNT="10"           # 风险控制

# 启动（建议通过 GitHub Actions）
python main.py
```

---

## 📱 Telegram 通知配置

### 创建 Bot 和获取 Chat ID

```bash
# 1. 和 @BotFather 对话创建 Bot
/newbot
# 获得 BOT_TOKEN

# 2. 启动 Bot，添加到群组
# 3. 和 @userinfobot 对话，获得 CHAT_ID

# 设置环境变量
export TELEGRAM_BOT_TOKEN="123456789:ABCDEFGHIJKLMNOPabcdefghijklmnop"
export TELEGRAM_CHAT_ID="-1001234567890"
```

### 通知类型

- ✅ **开仓通知** - 入场价、止损、保证金
- ✅ **止损调整** - 旧止损 → 新止损
- ✅ **阶段切换** - 进入锁利期/换轨期
- ✅ **平仓通知** - 盈亏、离场原因
- ✅ **反手建议** - 新方向的开仓参数
- ⚠️ **风控告警** - 熔断、冷静期

---

## 📊 日志和监控

### 执行日志文件

```
execution_log.json  # 所有交易操作记录
  ├── timestamp
  ├── action: "OPEN_LONG" / "CLOSE" / "ADJUST_STOP"
  ├── message: "执行结果"
  └── details: {...}

trading_state.json  # 辅助状态
  ├── trade_count: 总交易数
  └── consecutive_losses: 连续亏损
```

### 日志查询

```bash
# 查看最近的交易
tail -20 execution_log.json | jq '.[].message'

# 统计交易情况
cat execution_log.json | jq '\
  group_by(.action) | \
  map({action: .[0].action, count: length})'

# 监控实时日志（如果启用 GitHub Actions）
gh run list --workflow main.yml
```

---

## ⚙️ 配置参数速查表

```
【技术指标】
SUPERTREND_PERIOD = 10          # 周期
SUPERTREND_MULTIPLIER = 3.0     # 倍数
DEMA_PERIOD = 200               # DEMA 周期

【风控】
LEVERAGE = 10                   # 杠杆
LOCK_PROFIT_BUFFER = 1          # 锁利缓冲 (USDT)
CIRCUIT_BREAKER_EQUITY = 350    # 熔断线
MAX_CONSECUTIVE_LOSSES = 3      # 冷静期触发

【交易】
ENABLE_AUTO_TRADING = false     # 自动交易开关
AUTO_SET_STOP_LOSS = true       # 自动设止损
STOP_LOSS_MODE = "tight_only"   # 止损模式
CLOSE_MODE = "market"           # 平仓模式
```

---

## 🚨 常见问题

### Q1: 如何确保交易安全？
**A:** 
1. 先用信号模式运行 1-2 周
2. 使用固定小风险额度（如 10 USDT）
3. 启用熔断和冷静期保护
4. 监控所有 Telegram 通知
5. 定期检查执行日志

### Q2: 如何应对 API 错误？
**A:** 
- 检查 API Key/Secret 有效性
- 确认账户有充足余额
- 检查杠杆和持仓限制
- 查看 API rate limit
- 使用 DEBUG=true 获得详细日志

### Q3: 如何恢复一个亏损交易？
**A:**
- ✅ 系统自动平仓并通知
- ✅ 如果止损未触发，手动平仓（不要忘记取消止损单）
- ✅ 检查是否进入冷静期
- ✅ 等待冷静期结束后重新开始

### Q4: 止损被触发而不是按我想要的方式平仓？
**A:**
- ✅ 正常！系统设置了条件止损单
- ✅ 如果要改变上限，调整 AUTO_SET_STOP_LOSS
- ✅ 但建议保持启用以保护资金

---

## 📈 性能指标

### 系统健康检查

```bash
# 检查最近 24h 交易
git log --since="24 hours ago" --oneline

# 检查是否在熔断
grep "circuit_breaker" execution_log.json

# 检查冷静期
grep "cooldown" execution_log.json

# 统计胜率
cat execution_log.json | jq '\
  [.[] | select(.action=="CLOSE")] | \
  map(select(.details.pnl > 0)) | \
  length as $wins | \
  ([.[] | select(.action=="CLOSE")] | length) as $total | \
  ($wins / $total * 100)'
```

---

## ✅ 生产部署建议

### 使用 GitHub Actions 自动化

```yaml
# .github/workflows/trading.yml
name: ETH Auto Trading

on:
  schedule:
    - cron: '*/30 * * * *'  # 每 30 分钟运行一次

jobs:
  trade:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      
      - name: Set up Python
        uses: actions/setup-python@v2
        with:
          python-version: '3.10'
      
      - name: Install dependencies
        run: pip install -r requirements.txt
      
      - name: Run trading
        env:
          GATE_API_KEY: ${{ secrets.GATE_API_KEY }}
          GATE_API_SECRET: ${{ secrets.GATE_API_SECRET }}
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
          ENABLE_AUTO_TRADING: 'true'
        run: python main.py
```

---

## 📞 技术支持

- 📧 问题报告: GitHub Issues
- 💬 讨论: GitHub Discussions
- 🐛 Bug 追踪: GitHub Issues
- 📚 文档: README.md

---

**最后更新:** 2026-02-21 23:30 UTC  
**下一步:** 启用自动交易并监控性能
