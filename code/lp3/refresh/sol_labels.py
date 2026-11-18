#!/usr/bin/env python3
"""内部阶段 3 · Solana 代币标签刷新（研究机）。数据源：CoinGecko 公开接口 /coins/solana/contract/<mint>（第三方，免 key）。

用法（仓库根目录）：
  /usr/bin/python3 -m lp3.refresh.sol_labels incremental   # 只查新出现的、缓存里没有的、上次查询失败的代币
  /usr/bin/python3 -m lp3.refresh.sol_labels full          # 缓存里全部代币 + 新出现的代币
  可选：--days=7（往回看几天的输出找代币）  --pause=7（每次查询间隔秒数）  --limit=N（最多查 N 个，测试用）

缓存：out/lab/refdata/sol-token-labels.json（首次从 mvp3/stage0/out/sol-token-labels.json 复制）。格式不变：
  {mint: {id, cats, mcap, symbol, refreshed}}；id 为 null = CoinGecko 未收录；新增 stale_since = 最近一次查询失败、沿用旧值的日期。
规则：
  - 404 → 未收录（id=null）。
  - 429 → 等 60 秒重试，最多 3 次；其他错误等 10 秒重试。仍失败：已有条目保留旧值、写 stale_since；新代币记 id='ERROR'（与旧脚本一致，管线会挡在榜外并标「代币分类待更新」）。
  - 写入前备份旧缓存（out/lab/refdata/backup/，保留 8 份），先写临时文件再改名。
产出：out/lab/refdata/labels-diff-<日期>.{json,md}：新增、标签变化（尤其正常↔meme）、仍失败、以及「如果模块改用新缓存，哪些池的标签会变」（干跑）。
模块默认仍读基线缓存；切换要 July 批准（设 LP3_SOL_LABELS 指向新缓存）。
"""
import datetime
import glob
import json
import os
import shutil
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BASELINE = os.path.join(ROOT, 'mvp3', 'stage0', 'out', 'sol-token-labels.json')
REFDATA = os.path.join(ROOT, 'out', 'lab', 'refdata')
CACHE = os.path.join(REFDATA, 'sol-token-labels.json')
SOURCES = ('orca', 'raydium', 'meteora')
SGT = datetime.timezone(datetime.timedelta(hours=8))
UA = {'User-Agent': 'Mozilla/5.0 (Macintosh) lp-research-labels', 'Accept': 'application/json'}
KEEP_BACKUPS = 8


def now_sgt():
    return datetime.datetime.now(SGT)


def load(p, default=None):
    if not os.path.exists(p):
        return default
    with open(p) as fh:
        return json.load(fh)


def dump(obj, p):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + '.tmp'
    with open(tmp, 'w') as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, p)


def anchors():
    cfg = load(os.path.join(ROOT, 'lp3', 'modules', 'orca', 'config.json'))['rules']
    return set(cfg['sol_stable']) | set(cfg['sol_major'])


def recent_tokens(days, today=None):
    """最近 days 天三家输出里出现的非锚定代币 {mint: symbol}。读研究机模块输出和 1 号机同步来的 out/mvp3。"""
    today = today or now_sgt().date()
    skip = anchors()
    found = {}
    for k in range(days):
        d = (today - datetime.timedelta(days=k)).isoformat()
        for s in SOURCES:
            for p in (os.path.join(ROOT, 'out', 'lab', 'lp3', s, '%s-%s.json' % (s, d)), os.path.join(ROOT, 'out', 'mvp3', '%s-%s.json' % (s, d))):
                doc = load(p)
                for r in (doc or {}).get('rows', []):
                    for sym, mint in r.get('tokens') or []:
                        if mint and (sym or '').upper() not in skip:
                            found.setdefault(mint, sym)
    return found


def lookup(mint, pause, fetch=None):
    """返回 (结果字典或 None, 状态)。状态：ok / unlisted / failed:<原因>。"""
    url = 'https://api.coingecko.com/api/v3/coins/solana/contract/' + mint
    last = None
    for k in range(4):
        try:
            if fetch:
                code, d = fetch(url)
                if code != 200:
                    raise urllib.error.HTTPError(url, code, 'fake', {}, None)
            else:
                with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
                    d = json.loads(r.read())
            return {'id': d.get('id'), 'cats': d.get('categories') or [], 'mcap': ((d.get('market_data') or {}).get('market_cap') or {}).get('usd'),
                    'symbol': d.get('symbol')}, 'ok'
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return {'id': None, 'cats': [], 'mcap': None}, 'unlisted'
            last = 'HTTP %s' % e.code
            time.sleep(60 if e.code == 429 else 10)
        except Exception as e:
            last = type(e).__name__
            time.sleep(10)
    return None, 'failed:%s' % last


