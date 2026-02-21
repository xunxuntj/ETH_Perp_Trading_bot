# 🚀 ETH 永续交易系统 - 启动核检清单

## 📋 部署前检查 (Pre-Deployment Checklist)

### ✅ 环境准备 
- [ ] Python 3.10+ 已安装 (`python --version`)
- [ ] 依赖已安装 (`pip install -r requirements.txt`)
- [ ] Gate.io API 密钥已准备
- [ ] Telegram Bot Token 已准备
- [ ] Telegram Chat ID 已准备

### ✅ API 连接测试
```bash
export GATE_API_KEY="your_key"
export GATE_API_SECRET="your_secret"
python -c "from gate_client import GateClient; c = GateClient(); print(c.get_balance())"
```
- [ ] 余额查询成功
- [ ] 账户信息准确

### ✅ Telegram 通知测试
```bash
export TELEGRAM_BOT_TOKEN="your_token"
export TELEGRAM_CHAT_ID="your_id"
python -c "from telegram_notifier import send_telegram_message; send_telegram_message('Test notification')"
```
- [ ] 收到测试消息

### ✅ 初始配置检查
```bash
# 检查 config.py
grep -E "ENABLE_AUTO_TRADING|RISK_FIXED_AMOUNT|TRADING_SYMBOLS" config.py
```
- [ ] ENABLE_AUTO_TRADING = False (初始用模拟模式)
- [ ] RISK_FIXED_AMOUNT = 10 (10 USDT 风险)
- [ ] TRADING_SYMBOLS = ["ethusdt"] (只交易 ETH)

---

## 🎯 第一步：启动模拟模式（1-2 周）

### 1️⃣ 配置环境变量
```bash
# Linux/Mac
export GATE_API_KEY="your_key"
export GATE_API_SECRET="your_secret"
export TELEGRAM_BOT_TOKEN="your_token"
export TELEGRAM_CHAT_ID="your_id"
export ENABLE_AUTO_TRADING="false"

# 验证配置
echo "API Key: $GATE_API_KEY"
echo "Mode: $([ "$ENABLE_AUTO_TRADING" = "true" ] && echo "自动交易" || echo "模拟模式")"
```

### 2️⃣ 运行脚本
```bash
python main.py
```

### 3️⃣ 预期输出 (Simulation Mode)
```
🕐 2026-02-21 23:00:00 UTC
⚠️ 模拟（信号）模式
📋 策略: open_long
✅ 开多信号！
```

- [ ] 脚本成功运行
- [ ] 显示模拟模式标志
- [ ] 不显示"交易已执行"

### 4️⃣ 监控信号质量
```bash
# 查看实时日志
tail -f execution_log.json | jq '.'

# 统计信号胜率
cat execution_log.json | jq 'select(.type=="close") | select(.details.pnl > 0)' | wc -l
```

**检查点:**
- [ ] 过去 24 小时有交易信号
- [ ] 信号胜率 ≥ 50%
- [ ] 回调测试成功
- [ ] 止损按预期调整
- [ ] 平仓信号准确

**验证检查 (1 周后):**
- [ ] 确认信号质量
- [ ] 分析3阶段管理是否正常
- [ ] 检查 ST 指标跟随
- [ ] 验证 DEMA 过滤効果

---

## 💰 第二步：启用自动交易

### ✅ 前提条件
- [ ] 已验证信号质量 ≥ 50%
- [ ] 已检查三阶段管理正常
- [ ] 已测试止损调整
- [ ] 风险参数已理解
- [ ] 心理上已做好准备

### 1️⃣ 启用自动交易
```bash
export ENABLE_AUTO_TRADING="true"
python main.py
```

### 2️⃣ 预期输出 (Trading Mode)
```
🕐 2026-02-21 23:00:00 UTC
✅ 自动交易模式
📋 策略: open_long
✅ 开多信号！
✅ 交易已执行
🎯 开仓: ethusdt 多 0.01 张 / 入场: 2500 / 止损: 2480
```

- [ ] 显示自动交易模式标志
- [ ] 交易状态显示"已执行"

