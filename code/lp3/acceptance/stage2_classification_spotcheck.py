#!/usr/bin/env python3
"""3.0 内部阶段 2 · 分类抽查（20 池）。只读：读 1 号机同步来的 out/mvp3 产出，逐个代币查 CoinGecko 公开接口（免 key）。

方法（可复现）：
  样本：从 <日期> 三家输出的全部 ≥$50 万池里分层抽 20 个：Orca 7、Raydium 7、Meteora 6；随机种子固定。
        每家先各取一个「股票和商品」、meme、unlisted、unknown、error、ok、anchor（有就取），再随机补足；
        必含上次误挡的 USDG / sUSD.infra（Orca）和本次唯一「仅因待分类被挡」的 BLESS / USDC（Raydium）。
  核对：池里每个非稳定币、非主流币的代币，查 /coins/solana/contract/<mint>：
        404 = CoinGecko 未收录（unlisted）；分类名含 meme = meme；其他 = ok。
        股票和商品：实时分类名含代币化股票/ETF/商品等关键词，或币 id 在 11-11 股票名单里。
        池级标签按管线同样的优先级（meme > unknown > error > unlisted > ok；无需查询的代币 = anchor）。
  判定：资产类别一致 且 标签一致 = 正确。查询失败的池记「无法核实」，单列，不算正确。
用法（仓库根目录）：/usr/bin/python3 -m lp3.acceptance.stage2_classification_spotcheck --src=<out/mvp3 目录> --date=2026-11-17 --out=<目录>
"""
import datetime
import json
import os
import random
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SEED = 20261117
PER = (('orca', 7), ('raydium', 7), ('meteora', 6))
MUST = {('orca', 'USDG / sUSD.infra'), ('raydium', 'BLESS / USDC')}
BUCKETS = ('stock', 'meme', 'unlisted', 'unknown', 'error', 'ok', 'anchor')
STOCK_WORDS = ('tokenized stock', 'xstocks', 'tokenized commodit', 'tokenized gold', 'exchange-traded', 'etf', 'pre-ipo', 'ondo tokenized',
               'bstocks', 'prestocks', 'openstock', 'remora', 'vnx', 'commodity-backed', 'robinhood chain stocks')
SGT = datetime.timezone(datetime.timedelta(hours=8))
UA = {'User-Agent': 'Mozilla/5.0 (Macintosh) lp-research-spotcheck', 'Accept': 'application/json'}


def load(p):
    with open(p) as fh:
        return json.load(fh)


def module_cfg(name):
    return load(os.path.join(ROOT, 'lp3', 'modules', name, 'config.json'))['rules']


def bucket(r):
    return 'stock' if r.get('asset_class') == '股票和商品' else r.get('meme_label') or 'unknown'


def sample(src, date):
    rng = random.Random(SEED)
    picked = []
    for name, n in PER:
        rows = load(os.path.join(src, '%s-%s.json' % (name, date)))['rows']
        mine = [r for r in rows if (name, r['name']) in MUST]
        for b in BUCKETS:
            if len(mine) >= n:
                break
            cand = [r for r in rows if bucket(r) == b and r not in mine]
            if cand and not any(bucket(x) == b for x in mine):
                mine.append(rng.choice(cand))
        rest = [r for r in rows if r not in mine]
        rng.shuffle(rest)
        mine += rest[:max(0, n - len(mine))]
        picked += [dict(r, _src=name) for r in mine[:n]]
    return picked


def cg_lookup(mint, cache, pause=7.0):
    if mint in cache:
        return cache[mint]
    url = 'https://api.coingecko.com/api/v3/coins/solana/contract/' + mint
    res = None
    for k in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
                d = json.loads(r.read())
            res = {'http': 200, 'id': d.get('id'), 'symbol': d.get('symbol'), 'categories': d.get('categories') or []}
            break
        except urllib.error.HTTPError as e:
            if e.code == 404:
                res = {'http': 404}
                break
            res = {'http': e.code}
            time.sleep(60 if e.code == 429 else 10)
        except Exception as e:
            res = {'http': None, 'error': str(e)[:120]}
            time.sleep(10)
    res['checked_at'] = datetime.datetime.now(SGT).isoformat(timespec='seconds')
    cache[mint] = res
    time.sleep(pause)
    return res


def live_state(info):
    if info.get('http') == 404:
        return 'unlisted'
    if info.get('http') != 200:
        return 'lookup_failed'
    if any('meme' in str(c).lower() for c in info['categories']):
        return 'meme'
    return 'ok'


def is_stock_live(info, stock_ids):
    if info.get('http') != 200:
        return False
    cats = ' | '.join(info['categories']).lower()
    return info.get('id') in stock_ids or any(w in cats for w in STOCK_WORDS)


