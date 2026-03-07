# 问题修复总结

## 📌 2026-03-07 - 三阶段止损逻辑 V2 (重要更新)

### 问题说明
换轨期的判断逻辑有问题：
- 原逻辑使用 `lock_threshold`（按入场价计算）作为换轨条件
- 实际应该使用**进入锁利期时的 30m ST** 作为换轨条件
- 锁利期内不应该跟随 30m ST 调整，应该保持锁利止损不变

### 正确的三阶段逻辑
1. **生存期（SURVIVAL）**：期望盈利 < LOCK_PROFIT_BUFFER，止损跟随 30m ST
2. **锁利期（LOCKED）**：期望盈利 >= LOCK_PROFIT_BUFFER，暂停止损调整，保持当前 30m ST 作为 `locked_stop_loss`
3. **换轨期（HOURLY）**：1H ST <= `locked_stop_loss`（比锁利止损更紧），止损跟随 1H ST

### 实现修改
- **position_state.json**：新增 `locked_stop_loss` 和 `initial_30m_st` 字段
  - `locked_stop_loss`：进入锁利期时的 30m ST
  - `initial_30m_st`：开仓时的 30m ST
- **strategy.py `_infer_phase()`**：完全重新实现三阶段推导逻辑
  - 接收 `initial_30m_st` 和 `locked_stop_loss` 参数
  - 锁利期直接返回 `locked_stop_loss`，不跟随 30m ST
  - 换轨条件：1H ST vs locked_stop_loss，而非 vs lock_threshold
- **position_state.py `update_position_state()`**：支持新参数
  - 进入 LOCKED 时自动记录 `locked_stop_loss`
  - 保留历史的 `locked_stop_loss` 直到平仓

### 文档
- 新增 `TRADING_PHASE_LOGIC_V2.md` - 完整的三阶段逻辑说明

---

## 📌 2026-03-05 - GitHub Actions Schedule 问题修复

### 问题诊断

✅ **已确认的情况**：
- Workflow 文件在 2026-03-05 16:06:17 UTC 更新（改为每 5 分钟运行）
- 最后一次运行在 15:59:32 UTC（使用旧配置）
- 从 16:06 到现在 17:06，按新配置应该运行了 11 次，但实际 0 次
- 历史记录显示：即使配置每 10 分钟，实际也是每小时才运行 1 次

### 根本原因

**GitHub Actions 的 `schedule` 触发器存在严重限制**：

1. **修改延迟**：cron 表达式修改后，调度器需要时间识别（几分钟到几小时）
2. **频率限制**：免费账户的实际执行频率远低于配置频率
3. **资源竞争**：在高峰时段，低优先级的 scheduled workflows 会被延迟或跳过
4. **不适用场景**：不适合需要精确定时的交易机器人

### 已实施的修复

### 1. 更新 workflow 文件（已完成）

**文件**：`.github/workflows/trading.yml`

**修改内容**：
- ✅ 添加了问题警告注释
- ✅ 保留 `schedule` 作为兜底备份
- ✅ 新增 `repository_dispatch` 触发器（支持外部触发）
- ✅ 保留 `workflow_dispatch`（手动触发）

### 2. 创建外部触发专用 workflow（已完成）

**文件**：`.github/workflows/trading-external-trigger.yml`

**特点**：
- 只接受外部触发（`repository_dispatch` 和 `workflow_dispatch`）
- 不依赖不可靠的 `schedule`
- 配置与原 workflow 相同

### 3. 创建详细指南（已完成）

**文件**：`EXTERNAL_SCHEDULING_GUIDE.md`

**内容**：
- 问题说明和原因分析
- 4 种解决方案对比：
  - 外部 Cron 服务（cron-job.org）- 推荐
  - Self-Hosted Runner
  - 手动触发
  - 部署到云服务（最佳）
- 详细的设置步骤和示例代码

### 4. 创建触发脚本（已完成）

**文件**：`trigger_workflow.sh`

**功能**：
- 使用 GitHub API 触发 workflow
- 自动错误处理和提示
- 支持环境变量和命令行参数

### 5. 更新 README（已完成）

**文件**：`README.md`

**修改内容**：
- 添加了关于 schedule 不可靠的警告
- 更新功能特点说明
- 引导用户使用更可靠的方案

## 推荐解决方案

### 🥇 方案 1：免费外部 Cron 服务（最快实施）

**使用 cron-job.org**（完全免费，支持每分钟执行）：

#### 步骤：

1. **创建 GitHub Token**
   ```bash
   # 访问 https://github.com/settings/tokens
   # 生成 classic token，勾选 'repo' 和 'workflow' 权限
   ```

2. **在 cron-job.org 注册并创建任务**
   - URL: `https://api.github.com/repos/xunxuntj/ETH_Perp_Trading_bot/dispatches`
   - Method: `POST`
   - Headers:
     ```
     Authorization: Bearer YOUR_GITHUB_TOKEN
     Accept: application/vnd.github.v3+json
     Content-Type: application/json
     ```
   - Body:
     ```json
     {"event_type": "trading-check"}
     ```
   - Schedule: `*/5 * * * *`（每 5 分钟）

