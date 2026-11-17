#!/bin/bash
# 启用（正式）：只在 July 明确批准后运行。停用旧的 com.july.lp3-collect / lp3-stage2-collect（plist 改名留档），停用影子任务，
# 加载 com.july.lp3m-stage1（08:20）/ lp3m-stage2（10:20），经 run_task.sh 运行（失败照常走通用告警）。
# 用法：activate.sh --confirm="July 批准 YYYY-MM-DD <原话>"
set -uo pipefail
. "$(dirname "$0")/_common.sh"
CONFIRM=""; for a in "$@"; do case "$a" in --confirm=*) CONFIRM="${a#--confirm=}";; *) die "未知参数 $a";; esac; done
[ -n "$CONFIRM" ] || die "缺 --confirm=\"July 批准 …\"。没有 July 的明确批准不能启用。"
[ -x "$H/.openclaw/workspace/scripts/run_task.sh" ] || die "找不到 run_task.sh"
[ -f "$REPO/lp3/RELEASE_VERSION" ] || die "lp3 未安装，先跑 install.sh"
/bin/bash "$PKG/install/verify.sh" || die "verify 未通过，不启用"
YDAY=$($PY -c 'import datetime as d; print((d.datetime.now(d.timezone(d.timedelta(hours=8))).date()-d.timedelta(days=1)).isoformat())')
( cd "$REPO" && $PY -m lp3.lab.seed_history --src="$REPO/out/mvp3" --through="$YDAY" --days=8 --out-root="$REPO/out/lp3" ) || die "播种失败"
for L in $OLD_LABELS $SHADOW_LABELS; do unload_disable "$L"; done
for L in $PROD_LABELS; do render "$L"; load "$L"; say "已加载 $L"; done
$PY - "$REPO/out/lp3/ACTIVATE-RECORD.json" "$(cat "$REPO/lp3/RELEASE_VERSION")" "$TS" "$CONFIRM" <<'PY'
import json, sys
json.dump({'release': sys.argv[2], 'activated_at': sys.argv[3], 'confirm': sys.argv[4], 'disabled_suffix': '.disabled-' + sys.argv[3]},
          open(sys.argv[1], 'w'), ensure_ascii=False, indent=1)
PY
say "已启用。旧任务的 plist 保留为 .disabled-$TS，至少留 7 天；回退跑 rollback.sh。"
say "手工待办：AUTOMATIONS.md、PATHS.md 改登记；supervisor_collect.py 的 LAUNCHAGENTS 把 lp3-collect / lp3-stage2-collect 换成 lp3m-stage1 / lp3m-stage2（状态文件同名 .json，max_idle_hours 26）。"
