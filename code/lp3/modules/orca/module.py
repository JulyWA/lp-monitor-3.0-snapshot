"""Orca · Solana 模块。数据源：Orca 官方 API（🟢）api.orca.so/v2/solana/pools，游标翻页（大页会被静默截断）。
逻辑原样搬自 mvp3/collect.py 的 orca()。"""
import urllib.parse

from lp3.common import coverage as cov_lib
from lp3.common import defillama, http
from . import rules


def fetch_pages(min_tvl):
    """逐页取数，按 TVL 降序；页尾低于门槛或没有下一页就停。yield 每页的池列表。"""
    nxt = None
    while True:
        q = {'size': 200, 'sortBy': 'tvl', 'sortDirection': 'desc', 'minTvl': int(min_tvl)}
        if nxt:
            q['next'] = nxt
        d = http.get('https://api.orca.so/v2/solana/pools?' + urllib.parse.urlencode(q), timeout=120)
        data = d.get('data') or []
        if not isinstance(data, list):
            raise http.SourceError('Orca 返回结构异常：data 不是列表')
        yield data
        nxt = ((d.get('meta') or {}).get('cursor') or {}).get('next')
        if not data or not nxt or (http_f(data[-1].get('tvlUsdc')) or 0) < min_tvl:
            break


def http_f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def run(ctx):
    cfg = ctx.config()
    R, spec = cfg['rules'], cfg['coverage']
    stocks, labels, rows, pages = ctx.stocks, ctx.labels, [], 0
    f = http_f
    for data in fetch_pages(R['min_tvl']):
        pages += 1
        for p in data:
            s24, s7 = (p.get('stats') or {}).get('24h') or {}, (p.get('stats') or {}).get('7d') or {}
            tvl = f(p.get('tvlUsdc')) or 0
            if tvl < R['min_tvl']:
                continue
            proto_share = (f(p.get('protocolFeeRate')) or 0) / 1e4
            r = {'protocol': 'Orca', 'chain': 'Solana', 'pool': p['address'],
                 'name': '%s / %s' % (p['tokenA'].get('symbol'), p['tokenB'].get('symbol')),
                 'fee_pct': (f(p.get('feeRate')) or 0) / 1e4, 'tvl': tvl,
                 'vol24': f(s24.get('volume')), 'vol7d': f(s7.get('volume')),
                 'fee24': f(s24.get('fees')), 'fee7d': f(s7.get('fees')),
                 'lp_share': max(0, 1 - proto_share), 'created': None, 'age_days': None,
                 'tokens': [[p['tokenA'].get('symbol'), p['tokenA'].get('address')],
                            [p['tokenB'].get('symbol'), p['tokenB'].get('address')]],
                 'notes': '官方接口不提供建池时间；协议费占手续费 %.0f%%' % (proto_share * 100),
                 'updated_at': p.get('updatedAt')}
            rows.append(rules.finish_solana(r, stocks, labels, R, spec, filter_unlisted=True))
    return rows, {'pages': pages, 'n_raw': len(rows), 'label_counts': rules.label_counts(rows), 'archive': rules.meme_rows(rows)}


def coverage(ctx, rows, meta):
    cfg = ctx.config()
    cov = cov_lib.evaluate(cfg['coverage'], ctx.date, ctx.now, rows, defillama.protocol,
                           load_previous=lambda n, d: defillama.previous_ratio(ctx.out_root, n, d), tail_tvl=meta.get('tail_tvl'))
    cov['legacy'] = defillama.legacy_block(cfg['legacy_coverage'], sum(r['tvl'] for r in rows))
    return cov
