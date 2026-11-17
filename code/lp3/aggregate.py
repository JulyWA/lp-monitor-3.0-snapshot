#!/usr/bin/env python3
"""lp3 整合层：只读 6 个模块当天的输出文件，逐个校验，汇成一份日报草稿。不调用网络，不发送任何消息。

用法（在仓库根目录）：
  /usr/bin/python3 -m lp3.aggregate [--date=YYYY-MM-DD] [--out-root=目录]

每个模块的状态（互斥，按顺序判断）：
  正常 / 部分失败   主输出存在且通过契约校验（module.status = ok / partial）
  契约不符          主输出存在但校验不通过或文件损坏；原因逐条列出，不使用其中数据
  失败              只有 FAILED 文件；写出错误类型和信息
  未到点            当天该时段还没到开始时间
  运行中            已过开始时间、未超过该模块超时；尚无输出
  暂缺              已过超时仍无任何文件
一个模块出问题只影响它自己那一行，其余模块照常汇总。

产出（<out-root>/digest/）：
  digest-<日期>.json        结构化结果（产品第二阶段的卡片和表格从这里读）
  digest-<日期>.md          给人看的日报草稿
  card-dryrun-<日期>.json   按 1.0/2.0 飞书卡片结构生成的干跑卡片。只生成，本程序没有任何发送代码。
退出码：0 = 汇总完成（不论模块状态）；2 = 整合层自身出错。
"""
import datetime
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from lp3.common import contract  # noqa: E402

SGT = datetime.timezone(datetime.timedelta(hours=8))
DEFAULT_OUT_ROOT = os.environ.get('LP3_OUT_ROOT', os.path.join(ROOT, 'out', 'lab', 'lp3'))
OK_STATES = ('正常', '部分失败')


def load_json(path):
    with open(path) as fh:
        return json.load(fh)


def load_config():
    cfg = load_json(os.path.join(HERE, 'aggregate.json'))
    sched = load_json(os.path.join(HERE, 'schedule.json'))
    timeouts = {n: t for st in ('stage1', 'stage2') for n, t in sched[st]}
    return cfg, timeouts


def due_times(date, stage_start, stage):
    h, m = map(int, stage_start[stage].split(':'))
    d = datetime.date.fromisoformat(date)
    return datetime.datetime(d.year, d.month, d.day, h, m, tzinfo=SGT)


def health_brief(sh):
    """source_health -> (请求数, 429 次数, 重试数, 其他 HTTP 错误数, 异常数)。"""
    req = sum(v.get('requests', 0) for v in sh.values())
    n429 = sum(int(v.get('http_errors', {}).get('429', 0)) for v in sh.values())
    other = sum(int(n) for v in sh.values() for c, n in v.get('http_errors', {}).items() if c != '429')
    return {'requests': req, 'http_429': n429, 'retries': sum(v.get('retries', 0) for v in sh.values()),
            'http_other_errors': other, 'exceptions': sum(v.get('exceptions', 0) for v in sh.values())}


