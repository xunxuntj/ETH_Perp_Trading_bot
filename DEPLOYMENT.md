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
| Railway + cronjob.org | ⭐⭐ | 免费(有额度) | ✅ | 免费稳定定时触发 |
| 本地开发机 | ⭐ | 无 | ❌ | 测试验证 |
| VPS 服务器 | ⭐⭐ | $3-10/月 | ✅ | 生产环境 |
| GitHub Actions | ⭐⭐ | 免费 | ✅ | 备选方案 |
| Docker 容器 | ⭐⭐⭐ | $3-20/月 | ✅ | 高级用户 |

**推荐**: 🏆 Railway API + cronjob.org（免费、可控、触发稳定）

---

## 方案 1️⃣: Railway API + cronjob.org（推荐 ⭐⭐⭐⭐⭐）

将脚本部署为 HTTP API（Railway 常驻），由 cronjob.org 每 30 分钟调用一次 `/run`。

### 1.1 前置准备

1. Railway 账户（免费计划）
2. cronjob.org 账户（免费）
3. 本仓库已包含 API 入口文件：`api_server.py`
4. 启动命令已配置：`Procfile`

### 1.2 Railway 部署

1. 在 Railway 创建项目并连接本仓库
2. 部署分支选择 `main`
3. Railway 启动命令（默认读取 `Procfile`）：

```bash
uvicorn api_server:app --host 0.0.0.0 --port $PORT
```

### 1.3 配置 Railway 环境变量

在 Railway Variables 添加：

| 变量 | 说明 |
|------|------|
| `API_KEY` | API 调用鉴权密钥（cronjob.org 使用） |
| `GATE_API_KEY` | Gate.io API Key |
| `GATE_API_SECRET` | Gate.io API Secret |
| `TELEGRAM_BOT_TOKEN` | Telegram Bot Token |
| `TELEGRAM_CHAT_ID` | Telegram Chat ID |
| `ENABLE_AUTO_TRADING` | `true/false`，默认 `false` |
| `MIN_INTERVAL_SECONDS` | 触发最小间隔秒数（默认 `60`） |

### 1.4 API 说明

- `GET /health`：健康检查
- `POST /run`：执行一次完整策略流程
- Header 鉴权：`X-API-Key: <API_KEY>`
- 并发保护：运行中重复触发返回 `already_running`
- 频率保护：小于最小间隔返回 `too_frequent`

### 1.5 cronjob.org 配置（每 30 分钟）

创建一个 CronJob：

- URL: `https://<你的-railway-域名>/run`
- Method: `POST`
- Header: `X-API-Key: <你的 API_KEY>`
- Schedule: `*/30 * * * *`

### 1.6 验证流程

1. 浏览器访问 `https://<域名>/health`，返回 `{"ok": true, ...}`
2. 在 cronjob.org 执行一次手动触发
3. 检查 Railway 日志是否出现一次完整策略运行
4. 检查 Telegram 是否收到对应通知

### 1.7 故障排查

**问题**: `/run` 返回 401
- **原因**: `X-API-Key` 与 Railway `API_KEY` 不一致
- **解决**: 核对 Header 与 Railway Variables

**问题**: `/run` 返回 `already_running`
- **原因**: 上一次触发尚未执行完成
- **解决**: 等待本次执行结束后再触发

**问题**: `/run` 返回 `too_frequent`
- **原因**: 触发频率小于 `MIN_INTERVAL_SECONDS`
- **解决**: 放宽触发频率或调小 `MIN_INTERVAL_SECONDS`

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

- [ ] Git 已安装
- [ ] Python 3.11+ 已安装
- [ ] requirements.txt 依赖已安装
- [ ] GATE_API_KEY 正确
- [ ] GATE_API_SECRET 正确
- [ ] TELEGRAM_BOT_TOKEN 正确
- [ ] TELEGRAM_CHAT_ID 正确
- [ ] API_KEY 已设置（Railway API 部署需要）
- [ ] 在模拟模式运行至少 1 周验证信号
- [ ] 理解风险、杠杆和资金管理
- [ ] 有应急停止的方法（暂停 cronjob 或下线 Railway 服务）

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
- **Railway**: 平台托管变量，配合 `API_KEY` 鉴权，适合免费轻量部署

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
- Railway + cronjob.org: 暂停 cron 任务或删除 `/run` 调用
- VPS Cron: `crontab -e` 注释掉对应行
- VPS SystemD: `sudo systemctl stop trading-bot.service`
- Docker: `docker-compose stop`

### Q: GitHub Actions 还能用吗？

**A**: 可以。仓库保留了 GitHub Actions 工作流配置，你可按需启用；但当前文档主推荐是 Railway API + cronjob.org。

---

## 📚 相关文档

- [快速开始](QUICK_START.md) - 5 分钟快速开始
- [配置参数](CONFIGURATION.md) - 详细配置说明
- [信号逻辑](SIGNAL_LOGIC_QUICK_REFERENCE.md) - 交易信号说明
- [系统架构](SYSTEM_ARCHITECTURE.md) - 技术架构文档