3. **测试触发**
   ```bash
   # 使用提供的脚本测试
   ./trigger_workflow.sh YOUR_GITHUB_TOKEN
   
   # 或直接使用 curl
   curl -X POST \
     -H "Authorization: Bearer YOUR_GITHUB_TOKEN" \
     -H "Accept: application/vnd.github.v3+json" \
     -H "Content-Type: application/json" \
     https://api.github.com/repos/xunxuntj/ETH_Perp_Trading_bot/dispatches \
     -d '{"event_type": "trading-check"}'
   ```

4. **验证**
   ```bash
   # 查看运行记录
   gh run list --workflow=trading.yml --limit 10
   ```

**优点**：
- ✅ 完全免费
- ✅ 可靠，按时执行
- ✅ 5 分钟内可以设置完成
- ✅ 支持每分钟执行
- ✅ 有 Web 界面管理

**缺点**：
- ⚠️ 需要创建和管理 GitHub Token
- ⚠️ Token 需要定期更新（可设置不过期）

---

### 🥈 方案 2：部署到云服务（最佳长期方案）

**推荐平台**：

1. **Fly.io**（推荐）
   - 免费额度：3 个小型应用
   - 全球分布
   - 简单部署：`fly launch`

2. **Render**
   - 免费 tier 可用
   - 自动部署
   - Web 界面友好

3. **Railway**
   - 免费 $5 credit（够用一个月）
   - 支持 cron jobs
   - GitHub 集成

4. **VPS**（Vultr、DigitalOcean、Linode）
   - $5/月起
   - 完全控制
   - 使用系统 crontab

**部署后使用系统 cron**：
```bash
# 编辑 crontab
crontab -e

# 添加任务（每 5 分钟）
*/5 * * * * cd /path/to/ETH_Perp_Trading_bot && python main.py >> /var/log/trading.log 2>&1
```

**优点**：
- ✅ 100% 可靠
- ✅ 延迟最低
- ✅ 完全控制
- ✅ 可以运行其他服务

**缺点**：
- ⚠️ 可能需要付费（部分平台有免费额度）
- ⚠️ 需要一些服务器管理知识

---

### 🥉 方案 3：Self-Hosted Runner

如果你有自己的服务器但想保留 GitHub Actions workflow：

1. **安装 Runner**
   - GitHub 仓库 → Settings → Actions → Runners → New self-hosted runner
   - 按照指引在服务器上安装

2. **修改 workflow**
   ```yaml
   runs-on: self-hosted  # 替换 ubuntu-latest
   ```

3. **使用系统 cron 触发**
   ```bash
   */5 * * * * cd /path/to/runner && ./run.sh
   ```

**优点**：
- ✅ 保留 workflow 逻辑
- ✅ 可靠执行
- ✅ 免费（如果有服务器）

**缺点**：
- ⚠️ 需要维护 runner
- ⚠️ 需要有服务器
- ⚠️ 配置相对复杂

## 当前状态

- ✅ Workflow 文件已更新（包含外部触发支持）
- ✅ 文档已完善
- ✅ 触发脚本已创建
- ⏸️ 等待用户选择并实施解决方案

## 下一步行动

### 选项 A：快速实施（外部 Cron）

```bash
# 1. 创建 GitHub Token
# 访问 https://github.com/settings/tokens

# 2. 测试触发
./trigger_workflow.sh YOUR_GITHUB_TOKEN

# 3. 在 cron-job.org 设置定时任务
# 访问 https://cron-job.org
```

### 选项 B：最佳方案（部署到云）

查看 [DEPLOYMENT.md](DEPLOYMENT.md) 选择合适的云平台并部署。

### 选项 C：继续使用 GitHub Actions

如果你决定继续使用 GitHub Actions 的 schedule：

1. **等待调度器识别新配置**（可能需要几小时）
2. **接受不可靠性**（可能每小时才运行 1 次）
3. **仅作为兜底备份**，不依赖它进行精准交易

## 监控和验证

### 查看运行历史
```bash
gh run list --workflow=trading.yml --limit 20
```

### 查看最近运行详情
```bash
gh run view $(gh run list --workflow=trading.yml --limit 1 --json databaseId --jq '.[0].databaseId')
```

### 查看运行日志
```bash
gh run view --log $(gh run list --workflow=trading.yml --limit 1 --json databaseId --jq '.[0].databaseId')
```

## 相关文件

- `EXTERNAL_SCHEDULING_GUIDE.md` - 外部调度详细指南
- `trigger_workflow.sh` - 手动触发脚本
- `.github/workflows/trading.yml` - 主 workflow（带 schedule 兜底）
- `.github/workflows/trading-external-trigger.yml` - 外部触发专用
- `DEPLOYMENT.md` - 部署指南

## 总结

GitHub Actions 的 `schedule` 触发器不适合需要精确定时的应用。对于交易机器人：

- 如果需要**快速解决**：使用外部 Cron 服务（5 分钟搞定）
- 如果需要**长期稳定**：部署到云服务或 VPS（最佳方案）
- 如果只是**试用/测试**：可以继续用 GitHub Actions，但要接受不可靠性

**建议**：先用外部 Cron 服务快速解决问题，然后逐步迁移到云服务。