def module_entry(m, date, now_dt, out_root, cfg, timeouts):
    name = m['name']
    d = os.path.join(out_root, name)
    main_p, fail_p = os.path.join(d, '%s-%s.json' % (name, date)), os.path.join(d, '%s-%s-FAILED.json' % (name, date))
    e = {'name': name, 'label': m['label'], 'stage': m['stage'], 'tier': m['tier'], 'source': m['source'], 'issues': []}
    if os.path.exists(main_p):
        try:
            doc = load_json(main_p)
        except Exception as ex:
            e.update(state='契约不符', issues=['文件读不出：%s' % str(ex)[:120]])
            return e
        errs = contract.validate(doc, name, date)
        if errs:
            e.update(state='契约不符', issues=errs[:10])
            return e
        s, mod = doc['summary'], doc['module']
        cov = s.get('llama_coverage') or {}
        e.update(state='正常' if mod['status'] == 'ok' else '部分失败', version=mod['version'], git_commit=mod['git_commit'],
                 window=mod['window'], health=health_brief(mod.get('source_health') or {}),
                 n_ge_500k=s['n_ge_500k'], n_pass=s['n_pass'], n_apy_board=s.get('n_apy_board'), by_class=s['by_class'], tvl_sum=s['tvl_sum'],
                 coverage={'status': cov.get('status'), 'ratio': cov.get('ratio'), 'ratio_3d': cov.get('ratio_3d'), 'verdict': cov.get('verdict')},
                 warn=s.get('warn'), n_meme_archived=(s.get('meta') or {}).get('n_meme_archived'))
        if mod['status'] == 'partial':
            meta = s.get('meta') or {}
            e['issues'].append('部分接口失败：%s' % (str(meta.get('errors') or meta.get('front_error') or meta.get('priced_side_error')
                                                       or (meta.get('recheck') or {}).get('errors') or '见模块输出')[:160]))
        if os.path.exists(fail_p):
            e['issues'].append('同日另有 FAILED 文件（重跑前留下的？），以主输出为准')
        return e
    if os.path.exists(fail_p):
        try:
            f = load_json(fail_p)
            mod = f.get('module') or {}
            e.update(state='失败', error=str(f.get('error'))[:300], error_type=mod.get('error_type'), version=mod.get('version'),
                     health=health_brief(mod.get('source_health') or {}))
            e['issues'].append('%s：%s' % (mod.get('error_type') or '错误', str(f.get('error'))[:200]))
        except Exception as ex:
            e.update(state='失败', issues=['FAILED 文件读不出：%s' % str(ex)[:120]])
        return e
    start = due_times(date, cfg['stage_start'], m['stage'])
    if now_dt < start:
        e.update(state='未到点', issues=['%s 时段 %s 开始' % (m['stage'], cfg['stage_start'][m['stage']])])
    elif now_dt < start + datetime.timedelta(seconds=sum(t for n, t in timeouts.items() if n in stage_members(cfg, m['stage']))):
        e.update(state='运行中', issues=['已过开始时间，尚未产出'])
    else:
        e.update(state='暂缺', issues=['已过本时段最长运行时间，仍无输出文件'])
    return e


def stage_members(cfg, stage):
    return [m['name'] for m in cfg['modules'] if m['stage'] == stage]


def usd_m(x):
    return '$%.1fM' % (x / 1e6) if isinstance(x, (int, float)) else '—'


def pct(x):
    return '%.0f%%' % (x * 100) if isinstance(x, (int, float)) else '—'


def cov_text(c):
    if not c or c.get('status') != '已对比':
        return (c or {}).get('status') or '—'
    return '%s / %s · %s' % (pct(c.get('ratio')), pct(c.get('ratio_3d')), c.get('verdict'))


def build(date, out_root=None, now=None):
    out_root = out_root or DEFAULT_OUT_ROOT
    cfg, timeouts = load_config()
    now_dt = datetime.datetime.fromtimestamp(now, SGT) if now is not None else datetime.datetime.now(SGT)
    entries = [module_entry(m, date, now_dt, out_root, cfg, timeouts) for m in cfg['modules']]
    counts = {}
    for e in entries:
        counts[e['state']] = counts.get(e['state'], 0) + 1
    return {'date': date, 'generated_at': now_dt.isoformat(timespec='seconds'), 'out_root': os.path.relpath(out_root, ROOT),
            'n_modules': len(entries), 'n_usable': sum(e['state'] in OK_STATES for e in entries), 'counts': counts,
            'all_usable': all(e['state'] in OK_STATES for e in entries), 'modules': entries, 'tier_legend': cfg['tier_legend']}


def to_markdown(dg):
    L = ['# LP 3.0 影子日报（干跑）· %s' % dg['date'], '',
         '生成于 %s。可用 %d / %d 个模块；%s。影子数据，不进正式榜，不推送。' % (
             dg['generated_at'], dg['n_usable'], dg['n_modules'], '，'.join('%s %d' % kv for kv in dg['counts'].items())), '',
         '| 模块 | 数据源 | 状态 | ≥$50万 | 过门槛（代币/股票） | TVL | 采全比（单日 / 3 日 · 判定） | 版本 |',
         '| --- | --- | --- | --- | --- | --- | --- | --- |']
    for e in dg['modules']:
        if e['state'] in OK_STATES:
            L.append('| %s | %s | %s | %d | %d（%d/%d） | %s | %s | %s |' % (
                e['label'], e['tier'], e['state'], e['n_ge_500k'], e['n_pass'], e['by_class'].get('代币', 0), e['by_class'].get('股票和商品', 0),
                usd_m(e['tvl_sum']), cov_text(e['coverage']), e['version']))
        else:
            L.append('| %s | %s | **%s** | — | — | — | — | %s |' % (e['label'], e['tier'], e['state'], e.get('version') or '—'))
    issues = [(e, i) for e in dg['modules'] for i in e['issues']] + [(e, '告警：' + e['warn']) for e in dg['modules'] if e.get('warn')]
    L += ['', '## 需要注意', ''] + (['- **%s**：%s' % (e['label'], i) for e, i in issues] or ['- 无'])
    L += ['', '## 接口健康（本次运行）', '', '| 模块 | 请求 | 429 | 重试 | 其他 HTTP 错误 | 异常 |', '| --- | --- | --- | --- | --- | --- |']
    for e in dg['modules']:
        h = e.get('health')
        L.append('| %s | %s |' % (e['label'], ' | '.join(str(h[k]) for k in ('requests', 'http_429', 'retries', 'http_other_errors', 'exceptions')) if h else '— | — | — | — | —'))
    L += ['', '图例：' + '；'.join('%s %s' % kv for kv in dg['tier_legend'].items()), '']
    return '\n'.join(L)


