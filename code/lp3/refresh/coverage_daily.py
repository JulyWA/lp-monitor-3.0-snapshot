#!/usr/bin/env python3
"""内部阶段 3 · 扫描覆盖率每天自动重算（研究机，先干跑）。

用法（仓库根目录）：/usr/bin/python3 -m lp3.refresh.coverage_daily [--date=YYYY-MM-DD] [--inputs=已下载的目录]

口径与 mvp3/stage0/coverage_scope.py 完全相同（11-11 定、11-16 复算）：
  全市场 = DefiLlama 全部 DEX（category=Dexs），手续费、成交按 breakdown30d 近 30 天日均，TVL 按 chainTvls；
  扫描范围按同样 8 块划分；覆盖 = 能拿到数据（进榜 + 规则筛掉）。
与原脚本的唯一区别：「进榜 / 规则筛掉」的拆分不再读 11-11 的 coverage-pool 文件：
  3.0 的 6 块用当天输出里过门槛池的 24h 手续费合计（优先 1 号机同步来的 out/mvp3，没有再用研究机模块输出）；
  1.0、2.0 的部分研究机拿不到当天产出，沿用 11-11 值，报告里逐项标「沿用 11-11」。
干跑：同一份输入再跑一遍原脚本，三档扫描覆盖率必须与之相同（差 ≤ 0.05 个百分点），否则报告置顶标「口径不一致」。
告警：任一档扫描覆盖率比前 7 天均值变化超过 3 个百分点，报告置顶写明（只写文件，不推送）。
产出：out/lab/coverage/scope-<日期>.{json,md}；输入下载到 out/lab/coverage/inputs-<日期>/，只保留最近 3 天。
"""
import collections
import datetime
import glob
import json
import os
import re
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUTD = os.path.join(ROOT, 'out', 'lab', 'coverage')
STAGE0 = os.path.join(ROOT, 'mvp3', 'stage0')
SGT = datetime.timezone(datetime.timedelta(hours=8))
URLS = {'fees.json': 'https://api.llama.fi/overview/fees?dataType=dailyFees', 'dexs.json': 'https://api.llama.fi/overview/dexs',
        'protocols.json': 'https://api.llama.fi/protocols'}
ALERT_PP = 3.0
KEEP_INPUT_DAYS = 3


def load(p):
    with open(p) as fh:
        return json.load(fh)


# ---------- 以下与 coverage_scope.py 逐行一致 ----------
norm = lambda c: {'robinhood chain': 'robinhood', 'binance': 'bsc'}.get(c.lower(), c.lower())  # noqa: E731
par = lambda p: (p.get('parentProtocol') or p['name']).lower().replace('parent#', '')  # noqa: E731


def cells(X, key, div):
    m = collections.defaultdict(float)
    for p in X['protocols'] if isinstance(X, dict) else X:
        if p.get('category') != 'Dexs':
            continue
        if key:
            for c, vs in (p.get(key) or {}).items():
                m[(par(p), p['name'], norm(c))] += sum(v or 0 for v in vs.values()) / div
        else:
            for c, v in (p.get('chainTvls') or {}).items():
                if '-' in c or c.lower() in ('staking', 'pool2', 'borrowed', 'vesting'):
                    continue
                m[(par(p), p['name'], norm(c))] += v or 0
    return m


