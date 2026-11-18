#!/bin/bash
# 研究机定时入口：参考数据刷新（内部阶段 3）。每天增量刷新 Solana 标签；周日全量刷新标签并刷新股票和商品名单。
# 只写 out/lab/refdata/（模块默认仍读基线，切换要 July 批准）；日志追加到 automation-lab/logs/lp3-refdata.log。
set -uo pipefail
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
LOGD="$HOME/.local/state/automation-lab/logs"; mkdir -p "$LOGD"; LOG="$LOGD/lp3-refdata.log"
cd "$REPO"
{
  echo "================================================================"
  echo "[$(date '+%Y-%m-%dT%H:%M:%S%z')] refdata 开始"
  if [ "$(date +%u)" = "7" ]; then
    /usr/bin/python3 -m lp3.refresh.sol_labels full; R1=$?
    /usr/bin/python3 -m lp3.refresh.stocklist; R2=$?
  else
    /usr/bin/python3 -m lp3.refresh.sol_labels incremental; R1=$?; R2=0
  fi
  echo "[$(date '+%Y-%m-%dT%H:%M:%S%z')] refdata 结束 labels=$R1 stocklist=$R2"
} >> "$LOG" 2>&1
[ "$R1" = 0 ] && [ "$R2" = 0 ]
