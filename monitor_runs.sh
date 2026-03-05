#!/bin/bash

# 持续监控 GitHub Actions 运行状态
# 用法: ./monitor_runs.sh

set -e

echo "🔍 监控 GitHub Actions 运行状态..."
echo "按 Ctrl+C 停止监控"
echo ""

LAST_RUN_ID=""
COUNT=0

while true; do
    COUNT=$((COUNT + 1))
    CURRENT_TIME=$(date -u "+%Y-%m-%d %H:%M:%S UTC")
    
    # 获取最新的运行
    LATEST_RUN=$(gh run list --limit 1 --json databaseId,createdAt,event,status,conclusion 2>/dev/null)
    
    if [ -n "$LATEST_RUN" ]; then
        RUN_ID=$(echo "$LATEST_RUN" | jq -r '.[0].databaseId')
        RUN_TIME=$(echo "$LATEST_RUN" | jq -r '.[0].createdAt' | sed 's/T/ /' | sed 's/Z/ UTC/')
        RUN_EVENT=$(echo "$LATEST_RUN" | jq -r '.[0].event')
        RUN_STATUS=$(echo "$LATEST_RUN" | jq -r '.[0].status')
        RUN_CONCLUSION=$(echo "$LATEST_RUN" | jq -r '.[0].conclusion')
        
        # 检查是否有新的运行
        if [ "$RUN_ID" != "$LAST_RUN_ID" ]; then
            echo ""
            echo "🎉 检测到新的运行！"
            echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
            echo "运行 ID: $RUN_ID"
            echo "创建时间: $RUN_TIME"
            echo "触发方式: $RUN_EVENT"
            echo "状态: $RUN_STATUS"
            if [ "$RUN_CONCLUSION" != "null" ]; then
                echo "结果: $RUN_CONCLUSION"
            fi
            echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
            
            # 如果是 repository_dispatch 触发，显示特殊消息
            if [ "$RUN_EVENT" = "repository_dispatch" ]; then
                echo "✅ 外部触发成功！cron-job.org 配置正常工作！"
            fi
            
            LAST_RUN_ID=$RUN_ID
        fi
    fi
    
    # 显示监控状态
    echo -ne "\r[$COUNT] 检查中... 当前时间: $CURRENT_TIME | 最后运行: $RUN_TIME ($RUN_EVENT) "
    
    # 每 10 秒检查一次
    sleep 10
done