def to_card(dg):
    """飞书卡片结构（schema 2.0，与 1.0/2.0 一致）。标题带「影子/测试」，灰色。只生成，不发送。"""
    lines = []
    for e in dg['modules']:
        if e['state'] in OK_STATES:
            lines.append('%s **%s** · %s · 过门槛 %d 池 · TVL %s · 采全比 %s%s' % (
                e['tier'], e['label'], e['state'], e['n_pass'], usd_m(e['tvl_sum']), cov_text(e['coverage']), ' · ⚠ 有告警' if e.get('warn') else ''))
        else:
            lines.append('%s **%s** · **%s**%s' % (e['tier'], e['label'], e['state'], ('：' + e['issues'][0][:80]) if e['issues'] else ''))
    head = '可用 %d / %d 个模块（%s）' % (dg['n_usable'], dg['n_modules'], '，'.join('%s %d' % kv for kv in dg['counts'].items()))
    foot = ['- 影子数据：3.0 第一阶段只采集、只落本地文件，不进正式榜。本卡为干跑产物，未发送。',
            '- 每个模块独立采集、独立校验；一个模块失败只影响它自己这一行。',
            '- 数据源：' + '；'.join('%s %s' % kv for kv in dg['tier_legend'].items()),
            '- 生成于 %s' % dg['generated_at']]
    els = [{'tag': 'markdown', 'content': head}, {'tag': 'hr'}, {'tag': 'markdown', 'content': '\n'.join(lines)}, {'tag': 'hr'},
           {'tag': 'collapsible_panel', 'expanded': False, 'header': {'title': {'tag': 'markdown', 'content': '说明 / 数据源'}},
            'elements': [{'tag': 'markdown', 'content': '\n'.join(foot)}]}]
    return {'msg_type': 'interactive', 'card': {'schema': '2.0', 'config': {'wide_screen_mode': True},
                                                 'header': {'template': 'grey', 'title': {'tag': 'plain_text', 'content': 'LP 市场监控 3.0 · 影子/测试 · 模块状态 · %s' % dg['date']}},
                                                 'body': {'elements': els}}}


def write_all(dg, out_root=None):
    d = os.path.join(out_root or DEFAULT_OUT_ROOT, 'digest')
    os.makedirs(d, exist_ok=True)
    paths = {}
    for kind, name, content in (('json', 'digest-%s.json', dg), ('md', 'digest-%s.md', None), ('card', 'card-dryrun-%s.json', to_card(dg))):
        p = os.path.join(d, name % dg['date'])
        tmp = p + '.tmp'
        with open(tmp, 'w') as fh:
            if kind == 'md':
                fh.write(to_markdown(dg))
            else:
                json.dump(content, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, p)
        paths[kind] = p
    return paths


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    opts = dict(a[2:].split('=', 1) for a in argv if a.startswith('--') and '=' in a)
    date = opts.get('date') or datetime.datetime.now(SGT).strftime('%Y-%m-%d')
    try:
        dg = build(date, opts.get('out-root'))
        paths = write_all(dg, opts.get('out-root'))
    except Exception as e:
        print('整合层出错：%s（%s）' % (e, type(e).__name__))
        return 2
    print('lp3 整合 %s：可用 %d/%d（%s）→ %s' % (date, dg['n_usable'], dg['n_modules'], '，'.join('%s %d' % kv for kv in dg['counts'].items()), paths['md']))
    return 0


if __name__ == '__main__':
    sys.exit(main())
