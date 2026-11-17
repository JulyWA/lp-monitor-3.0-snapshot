# 发布包脚本共用设置。可用环境变量覆盖（演练时用临时目录，正式运行不用设）：
#   LP3_HOME      家目录（缺省 $HOME）
#   LP3_REPO      lp-research 仓库（缺省 $LP3_HOME/claude test/lp-research）
#   LP3_LAUNCHCTL launchctl 命令（演练时设成 echo，不真的加载）
PKG="$(cd "$(dirname "$0")/.." && pwd)"
H="${LP3_HOME:-$HOME}"
REPO="${LP3_REPO:-$H/claude test/lp-research}"
LA="$H/Library/LaunchAgents"
LCTL="${LP3_LAUNCHCTL:-launchctl}"
DOMAIN="gui/$(id -u)"
TS="$(date +%Y%m%d-%H%M%S)"
PY=/usr/bin/python3
OLD_LABELS="com.july.lp3-collect com.july.lp3-stage2-collect"
SHADOW_LABELS="com.july.lp3m-shadow-stage1 com.july.lp3m-shadow-stage2"
PROD_LABELS="com.july.lp3m-stage1 com.july.lp3m-stage2"
say() { echo "[$(date '+%H:%M:%S')] $*"; }
die() { echo "停止：$*" >&2; exit 1; }
render() { # 模板标签 -> LaunchAgents/<标签>.plist（先渲染到临时文件、校验，再替换）
  local L="$1" out="$LA/$1.plist"
  mkdir -p "$LA"
  sed -e "s#__REPO__#$REPO#g" -e "s#__HOME__#$H#g" "$PKG/launchd/templates/$L.plist.template" > "$out.tmp"
  plutil -lint "$out.tmp" >/dev/null || die "$L 渲染后 plist 校验失败"
  mv "$out.tmp" "$out"
}
load() { $LCTL bootout "$DOMAIN/$1" 2>/dev/null || true; $LCTL bootstrap "$DOMAIN" "$LA/$1.plist" || die "加载 $1 失败"; }
unload_disable() { # 停掉并把 plist 改名留档（不删）
  $LCTL bootout "$DOMAIN/$1" 2>/dev/null || true
  [ -f "$LA/$1.plist" ] && mv "$LA/$1.plist" "$LA/$1.plist.disabled-$TS" && say "已停用 $1（plist 改名 .disabled-$TS）"
  return 0
}