### 3️⃣ 第一笔交易验证
```bash
# 检查订单
python -c "
from gate_client import GateClient
c = GateClient()
orders = c.get_orders('ethusdt', 'status=finished', limit=10)
print(orders)
"
```

- [ ] 订单已下达
- [ ] 价格合理
- [ ] 止损已设置
- [ ] Telegram 通知已推送

### 4️⃣ 持续监控 (第一个月)

**每天检查:**
```bash
# 1. 查看最近交易
tail -10 execution_log.json

# 2. 统计今日 PnL
cat execution_log.json | jq 'select(.timestamp | test("2026-02-21")) | .details.pnl' | jq -s add

# 3. 检查是否触发风控
cat execution_log.json | jq 'select(.message | test("风控|冷静|熔断"))'
```

- [ ] 无错误日志
- [ ] 账户余额稳定
- [ ] 止损工作正常
- [ ] 通知推送及时

**每周检查:**
```bash
# 周报: 统计一周数据
python -c "
import json
with open('execution_log.json') as f:
    logs = [json.loads(x) for x in f]
trades = [x for x in logs if x.get('type') in ['open', 'close']]
wins = sum(1 for x in trades if x.get('details', {}).get('pnl', 0) > 0)
print(f'周交易数: {len(trades)}, 胜率: {wins/len(trades)*100:.1f}%')
"
```

**检查项:**
- [ ] 胜率是否维持 ≥ 50%
- [ ] 是否有异常亏损
- [ ] 止损是否有效
- [ ] 风控是否正确

---

## 🤖 第三步：GitHub Actions 自动化

### 1️⃣ 创建工作流文件

创建 `.github/workflows/trading.yml`:

```yaml
name: ETH Trading Bot

on:
  schedule:
    # 每 30 分钟执行一次
    - cron: '*/30 * * * *'
  
  workflow_dispatch:  # 支持手动触发

jobs:
  trade:
    runs-on: ubuntu-latest
    
    steps:
      - uses: actions/checkout@v3
      
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.10'
      
      - name: Install dependencies
        run: |
          pip install -r requirements.txt
      
      - name: Run trading bot
        env:
          GATE_API_KEY: ${{ secrets.GATE_API_KEY }}
          GATE_API_SECRET: ${{ secrets.GATE_API_SECRET }}
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
          ENABLE_AUTO_TRADING: 'true'
        run: |
          python main.py
      
      - name: Commit logs
        run: |
          git config --local user.email "bot@trading.local"
          git config --local user.name "Trading Bot"
          git add execution_log.json
          git commit -m "Auto: Trading execution at $(date)"
          git push
        continue-on-error: true
```

### 2️⃣ 配置 GitHub Secrets

在 GitHub 仓库设置中添加：
- [ ] GATE_API_KEY
- [ ] GATE_API_SECRET
- [ ] TELEGRAM_BOT_TOKEN
- [ ] TELEGRAM_CHAT_ID

### 3️⃣ 运行工作流

```bash
# 手动触发测试
# GitHub UI → Actions → ETH Trading Bot → Run workflow
```

- [ ] 工作流成功运行
- [ ] 日志提交到仓库
- [ ] Telegram 通知收到

### 4️⃣ 设置通知

在 `.github/workflows/trading.yml` 后添加：

```yaml
      - name: Notify on failure
        if: failure()
        run: |
          python -c "
          from telegram_notifier import send_telegram_message
          send_telegram_message('❌ Trading bot execution failed!')
          "
        env:
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
```

---

## 🛡️ 风险管理检查

### 风控三层防护验证

#### 层 1: 精准风控 (10 USDT)
```bash
# 验证最大单笔亏损
cat execution_log.json | jq '[.[] | select(.type=="close") | .details.pnl] | map(select(. < 0)) | min'
```
- [ ] 最大亏损 ≤ 10 USDT

#### 层 2: 熔断保护 (350 USDT)
```bash
# 检查账户余额
python -c "from gate_client import GateClient; print(GateClient().get_balance())"
```
- [ ] 账户余额 > 350 USDT
- [ ] 熔断保护未触发

