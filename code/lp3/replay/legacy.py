#!/usr/bin/env python3
"""在沙箱里跑原 mvp3/collect.py：录制上游响应，或用录制的响应回放。不改 mvp3 的任何文件。

用法（在仓库根目录）：
  /usr/bin/python3 -m lp3.replay.legacy record --sources=orca,raydium,meteora --date=2026-11-17 \
      --cassette=out/lab/replay/<名>/cassette --out=out/lab/replay/<名>/legacy-live --seed=out/mvp3
  /usr/bin/python3 -m lp3.replay.legacy replay --sources=... --date=... --cassette=... --out=out/lab/replay/<名>/legacy-replay --seed=out/mvp3

沙箱：collect.OUT 和 COVERAGE_BACKFILL 指到 --out。运行前从 --seed 复制「日期早于 --date」的历史文件（前一天复查、
Meteora 前 7 天、采全比前两天要用），并把复制清单写进 <out>/SEED.json。不会写 out/mvp3。
"""
import datetime
import importlib
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

from lp3.replay.cassette import Cassette  # noqa: E402

SEED_DAYS = 8  # Meteora 用前 7 天，留 1 天余量


def seed(src_dir, out_dir, sources, date):
    os.makedirs(out_dir, exist_ok=True)
    d0 = datetime.date.fromisoformat(date)
    want = {(d0 - datetime.timedelta(days=k)).isoformat() for k in range(1, SEED_DAYS + 1)}
    copied = []
    for s in sources:
        for d in sorted(want):
            for fn in ('%s-%s.json' % (s, d),):
                p = os.path.join(src_dir, fn)
                if os.path.exists(p):
                    shutil.copy2(p, os.path.join(out_dir, fn))
                    copied.append(fn)
    bf = os.path.join(src_dir, 'coverage-backfill-2026-11-16.json')
    if os.path.exists(bf):
        shutil.copy2(bf, os.path.join(out_dir, os.path.basename(bf)))
        copied.append(os.path.basename(bf))
    json.dump({'from': os.path.relpath(src_dir, ROOT), 'date': date, 'files': copied}, open(os.path.join(out_dir, 'SEED.json'), 'w'),
              ensure_ascii=False, indent=1)
    return copied


def run_legacy(mode, sources, date, cassette_dir, out_dir, seed_dir):
    if os.path.exists(os.path.join(out_dir, '%s-%s.json' % (sources[0], date))):
        raise SystemExit('输出目录已有 %s 当天文件，换一个目录：%s' % (date, out_dir))
    seed(seed_dir, out_dir, sources, date)
    sys.path.insert(0, os.path.join(ROOT, 'mvp3'))
    collect = importlib.import_module('collect')
    collect.OUT = out_dir
    collect.COVERAGE_BACKFILL = os.path.join(out_dir, 'coverage-backfill-2026-11-16.json')
    collect._LLAMA_ALL.clear()
    cas = Cassette(cassette_dir, mode)
    rc = 0
    argv = sys.argv
    with cas.patched():
        sys.argv = ['collect.py'] + list(sources) + ['--date=' + date]
        try:
            collect.main()
        except SystemExit as e:
            rc = e.code or 0
        finally:
            sys.argv = argv
    info = {'mode': mode, 'rc': rc, 'now': cas.meta.get('now')}
    if mode == 'record':
        info['n_recorded'] = cas.n_recorded
    else:
        info['unused'] = cas.unused()
    json.dump(info, open(os.path.join(out_dir, 'RUN.json'), 'w'), ensure_ascii=False, indent=1)
    print(json.dumps(info, ensure_ascii=False))
    return rc


def main():
    mode = sys.argv[1]
    o = dict(a[2:].split('=', 1) for a in sys.argv[2:] if a.startswith('--') and '=' in a)
    rel = lambda p: p if os.path.isabs(p) else os.path.join(ROOT, p)
    os.makedirs(rel(o['cassette']), exist_ok=True)
    return run_legacy(mode, o['sources'].split(','), o['date'], rel(o['cassette']), rel(o['out']), rel(o.get('seed', 'out/mvp3')))


if __name__ == '__main__':
    sys.exit(main())
