#!/usr/bin/env python3
"""M4：研究机 lp3 模块产出 vs 1 号机 mvp3 生产产出，同一天逐模块对比。只读。

两边代码逻辑相同（回放已证明 0 差异），但采集时刻不同、上游数据会变，所以这里不要求逐字段相同，而是看：
  池覆盖     ：≥$50 万池地址的交集和差集（差集列出 TVL，靠近门槛的属正常进出）
  TVL        ：共同池的相对偏差（中位数、最大值、>5% 的池）
  过门槛判定 ：共同池里一边过、一边不过的池，以及原因
  分类       ：共同池的资产类别、meme 标签是否一致
  汇总       ：池数、过门槛数、TVL 合计、采全比，以及两边的采集时刻差
用法：/usr/bin/python3 -m lp3.lab.compare_prod --prod=<1 号机 out/mvp3 目录> --date=YYYY-MM-DD [--lab-root=out/lab/lp3] [--out=报告.md]
"""
import datetime
import json
import os
import statistics
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MODULES = ('curve', 'aero', 'rh', 'orca', 'raydium', 'meteora')
SGT = datetime.timezone(datetime.timedelta(hours=8))
NEAR = 0.2  # 差集池 TVL 在门槛 ±20% 内，算「门槛边缘」


def load(p):
    if not os.path.exists(p):
        return None
    with open(p) as fh:
        return json.load(fh)


def t(ts):
    return datetime.datetime.fromtimestamp(ts, SGT).strftime('%H:%M') if ts else '—'


def compare(name, lab, prod, min_tvl=5e5):
    out = {'module': name}
    if lab is None or prod is None:
        out['missing'] = '研究机缺' if lab is None else '1 号机缺'
        return out
    L = {r['pool']: r for r in lab['rows']}
    P = {r['pool']: r for r in prod['rows']}
    common = sorted(set(L) & set(P))
    only_l, only_p = sorted(set(L) - set(P)), sorted(set(P) - set(L))
    near = lambda r: abs(r['tvl'] - min_tvl) <= NEAR * min_tvl
    devs = [(p, L[p]['tvl'] / P[p]['tvl'] - 1) for p in common if P[p]['tvl']]
    big = sorted([d for d in devs if abs(d[1]) > 0.05], key=lambda d: -abs(d[1]))
    flip = [(p, bool(L[p]['why_out']), bool(P[p]['why_out']), L[p]['why_out'], P[p]['why_out']) for p in common if bool(L[p]['why_out']) != bool(P[p]['why_out'])]
    cls = [p for p in common if L[p].get('asset_class') != P[p].get('asset_class')]
    meme = [p for p in common if L[p].get('meme_label') != P[p].get('meme_label')]
    ls, ps = lab['summary'], prod['summary']
    out.update(
        time={'lab': t(ls.get('fetched_at')), 'prod': t(ps.get('fetched_at')), 'gap_min': round(abs((ls.get('fetched_at') or 0) - (ps.get('fetched_at') or 0)) / 60)},
        counts={'lab': (ls['n_ge_500k'], ls['n_pass'], ls['tvl_sum']), 'prod': (ps['n_ge_500k'], ps['n_pass'], ps['tvl_sum'])},
        coverage={'lab': (ls.get('llama_coverage') or {}).get('ratio'), 'prod': (ps.get('llama_coverage') or {}).get('ratio')},
        n_common=len(common), only_lab=[(p, L[p]['name'], L[p]['tvl'], near(L[p])) for p in only_l],
        only_prod=[(p, P[p]['name'], P[p]['tvl'], near(P[p])) for p in only_p],
        tvl_median=statistics.median([abs(d) for _, d in devs]) if devs else None, tvl_max=max((abs(d) for _, d in devs), default=None),
        tvl_big=[(p, L[p]['name'], d) for p, d in big], flips=[(p, L[p]['name'], a, b, wa, wb) for p, a, b, wa, wb in flip],
        class_diff=[(p, L[p]['name'], L[p].get('asset_class'), P[p].get('asset_class')) for p in cls],
        meme_diff=[(p, L[p]['name'], L[p].get('meme_label'), P[p].get('meme_label')) for p in meme],
        lab_version=(lab.get('module') or {}).get('version'))
    return out