def label_of(entry):
    if entry is None:
        return 'unknown'
    if entry.get('id') == 'ERROR':
        return 'error'
    if not entry.get('id'):
        return 'unlisted'
    return 'meme' if any('meme' in str(c).lower() for c in entry.get('cats') or []) else 'ok'


def backup(cache_path):
    if not os.path.exists(cache_path):
        return None
    bdir = os.path.join(os.path.dirname(cache_path), 'backup')
    os.makedirs(bdir, exist_ok=True)
    dst = os.path.join(bdir, 'sol-token-labels-%s.json' % now_sgt().strftime('%Y%m%d-%H%M%S'))
    shutil.copy2(cache_path, dst)
    olds = sorted(glob.glob(os.path.join(bdir, 'sol-token-labels-*.json')))
    for p in olds[:-KEEP_BACKUPS]:
        os.remove(p)
    return dst


def refresh(mode, days=7, pause=7.0, limit=None, cache_path=CACHE, fetch=None, today=None):
    if not os.path.exists(cache_path):
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        shutil.copy2(BASELINE, cache_path)
    old = load(cache_path, {})
    seen = recent_tokens(days, today)
    if mode == 'full':
        todo = list(old) + [m for m in seen if m not in old]
    else:
        todo = [m for m in seen if m not in old or old[m].get('id') == 'ERROR' or old[m].get('stale_since')]
    if limit:
        todo = todo[:limit]
    new = json.loads(json.dumps(old))
    today_s = (today or now_sgt().date()).isoformat()
    added, changed, failed, unchanged = [], [], [], 0
    for i, mint in enumerate(todo):
        res, st = lookup(mint, pause, fetch)
        prev = old.get(mint)
        sym = (res or {}).get('symbol') or (prev or {}).get('symbol') or seen.get(mint)
        if res is None:
            failed.append({'mint': mint, 'symbol': sym, 'reason': st})
            if prev and prev.get('id') != 'ERROR':
                new[mint] = dict(prev, stale_since=prev.get('stale_since') or today_s)
            else:
                new[mint] = {'id': 'ERROR', 'cats': [], 'mcap': None, 'symbol': sym, 'refreshed': today_s}
        else:
            entry = {'id': res['id'], 'cats': res['cats'], 'mcap': res['mcap'], 'symbol': sym, 'refreshed': today_s}
            new[mint] = entry
            if prev is None:
                added.append({'mint': mint, 'symbol': sym, 'label': label_of(entry)})
            elif label_of(prev) != label_of(entry):
                changed.append({'mint': mint, 'symbol': sym, 'from': label_of(prev), 'to': label_of(entry)})
            else:
                unchanged += 1
        if i < len(todo) - 1:
            time.sleep(pause)
    bk = backup(cache_path)
    dump(new, cache_path)
    return {'mode': mode, 'date': today_s, 'queried': len(todo), 'added': added, 'changed': changed, 'failed': failed,
            'unchanged': unchanged, 'cache_size': len(new), 'backup': bk and os.path.relpath(bk, ROOT)}, old, new


def impact(old, new, date):
    """干跑：用研究机当天三家输出的池，比较新旧缓存下的池级标签。返回标签会变的池。"""
    sys.path.insert(0, ROOT)
    from lp3.modules.orca import rules
    R = load(os.path.join(ROOT, 'lp3', 'modules', 'orca', 'config.json'))['rules']
    out = []
    for s in SOURCES:
        for p in (os.path.join(ROOT, 'out', 'lab', 'lp3', s, '%s-%s.json' % (s, date)), os.path.join(ROOT, 'out', 'mvp3', '%s-%s.json' % (s, date))):
            doc = load(p)
            if doc:
                spec = load(os.path.join(ROOT, 'lp3', 'modules', s, 'config.json'))['coverage']
                for r in doc['rows']:
                    a, b = rules.solana_label(r['tokens'], old, R), rules.solana_label(r['tokens'], new, R)
                    if a != b:
                        out.append({'source': s, 'name': r['name'], 'tvl': r['tvl'], 'from': a, 'to': b, 'why_out_now': r.get('why_out'),
                                    'why_out_after': rerun(r, new, R, spec, rules)})
                break
    return out


