#!/bin/bash
# 预检：只读，不改任何东西。检查发布包完整性、Python、仓库、基线代码是否被改过、任务名冲突。退出码非 0 表示不能装。
set -uo pipefail
. "$(dirname "$0")/_common.sh"
FAIL=0; bad() { echo "  ✗ $*"; FAIL=1; }; ok() { echo "  ✓ $*"; }
say "预检：仓库 $REPO"
( cd "$PKG" && shasum -a 256 -c -s SHA256SUMS.txt ) && ok "发布包校验和" || bad "发布包校验和不对"
V=$($PY -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null); [ "$V" = "3.9" ] && ok "Python $V" || bad "Python 版本是 ${V:-无}，需要 3.9"
[ -f "$REPO/mvp3/collect.py" ] && ok "仓库存在" || bad "找不到 $REPO/mvp3/collect.py"
git -C "$REPO" rev-parse --git-dir >/dev/null 2>&1 && ok "git 仓库，HEAD $(git -C "$REPO" rev-parse --short HEAD)" || bad "不是 git 仓库"
for f in $($PY -c 'import json,sys; print(" ".join(json.load(open(sys.argv[1]))["baseline"]["files"]))' "$PKG/MANIFEST.json"); do
  want=$($PY -c 'import json,sys; print(json.load(open(sys.argv[1]))["baseline"]["files"][sys.argv[2]])' "$PKG/MANIFEST.json" "$f")
  have=$(shasum -a 256 "$REPO/$f" 2>/dev/null | cut -d' ' -f1)
  [ "$want" = "$have" ] && ok "基线未变：$f" || bad "基线已变：$f（发布包按旧代码做的回放，需要研究机按新代码重做）"
done
if [ -e "$REPO/lp3" ]; then
  [ -f "$REPO/lp3/RELEASE_VERSION" ] && ok "已有 lp3（版本 $(cat "$REPO/lp3/RELEASE_VERSION")），安装会备份后替换" || bad "$REPO/lp3 已存在且不是发布包装的，先人工确认"
else ok "仓库里还没有 lp3"; fi
for L in $SHADOW_LABELS $PROD_LABELS; do [ -f "$LA/$L.plist" ] && echo "  · 已有 $L（安装/启用会替换）"; done
for L in $OLD_LABELS; do [ -f "$LA/$L.plist" ] && ok "现有正式任务 $L 在（安装不动它）" || echo "  · 没找到 $L.plist"; done
[ -x "$H/.openclaw/workspace/scripts/run_task.sh" ] && ok "run_task.sh 在（启用时用）" || echo "  · 没找到 run_task.sh：影子安装不受影响，正式启用前必须有"
[ $FAIL = 0 ] && say "预检通过" || say "预检未通过"
exit $FAIL
