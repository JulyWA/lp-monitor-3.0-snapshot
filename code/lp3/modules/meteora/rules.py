"""本模块的筛选规则（Solana 三家各持一份副本，改动只影响本模块）。逻辑原样搬自 mvp3/collect.py，参数来自本模块 config.json 的 rules 段。

规则：TVL ≥ min_tvl、部署 ≥ min_days 天、24h 成交 ≤ spike × 7 天日均；CoinGecko meme 标签存档；待分类代币挡在榜外；
CoinGecko 未收录且 7 天手续费/TVL < unlisted_min_fee_tvl_7d 的池按假 TVL 排除并存档。
"""
from lp3.common import coverage as cov_lib


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


def solana_label(tokens, labels, R):
    """返回 anchor / ok / meme / unlisted / unknown / error；优先级从风险高到低。"""
    skip = set(R['sol_stable']) | set(R['sol_major'])
    states = []
    for sym, addr in tokens:
        if (sym or '').upper() in skip:
            continue
        if not addr or addr not in labels:
            states.append('unknown'); continue
        info = labels[addr]
        if info.get('id') == 'ERROR':
            states.append('error')
        elif not info.get('id'):
            states.append('unlisted')
        elif any('meme' in str(c).lower() for c in info.get('cats') or []):
            states.append('meme')
        else:
            states.append('ok')
    if not states:
        return 'anchor'
    for state in ('meme', 'unknown', 'error', 'unlisted', 'ok'):
        if state in states:
            return state
    return 'unknown'


def finish_solana(r, stocks, labels, R, cov_spec, filter_unlisted=False):
    label = solana_label(r['tokens'], labels, R)
    r['meme_label'] = label
    if label == 'meme':
        r.setdefault('_filter_reasons', []).append('CoinGecko meme 标签')
    elif label in ('unknown', 'error'):
        r.setdefault('_filter_reasons', []).append('代币分类待更新')
    elif label == 'unlisted':
        r['meme_candidate'] = True
        fee, est = cov_lib.weekly_fee(r, cov_spec)
        ratio = fee / r['tvl'] if fee is not None and r.get('tvl') else None
        if filter_unlisted and ratio is not None and ratio < R['unlisted_min_fee_tvl_7d']:
            r['low_fee_unlisted'] = True
            r.setdefault('_filter_reasons', []).append('CoinGecko 未收录且 7 天手续费/TVL < 0.01%' + ('（fee24×7 估算）' if est else ''))
            note = '按 11-12 已批阈值排除' + ('（Meteora 按 11-16 批准用 fee24×7 估算）' if est else '')
        else:
            note = '未达到自动排除条件' if filter_unlisted else '未启用低费排除'
        r['notes'] = (r.get('notes') or '') + ('；' if r.get('notes') else '') + 'CoinGecko 未收录，' + note
    return finish(r, stocks, R)


def label_counts(rows):
    return {k: sum(1 for r in rows if r.get('meme_label') == k) for k in ('anchor', 'ok', 'meme', 'unlisted', 'unknown', 'error')}


def meme_rows(rows):
    return [r for r in rows if r.get('meme_label') == 'meme' or r.get('low_fee_unlisted')]
