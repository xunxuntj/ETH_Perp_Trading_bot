# 🚀 部署和运行指南

本文档说明如何在不同环境中部署和运行 ETH SuperTrend Trading Bot。

## 📋 系统要求

- **操作系统**: Linux / macOS / Windows (with WSL2)
- **Python**: 3.11+
- **网络**: 需要访问 Gate.io API 和 Telegram API
- **账户**: Gate.io 永续合约账户

---

## 🌐 方案选择

根据您的需求选择部署方案：

| 方案 | 难度 | 成本 | 是否7x24 | 推荐场景 |
|------|------|------|---------|---------|
| 本地开发机 | ⭐ | 无 | ❌ | 测试验证 |
| VPS 服务器 | ⭐⭐ | $3-10/月 | ✅ | 生产环境 |
| GitHub Actions | ⭐⭐ | 免费 | ✅ | 最简便 |
| Docker 容器 | ⭐⭐⭐ | $3-20/月 | ✅ | 高级用户 |

**推荐**: 🏆 GitHub Actions（最简单、免费、可靠）

---

## 方案 1️⃣: GitHub Actions（推荐 ⭐⭐⭐⭐⭐）

最简单、最便宜、最稳定的方案，完全免费。

### 1.1 前置准备

1. **Fork 本仓库** 到您的 GitHub 账户
   ```bash
   # 在 GitHub 网页上点击 "Fork"
   ```

2. **获取 Secrets**:
   - Gate.io 的 API Key 和 Secret（见 [CONFIGURATION.md](CONFIGURATION.md)）
   - Telegram Bot Token 和 Chat ID（下文获取）

### 1.2 配置环境变量（Secrets）

1. 打开您 fork 的仓库 → Settings → Secrets and variables → Actions
2. 点击 "New repository secret"，添加以下 Secrets：

| Secret 名称 | 值 | 获取方式 |
|------------|-----|---------|
| `GATE_API_KEY` | 您的 API Key | Gate.io 账户设置 |
| `GATE_API_SECRET` | 您的 API Secret | Gate.io 账户设置 |
| `TELEGRAM_BOT_TOKEN` | Bot Token | BotFather 创建 |
| `TELEGRAM_CHAT_ID` | Chat ID | 发送 /start 到 Bot |

**Telegram 设置步骤**:

1. 打开 Telegram 搜索 `@BotFather`
2. 发送 `/newbot`
3. 按照提示创建机器人，获得 Token：`123456:ABCDefghijKLMNOpqrSTUVwxyz`
4. 创建私人群组 (Settings → Create Channel → Private)
5. 将您的 Bot 添加到群组
6. 发送一条消息到群组，然后：
   ```bash
   # 在浏览器访问 (replace TOKEN with your token)
   https://api.telegram.org/botTOKEN/getUpdates
   ```
7. 从 JSON 响应中找到 `"chat":{"id":123456789}` - 这就是 CHAT_ID

### 1.3 启用工作流

1. 打开仓库 → Actions 标签
2. 左侧选择 "ETH Trading Bot Scheduler"
3. 点击 "Enable workflow"

### 1.4 工作流配置说明

工作流文件: `.github/workflows/trading.yml`

**当前配置**:
- 每 30 分钟运行一次
- 在 UTC 时区执行
- 模式: 仅信号模式（ENABLE_AUTO_TRADING=false）

**修改运行频率**:

```yaml
# .github/workflows/trading.yml
on:
  schedule:
    - cron: '0 */1 * * *'  # 每小时运行一次
    # cron: '*/30 * * * *'  # 每30分钟运行一次（当前）
    # cron: '0 0 * * *'     # 每天 00:00 UTC 运行
```

Cron 格式: `分钟 小时 日 月 周几`

**启用自动交易**:

如果已验证信号准确，可启用自动交易：

```yaml
# .github/workflows/trading.yml
env:
  ENABLE_AUTO_TRADING: 'true'
```

### 1.5 监控运行

1. 打开仓库 → Actions 标签
2. 查看最新运行记录
3. 点击运行记录查看详细日志
4. 检查 Telegram 是否收到消息

### 1.6 故障排查

**问题**: 收不到通知
- **原因**: Secrets 配置有误或 Telegram 权限问题
- **解决**: 
  1. 检查 Secrets 是否正确设置
  2. 手动运行工作流观察日志
  3. 点击 Telegram Bot 的链接测试权限

**问题**: 工作流运行失败
- **原因**: API 配置错误、网络问题或代码错误
- **解决**:
  1. 查看详细错误日志
  2. 验证 API Key 和 Secret
  3. 根据错误消息调整配置

---

## 方案 2️⃣: VPS 服务器

