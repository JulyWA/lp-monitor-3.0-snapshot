"""本模块的筛选规则（每个模块各持一份副本，改动只影响本模块）。逻辑原样搬自 mvp3/collect.py 的 apply_rules() / finish()，
参数来自本模块 config.json 的 rules 段：TVL ≥ min_tvl、部署 ≥ min_days 天、24h 成交 ≤ spike × 7 天日均。"""


def apply_rules(r, R):
    w = list(r.pop('_filter_reasons', []))
    if (r.get('tvl') or 0) < R['min_tvl']:
        w.append('TVL < $%g 万' % (R['min_tvl'] / 1e4))
    if r.get('age_days') is not None and r['age_days'] < R['min_days']:
        w.append('部署 %.0f 天' % r['age_days'])
    if r.get('vol7d') and (r.get('vol24') or 0) > R['spike'] * r['vol7d'] / 7:
        w.append('24h 成交是 7 天日均的 %.1f 倍' % (r['vol24'] / (r['vol7d'] / 7)))
    r['why_out'] = '；'.join(w)
    return r


def finish(r, stocks, R):
    r['asset_class'] = '股票和商品' if any((a or '').lower() in stocks or (a or '') in stocks for _, a in r['tokens']) else '代币'
    lp = 1.0 if r.get('lp_share') is None else r['lp_share']
    if r.get('fee24') is not None and r.get('tvl'):
        r['apy_now'] = r['fee24'] * lp * 365 / r['tvl'] * 100
    if r.get('fee7d') is not None and r.get('tvl'):
        r['apy_7d'] = r['fee7d'] * lp * 52 / r['tvl'] * 100
    return apply_rules(r, R)