SCOPE = [
    ('现在', '1.0 Uniswap · Ethereum / Base / Arbitrum', lambda a, n, c: a == 'uniswap' and c in ('ethereum', 'base', 'arbitrum')),
    ('现在', '2.0 Pancake V3 + Infinity · BSC', lambda a, n, c: c == 'bsc' and n in ('PancakeSwap AMM V3', 'PancakeSwap Infinity')),
    ('现在', '2.0 Uniswap · Robinhood（全链可扫，股票池以外按 meme 筛掉）', lambda a, n, c: a == 'uniswap' and c == 'robinhood'),
    ('第一步', 'Aerodrome · Base', lambda a, n, c: 'aero' in a and c == 'base'),
    ('第一步', 'Curve · Ethereum', lambda a, n, c: a == 'curve-finance' and c == 'ethereum'),
    ('第二步', 'Orca · Solana', lambda a, n, c: a == 'orca' and c == 'solana'),
    ('第二步', 'Raydium · Solana', lambda a, n, c: n == 'Raydium AMM' and c == 'solana'),
    ('第二步', 'Meteora DLMM + DAMM v2 · Solana', lambda a, n, c: n in ('Meteora DLMM', 'Meteora DAMM V2') and c == 'solana'),
]
# ---------- 以上与 coverage_scope.py 逐行一致 ----------

MODULE_OF = {'Curve · Ethereum': ['curve'], 'Orca · Solana': ['orca'], 'Raydium · Solana': ['raydium'],
             'Meteora DLMM + DAMM v2 · Solana': ['meteora'], 'Aerodrome · Base': None}


def pass_fee_today(modules, date):
    """当天过门槛池的 24h 手续费合计；返回 (金额, 来源说明)。"""
    total, srcs = 0.0, []
    for m in modules:
        for p, tag in ((os.path.join(ROOT, 'out', 'mvp3', '%s-%s.json' % (m, date)), '1 号机'),
                       (os.path.join(ROOT, 'out', 'lab', 'lp3', m, '%s-%s.json' % (m, date)), '研究机')):
            if os.path.exists(p):
                rows = load(p)['rows']
                total += sum(r.get('fee24') or 0 for r in rows if not r.get('why_out'))
                srcs.append('%s %s' % (m, tag))
                break
        else:
            return None, '缺 %s 当天输出' % m
    return total, '、'.join(srcs)


def pass_split(date):
    C = load(os.path.join(STAGE0, 'out', 'coverage-pool-2026-11-11.json'))['res']
    out = {}
    out['1.0 Uniswap · Ethereum / Base / Arbitrum'] = (C['1.0 Uniswap · Ethereum/Base/Arbitrum'][0], '沿用 11-11')
    out['2.0 Pancake V3 + Infinity · BSC'] = (C['2.0 Pancake V3 + Infinity · BSC'][0], '沿用 11-11')
    rh, src = pass_fee_today(['rh'], date)
    out['2.0 Uniswap · Robinhood（全链可扫，股票池以外按 meme 筛掉）'] = (
        (C['2.0 Robinhood 股票池'][0] + rh, '股票池沿用 11-11 + 主流对当天（%s）' % src) if rh is not None else (None, src))
    for name, mods in MODULE_OF.items():
        out[name] = (None, '池级手续费拿不到') if mods is None else pass_fee_today(mods, date)
    return out