def m(x):
    return '$%.1fM' % (x / 1e6)


def report(res, date):
    R = ['# 研究机 vs 1 号机 · %s' % date, '',
         '| 模块 | 采集时刻（研究/生产） | 大池（研究/生产） | 过门槛 | TVL 合计 | 采全比 | 共同池 | 只在研究机 | 只在生产 | TVL 偏差中位/最大 | >5% | 过门槛不一致 | 分类不一致 |',
         '| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |']
    for r in res:
        if 'missing' in r:
            R.append('| %s | **%s** |' % (r['module'], r['missing']) + ' — |' * 11)
            continue
        cl, cp = r['counts']['lab'], r['counts']['prod']
        cov = '%s / %s' % tuple(('%.1f%%' % (x * 100) if isinstance(x, float) else '—') for x in (r['coverage']['lab'], r['coverage']['prod']))
        R.append('| %s | %s / %s（差 %d 分钟） | %d / %d | %d / %d | %s / %s | %s | %d | %d（边缘 %d） | %d（边缘 %d） | %s / %s | %d | %d | %d |' % (
            r['module'], r['time']['lab'], r['time']['prod'], r['time']['gap_min'], cl[0], cp[0], cl[1], cp[1], m(cl[2]), m(cp[2]), cov, r['n_common'],
            len(r['only_lab']), sum(x[3] for x in r['only_lab']), len(r['only_prod']), sum(x[3] for x in r['only_prod']),
            '%.2f%%' % (r['tvl_median'] * 100) if r['tvl_median'] is not None else '—', '%.1f%%' % (r['tvl_max'] * 100) if r['tvl_max'] is not None else '—',
            len(r['tvl_big']), len(r['flips']), len(r['class_diff']) + len(r['meme_diff'])))
    for r in res:
        if 'missing' in r:
            continue
        det = []
        det += ['- 只在研究机：%s %s%s' % (n, m(v), '（门槛边缘）' if e else '') for _, n, v, e in r['only_lab'] if not e]
        det += ['- 只在生产：%s %s%s' % (n, m(v), '（门槛边缘）' if e else '') for _, n, v, e in r['only_prod'] if not e]
        det += ['- TVL 偏差 %+.1f%%：%s' % (d * 100, n) for _, n, d in r['tvl_big'][:8]]
        det += ['- 过门槛不一致：%s（研究机%s：%s；生产%s：%s）' % (n, '挡' if a else '过', wa or '—', '挡' if b else '过', wb or '—') for _, n, a, b, wa, wb in r['flips'][:8]]
        det += ['- 资产类别不一致：%s（研究机 %s，生产 %s）' % (n, a, b) for _, n, a, b in r['class_diff']]
        det += ['- 标签不一致：%s（研究机 %s，生产 %s）' % (n, a, b) for _, n, a, b in r['meme_diff']]
        if det:
            R += ['', '## %s（研究机模块 v%s）' % (r['module'], r.get('lab_version'))] + det
    R += ['', '说明：门槛边缘 = TVL 在 $50 万 ±20% 内，两次采集之间进出门槛属正常。两边代码逻辑相同（录制回放 0 差异），差异来自采集时刻和上游数据变化。']
    return '\n'.join(R) + '\n'


def main():
    o = dict(a[2:].split('=', 1) for a in sys.argv[1:] if a.startswith('--') and '=' in a)
    lab_root = o.get('lab-root') or os.path.join(ROOT, 'out', 'lab', 'lp3')
    res = [compare(n, load(os.path.join(lab_root, n, '%s-%s.json' % (n, o['date']))), load(os.path.join(o['prod'], '%s-%s.json' % (n, o['date']))))
           for n in (o.get('modules') or ','.join(MODULES)).split(',')]
    text = report(res, o['date'])
    print(text)
    if o.get('out'):
        with open(o['out'], 'w') as fh:
            fh.write(text)
    return 0


if __name__ == '__main__':
    sys.exit(main())
