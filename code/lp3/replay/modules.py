#!/usr/bin/env python3
"""用录制的上游响应回放新模块（lp3/modules/*），输出按模块分目录，再交给 compare 和旧代码比。

用法（在仓库根目录）：
  /usr/bin/python3 -m lp3.replay.modules --sources=orca,raydium,meteora --date=2026-11-17 \
      --cassette=out/lab/replay/<名>/cassette --out=out/lab/replay/<名>/modules --seed=out/mvp3

沙箱：从 --seed 把「日期早于 --date」的历史文件复制到 <out>/<模块>/，回填文件复制到 <out>/，清单写 <out>/SEED.json。
时间固定为录制时刻；网络只走录制，缺一条就失败。
"""
import datetime
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

from lp3 import run_module  # noqa: E402
from lp3.common import defillama  # noqa: E402
from lp3.replay.cassette import Cassette  # noqa: E402

SEED_DAYS = 8


def seed(src_dir, out_root, sources, date):
    d0 = datetime.date.fromisoformat(date)
    days = [(d0 - datetime.timedelta(days=k)).isoformat() for k in range(SEED_DAYS, 0, -1)]
    copied = []
    for s in sources:
        os.makedirs(os.path.join(out_root, s), exist_ok=True)
        for d in days:
            fn = '%s-%s.json' % (s, d)
            p = os.path.join(src_dir, fn)
            if os.path.exists(p):
                shutil.copy2(p, os.path.join(out_root, s, fn))
                copied.append('%s/%s' % (s, fn))
    bf = os.path.join(src_dir, defillama.BACKFILL_NAME)
    if os.path.exists(bf):
        shutil.copy2(bf, os.path.join(out_root, defillama.BACKFILL_NAME))
        copied.append(defillama.BACKFILL_NAME)
    with open(os.path.join(out_root, 'SEED.json'), 'w') as fh:
        json.dump({'from': os.path.relpath(src_dir, ROOT), 'date': date, 'files': copied}, fh, ensure_ascii=False, indent=1)
    return copied


def replay(sources, date, cassette_dir, out_root, seed_dir):
    for s in sources:
        if os.path.exists(os.path.join(out_root, s, '%s-%s.json' % (s, date))):
            raise SystemExit('输出目录已有 %s 当天文件，换一个目录：%s' % (date, out_root))
    seed(seed_dir, out_root, sources, date)
    cas = Cassette(cassette_dir, 'replay', reuse_exhausted=True)
    results = {}
    with cas.patched() as now:
        for s in sources:
            defillama.reset_cache()  # 模拟每个模块独立进程
            results[s] = run_module.run_one(s, date, now=now, out_root=out_root)[0]
    info = {'results': results, 'now': cas.meta['now'], 'unused': cas.unused(), 'reused': cas.reused}
    with open(os.path.join(out_root, 'RUN.json'), 'w') as fh:
        json.dump(info, fh, ensure_ascii=False, indent=1)
    print(json.dumps(info, ensure_ascii=False)[:2000])
    return 0 if all(v in ('ok', 'partial') for v in results.values()) else 1


def main():
    o = dict(a[2:].split('=', 1) for a in sys.argv[1:] if a.startswith('--') and '=' in a)
    rel = lambda p: p if os.path.isabs(p) else os.path.join(ROOT, p)
    return replay(o['sources'].split(','), o['date'], rel(o['cassette']), rel(o['out']), rel(o.get('seed', 'out/mvp3')))


if __name__ == '__main__':
    sys.exit(main())
