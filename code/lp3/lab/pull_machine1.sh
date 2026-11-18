#!/bin/bash
# 研究机从 1 号机只读拉取当天 3.0 产出（代替手动同步）。用 ~/.ssh/config 里的 Host lp-machine1（受限钥匙，1 号机只会执行导出脚本）。
# 结果放进 ~/lp-lab/sync/<时间>/（out-mvp3/、state/、meta/，与手动同步包同结构），校验和通过后，
# 把研究机仓库 out/mvp3/ 里还没有的文件补进去（不覆盖；内容不同的只报告）。记录追加到 ~/lp-lab/sync/PULL-LOG.jsonl。
set -uo pipefail
TS="$(date +%Y%m%d-%H%M%S)"
SYNC="$HOME/lp-lab/sync"; DEST="$SYNC/$TS-pull"; LAB_MVP3="$HOME/lp-lab/lp-research/out/mvp3"
mkdir -p "$DEST"
log() { printf '{"at":"%s","dest":"%s","status":"%s","detail":"%s"}\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')" "$DEST" "$1" "$2" >> "$SYNC/PULL-LOG.jsonl"; echo "[$1] $2"; }
if ! /usr/bin/ssh -o BatchMode=yes -o ConnectTimeout=20 lp-machine1 > "$DEST/export.tgz" 2> "$DEST/ssh.err"; then
  log failed "ssh 失败：$(tail -c 200 "$DEST/ssh.err" | tr '\n"' ' _')"; exit 1
fi
tar -xzf "$DEST/export.tgz" -C "$DEST" 2>"$DEST/tar.err" || { log failed "解包失败：$(tail -c 200 "$DEST/tar.err" | tr '\n"' ' _')"; exit 1; }
( cd "$DEST" && shasum -a 256 -c -s SHA256SUMS.txt ) || { log failed "校验和不对"; exit 1; }
rm -f "$DEST/export.tgz"
NEW=0; DIFF=""
for f in "$DEST"/out-mvp3/*; do
  b="$(basename "$f")"
  if [ ! -e "$LAB_MVP3/$b" ]; then cp -p "$f" "$LAB_MVP3/$b"; NEW=$((NEW+1))
  elif ! cmp -s "$f" "$LAB_MVP3/$b"; then DIFF="$DIFF $b"; fi
done
log ok "导出于 $(grep -m1 "^20" "$DEST/meta/EXPORT_INFO.txt")（$(grep -m1 "^export" "$DEST/meta/EXPORT_INFO.txt" || echo export v1)）；新增 $NEW 个到研究机 out/mvp3；内容不同未覆盖：${DIFF:- 无}"