适合需要完全控制和自定义的用户。

### 2.1 VPS 选择

推荐轻量级 VPS（足以运行本程序）:

| 厂商 | 配置 | 价格 | 推荐度 |
|------|------|------|--------|
| Linode | 1GB RAM, 25GB SSD | $5/月 | ⭐⭐⭐⭐⭐ |
| DigitalOcean | 512MB RAM, 10GB SSD | $4/月 | ⭐⭐⭐⭐ |
| Vultr | 512MB RAM, 10GB SSD | $2.5/月 | ⭐⭐⭐ |
| Hetzner | 1GB RAM, 20GB SSD | €2.5/月 | ⭐⭐⭐⭐ |

**操作系统**: Ubuntu 22.04 LTS 或 Debian 12

### 2.2 初始化 VPS

```bash
# 1. SSH 连接到 VPS
ssh root@your_vps_ip

# 2. 更新系统
apt update && apt upgrade -y

# 3. 安装 Python 和依赖
apt install -y python3.11 python3-pip git curl wget

# 4. 创建非 root 用户（推荐）
adduser trader
usermod -aG sudo trader
su - trader

# 5. 克隆仓库
git clone https://github.com/yourusername/eth-trading-bot.git
cd eth-trading-bot

# 6. 安装 Python 依赖
pip3 install -r requirements.txt
```

### 2.3 配置环境变量

创建 `.env` 文件:

```bash
# 在 eth-trading-bot 目录下
cat > .env << 'EOF'
export GATE_API_KEY="your_api_key"
export GATE_API_SECRET="your_api_secret"
export TELEGRAM_BOT_TOKEN="your_bot_token"
export TELEGRAM_CHAT_ID="your_chat_id"
export ENABLE_AUTO_TRADING="false"
export RISK_MODE="fixed"
export RISK_FIXED_AMOUNT="10"
EOF

# 加载环境变量
source .env
```

### 2.4 手动运行脚本

```bash
# 测试一次运行
python3 main.py

# 预期输出
# 🕐 2026-02-21 23:00:00 UTC
# ========================================================
# 🔧 ⚠️ 模拟（信号）模式
# 📋 策略: no_signal
# ✅ 无信号，继续观察...
```

### 2.5 使用 Cron 定时运行

**选项 A**: 每 30 分钟运行一次

```bash
# 编辑 crontab
crontab -e

# 添加以下行
*/30 * * * * cd /home/trader/eth-trading-bot && source .env && python3 main.py >> logs/trading.log 2>&1
```

**选项 B**: 使用 SystemD Timer（更推荐）

创建 service 文件:

```bash
# 创建 service
sudo nano /etc/systemd/system/trading-bot.service
```

内容:

```ini
[Unit]
Description=ETH Trading Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=trader
WorkingDirectory=/home/trader/eth-trading-bot
EnvironmentFile=/home/trader/eth-trading-bot/.env
ExecStart=/usr/bin/python3 /home/trader/eth-trading-bot/main.py
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

创建 timer:

```bash
# 创建 timer
sudo nano /etc/systemd/system/trading-bot.timer
```

内容:

```ini
[Unit]
Description=Run ETH Trading Bot every 30 minutes
Requires=trading-bot.service

[Timer]
OnBootSec=2min
OnUnitActiveSec=30min
AccuracySec=1s

[Install]
WantedBy=timers.target
```

启用 timer:

```bash
# 重新加载 systemd 配置
sudo systemctl daemon-reload

# 启用并启动 timer
sudo systemctl enable trading-bot.timer
sudo systemctl start trading-bot.timer

# 查看 timer 状态
sudo systemctl list-timers --all
systemctl status trading-bot.timer

# 查看最后一次运行日志
sudo journalctl -u trading-bot.service -n 50
```

### 2.6 VPS 监控和维护

**查看实时日志**:

```bash
# 旧式 cron 方式的日志
tail -f logs/trading.log

# SystemD Timer 方式的日志
sudo journalctl -u trading-bot.service -f
```

**定期备份状态文件**:

```bash
# 创建备份脚本
cat > backup_state.sh << 'EOF'
#!/bin/bash
mkdir -p backups
cp trading_state.json backups/trading_state_$(date +%Y-%m-%d_%H:%M:%S).json
echo "State file backed up"
EOF