def rerun(r, labels, R, spec, rules):
    """用新标签重跑本模块的筛选规则，返回新的挡因（空串 = 过门槛）。只用行里已有字段；Meteora 黑名单原因保留。"""
    x = {k: v for k, v in r.items() if k not in ('why_out', 'meme_label', 'meme_candidate', 'low_fee_unlisted', 'apy_now', 'apy_7d', 'asset_class')}
    x['notes'] = ''
    if 'Meteora 官方黑名单' in (r.get('why_out') or ''):
        x['_filter_reasons'] = ['Meteora 官方黑名单']
    return rules.finish_solana(x, {}, labels, R, spec, filter_unlisted=True)['why_out']


def report(res, imp):
    L = ['# Solana 标签刷新 · %s（%s）' % (res['date'], '全量' if res['mode'] == 'full' else '增量'), '',
         '查询 %d 个；新增 %d；标签变化 %d；仍失败 %d；未变 %d；缓存共 %d 个。' % (
             res['queried'], len(res['added']), len(res['changed']), len(res['failed']), res['unchanged'], res['cache_size']), '']
    if res['changed']:
        L += ['## 标签变化', '', '| 代币 | 原 | 新 |', '| --- | --- | --- |'] + ['| %s | %s | %s |' % (x['symbol'], x['from'], x['to']) for x in res['changed']] + ['']
    if res['added']:
        L += ['## 新增', '', '| 代币 | 标签 |', '| --- | --- |'] + ['| %s | %s |' % (x['symbol'], x['label']) for x in res['added']] + ['']
    if res['failed']:
        L += ['## 仍失败（沿用旧值或记为待分类）', ''] + ['- %s：%s' % (x['symbol'], x['reason']) for x in res['failed']] + ['']
    L += ['## 干跑：模块改用新缓存后，当天会变的池', '']
    L += (['| 来源 | 池 | TVL | 标签 | 现在的挡因 | 改用新缓存后的挡因 |', '| --- | --- | --- | --- | --- | --- |'] +
          ['| %s | %s | $%.1fM | %s → %s | %s | %s |' % (x['source'], x['name'], x['tvl'] / 1e6, x['from'], x['to'], x['why_out_now'] or '过门槛', x['why_out_after'] or '**过门槛**') for x in imp]
          if imp else ['无。'])
    L += ['', '模块目前仍读基线缓存（M4 研究机自然运行期间保持与 1 号机一致）；切换需 July 批准。']
    return '\n'.join(L) + '\n'


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    mode = next((a for a in argv if not a.startswith('--')), 'incremental')
    if mode not in ('incremental', 'full'):
        raise SystemExit('用法：sol_labels incremental|full [--days=7] [--pause=7] [--limit=N]')
    o = dict(a[2:].split('=', 1) for a in argv if a.startswith('--') and '=' in a)
    res, old, new = refresh(mode, int(o.get('days', 7)), float(o.get('pause', 7)), int(o['limit']) if o.get('limit') else None)
    sys.path.insert(0, ROOT)
    from lp3.common import refdata
    imp = impact(load(refdata.SOL_LABELS, {}), new, res['date'])  # 和模块当前实际读的缓存比（M4 期间是基线）
    res['impact'] = imp
    dump(res, os.path.join(REFDATA, 'labels-diff-%s.json' % res['date']))
    with open(os.path.join(REFDATA, 'labels-diff-%s.md' % res['date']), 'w') as fh:
        fh.write(report(res, imp))
    print('标签刷新（%s）：查询 %d，新增 %d，变化 %d，失败 %d；干跑影响 %d 个池' % (mode, res['queried'], len(res['added']), len(res['changed']), len(res['failed']), len(imp)))
    return 1 if res['failed'] and len(res['failed']) == res['queried'] and res['queried'] else 0


if __name__ == '__main__':
    sys.exit(main())
