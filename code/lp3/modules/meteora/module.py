"""Meteora · Solana 模块（DLMM + DAMM v2，共用一个采全比分母）。
数据源：Meteora 官方数据 API（🟢）dlmm.datapi.meteora.ag、damm-v2.datapi.meteora.ag，按 TVL 降序分页并校验顺序。
没有 7 天字段：history_7d_from 之后，若前 7 个连续日本模块快照齐全，fee7d = 7 日 fee24 合计；否则低费过滤用 fee24×7 估算。
逻辑原样搬自 mvp3/collect.py 的 meteora() / _meteora_kind() / meteora_fee7d_from_history()。"""
import datetime

from lp3.common import coverage as cov_lib
from lp3.common import defillama, http
from . import rules

HOSTS = {'dlmm': 'dlmm.datapi.meteora.ag', 'damm2': 'damm-v2.datapi.meteora.ag'}
PROTOCOLS = {'dlmm': 'Meteora DLMM', 'damm2': 'Meteora DAMM v2'}


def f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def timestamp_seconds(x):
    """上游时间戳统一成秒；Meteora 用毫秒。"""
    n = f(x)
    if not n or n <= 0:
        return None
    return int(n / 1000 if n > 10**11 else n)


def age(ts, now):
    return None if ts is None else (now - ts) / 86400


def previous_date(date, days=1):
    return (datetime.date.fromisoformat(date) - datetime.timedelta(days=days)).isoformat()


def fee7d_from_history(ctx, start):
    if ctx.date < start:
        return None
    days = [ctx.load_rows(previous_date(ctx.date, k)) for k in range(1, 8)]
    if any(d is None for d in days):
        return None
    sums, cnt = {}, {}
    for rows in days:
        for r in rows:
            if r.get('fee24') is not None:
                sums[r['pool']] = sums.get(r['pool'], 0) + r['fee24']; cnt[r['pool']] = cnt.get(r['pool'], 0) + 1
    return {p: v for p, v in sums.items() if cnt[p] == 7}


def _kind(kind, ctx, R, spec, labels, history=None):
    host, protocol = HOSTS[kind], PROTOCOLS[kind]
    stocks, now = ctx.stocks, ctx.now
    rows, page, previous_tvl = [], 1, None
    while True:
        d = http.get('https://%s/pools?page=%d&page_size=100&sort_by=tvl:desc' % (host, page), timeout=120)
        data = d.get('data') or []
        if not isinstance(data, list):
            raise http.SourceError('%s 返回结构异常：data 不是列表' % protocol)
        for p in data:
            tvl = f(p.get('tvl')) or 0
            if previous_tvl is not None and tvl > previous_tvl + max(1, previous_tvl * 1e-9):
                raise http.SourceError('%s 未按 TVL 降序返回：第 %d 页 %.2f > %.2f' % (protocol, page, tvl, previous_tvl))
            previous_tvl = tvl
            if tvl < R['min_tvl']:
                continue
            fee24 = f((p.get('fees') or {}).get('24h'))
            pfee24 = f((p.get('protocol_fees') or {}).get('24h')) or 0
            lp_share = max(0, 1 - pfee24 / fee24) if fee24 else 1.0
            created = timestamp_seconds(p.get('created_at'))
            r = {'protocol': protocol, 'chain': 'Solana', 'pool': p['address'], 'name': p.get('name'),
                 'fee_pct': f((p.get('pool_config') or {}).get('base_fee_pct')), 'tvl': tvl,
                 'vol24': f((p.get('volume') or {}).get('24h')), 'vol7d': None,
                 'fee24': fee24, 'fee7d': None, 'lp_share': lp_share,
                 'created': created, 'age_days': age(created, now),
                 'tokens': [[p['token_x'].get('symbol'), p['token_x'].get('address')],
                            [p['token_y'].get('symbol'), p['token_y'].get('address')]],
                 'notes': '官方接口暂无 7 天成交；24h 协议费 %.2f 美元' % pfee24,
                 'verified': [p['token_x'].get('is_verified'), p['token_y'].get('is_verified')]}
            if p.get('is_blacklisted'):
                r.setdefault('_filter_reasons', []).append('Meteora 官方黑名单')
            real7 = history.get(r['pool']) if history else None
            if real7 is not None:
                r['fee7d'] = real7
                r['notes'] += '；fee7d = 前 7 个日快照 fee24 合计'
            rows.append(rules.finish_solana(r, stocks, labels, R, spec, filter_unlisted=True))
        if not data or (f(data[-1].get('tvl')) or 0) < R['min_tvl'] or page >= int(d.get('pages') or 1):
            break
        page += 1
    return rows, page


def run(ctx):
    cfg = ctx.config()
    R, spec = cfg['rules'], cfg['coverage']
    labels = ctx.labels
    history = fee7d_from_history(ctx, cfg['history_7d_from'])
    dlmm, p1 = _kind('dlmm', ctx, R, spec, labels, history)
    damm2, p2 = _kind('damm2', ctx, R, spec, labels, history)
    rows = dlmm + damm2
    return rows, {'pages': {'dlmm': p1, 'damm2': p2}, 'n_raw': len(rows),
                  'by_protocol': {'dlmm': len(dlmm), 'damm2': len(damm2)},
                  'label_counts': rules.label_counts(rows), 'archive': rules.meme_rows(rows)}


def coverage(ctx, rows, meta):
    cfg = ctx.config()
    cov = cov_lib.evaluate(cfg['coverage'], ctx.date, ctx.now, rows, defillama.protocol,
                           load_previous=lambda n, d: defillama.previous_ratio(ctx.out_root, n, d), tail_tvl=meta.get('tail_tvl'))
    cov['legacy'] = defillama.legacy_block(cfg['legacy_coverage'], sum(r['tvl'] for r in rows))
    return cov
