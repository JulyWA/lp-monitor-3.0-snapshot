#!/bin/bash
# 卸载研究机的 lp3 定时任务。plist 改名为 .disabled-<时间> 留档，不删除；输出和状态不动。
set -uo pipefail
TS="$(date +%Y%m%d-%H%M%S)"
for S in 1 2; do
  L="com.july.lab.lp3-stage$S"; P="$HOME/Library/LaunchAgents/$L.plist"
  launchctl bootout "gui/$(id -u)/$L" 2>/dev/null && echo "已停止 $L"
  [ -f "$P" ] && mv "$P" "$P.disabled-$TS" && echo "plist 已改名 $P.disabled-$TS"
done
