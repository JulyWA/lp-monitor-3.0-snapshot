#!/bin/bash
# 安装（影子）：把 lp3 代码放进仓库，用 1 号机 out/mvp3 的历史播种，渲染并加载两个影子任务。
# 不停、不改现有正式任务；影子只写 out/lp3-shadow 和 ~/.local/state/automation-lp3m-shadow，不推送。
# 用法：install.sh [--no-load] [--commit]
set -uo pipefail
. "$(dirname "$0")/_common.sh"
NOLOAD=0; COMMIT=0; for a in "$@"; do case "$a" in --no-load) NOLOAD=1;; --commit) COMMIT=1;; *) die "未知参数 $a";; esac; done
/bin/bash "$PKG/install/preflight.sh" || die "预检未通过"
if [ -e "$REPO/lp3" ]; then mv "$REPO/lp3" "$REPO/lp3.bak-$TS" && say "旧 lp3 备份到 lp3.bak-$TS"; fi
cp -R "$PKG/src/lp3" "$REPO/lp3" && say "lp3 已放入仓库（版本 $(cat "$REPO/lp3/RELEASE_VERSION")）"
YDAY=$($PY -c 'import datetime as d; print((d.datetime.now(d.timezone(d.timedelta(hours=8))).date()-d.timedelta(days=1)).isoformat())')
( cd "$REPO" && $PY -m lp3.lab.seed_history --src="$REPO/out/mvp3" --through="$YDAY" --days=8 --out-root="$REPO/out/lp3-shadow" ) || die "播种失败"
mkdir -p "$H/.local/state/automation-lp3m-shadow"
for L in $SHADOW_LABELS; do render "$L"; say "已渲染 $L"; [ $NOLOAD = 1 ] || { load "$L"; say "已加载 $L"; }; done
if [ $COMMIT = 1 ]; then
  ( cd "$REPO" && git add lp3 && git commit -q -m "lp3 $(cat lp3/RELEASE_VERSION)：3.0 模块化（发布包安装，影子运行）" && say "已提交 $(git rev-parse --short HEAD)" )
fi
$PY - "$REPO/out/lp3-shadow/INSTALL-RECORD.json" "$(cat "$REPO/lp3/RELEASE_VERSION")" "$TS" <<'PY'
import json, sys
json.dump({'release': sys.argv[2], 'installed_at': sys.argv[3], 'mode': 'shadow'}, open(sys.argv[1], 'w'), ensure_ascii=False, indent=1)
PY
say "安装完成。影子任务：stage2 每天 10:35、stage1 每天 11:00。现有 com.july.lp3-collect / lp3-stage2-collect 照常运行。"
say "下一步：verify.sh；影子自然运行 1–3 天后，用 lp3.lab.compare_prod 对比影子与正式产出。"
