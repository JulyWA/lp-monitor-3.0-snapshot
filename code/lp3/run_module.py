#!/usr/bin/env python3
"""跑单个 lp3 模块，写它自己的输出文件。

用法（在仓库根目录）：
  /usr/bin/python3 -m lp3.run_module <模块> [--date=YYYY-MM-DD] [--out-root=目录]

模块接口（lp3/modules/<名>/module.py）：
  run(ctx) -> (rows, meta)            必需；任何异常都记为本模块失败
  coverage(ctx, rows, meta) -> dict   可选；采全比，缺省 {'status': '不适用'}
  extra_warn(ctx, meta) -> str|None   可选；模块自己的告警文字
  status(meta) -> 'ok' | 'partial'    可选；缺省：meta['errors'] 非空即 partial

汇总逻辑（冻结检测、meme 存档、过门槛计数、summary 字段与顺序、日志行）与 mvp3/collect.py 的 main() 一致，
这样新旧两套代码对同一份上游数据输出相同的 summary 和 rows。
退出码：0 = ok 或 partial；1 = 失败。
"""
import datetime
import importlib
import json
import os
import subprocess
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from lp3.common import contract, http, quality, refdata  # noqa: E402

SGT = datetime.timezone(datetime.timedelta(hours=8))
DEFAULT_OUT_ROOT = os.environ.get('LP3_OUT_ROOT', os.path.join(ROOT, 'out', 'lab', 'lp3'))


def iso(ts):
    return datetime.datetime.fromtimestamp(ts, SGT).isoformat(timespec='seconds')


def dump(obj, path):
    """原子写：先写临时文件再改名，避免中途被杀留下半个 JSON。"""
    tmp = path + '.tmp'
    with open(tmp, 'w') as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def load(path):
    with open(path) as fh:
        return json.load(fh)


def previous_date(date, days=1):
    return (datetime.date.fromisoformat(date) - datetime.timedelta(days=days)).isoformat()


def git_commit():
    try:
        p = subprocess.run(['git', '-C', ROOT, 'rev-parse', '--short', 'HEAD'], capture_output=True, text=True, timeout=10)
        return p.stdout.strip() or 'unknown'
    except Exception:
        return 'unknown'


class Context:
    """模块运行时拿到的东西。模块只能写自己的 out_dir。"""

    def __init__(self, name, date, now, out_dir, module_dir=None):
        self.name, self.date, self.now, self.out_dir = name, date, now, out_dir
        self.out_root = os.path.dirname(out_dir)
        self.module_dir = module_dir
        self._stocks = self._labels = None
        self.refdata_used = {}

    @property
    def stocks(self):
        if self._stocks is None:
            self._stocks = refdata.stock_index()
            self.refdata_used['stocklist'] = refdata.fingerprint(refdata.STOCKLIST)
        return self._stocks

    @property
    def labels(self):
        if self._labels is None:
            self._labels = refdata.sol_labels()
            self.refdata_used['sol_labels'] = refdata.fingerprint(refdata.SOL_LABELS)
        return self._labels

    def config(self):
        p = os.path.join(self.module_dir or '', 'config.json')
        return load(p) if self.module_dir and os.path.exists(p) else {}

    def path(self, name, date):
        return os.path.join(self.out_dir, '%s-%s.json' % (name, date))

    def load_rows(self, date, name=None):
        p = self.path(name or self.name, date)
        return load(p)['rows'] if os.path.exists(p) else None

    def previous_doc(self, date, name=None):
        p = self.path(name or self.name, date)
        return load(p) if os.path.exists(p) else None


def load_module(name, module_path=None):
    mod = importlib.import_module(module_path or 'lp3.modules.%s.module' % name)
    mdir = os.path.dirname(os.path.abspath(mod.__file__))
    vf = os.path.join(mdir, 'VERSION')
    version = open(vf).read().strip() if os.path.exists(vf) else getattr(mod, 'VERSION', '0.0.0')
    return mod, mdir, version


def run_one(name, date, now=None, out_root=None, module_path=None, quiet=False):
    """跑一个模块。返回 (status, 输出文件路径)。不向外抛异常。"""
    now = int(time.time()) if now is None else now
    out_dir = os.path.join(out_root or DEFAULT_OUT_ROOT, name)
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, '%s-%s.json' % (name, date))
    failed_path = path.replace('.json', '-FAILED.json')
    commit = git_commit()
    t0 = time.time()
    started = iso(now)
    http.reset_stats()
    version = 'unknown'
    try:
        mod, mdir, version = load_module(name, module_path)
        ctx = Context(name, date, now, out_dir, mdir)
        rows, meta = mod.run(ctx)
        return _finalize(mod, ctx, name, date, now, rows, meta, version, commit, started, t0, path, failed_path, quiet)
    except BaseException as e:  # 模块内任何异常（含 KeyboardInterrupt 以外的系统退出）都只算本模块失败
        if isinstance(e, KeyboardInterrupt):
            raise
        tb = traceback.format_exc().strip().splitlines()[-6:]
        doc = contract.failure(name, version, commit, date, now, str(e)[-500:], type(e).__name__, started, iso(int(time.time())),
                               http.stats(), tb)
        dump(doc, failed_path)
        if not quiet:
            print('%-6s 失败：%s（%s）' % (name, str(e)[-300:], type(e).__name__))
        return 'failed', failed_path


