#!/bin/bash
# 跑一个时段：编排各模块（每个独立子进程），再刷新整合日报。输出到标准输出（由外层 run_task.sh 或 run_lab.sh 收日志）。
# 必须设置 LP3_STATE_DIR 和 LP3_OUT_ROOT（研究机、1 号机影子、1 号机正式各用各的目录）。
# 用法：run_stage.sh stage1|stage2    退出码 = 编排退出码（任一模块失败或超时为 1）
set -uo pipefail
STAGE="${1:?用法：run_stage.sh stage1|stage2}"
: "${LP3_STATE_DIR:?缺 LP3_STATE_DIR}" "${LP3_OUT_ROOT:?缺 LP3_OUT_ROOT}"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
PY=/usr/bin/python3
export PATH=/usr/bin:/bin:/usr/sbin:/sbin LP3_STATE_DIR LP3_OUT_ROOT
mkdir -p "$LP3_STATE_DIR" "$LP3_OUT_ROOT"
LOCK="$LP3_STATE_DIR/lp3-$STAGE.lock"
if ! mkdir "$LOCK" 2>/dev/null; then
  echo "[$(date '+%Y-%m-%dT%H:%M:%S%z')] $STAGE 上一次还在运行（$LOCK），本次跳过"; exit 0
fi
trap 'rmdir "$LOCK"' EXIT
cd "$REPO"
echo "[$(date '+%Y-%m-%dT%H:%M:%S%z')] lp3 $STAGE 开始 @ $(git -C "$REPO" rev-parse --short HEAD 2>/dev/null || echo 无git) out=$LP3_OUT_ROOT"
"$PY" -m lp3.orchestrate "$STAGE"
RC=$?
"$PY" -m lp3.aggregate || echo "整合日报生成失败（不影响采集结果）"
echo "[$(date '+%Y-%m-%dT%H:%M:%S%z')] lp3 $STAGE 结束 rc=$RC"
exit $RC
