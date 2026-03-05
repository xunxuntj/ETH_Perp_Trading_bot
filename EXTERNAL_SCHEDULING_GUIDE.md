# 外部调度指南

## 问题说明

GitHub Actions 的 `schedule` 触发器存在以下限制：

1. **执行延迟**：实际运行时间可能比 cron 表达式设置的晚几分钟到几小时
2. **频率限制**：免费账户的 scheduled workflows 实际执行频率远低于配置频率
3. **不可靠性**：在高峰时段可能会跳过某些执行

从历史运行记录看，虽然配置为每 10 分钟运行一次，但实际大约每小时才运行一次。

## 解决方案

### 方案 1：使用免费的外部 Cron 服务（推荐）

使用 **cron-job.org** 或 **EasyCron** 等免费服务来精确调度。

#### 设置步骤：

1. **创建 GitHub Personal Access Token**
   - 访问：https://github.com/settings/tokens
   - 点击 "Generate new token (classic)"
   - 设置权限：勾选 `repo` 和 `workflow`
   - 保存生成的 token（仅显示一次）

2. **在 cron-job.org 注册并创建任务**
   - 访问：https://cron-job.org
   - 注册账户（免费账户支持每分钟执行）
   - 创建新任务：
     - **URL**: `https://api.github.com/repos/YOUR_USERNAME/ETH_Perp_Trading_bot/dispatches`
       - 替换 `YOUR_USERNAME` 为你的 GitHub 用户名
     - **Method**: POST
     - **Headers**:
       ```
       Authorization: Bearer YOUR_GITHUB_TOKEN
       Accept: application/vnd.github.v3+json
       Content-Type: application/json
       ```
     - **Body**:
       ```json
       {"event_type": "trading-check"}
       ```
     - **Schedule**: 每 5 分钟（`*/5 * * * *`）

3. **禁用原 workflow 的 schedule**
   - 保留 `trading.yml` 作为备份，但注释掉 `schedule` 部分
   - 使用新的 `trading-external-trigger.yml`（只接受外部触发）

#### 使用 curl 测试外部触发：

```bash
curl -X POST \
  -H "Authorization: Bearer YOUR_GITHUB_TOKEN" \
  -H "Accept: application/vnd.github.v3+json" \
  -H "Content-Type: application/json" \
  https://api.github.com/repos/YOUR_USERNAME/ETH_Perp_Trading_bot/dispatches \
  -d '{"event_type": "trading-check"}'
```

### 方案 2：使用 Self-Hosted Runner

如果你有自己的服务器或 VPS：

1. **设置 Self-Hosted Runner**
   - 在 GitHub 仓库页面：Settings → Actions → Runners → New self-hosted runner
   - 按照指引在你的服务器上安装 runner

2. **修改 workflow**
   ```yaml
   runs-on: self-hosted  # 替换 ubuntu-latest
   ```

3. **在服务器上设置 cron**
   ```bash
   */5 * * * * cd /path/to/runner && ./run.sh
   ```

### 方案 3：使用 GitHub Actions + workflow_dispatch（手动触发）

保留原有的 schedule 作为兜底，同时支持手动触发：
- 在 GitHub 仓库页面：Actions → 选择 workflow → Run workflow
- 如果需要自动化，可以使用 GitHub API 或 GitHub CLI

### 方案 4：部署到云服务（最佳方案）

将交易机器人部署到以下平台：

1. **Heroku**（免费层已停止，付费 $5/月起）
2. **Railway**（免费 $5 credit，付费 $5/月起）
3. **Fly.io**（免费额度，3个小型应用）
4. **Render**（免费层可用）
5. **VPS**（Vultr、DigitalOcean、Linode 等，$5/月起）

使用云服务可以让程序持续运行或使用准确的 cron 调度。

## 当前 workflow 状态

- **trading.yml**：使用 GitHub Actions schedule（不可靠，仅作备份）
- **trading-external-trigger.yml**：接受外部触发（推荐使用）

## 监控和调试

### 查看运行历史：
```bash
gh run list --workflow=trading.yml --limit 20
```

### 查看最近运行详情：
```bash
gh run view $(gh run list --workflow=trading.yml --limit 1 --json databaseId --jq '.[0].databaseId')
```

### 手动触发（如果有权限）：
```bash
gh workflow run trading-external-trigger.yml
```

## 建议

对于需要高频率和精确调度的交易机器人：
1. **短期方案**：使用 cron-job.org（免费，5分钟内生效）
2. **长期方案**：部署到云服务或 VPS（更可靠，延迟更低）

GitHub Actions 的 schedule 适合低频率、对时间不敏感的任务（如每天的备份、周报生成等），不适合交易机器人这种需要精确定时的场景。