#### 层 3: 冷静期保护 (3 次亏损)
```bash
# 检查连续亏损次数
cat execution_log.json | jq -r '.[] | select(.type=="close") | "\(.timestamp): \(.details.pnl)"' | tail -5
```
- [ ] 无连续 3 次亏损
- [ ] 冷静期保护未触发

---

## 📊 性能指标检查

### 关键性能指标 (KPI)

```bash
# 运行分析脚本
python -c "
import json
import statistics

with open('execution_log.json') as f:
    logs = [json.loads(x) for x in f]

# 统计交易
trades = [x for x in logs if x.get('type') == 'close']
if trades:
    pnls = [x.get('details', {}).get('pnl', 0) for x in trades]
    wins = sum(1 for pnl in pnls if pnl > 0)
    
    print(f'📊 性能统计:')
    print(f'  总交易数: {len(trades)}')
    print(f'  胜率: {wins/len(trades)*100:.1f}%')
    print(f'  总盈亏: {sum(pnls):.2f} USDT')
    print(f'  平均盈利: {statistics.mean(pnls):.2f} USDT')
    print(f'  最大盈利: {max(pnls):.2f} USDT')
    print(f'  最大亏损: {min(pnls):.2f} USDT')
    if len(pnls) > 1:
        print(f'  标准差: {statistics.stdev(pnls):.2f} USDT')
"
```

**目标指标:**
- [ ] 胜率 ≥ 50%
- [ ] 总盈亏 > 0 USDT
- [ ] 平均盈利 ≥ 5 USDT
- [ ] 最大亏损 ≤ 10 USDT

---

## 🐛 故障排查

### 常见问题

| 问题 | 症状 | 解决 |
|------|------|------|
| API 连接失败 | `Connection error` | 检查密钥、网络 |
| 信号未生成 | 日志显示 `None` | 检查 K 线数据 |
| 止损未设置 | 手册显示无止损 | 检查 `AUTO_SET_STOP_LOSS` |
| 平仓失败 | 交易显示 `Failed` | 检查头寸是否存在 |
| Telegram 无通知 | 未收到消息 | 检查 `TELEGRAM_CHAT_ID` |

### 调试步骤

```bash
# 1. 启用详细日志
export DEBUG="true"
export VERBOSE="true"

# 2. 单步执行
python -c "
from strategy import TradingStrategy
from config import *
st = TradingStrategy()
result = st.analyze()
print(f'Signal: {result.get(\"action\")}'）
print(f'Price: {result.get(\"price\")}')
"

# 3. 检查日志
tail -50 execution_log.json | jq '.[-1]'
```

---

## ✅ 完整核检清单

### 启动前
- [ ] API 连接成功
- [ ] Telegram 通知成功
- [ ] 配置参数正确
- [ ] 环境变量设置完成

### 模拟模式 (1-2 周)
- [ ] 信号生成正常
- [ ] 胜率 ≥ 50%
- [ ] 三阶段管理正常
- [ ] 止损调整合理

### 启用自动交易
- [ ] 前置条件满足
- [ ] 第一笔交易成功
- [ ] 日志记录完整
- [ ] Telegram 推送正常

### 持续监控 (第一个月)
- [ ] 日均无异常错误
- [ ] 风控正常工作
- [ ] 胜率维持 ≥ 50%
- [ ] 账户余额稳定

### 自动化设置
- [ ] GitHub Actions 配置完成
- [ ] 工作流成功运行
- [ ] 日志正确提交
- [ ] 失败通知设置

---

## 🎯 下一步行动

```bash
# 1️⃣ 立即启动
python main.py

# 2️⃣ 验证 1-2 周
# 每天检查一次日志和胜率

# 3️⃣ 启用自动交易
export ENABLE_AUTO_TRADING="true"
python main.py

# 4️⃣ 设置自动化
# 配置 GitHub Actions

# 5️⃣ 持续优化
# 监控 KPI，调整参数
```

---

**准备好了吗？立即启动！** 🚀
