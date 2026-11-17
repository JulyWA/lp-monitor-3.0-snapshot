#!/usr/bin/env python3
"""逐池逐字段对比两份输出（旧代码 vs 新模块，或旧代码实跑 vs 旧代码回放）。

用法：
  /usr/bin/python3 -m lp3.replay.compare --a=<目录A> --b=<目录B> --sources=orca,raydium --date=2026-11-17 [--report=报告.md]
目录里的文件可以是平铺（<源>-<日期>.json，旧代码）或分模块（<源>/<源>-<日期>.json，新模块），自动识别。

判据：rows 逐池逐字段完全相同（顺序也要相同）；summary 除 elapsed_s 外完全相同；meme 存档 rows 完全相同。
新模块独有的 module 块不参与比较。浮点数要求完全相等，不设容差：规则没改，结果就应该一模一样。
退出码：0 = 全部一致；1 = 有差异或缺文件。
"""
import json
import os
import sys

SUMMARY_IGNORE = {'elapsed_s'}


def find(d, name):
    for p in (os.path.join(d, name), os.path.join(d, name.split('-')[0] if not name.startswith('meme-') else name.split('-')[1], name)):
        if os.path.exists(p):
            return p
    return None


def diff_values(a, b, path, out, limit=50):
    if len(out) >= limit:
        return
    if type(a) != type(b) and not (isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool) and not isinstance(b, bool)):
        out.append('%s：类型不同 %r vs %r' % (path, a, b)); return
    if isinstance(a, dict):
        for k in sorted(set(a) | set(b), key=str):
            if k not in a:
                out.append('%s.%s：只在 B 里有' % (path, k))
            elif k not in b:
                out.append('%s.%s：只在 A 里有' % (path, k))
            else:
                diff_values(a[k], b[k], '%s.%s' % (path, k), out, limit)
    elif isinstance(a, list):
        if len(a) != len(b):
            out.append('%s：长度 %d vs %d' % (path, len(a), len(b)))
        for i, (x, y) in enumerate(zip(a, b)):
            diff_values(x, y, '%s[%d]' % (path, i), out, limit)
    elif a != b:
        out.append('%s：%r vs %r' % (path, a, b))


def compare_source(a_dir, b_dir, src, date):
    res = {'source': src, 'diffs': [], 'missing': []}
    fa, fb = find(a_dir, '%s-%s.json' % (src, date)), find(b_dir, '%s-%s.json' % (src, date))
    if not fa or not fb:
        res['missing'].append('主输出：A=%s B=%s' % (bool(fa), bool(fb)))
        return res
    A, B = json.load(open(fa)), json.load(open(fb))
    diff_values(A['rows'], B['rows'], 'rows', res['diffs'])
    sa = {k: v for k, v in A['summary'].items() if k not in SUMMARY_IGNORE}
    sb = {k: v for k, v in B['summary'].items() if k not in SUMMARY_IGNORE}
    diff_values(sa, sb, 'summary', res['diffs'])
    ma, mb = find(a_dir, 'meme-%s-%s.json' % (src, date)), find(b_dir, 'meme-%s-%s.json' % (src, date))
    if bool(ma) != bool(mb):
        res['missing'].append('meme 存档：A=%s B=%s' % (bool(ma), bool(mb)))
    elif ma:
        MA, MB = json.load(open(ma)), json.load(open(mb))
        diff_values({k: v for k, v in MA.items()}, {k: v for k, v in MB.items()}, 'meme', res['diffs'])
    res['n_rows'] = len(A['rows'])
    return res


def main():
    o = dict(a[2:].split('=', 1) for a in sys.argv[1:] if a.startswith('--') and '=' in a)
    results = [compare_source(o['a'], o['b'], s, o['date']) for s in o['sources'].split(',')]
    lines = ['# 新旧输出对比 %s' % o['date'], '', 'A：`%s`' % o['a'], '', 'B：`%s`' % o['b'], '',
             '| 源 | 行数 | 差异 | 缺文件 | 结论 |', '| --- | --- | --- | --- | --- |']
    bad = 0
    for r in results:
        ok = not r['diffs'] and not r['missing']
        bad += not ok
        lines.append('| %s | %s | %d | %s | %s |' % (r['source'], r.get('n_rows', '—'), len(r['diffs']), '；'.join(r['missing']) or '—', '一致' if ok else '**不一致**'))
    for r in results:
        if r['diffs']:
            lines += ['', '## %s 差异（最多 50 条）' % r['source'], ''] + ['- ' + d for d in r['diffs']]
    text = '\n'.join(lines) + '\n'
    print(text)
    if o.get('report'):
        open(o['report'], 'w').write(text)
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