def _finalize(mod, ctx, name, date, now, rows, meta, version, commit, started, t0, path, failed_path, quiet):
    out_dir = ctx.out_dir
    prev = ctx.load_rows(previous_date(date))
    warn = quality.sanity(name, rows, prev)
    archive = meta.pop('archive', None)
    if archive is not None:  # meme 存档：单独文件，不进榜、不进卡片
        dump({'date': date, 'source': name, 'fetched_at': now, 'n': len(archive), 'tvl_sum': sum(a['tvl'] for a in archive),
              'vol24_sum': sum(a['vol24'] for a in archive), 'rows': archive}, os.path.join(out_dir, 'meme-%s-%s.json' % (name, date)))
        meta['n_meme_archived'] = sum(a.get('meme_label') in (None, 'meme') for a in archive)
        if any(a.get('low_fee_unlisted') for a in archive):
            meta['n_low_fee_unlisted_archived'] = sum(bool(a.get('low_fee_unlisted')) for a in archive)
            meta['n_filter_archived'] = len(archive)
    ok = [r for r in rows if not r['why_out']]
    tvl_sum = sum(r['tvl'] for r in rows)
    cov = mod.coverage(ctx, rows, meta) if hasattr(mod, 'coverage') else {'status': '不适用'}
    extra = mod.extra_warn(ctx, meta) if hasattr(mod, 'extra_warn') else None
    warn = '；'.join(w for w in (warn, cov.get('warn'), extra) if w) or None
    summ = {'date': date, 'source': name, 'fetched_at': now, 'elapsed_s': round(time.time() - t0), 'n_ge_500k': len(rows), 'n_pass': len(ok),
            'n_apy_board': sum(1 for r in ok if r.get('apy_7d') is not None and not r.get('apy_out')),
            'tvl_sum': tvl_sum, 'by_class': {c: sum(1 for r in ok if r['asset_class'] == c) for c in ('代币', '股票和商品')},
            'warn': warn, 'llama_coverage': cov, 'meta': meta}
    status = mod.status(meta) if hasattr(mod, 'status') else ('partial' if meta.get('errors') else 'ok')
    block = contract.module_block(name, version, commit, status, started, iso(int(time.time())), http.stats(), ctx.refdata_used)
    dump({'summary': summ, 'rows': rows, 'module': block}, path)
    if os.path.exists(failed_path):  # 同一天先失败后重跑成功：失败文件改名留档，不删
        os.replace(failed_path, failed_path.replace('-FAILED.json', '-FAILED-superseded-%d.json' % now))
    if not quiet:
        cov_txt = (' | 采全比 %.0f%%（3 日均值 %s，%s）' % (cov['ratio'] * 100, '%.0f%%' % (cov['ratio_3d'] * 100) if cov.get('ratio_3d') is not None else '—', cov['verdict'])
                   if cov.get('status') == '已对比' else ' | 采全比 %s' % cov.get('status'))
        print('%-6s ≥$50万 %3d 池（过门槛 %3d：代币 %d / 股票和商品 %d）TVL $%.1fM | %ds%s%s | v%s %s' % (
            name, len(rows), len(ok), summ['by_class']['代币'], summ['by_class']['股票和商品'], summ['tvl_sum'] / 1e6, summ['elapsed_s'], cov_txt,
            ' | ⚠ ' + warn if warn else '', version, status))
    return status, path


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    names = [a for a in argv if not a.startswith('--')]
    opts = dict(a[2:].split('=', 1) for a in argv if a.startswith('--') and '=' in a)
    if len(names) != 1:
        raise SystemExit('用法：python3 -m lp3.run_module <模块> [--date=YYYY-MM-DD] [--out-root=目录]')
    date = opts.get('date') or datetime.datetime.now(SGT).strftime('%Y-%m-%d')
    status, _ = run_one(names[0], date, out_root=opts.get('out-root'), module_path=opts.get('module-path'))
    return 1 if status == 'failed' else 0


if __name__ == '__main__':
    sys.exit(main())
