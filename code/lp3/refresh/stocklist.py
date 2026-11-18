#!/usr/bin/env python3
"""内部阶段 3 · 股票和商品名单刷新（研究机，每周一次）。数据源：CoinGecko 公开接口（第三方，免 key）。

用法（仓库根目录）：/usr/bin/python3 -m lp3.refresh.stocklist [--pause=7]
  1. 对 15 个分类逐页拉 /coins/markets?category=<分类>，得到当前成员。
  2. 和上一版名单比：新成员逐个拉 /coins/<id> 取各链合约地址；不再出现的成员**不删**，记 missing_since。
  3. 写 out/lab/refdata/stocklist-raw-<日期>.json（格式与 mvp3/stage0/out/stocklist-raw-2026-11-11.json 相同，多一个 missing_since）
     和 stocklist-diff-<日期>.md。
任一分类拉取失败：整次不写新名单，只写报告（名单宁可旧，不能残缺）。模块默认仍读基线名单；切换要 July 批准（LP3_STOCKLIST）。
"""
import datetime
import glob
import json
import os
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BASELINE = os.path.join(ROOT, 'mvp3', 'stage0', 'out', 'stocklist-raw-2026-11-11.json')
REFDATA = os.path.join(ROOT, 'out', 'lab', 'refdata')
SGT = datetime.timezone(datetime.timedelta(hours=8))
UA = {'User-Agent': 'Mozilla/5.0 (Macintosh) lp-research-stocklist', 'Accept': 'application/json'}


def load(p):
    with open(p) as fh:
        return json.load(fh)


def get(url, pause, fetch=None):
    last = None
    for k in range(4):
        try:
            if fetch:
                code, d = fetch(url)
                if code != 200:
                    raise urllib.error.HTTPError(url, code, 'fake', {}, None)
                return d
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            last = 'HTTP %s' % e.code
            if e.code == 404:
                break
            time.sleep(60 if e.code == 429 else 10)
        except Exception as e:
            last = type(e).__name__
            time.sleep(10)
        finally:
            time.sleep(pause)
    raise RuntimeError('%s -> %s' % (url[:120], last))


def latest_previous():
    cands = sorted(glob.glob(os.path.join(REFDATA, 'stocklist-raw-*.json')))
    return cands[-1] if cands else BASELINE


def refresh(pause=7.0, fetch=None, today=None):
    prev_p = latest_previous()
    prev = load(prev_p)
    today_s = (today or datetime.datetime.now(SGT).date()).isoformat()
    members, errors = {}, []
    for cat in prev['categories']:
        got, page = [], 1
        while True:
            try:
                d = get('https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&category=%s&per_page=250&page=%d' % (cat, page), pause, fetch)
            except RuntimeError as e:
                errors.append('%s：%s' % (cat, e)); break
            got += [[c['id'], c.get('symbol'), c.get('market_cap')] for c in d]
            if len(d) < 250:
                break
            page += 1
        members[cat] = got
    old_ids = {i for v in prev['members'].values() for i, _, _ in v}
    new_ids = {i for v in members.values() for i, _, _ in v}
    added, gone = sorted(new_ids - old_ids), sorted(old_ids - new_ids)
    res = {'date': today_s, 'previous': os.path.relpath(prev_p, ROOT), 'errors': errors, 'added': added, 'gone': gone, 'written': None}
    if errors:
        return res
    platforms = dict(prev['platforms'])
    for cid in added:
        try:
            d = get('https://api.coingecko.com/api/v3/coins/%s?localization=false&tickers=false&market_data=false&community_data=false&developer_data=false' % cid, pause, fetch)
            platforms[cid] = {k: v for k, v in (d.get('platforms') or {}).items() if k and v}
        except RuntimeError as e:
            res['errors'].append('%s 合约地址：%s' % (cid, e))
    if res['errors']:
        return res
    merged = {cat: list(members[cat]) for cat in prev['categories']}
    missing = dict(prev.get('missing_since') or {})
    for cat, lst in prev['members'].items():
        have = {i for i, _, _ in merged.get(cat, [])}
        for item in lst:
            if item[0] not in have:  # CoinGecko 这次没列出：保留，记日期
                merged.setdefault(cat, []).append(item)
                missing.setdefault(item[0], today_s)
    for cid in list(missing):
        if cid in new_ids:
            missing.pop(cid)
    out = {'categories': prev['categories'], 'members': merged, 'platforms': platforms, 'missing_since': missing, 'refreshed': today_s}
    p = os.path.join(REFDATA, 'stocklist-raw-%s.json' % today_s)
    os.makedirs(REFDATA, exist_ok=True)
    tmp = p + '.tmp'
    with open(tmp, 'w') as fh:
        json.dump(out, fh, ensure_ascii=False)
    os.replace(tmp, p)
    res['written'] = os.path.relpath(p, ROOT)
    return res


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    o = dict(a[2:].split('=', 1) for a in argv if a.startswith('--') and '=' in a)
    res = refresh(float(o.get('pause', 7)))
    L = ['# 股票和商品名单刷新 · %s' % res['date'], '', '上一版：`%s`' % res['previous'], '',
         '新增 %d 个；本次未列出 %d 个（保留，记 missing_since）；错误 %d 条；%s。' % (
             len(res['added']), len(res['gone']), len(res['errors']), '已写新名单 `%s`' % res['written'] if res['written'] else '**未写新名单**')]
    if res['added']:
        L += ['', '## 新增', ''] + ['- ' + x for x in res['added'][:200]]
    if res['gone']:
        L += ['', '## 本次未列出', ''] + ['- ' + x for x in res['gone'][:200]]
    if res['errors']:
        L += ['', '## 错误', ''] + ['- ' + x for x in res['errors']]
    os.makedirs(REFDATA, exist_ok=True)
    with open(os.path.join(REFDATA, 'stocklist-diff-%s.md' % res['date']), 'w') as fh:
        fh.write('\n'.join(L) + '\n')
    print('股票名单刷新：新增 %d，未列出 %d，错误 %d，%s' % (len(res['added']), len(res['gone']), len(res['errors']), res['written'] or '未写新名单'))
    return 1 if res['errors'] else 0


if __name__ == '__main__':
    sys.exit(main())
