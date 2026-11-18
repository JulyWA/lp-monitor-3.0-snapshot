"""Raydium · Solana 模块。数据源：Raydium 官方 API（🟢）api-v3.raydium.io/pools/info/list，按 TVL 降序分页。
采全比只算 DefiLlama 能定价的一侧（coins.llama.fi，🔴 第三方，只影响采全比），豁免 80% 线。
逻辑原样搬自 mvp3/collect.py 的 raydium() 与 priced_shares()。"""
import datetime

from lp3.common import coverage as cov_lib
from lp3.common import defillama, http
from . import rules


def f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def timestamp_seconds(x):
    """上游时间戳统一成秒；Raydium 的 0 表示未知。"""
    n = f(x)
    if not n or n <= 0:
        return None
    return int(n / 1000 if n > 10**11 else n)


def age(ts, now):
    return None if ts is None else (now - ts) / 86400


AMM_V4_PROGRAM = '675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8'
AMM_V4_LP_SHARE = 0.22 / 0.25  # Raydium 官方文档：AMM v4 收 0.25%，LP 拿 0.22%


def lp_share(p):
    """返回 (LP 实收占总手续费的比例或 None, 说明)。11-18 核实：官方接口 day.volumeFee = 成交 × feeRate，是总手续费，页面 feeApr 也是总口径。
    Concentrated：1 − (protocolFeeRate + fundFeeRate)/1e6（实测 12% + 4%，LP 84%）。
    Standard · CPMM：总费率 = tradeFeeRate + creatorFeeRate；LP 只分交易费的 1 − 协议 − 基金，创建者费归建池人。
    Standard · AMM v4：接口不给 config，按官方文档 0.22/0.25。"""
    c = p.get('config') or {}
    fee = f(p.get('feeRate')) or 0
    prot, fund = f(c.get('protocolFeeRate')), f(c.get('fundFeeRate'))
    if p.get('type') == 'Concentrated' and prot is not None and fund is not None:
        return max(0.0, 1 - (prot + fund) / 1e6), 'LP 实收：总手续费 × (1 − 协议 %.0f%% − 基金 %.0f%%)' % (prot / 1e4, fund / 1e4)
    if c.get('tradeFeeRate') is not None and prot is not None and fund is not None and fee:
        trade = f(c.get('tradeFeeRate')) / 1e6
        share = trade * (1 - (prot + fund) / 1e6) / fee
        return max(0.0, min(1.0, share)), 'LP 实收：交易费 %.4f%% × (1 − 协议 − 基金) ÷ 总费率 %.4f%%（创建者费 %.4f%% 归建池人）' % (
            trade * 100, fee * 100, (f(c.get('creatorFeeRate')) or 0) / 1e4)
    if p.get('programId') == AMM_V4_PROGRAM:
        return AMM_V4_LP_SHARE, 'LP 实收：AMM v4 按官方文档 0.22% ÷ 0.25%'
    return None, 'LP 分成未知，按名义'


def fetch_pages(min_tvl):
    page = 1
    while True:
        outer = http.get('https://api-v3.raydium.io/pools/info/list?poolType=all&poolSortField=liquidity&sortType=desc&pageSize=500&page=%d' % page, timeout=120)
        d = outer.get('data') or {}
        data = d.get('data') or []
        if not isinstance(data, list):
            raise http.SourceError('Raydium 返回结构异常：data.data 不是列表')
        yield page, data
        if not data or (f(data[-1].get('tvl')) or 0) < min_tvl or not d.get('hasNextPage'):
            break
        page += 1


def run(ctx):
    cfg = ctx.config()
    R, spec = cfg['rules'], cfg['coverage']
    stocks, labels, rows, page, now = ctx.stocks, ctx.labels, [], 1, ctx.now
    for page, data in fetch_pages(R['min_tvl']):
        for p in data:
            tvl = f(p.get('tvl')) or 0
            if tvl < R['min_tvl']:
                continue
            day, week = p.get('day') or {}, p.get('week') or {}
            created = timestamp_seconds(p.get('openTime'))
            r = {'protocol': 'Raydium ' + str(p.get('type') or ''), 'chain': 'Solana', 'pool': p['id'],
                 'name': '%s / %s' % (p['mintA'].get('symbol'), p['mintB'].get('symbol')),
                 'fee_pct': (f(p.get('feeRate')) or 0) * 100, 'tvl': tvl,
                 'vol24': f(day.get('volume')), 'vol7d': f(week.get('volume')),
                 'fee24': f(day.get('volumeFee')), 'fee7d': f(week.get('volumeFee')),
                 'lp_share': None, 'created': created, 'age_days': age(created, now),
                 'tokens': [[p['mintA'].get('symbol'), p['mintA'].get('address')],
                            [p['mintB'].get('symbol'), p['mintB'].get('address')]],
                 'notes': '官方接口 openTime 为 0 时无法判断建池时间',
                 'amounts': [f(p.get('mintAmountA')), f(p.get('mintAmountB'))]}  # 11-16：能定价一侧估值要用两侧数量
            if cfg.get('lp_share_mode') == 'net':  # 1.1.0：开关打开后按池类型扣成 LP 实收（默认关，M4 期间与旧代码一致）
                r['lp_share'], basis = lp_share(p)
                r['notes'] += '；' + basis
            rows.append(rules.finish_solana(r, stocks, labels, R, spec, filter_unlisted=True))
    return rows, {'pages': page, 'n_raw': len(rows), 'label_counts': rules.label_counts(rows), 'archive': rules.meme_rows(rows)}


def priced_shares(rows):
    """每个池「DefiLlama 能定价的一侧」占 Raydium 报的 TVL 的比例。价格来自 coins.llama.fi（公开、只读）。"""
    mints = sorted({a for r in rows for _, a in r['tokens'] if a})
    price = {}
    for i in range(0, len(mints), 60):
        d = http.get('https://coins.llama.fi/prices/current/' + ','.join('solana:' + m for m in mints[i:i + 60]), tries=3)
        for k, v in (d.get('coins') or {}).items():
            price[k.split(':', 1)[1]] = v.get('price')
    out = {}
    for r in rows:
        amts = r.get('amounts') or []
        if len(amts) != 2 or not r.get('tvl') or any(a is None for a in amts):
            continue
        val = sum(amt * price[a] for (_, a), amt in zip(r['tokens'], amts) if price.get(a))
        out[r['pool']] = min(1.0, val / r['tvl'])
    return out


def coverage(ctx, rows, meta):
    cfg = ctx.config()
    priced = None
    try:
        priced = priced_shares(rows)
    except http.SourceError as e:
        meta['priced_side_error'] = str(e)[-120:]
    cov = cov_lib.evaluate(cfg['coverage'], ctx.date, ctx.now, rows, defillama.protocol,
                           load_previous=lambda n, d: defillama.previous_ratio(ctx.out_root, n, d), tail_tvl=meta.get('tail_tvl'), priced=priced)
    cov['legacy'] = defillama.legacy_block(cfg['legacy_coverage'], sum(r['tvl'] for r in rows))
    return cov


def status(meta):
    return 'partial' if meta.get('priced_side_error') else 'ok'
