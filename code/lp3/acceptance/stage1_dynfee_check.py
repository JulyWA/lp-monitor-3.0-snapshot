#!/usr/bin/env python3
"""阶段 1 · 动态费率补丁（提交 872cf6d）实跑核对。只读：读一天的 aero、rh 输出（1 号机 out/mvp3 平铺或研究机模块目录都行）。

逐条检查验收草稿 §2 的 8 项，输出 md 表格。退出码：0 = 8 项全部符合；1 = 有不符合或缺文件。
用法：/usr/bin/python3 -m lp3.acceptance.stage1_dynfee_check --src=<目录> --date=2026-11-18 [--log=<lp3-collect.log>] [--out=<报告.md>]
"""
import json
import os
import re
import sys

DYN_PREFIXES = ('aero-', 'aerodrome-', 'ramses-')
NOTE = '动态费率，未取'


def find(src, name, date):
    for p in (os.path.join(src, '%s-%s.json' % (name, date)), os.path.join(src, name, '%s-%s.json' % (name, date))):
        if os.path.exists(p):
            with open(p) as fh:
                return json.load(fh)
    return None


def check(src, date, log=None):
    rh, aero = find(src, 'rh', date), find(src, 'aero', date)
    res = []
    if rh is None or aero is None:
        return [(0, '输出文件', '缺 %s' % '、'.join(n for n, d in (('rh', rh), ('aero', aero)) if d is None), False)]
    dyn = [r for r in rh['rows'] if (r.get('protocol') or '').startswith(DYN_PREFIXES)]
    other = [r for r in rh['rows'] if r not in dyn]
    ok1 = bool(dyn) and all(r.get('fee_pct') is None and r.get('apy_now') is None for r in dyn)
    res.append((1, 'Robinhood 动态费率池 fee/APY 为空', '%d 池：%s' % (len(dyn), '；'.join('%s fee=%s apy=%s' % (r['name'], r.get('fee_pct'), r.get('apy_now')) for r in dyn)), ok1))
    ok2 = bool(dyn) and all((r.get('notes') or '').startswith(NOTE) and 'GeckoTerminal 池名费率' in (r.get('notes') or '') for r in dyn)
    res.append((2, 'notes 以「%s」开头并写明 GT 池名费率' % NOTE, '；'.join((r.get('notes') or '')[:40] for r in dyn), ok2))
    ok3 = bool(dyn) and all(not re.search(r'[\d.]+%$', r['name']) and r.get('name_gt') for r in dyn)
    res.append((3, '池名去掉费率，原名在 name_gt', '；'.join('%s ← %s' % (r['name'], r.get('name_gt')) for r in dyn), ok3))
    aero_rh = [r for r in dyn if r['protocol'].startswith('aero-')]
    ram = [r for r in dyn if r['protocol'].startswith('ramses-')]
    ok4 = all((r.get('front_url') or '') == 'https://app.aero.xyz/deposit/4663-%s' % r['pool'] for r in aero_rh) and all(not r.get('front_url') for r in ram)
    res.append((4, 'Aero 池链接 app.aero.xyz/deposit/4663-<地址>；Ramses 无链接', '；'.join('%s %s' % (r['protocol'], r.get('front_url')) for r in dyn), ok4))
    protos = {}
    for r in aero['rows']:
        protos[r['protocol']] = protos.get(r['protocol'], 0) + 1
    ok5 = set(protos) <= {'Aero', 'Aerodrome 旧版'} and sum(protos.values()) == aero['summary']['n_ge_500k']
    res.append((5, 'Base 协议名只有 Aero / Aerodrome 旧版', '%s；大池 %d' % (protos, aero['summary']['n_ge_500k']), ok5))
    dormant = [r for r in aero['rows'] if r.get('tag') == '旧版沉睡']
    ok6 = all(r['protocol'] == 'Aerodrome 旧版' and r['tvl'] and (r.get('vol24') or 0) / r['tvl'] < 0.001 for r in dormant) and \
        all(r.get('tag') == '旧版沉睡' for r in aero['rows'] if r['protocol'] == 'Aerodrome 旧版' and r['tvl'] and (r.get('vol24') or 0) / r['tvl'] < 0.001) and \
        not any('旧版沉睡' in (r.get('why_out') or '') for r in dormant)
    res.append((6, '「旧版沉睡」只在旧版低成交池上，且不挡榜', '%d 池；其中过门槛 %d' % (len(dormant), sum(1 for r in dormant if not r['why_out'])), ok6))
    with_fee = [r for r in other if r.get('fee_pct')]
    ok7 = all(r.get('fee24') is not None for r in with_fee) and (not with_fee or any(r.get('apy_now') is not None for r in with_fee))
    res.append((7, '非动态费率池照常算费率和 APY', '%d 池有费率：%s' % (len(with_fee), '；'.join('%s %s%%' % (r['name'], r['fee_pct']) for r in with_fee[:5])), ok7))
    if log and os.path.exists(log):
        with open(log) as fh:
            lines = [l for l in fh if l.startswith('[%s' % date) and 'rc=' in l]
        ok8 = bool(lines) and 'rc=0' in lines[-1]
        res.append((8, '运行 rc=0', lines[-1].strip() if lines else '日志里没有这天的运行记录', ok8))
    else:
        res.append((8, '运行 rc=0', '未提供日志', False))
    return res


def main():
    o = dict(a[2:].split('=', 1) for a in sys.argv[1:] if a.startswith('--') and '=' in a)
    res = check(o['src'], o['date'], o.get('log'))
    L = ['# 动态费率补丁实跑核对 · %s' % o['date'], '', '来源：`%s`' % o['src'], '', '| # | 检查 | 证据 | 结果 |', '| --- | --- | --- | --- |']
    L += ['| %s | %s | %s | %s |' % (i, k, (e or '—').replace('|', '/'), '符合' if ok else '**不符合**') for i, k, e, ok in res]
    n_ok = sum(1 for *_, ok in res if ok)
    L += ['', '**%d / %d 符合**' % (n_ok, len(res))]
    text = '\n'.join(L) + '\n'
    print(text)
    if o.get('out'):
        with open(o['out'], 'w') as fh:
            fh.write(text)
    return 0 if n_ok == len(res) == 8 else 1


if __name__ == '__main__':
    sys.exit(main())