# 添加到 crontab（每天 00:00 执行）
0 0 * * * /home/trader/eth-trading-bot/backup_state.sh
```

**设置日志轮转**:

```bash
# 创建日志轮转配置
sudo nano /etc/logrotate.d/trading-bot
```

内容:

```
/home/trader/eth-trading-bot/logs/*.log {
    daily
    missingok
    rotate 7
    compress
    delaycompress
    notifempty
    create 0640 trader trader
}
```

---

## 方案 3️⃣: Docker 容器

对于需要完全隔离和易于扩展的情况。

### 3.1 Dockerfile

```dockerfile
# Dockerfile
FROM python:3.11-slim

WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 复制文件
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 运行
CMD ["python", "main.py"]
```

### 3.2 Docker Compose

```yaml
# docker-compose.yml
version: '3.8'

services:
  trading-bot:
    build: .
    container_name: eth-trading-bot
    environment:
      - GATE_API_KEY=${GATE_API_KEY}
      - GATE_API_SECRET=${GATE_API_SECRET}
      - TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN}
      - TELEGRAM_CHAT_ID=${TELEGRAM_CHAT_ID}
      - ENABLE_AUTO_TRADING=${ENABLE_AUTO_TRADING:-false}
      - RISK_MODE=${RISK_MODE:-fixed}
      - RISK_FIXED_AMOUNT=${RISK_FIXED_AMOUNT:-10}
    volumes:
      - ./trading_state.json:/app/trading_state.json
      - ./logs:/app/logs
    restart: on-failure
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
```

### 3.3 运行 Docker

```bash
# 启动容器
docker-compose up -d

# 查看日志
docker-compose logs -f trading-bot

# 停止容器
docker-compose down
```

---

## 方案 4️⃣: 本地开发机（仅用于测试）

### 4.1 安装依赖

```bash
# Ubuntu/Debian
sudo apt install python3 python3-pip

# macOS
brew install python3

# 克隆仓库
git clone https://github.com/yourusername/eth-trading-bot.git
cd eth-trading-bot

# 安装 Python 依赖
pip3 install -r requirements.txt
```

### 4.2 配置和运行

```bash
# 设置环境变量
export GATE_API_KEY="your_key"
export GATE_API_SECRET="your_secret"
export TELEGRAM_BOT_TOKEN="your_token"
export TELEGRAM_CHAT_ID="your_chat_id"

# 运行
python3 main.py
```

### 4.3 持续运行（开发用）

使用 `screen` 或 `tmux` 保持进程运行:

```bash
# 使用 screen
screen -S trading
# 进入 screen 后运行脚本，按 Ctrl+A 然后 D 分离

# 重新连接
screen -r trading

# 查看所有 screen
screen -ls
```

---

## ✅ 部署检查清单

完成部署前，请检查：

- [ ] Git 已安装 (GitHub Actions 不需要)
- [ ] Python 3.11+ 已安装 (GitHub Actions 不需要)
- [ ] requirements.txt 依赖已安装
- [ ] GATE_API_KEY 正确
- [ ] GATE_API_SECRET 正确
- [ ] TELEGRAM_BOT_TOKEN 正确
- [ ] TELEGRAM_CHAT_ID 正确
- [ ] 在模拟模式运行至少 1 周验证信号
- [ ] 理解风险、杠杆和资金管理
- [ ] 有应急停止的方法（GitHub Actions 可禁用运行）

---

## 🛟 常见问题

### Q: 为什么脚本需要每 30 分钟运行一次？

**A**: 
- 交易信号基于 30 分钟 K线计算
- 每 30 分钟验证一次信号和持仓
- 其他时间间隔（1小时、15分钟等）需自行调整指标参数

### Q: 本地和 VPS 哪个更安全？

**A**: 
- **本地**: 不需要在远程服务器存储 API Key，更安全
- **VPS**: 需要小心管理 Secrets，但支持 7x24 运行
- **GitHub Actions**: GitHub 负责安全管理 Secrets，推荐

### Q: 可以同时在多个 VPS 上运行脚本吗？

**A**: ⚠️ **不推荐**
- 可能导致重复开仓
- 交易冲突
- 账户同步混乱
- 建议只在一个地方运行脚本

### Q: 脚本运行失败如何调试？

**A**: 
1. 查看详细日志（print 输出）
2. 检查 API Key 和网络连接
3. 验证 Telegram 权限
4. 查看 trading_state.json 状态文件

### Q: 如何停止脚本？

**A**:
- GitHub Actions: 禁用工作流或修改 Secrets
- VPS Cron: `crontab -e` 注释掉对应行
- VPS SystemD: `sudo systemctl stop trading-bot.service`
- Docker: `docker-compose stop`

---

## 📚 相关文档

- [快速开始](QUICK_START.md) - 5 分钟快速开始
- [配置参数](CONFIGURATION.md) - 详细配置说明
- [信号逻辑](SIGNAL_LOGIC_QUICK_REFERENCE.md) - 交易信号说明
- [系统架构](SYSTEM_ARCHITECTURE.md) - 技术架构文档
