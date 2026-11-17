#!/bin/bash
# 回退：停用 lp3m 正式和影子任务（plist 改名留档），恢复最近一次被停用的 com.july.lp3-collect / lp3-stage2-collect 并加载。
# 不删代码、不删任何输出和状态。
set -uo pipefail
. "$(dirname "$0")/_common.sh"
for L in $PROD_LABELS $SHADOW_LABELS; do unload_disable "$L"; done
for L in $OLD_LABELS; do
  if [ -f "$LA/$L.plist" ]; then say "$L 本来就在，重新加载"; load "$L"; continue; fi
  LAST=$(ls -1 "$LA/$L.plist.disabled-"* 2>/dev/null | sort | tail -1)
  [ -n "$LAST" ] || { say "找不到 $L 的留档 plist，需人工处理"; continue; }
  mv "$LAST" "$LA/$L.plist" && load "$L" && say "已恢复并加载 $L（来自 $(basename "$LAST")）"
done
say "回退完成。lp3 代码和 out/lp3*、状态文件都保留，未删除。"
