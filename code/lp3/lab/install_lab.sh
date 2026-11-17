#!/bin/bash
# 渲染并加载研究机的两个 lp3 定时任务（com.july.lab.lp3-stage1 08:20、stage2 10:20）。
# 路径按本机 $HOME 和仓库位置渲染，不写死用户名。只装 com.july.lab.* 命名空间，拒绝覆盖正式任务名。
# 用法：install_lab.sh [--dry-run]   卸载：uninstall_lab.sh
set -euo pipefail
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
DEST="$HOME/Library/LaunchAgents"
DRY="${1:-}"
mkdir -p "$DEST" "$HOME/.local/state/automation-lab/logs"
for S in 1 2; do
  L="com.july.lab.lp3-stage$S"
  case "$L" in com.july.lab.*) ;; *) echo "拒绝：$L 不在 lab 命名空间"; exit 1;; esac
  OUTP="$DEST/$L.plist"
  sed -e "s#__REPO__#$REPO#g" -e "s#__HOME__#$HOME#g" "$REPO/lp3/lab/launchd/$L.plist.template" > "$OUTP.tmp"
  plutil -lint "$OUTP.tmp" >/dev/null
  if [ "$DRY" = "--dry-run" ]; then cat "$OUTP.tmp"; rm "$OUTP.tmp"; continue; fi
  mv "$OUTP.tmp" "$OUTP"
  launchctl bootout "gui/$(id -u)/$L" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$OUTP"
  echo "已加载 $L"
  launchctl print "gui/$(id -u)/$L" | grep -E "state =|path =" | head -3
done
