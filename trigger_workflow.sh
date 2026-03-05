#!/bin/bash

# 外部触发 GitHub Actions Workflow 脚本
# 用法: ./trigger_workflow.sh [GITHUB_TOKEN]

set -e

# GitHub 配置
REPO_OWNER="xunxuntj"
REPO_NAME="ETH_Perp_Trading_bot"
EVENT_TYPE="trading-check"

# 从参数或环境变量获取 token
GITHUB_TOKEN="${1:-${GITHUB_TOKEN}}"

if [ -z "$GITHUB_TOKEN" ]; then
    echo "❌ 错误：需要提供 GitHub Personal Access Token"
    echo ""
    echo "用法："
    echo "  ./trigger_workflow.sh YOUR_GITHUB_TOKEN"
    echo "  或设置环境变量："
    echo "  export GITHUB_TOKEN=YOUR_TOKEN"
    echo "  ./trigger_workflow.sh"
    echo ""
    echo "创建 Token："
    echo "  1. 访问 https://github.com/settings/tokens"
    echo "  2. 生成新 token (classic)"
    echo "  3. 勾选 'repo' 和 'workflow' 权限"
    exit 1
fi

echo "🚀 触发 GitHub Actions Workflow..."
echo "   Repository: $REPO_OWNER/$REPO_NAME"
echo "   Event Type: $EVENT_TYPE"
echo ""

# 发送 repository_dispatch 事件
RESPONSE=$(curl -s -w "\n%{http_code}" -X POST \
  -H "Authorization: Bearer $GITHUB_TOKEN" \
  -H "Accept: application/vnd.github.v3+json" \
  -H "Content-Type: application/json" \
  "https://api.github.com/repos/$REPO_OWNER/$REPO_NAME/dispatches" \
  -d "{\"event_type\": \"$EVENT_TYPE\"}")

HTTP_CODE=$(echo "$RESPONSE" | tail -n1)
BODY=$(echo "$RESPONSE" | head -n-1)

if [ "$HTTP_CODE" = "204" ]; then
    echo "✅ 成功触发 workflow！"
    echo ""
    echo "查看运行状态："
    echo "  https://github.com/$REPO_OWNER/$REPO_NAME/actions"
    echo ""
    echo "或使用命令："
    echo "  gh run list --workflow=trading.yml --limit 5"
    exit 0
else
    echo "❌ 触发失败！HTTP $HTTP_CODE"
    echo ""
    echo "响应内容："
    echo "$BODY" | jq -r . 2>/dev/null || echo "$BODY"
    echo ""
    echo "常见问题："
    echo "  - 403: Token 权限不足，需要 'repo' 和 'workflow' 权限"
    echo "  - 401: Token 无效或已过期"
    echo "  - 404: 仓库名称错误或 Token 无权访问"
    exit 1
fi