def download(date):
    d = os.path.join(OUTD, 'inputs-%s' % date)
    os.makedirs(d, exist_ok=True)
    for fn, url in URLS.items():
        p = os.path.join(d, fn)
        if os.path.exists(p) and os.path.getsize(p) > 1000:
            continue
        r = subprocess.run(['curl', '-sS', '--fail', '--max-time', '180', '-A', 'Mozilla/5.0 (Macintosh) lp-coverage-daily', url, '-o', p + '.tmp'],
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError('下载 %s 失败：%s' % (fn, r.stderr.strip()[-160:]))
        os.replace(p + '.tmp', p)
    for old in sorted(glob.glob(os.path.join(OUTD, 'inputs-*')))[:-KEEP_INPUT_DAYS]:
        shutil.rmtree(old)
    return d


def compute(inputs, date):
    F, V, P = (load(os.path.join(inputs, n)) for n in ('fees.json', 'dexs.json', 'protocols.json'))
    FEE, VOL, TVL = cells(F, 'breakdown30d', 30), cells(V, 'breakdown30d', 30), cells(P, None, 1)
    tot = {k: sum(m.values()) for k, m in (('fee', FEE), ('vol', VOL), ('tvl', TVL))}
    split = pass_split(date)
    blocks, used = [], set()
    for stage, name, pred in SCOPE:
        ks = [k for k in set(FEE) | set(VOL) | set(TVL) if pred(*k)]
        used |= set(ks)
        f, v, t = sum(FEE.get(k, 0) for k in ks), sum(VOL.get(k, 0) for k in ks), sum(TVL.get(k, 0) for k in ks)
        pf, psrc = split[name]
        blocks.append({'stage': stage, 'name': name, 'fee': f, 'vol': v, 'tvl': t, 'fee_pct': f / tot['fee'] * 100,
                       'vol_pct': v / tot['vol'] * 100, 'tvl_pct': t / tot['tvl'] * 100, 'pass_fee': pf, 'pass_source': psrc})
    levels = []
    for upto, st in (('现在', ('现在',)), ('第一步', ('现在', '第一步')), ('第二步', ('现在', '第一步', '第二步'))):
        xs = [b for b in blocks if b['stage'] in st]
        f = sum(x['fee'] for x in xs)
        ps = sum((x['pass_fee'] if x['pass_fee'] is not None else x['fee']) for x in xs)
        levels.append({'level': upto, 'fee_pct': f / tot['fee'] * 100, 'vol_pct': sum(x['vol'] for x in xs) / tot['vol'] * 100,
                       'tvl_pct': sum(x['tvl'] for x in xs) / tot['tvl'] * 100, 'pass_pct': ps / tot['fee'] * 100, 'filtered_pct': (f - ps) / tot['fee'] * 100})
    outside = collections.defaultdict(float)
    for k in set(FEE):
        if k not in used:
            outside[(k[0], k[2])] += FEE[k]
    top_out = [{'protocol': a, 'chain': c, 'fee_pct': f / tot['fee'] * 100} for (a, c), f in sorted(outside.items(), key=lambda x: -x[1])[:5]]
    return {'date': date, 'market': {'fee_per_day': tot['fee'], 'vol_per_day': tot['vol'], 'tvl': tot['tvl']},
            'blocks': blocks, 'levels': levels, 'outside_top5': top_out}


def legacy_levels(inputs):
    """干跑：同一份输入跑原脚本，解析三档扫描覆盖率（手续费）。"""
    r = subprocess.run(['/usr/bin/python3', 'coverage_scope.py', inputs], cwd=STAGE0, capture_output=True, text=True, timeout=600)
    got = {}
    for line in r.stdout.splitlines():
        m = re.match(r'^(现在|第一步|第二步)\s+扫描范围：手续费\s*([\d.]+)%', line)
        if m:
            got[m.group(1)] = float(m.group(2))
    return got, (r.returncode, r.stderr.strip()[-200:])


def history(date, days=7):
    vals = []
    d0 = datetime.date.fromisoformat(date)
    for k in range(1, days + 1):
        p = os.path.join(OUTD, 'scope-%s.json' % (d0 - datetime.timedelta(days=k)).isoformat())
        if os.path.exists(p):
            vals.append({x['level']: x['fee_pct'] for x in load(p)['levels']})
    return vals


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    o = dict(a[2:].split('=', 1) for a in argv if a.startswith('--') and '=' in a)
    date = o.get('date') or datetime.datetime.now(SGT).date().isoformat()
    inputs = o.get('inputs') or download(date)
    res = compute(inputs, date)
    legacy, (lrc, lerr) = legacy_levels(inputs)
    res['dry_run'] = {'legacy_fee_pct': legacy, 'legacy_rc': lrc, 'legacy_err': lerr,
                      'match': bool(legacy) and all(abs(legacy.get(x['level'], -99) - round(x['fee_pct'], 1)) <= 0.05 for x in res['levels'])}
    hist = history(date)
    alerts = []
    if hist:
        for x in res['levels']:
            prev = [h[x['level']] for h in hist if x['level'] in h]
            if prev and abs(x['fee_pct'] - sum(prev) / len(prev)) > ALERT_PP:
                alerts.append('%s 扫描覆盖率 %.1f%%，比前 %d 天均值 %.1f%% 变化超过 %.0f 个百分点' % (x['level'], x['fee_pct'], len(prev), sum(prev) / len(prev), ALERT_PP))
    if not res['dry_run']['match']:
        alerts.insert(0, '口径不一致：新算法与原脚本的三档扫描覆盖率对不上（原脚本 %s）' % (legacy or '运行失败'))
    res['alerts'] = alerts
    res['history_days'] = len(hist)
    os.makedirs(OUTD, exist_ok=True)
    with open(os.path.join(OUTD, 'scope-%s.json' % date), 'w') as fh:
        json.dump(res, fh, ensure_ascii=False, indent=1)
    with open(os.path.join(OUTD, 'scope-%s.md' % date), 'w') as fh:
        fh.write(report(res))
    lv = {x['level']: x['fee_pct'] for x in res['levels']}
    print('扫描覆盖率 %s：现在 %.1f%%、第一步 %.1f%%、第二步 %.1f%%；干跑对照原脚本 %s；告警 %d 条' % (
        date, lv['现在'], lv['第一步'], lv['第二步'], '一致' if res['dry_run']['match'] else '不一致', len(alerts)))
    return 0 if res['dry_run']['match'] else 1


def report(res):
    m = res['market']
    L = ['# 扫描覆盖率 · %s（干跑）' % res['date'], '']
    if res['alerts']:
        L += ['> **注意**：' + a for a in res['alerts']] + ['']
    L += ['全市场 DEX：日均手续费 $%.0f 万，日均成交 $%.1f 亿，TVL $%.1f 亿（DefiLlama，近 30 天日均）。' % (m['fee_per_day'] / 1e4, m['vol_per_day'] / 1e8, m['tvl'] / 1e8), '',
          '| 节点 | 扫描覆盖率（手续费） | 成交 | TVL | 其中进榜 | 规则筛掉 |', '| --- | --- | --- | --- | --- | --- |']
    L += ['| %s | %.1f%% | %.1f%% | %.1f%% | %.1f%% | %.1f%% |' % (x['level'], x['fee_pct'], x['vol_pct'], x['tvl_pct'], x['pass_pct'], x['filtered_pct']) for x in res['levels']]
    L += ['', '干跑对照：原脚本同一输入 %s；%s。' % (
        '、'.join('%s %.1f%%' % kv for kv in res['dry_run']['legacy_fee_pct'].items()) or '无输出', '一致' if res['dry_run']['match'] else '**不一致**'), '',
        '| 块 | 阶段 | 手续费占比 | 进榜手续费（日） | 进榜来源 |', '| --- | --- | --- | --- | --- |']
    L += ['| %s | %s | %.1f%% | %s | %s |' % (b['name'], b['stage'], b['fee_pct'], ('$%.1f 万' % (b['pass_fee'] / 1e4)) if b['pass_fee'] is not None else '—', b['pass_source'])
          for b in res['blocks']]
    L += ['', '范围外前 5：' + '；'.join('%s · %s %.1f%%' % (x['protocol'], x['chain'], x['fee_pct']) for x in res['outside_top5']), '',
          '说明：进榜拆分用当天 24h 手续费，扫描范围用近 30 天日均，两者口径与原脚本相同（原脚本同样混用）；1.0、2.0 的进榜部分沿用 11-11。',
          '前 7 天历史 %d 天；变化超过 %.0f 个百分点时置顶提示。只写文件，不推送。' % (res['history_days'], ALERT_PP)]
    return '\n'.join(L) + '\n'


if __name__ == '__main__':
    sys.exit(main())
