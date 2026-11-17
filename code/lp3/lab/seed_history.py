#!/usr/bin/env python3
"""把 1 号机同步来的 out/mvp3 历史文件放进研究机各模块目录，作为首次运行的历史（前一天复查、Meteora 前 7 天、采全比前两天）。

用法（仓库根目录）：/usr/bin/python3 -m lp3.lab.seed_history --src=<解压后的 out/mvp3 目录> [--through=YYYY-MM-DD] [--days=8] [--out-root=out/lab/lp3]
--through 是最后一天（含），缺省昨天；研究机当天不跑时可设为今天。只复制「截止日及之前 days 天」的 <模块>-<日期>.json 和回填文件；目标已存在的一律不覆盖（研究机自己的产出优先）。清单追加到 <out-root>/SEED-LOG.jsonl。
"""
import datetime
import json
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MODULES = ('curve', 'aero', 'rh', 'orca', 'raydium', 'meteora')
SGT = datetime.timezone(datetime.timedelta(hours=8))
BACKFILL = 'coverage-backfill-2026-11-16.json'


def main():
    o = dict(a[2:].split('=', 1) for a in sys.argv[1:] if a.startswith('--') and '=' in a)
    src = o['src']
    out_root = o.get('out-root') or os.path.join(ROOT, 'out', 'lab', 'lp3')
    days = int(o.get('days', 8))
    through = datetime.date.fromisoformat(o['through']) if o.get('through') else datetime.datetime.now(SGT).date() - datetime.timedelta(days=1)
    copied, skipped = [], []
    for m in MODULES:
        os.makedirs(os.path.join(out_root, m), exist_ok=True)
        for k in range(0, days):
            fn = '%s-%s.json' % (m, (through - datetime.timedelta(days=k)).isoformat())
            s, d = os.path.join(src, fn), os.path.join(out_root, m, fn)
            if not os.path.exists(s):
                continue
            if os.path.exists(d):
                skipped.append('%s/%s' % (m, fn)); continue
            shutil.copy2(s, d); copied.append('%s/%s' % (m, fn))
    if os.path.exists(os.path.join(src, BACKFILL)) and not os.path.exists(os.path.join(out_root, BACKFILL)):
        shutil.copy2(os.path.join(src, BACKFILL), os.path.join(out_root, BACKFILL)); copied.append(BACKFILL)
    rec = {'at': datetime.datetime.now(SGT).isoformat(timespec='seconds'), 'src': src, 'through': through.isoformat(), 'days': days, 'copied': copied, 'skipped_existing': skipped}
    with open(os.path.join(out_root, 'SEED-LOG.jsonl'), 'a') as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + '\n')
    print('复制 %d 个，已存在跳过 %d 个' % (len(copied), len(skipped)))
    for m in MODULES:
        have = sorted(f for f in os.listdir(os.path.join(out_root, m)) if f.startswith(m + '-') and not f.endswith('-FAILED.json'))
        print('  %-8s %s' % (m, '、'.join(h[len(m) + 1:-5] for h in have) or '无'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
