"""lp3 模块输出契约（schema lp3.module.v1）。

每个模块每天一个文件 <模块>-<日期>.json：
  summary  与 mvp3 原输出相同（新旧对比时逐字段比较，elapsed_s 除外）
  rows     与 mvp3 原输出相同（逐池逐字段比较）
  module   新增的追溯块：name、version、git_commit、schema_version、status、window、source_health、refdata
失败时写 <模块>-<日期>-FAILED.json，字段见 failure()。
整合层只认通过 validate() 的文件。
"""
SCHEMA_VERSION = 'lp3.module.v1'
STATUSES = ('ok', 'partial', 'failed')
ROW_REQUIRED = ('protocol', 'chain', 'pool', 'name', 'tvl', 'vol24', 'tokens', 'asset_class', 'why_out', 'notes')
SUMMARY_REQUIRED = ('date', 'source', 'fetched_at', 'n_ge_500k', 'n_pass', 'tvl_sum', 'by_class', 'warn', 'llama_coverage', 'meta')
MODULE_REQUIRED = ('name', 'version', 'git_commit', 'schema_version', 'status', 'window', 'source_health')


def module_block(name, version, git_commit, status, started_at, finished_at, source_health, refdata=None):
    if status not in STATUSES:
        raise ValueError('未知状态：%s' % status)
    return {'name': name, 'version': version, 'git_commit': git_commit, 'schema_version': SCHEMA_VERSION,
            'status': status, 'window': {'started_at': started_at, 'finished_at': finished_at},
            'source_health': source_health, 'refdata': refdata or {}}


def failure(name, version, git_commit, date, at, error, error_type, started_at, finished_at, source_health=None, traceback_tail=None):
    """失败文件。保留 mvp3 原 FAILED 文件的 date/source/error/at 四个键，另加追溯字段。"""
    return {'date': date, 'source': name, 'error': error, 'at': at,
            'module': {'name': name, 'version': version, 'git_commit': git_commit, 'schema_version': SCHEMA_VERSION,
                       'status': 'failed', 'error_type': error_type, 'traceback_tail': traceback_tail,
                       'window': {'started_at': started_at, 'finished_at': finished_at}, 'source_health': source_health or {}}}


def validate(doc, expect_name=None, expect_date=None):
    """返回问题列表；空列表表示通过。不抛异常，方便整合层逐个模块标注。"""
    errs = []
    if not isinstance(doc, dict):
        return ['顶层不是对象']
    mod, summ, rows = doc.get('module'), doc.get('summary'), doc.get('rows')
    if not isinstance(mod, dict):
        errs.append('缺 module 块')
    else:
        errs += ['module 缺字段 %s' % k for k in MODULE_REQUIRED if k not in mod]
        if mod.get('schema_version') != SCHEMA_VERSION:
            errs.append('schema_version 是 %r，应为 %s' % (mod.get('schema_version'), SCHEMA_VERSION))
        if mod.get('status') not in ('ok', 'partial'):
            errs.append('module.status 是 %r，正常输出只能是 ok 或 partial' % mod.get('status'))
        if expect_name and mod.get('name') != expect_name:
            errs.append('module.name 是 %r，应为 %s' % (mod.get('name'), expect_name))
    if not isinstance(summ, dict):
        errs.append('缺 summary')
    else:
        errs += ['summary 缺字段 %s' % k for k in SUMMARY_REQUIRED if k not in summ]
        if expect_date and summ.get('date') != expect_date:
            errs.append('summary.date 是 %r，应为 %s' % (summ.get('date'), expect_date))
    if not isinstance(rows, list):
        errs.append('rows 不是列表')
    else:
        for i, r in enumerate(rows):
            miss = [k for k in ROW_REQUIRED if k not in r]
            if miss:
                errs.append('第 %d 行缺字段 %s' % (i, ','.join(miss)))
                if len(errs) > 20:
                    errs.append('……问题过多，截断')
                    break
            elif not isinstance(r['tvl'], (int, float)):
                errs.append('第 %d 行 tvl 不是数字：%r' % (i, r['tvl']))
        if isinstance(summ, dict) and isinstance(summ.get('n_ge_500k'), int) and summ['n_ge_500k'] != len(rows):
            errs.append('summary.n_ge_500k=%d 与 rows 行数 %d 不一致' % (summ['n_ge_500k'], len(rows)))
    return errs