def check(picked, stock_ids, cache):
    R = module_cfg('orca')
    skip = set(R['sol_stable']) | set(R['sol_major'])
    out = []
    for r in picked:
        toks = []
        for sym, mint in r['tokens']:
            if (sym or '').upper() in skip:
                toks.append({'symbol': sym, 'mint': mint, 'skipped': '稳定币或主流币（anchor）'})
                continue
            info = cg_lookup(mint, cache) if mint else {'http': None, 'error': '无地址'}
            toks.append({'symbol': sym, 'mint': mint, 'cg': info, 'live_state': live_state(info), 'live_stock': is_stock_live(info, stock_ids)})
        states = [t['live_state'] for t in toks if 'live_state' in t]
        if 'lookup_failed' in states:
            live = 'lookup_failed'
        elif not states:
            live = 'anchor'
        else:
            live = next(s for s in ('meme', 'unlisted', 'ok') if s in states)
        live_stock = any(t.get('live_stock') for t in toks)
        pipe_stock = r.get('asset_class') == '股票和商品'
        if live == 'lookup_failed':
            verdict, cause = '无法核实', 'CoinGecko 查询失败'
        else:
            class_ok, label_ok = pipe_stock == live_stock, r.get('meme_label') == live
            verdict = '正确' if class_ok and label_ok else '错误'
            cause = None
            if not label_ok:
                cause = '管线标签 %s，CoinGecko 实时 %s' % (r.get('meme_label'), live)
                if r.get('meme_label') in ('unknown', 'error'):
                    cause += '（标签缓存未覆盖或过期）'
            if not class_ok:
                cause = (cause + '；' if cause else '') + '资产类别：管线 %s，实时 %s' % (r.get('asset_class'), '股票和商品' if live_stock else '代币')
        only_label_block = r.get('why_out') in ('代币分类待更新',)
        out.append({'source': r['_src'], 'protocol': r['protocol'], 'pool': r['pool'], 'name': r['name'], 'tvl': r['tvl'],
                    'pipeline': {'asset_class': r.get('asset_class'), 'meme_label': r.get('meme_label'), 'why_out': r.get('why_out')},
                    'live': {'meme_label': live, 'stock': live_stock}, 'tokens': toks, 'verdict': verdict, 'cause': cause,
                    'blocked_only_by_label': only_label_block})
    return out


def report(res, date, src):
    n = len(res)
    ok = sum(x['verdict'] == '正确' for x in res)
    bad = [x for x in res if x['verdict'] == '错误']
    na = [x for x in res if x['verdict'] == '无法核实']
    L = ['# 阶段 2 分类抽查 · %s 输出（20 池）' % date, '',
         '**结论：%d / %d 正确**%s。' % (ok, n, '；无法核实 %d' % len(na) if na else ''), '',
         '- 数据：1 号机 %s 10:20 自然运行产出（同步包 `%s`）。' % (date, os.path.relpath(src, os.path.expanduser('~'))),
         '- 管线标签：来自 11-16 17:22 刷新的 Solana 标签缓存；对照：CoinGecko 公开接口实时查询（时间见每行）。',
         '- 方法：分层抽样（种子 %d），每家覆盖全部标签类型，必含 USDG / sUSD.infra 和 BLESS / USDC；判定 = 资产类别一致且标签一致。' % SEED, '',
         '| # | 协议 | 池 | TVL | 管线（类别 · 标签 · 挡因） | 实时（类别 · 标签） | 判定 |', '| --- | --- | --- | --- | --- | --- | --- |']
    for i, x in enumerate(res, 1):
        p, l = x['pipeline'], x['live']
        L.append('| %d | %s | %s | $%.1fM | %s · %s · %s | %s · %s | %s |' % (
            i, x['protocol'], x['name'], x['tvl'] / 1e6, p['asset_class'], p['meme_label'], p['why_out'] or '过门槛',
            '股票和商品' if l['stock'] else '代币', l['meme_label'], ('**%s**' % x['verdict']) if x['verdict'] != '正确' else '正确'))
    if bad or na:
        L += ['', '## 错误与无法核实', ''] + ['- **%s %s**：%s%s' % (x['protocol'], x['name'], x['cause'],
                                                                 '；该池**仅因待分类被挡**' if x['blocked_only_by_label'] else '') for x in bad + na]
    L += ['', '## 逐代币查询', '']
    for x in res:
        for t in x['tokens']:
            if 'cg' in t:
                c = t['cg']
                L.append('- %s `%s…`：HTTP %s，id=%s，分类=%s（%s）' % (t['symbol'], t['mint'][:8], c.get('http'), c.get('id'),
                                                                 '、'.join(c.get('categories') or [])[:160] or '—', c.get('checked_at')))
    return '\n'.join(L) + '\n'


def main():
    o = dict(a[2:].split('=', 1) for a in sys.argv[1:] if a.startswith('--') and '=' in a)
    src, date, out = o['src'], o['date'], o['out']
    os.makedirs(out, exist_ok=True)
    stock_ids = {i for v in load(os.path.join(ROOT, 'mvp3', 'stage0', 'out', 'stocklist-raw-2026-11-11.json'))['members'].values() for i, _, _ in v}
    cache_p = os.path.join(out, 'cg-cache.json')
    cache = load(cache_p) if os.path.exists(cache_p) else {}
    picked = sample(src, date)
    print('样本：' + '；'.join('%s %s' % (r['_src'], r['name']) for r in picked))
    res = check(picked, stock_ids, cache)
    with open(cache_p, 'w') as fh:
        json.dump(cache, fh, ensure_ascii=False, indent=1)
    with open(os.path.join(out, 'stage2-classification-%s.json' % date), 'w') as fh:
        json.dump({'date': date, 'seed': SEED, 'results': res}, fh, ensure_ascii=False, indent=1)
    md = report(res, date, src)
    with open(os.path.join(out, 'stage2-classification-%s.md' % date), 'w') as fh:
        fh.write(md)
    print(md.split('\n')[2])
    return 0


if __name__ == '__main__':
    sys.exit(main())
