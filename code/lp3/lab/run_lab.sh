#!/bin/bash
# 研究机定时入口：调 lp3/run_stage.sh，目录固定为研究机的 automation-lab 和 out/lab/lp3，日志追加到 automation-lab/logs。
# 用法：run_lab.sh stage1|stage2
set -uo pipefail
STAGE="${1:?用法：run_lab.sh stage1|stage2}"
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
export LP3_STATE_DIR="${LP3_STATE_DIR:-$HOME/.local/state/automation-lab}"
export LP3_OUT_ROOT="${LP3_OUT_ROOT:-$REPO/out/lab/lp3}"
mkdir -p "$LP3_STATE_DIR/logs"
echo "================================================================" >> "$LP3_STATE_DIR/logs/lp3-$STAGE.log"
/bin/bash "$REPO/lp3/run_stage.sh" "$STAGE" >> "$LP3_STATE_DIR/logs/lp3-$STAGE.log" 2>&1
