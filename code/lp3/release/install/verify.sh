#!/bin/bash
# 验证：在本机跑 lp3 全部单元测试；用发布包里的录制数据回放 ——
#   ① 新模块 vs 研究机录制时旧代码的实跑输出，必须 0 差异；
#   ② 本机自己的 mvp3/collect.py 回放 vs 同一份实跑输出，必须 0 差异（证明本机旧代码与基线一致）。
# 只写临时目录。退出码非 0 = 不通过。
set -uo pipefail
. "$(dirname "$0")/_common.sh"
cd "$REPO" || die "找不到仓库"
WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT; FAIL=0
say "单元测试"
$PY -m unittest discover -s lp3/tests -t . 2>&1 | tail -3 | grep -q "^OK" && say "  ✓ 单元测试全过" || { say "  ✗ 单元测试失败"; FAIL=1; }
for B in "$PKG"/evidence/replay/*/; do
  N=$(basename "$B"); SRC=$(cat "$B/SOURCES"); D=$(cat "$B/DATE")
  $PY -m lp3.replay.modules --sources="$SRC" --date="$D" --cassette="$B/cassette" --out="$WORK/$N-modules" --seed="$B/seed" >/dev/null 2>&1
  $PY -m lp3.replay.compare --a="$B/legacy-live" --b="$WORK/$N-modules" --sources="$SRC" --date="$D" >/dev/null && say "  ✓ $N 新模块回放 0 差异（$SRC）" || { say "  ✗ $N 新模块回放有差异"; FAIL=1; }
  $PY -m lp3.replay.legacy replay --sources="$SRC" --date="$D" --cassette="$B/cassette" --out="$WORK/$N-legacy" --seed="$B/seed" >/dev/null 2>&1
  $PY -m lp3.replay.compare --a="$B/legacy-live" --b="$WORK/$N-legacy" --sources="$SRC" --date="$D" >/dev/null && say "  ✓ $N 本机旧代码回放 0 差异" || { say "  ✗ $N 本机旧代码回放有差异（本机 mvp3 与基线不同？）"; FAIL=1; }
done
for L in $SHADOW_LABELS $PROD_LABELS; do
  sed -e "s#__REPO__#$REPO#g" -e "s#__HOME__#$H#g" "$PKG/launchd/templates/$L.plist.template" > "$WORK/$L.plist"
  plutil -lint "$WORK/$L.plist" >/dev/null || { say "  ✗ $L plist 无效"; FAIL=1; }
done
[ $FAIL = 0 ] && say "验证通过" || say "验证未通过"
exit $FAIL
