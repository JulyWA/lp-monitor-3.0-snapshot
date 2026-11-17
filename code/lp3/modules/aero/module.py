"""Aero + Aerodrome 旧版 · Base 模块（同一组 GeckoTerminal 请求、同一个 DefiLlama 分母，用 protocol 字段区分）。
数据源：GeckoTerminal（🔴 第三方聚合，非官方；按成交排序只拉前 10 页）。前一天 ≥$50 万、今天掉出列表的池按地址复查补回；
复查池算采全比时只计 DefiLlama 能定价的一侧（coins.llama.fi，🔴，只影响采全比）。
动态费率：不取池名费率，fee/APY 留空；旧版池 24h 成交/TVL < dormant_vol_tvl 标「旧版沉睡」（照常进榜和采全比）。
逻辑原样搬自 mvp3/collect.py 的 aero() 及 Aero 相关辅助函数（11-17 July 批，提交 872cf6d）。
更稳的替代源（Aero 官方 LpSugar 合约）另行评估，见任务书 §3.3。"""
import datetime
import re

from lp3.common import coverage as cov_lib
from lp3.common import defillama, geckoterminal as gt
from . import rules

AERO_NEW, AERO_LEGACY = 'Aero', 'Aerodrome 旧版'
DYNFEE_NOTE = '动态费率，未取'
DORMANT_TAG = '旧版沉睡'


def age(ts, now):
    return None if ts is None else (now - ts) / 86400


def previous_date(date, days=1):
    return (datetime.date.fromisoformat(date) - datetime.timedelta(days=days)).isoformat()


def strip_fee_suffix(name):
    """去掉 GT 池名末尾的费率，如 'WETH / USDC 0.04%' -> 'WETH / USDC'。"""
    return re.sub(r'\s+[\d.]+%$', '', name or '')


def aero_protocol(dex):
    """aero-* -> Aero；aerodrome-* -> Aerodrome 旧版；其他 None。"""
    d = dex or ''
    return AERO_NEW if d.startswith('aero-') else AERO_LEGACY if d.startswith('aerodrome-') else None


def front_url(dex, chain, pool, chain_id):
    """Aero 池 -> app.aero.xyz 存款页（按链 id）；旧版池 -> aerodrome.finance 按地址搜索；其他 None。仅作跳转链接，程序不访问。"""
    kind = aero_protocol(dex)
    if kind == AERO_NEW and chain in chain_id:
        return 'https://app.aero.xyz/deposit/%d-%s' % (chain_id[chain], pool)
    if kind == AERO_LEGACY:
        return 'https://aerodrome.finance/liquidity?query=%s' % pool
    return None


def is_dormant_legacy(dex, tvl, vol24, ratio):
    return aero_protocol(dex) == AERO_LEGACY and bool(tvl) and (vol24 or 0) / tvl < ratio


def recheck_previous(raw, prev_rows, fetch_multi, min_tvl):
    """前一天 TVL ≥ 门槛、今天列表里没有的池，按地址复查；仍 ≥ 门槛的补回 raw（标 rechecked）。复查失败不让模块失败，只记 errors。"""
    have = {x['pool'] for x in raw}
    want = [r['pool'] for r in prev_rows if (r.get('tvl') or 0) >= min_tvl and r['pool'] not in have]
    stat = {'n_prev_missing': len(want), 'n_added': 0, 'tvl_added': 0.0, 'n_below_threshold': 0, 'n_not_found': 0, 'errors': []}
    if not want:
        return [], stat
    try:
        found = fetch_multi(want)
    except Exception as e:
        stat['errors'].append(str(e)[-120:])
        return [], stat
    added = []
    for a in want:
        it = found.get(a)
        if it is None:
            stat['n_not_found'] += 1
        elif it['tvl'] < min_tvl:
            stat['n_below_threshold'] += 1
        else:
            it = dict(it, rechecked=True)
            added.append(it); stat['n_added'] += 1; stat['tvl_added'] += it['tvl']
    return added, stat


def recheck_priced_share(added, fetch_priced):
    """两侧都能定价记 1；有任何一侧定不了价记 0（下限）。价格接口失败记 None（采全比按 0 算）。原地写 cover_priced_share，返回错误信息或 None。"""
    if not added:
        return None
    try:
        ok = fetch_priced([a for x in added for _, a in x.get('tokens') or []])
    except Exception as e:
        for x in added:
            x['cover_priced_share'] = None
        return str(e)[-120:]
    for x in added:
        toks = [a for _, a in x.get('tokens') or [] if a]
        x['cover_priced_share'] = 1.0 if toks and all(a.lower() in ok for a in toks) else 0.0
    return None


def run(ctx):
    cfg = ctx.config()
    R, chain_id, dormant_ratio = cfg['rules'], cfg['chain_id'], cfg['dormant_vol_tvl']
    stocks, now = ctx.stocks, ctx.now
    raw, errs = gt.pools('base', cfg['dex_ids'])
    if errs and not raw:
        raise gt.SourceError('GeckoTerminal Aerodrome 全部失败：%s' % errs[:2])
    tail = sum(x['tvl'] for x in raw if x['tvl'] < R['min_tvl'])  # 只是成交榜前 10 页里出现的那部分长尾（partial）
    prev = ctx.load_rows(previous_date(ctx.date))
    added, rstat = recheck_previous(raw, prev or [], lambda addrs: gt.multi('base', addrs), R['min_tvl'])
    perr = recheck_priced_share(added, lambda addrs: defillama.priced_set('base', addrs))
    if perr:
        rstat['priced_error'] = perr
    rstat['tvl_counted_in_coverage'] = sum(x['tvl'] * (x.get('cover_priced_share') or 0) for x in added)
    raw = raw + added
    rows = []
    for x in raw:
        if x['tvl'] < R['min_tvl']:
            continue
        dormant = is_dormant_legacy(x['dex'], x['tvl'], x['vol24'], dormant_ratio)
        rows.append({'protocol': aero_protocol(x['dex']) or 'Aerodrome', 'chain': 'Base', 'pool': x['pool'], 'name': strip_fee_suffix(x['name']),
                     'name_gt': x['name'], 'dex': x['dex'], 'fee_pct': None, 'tvl': x['tvl'],
                     'vol24': x['vol24'], 'vol7d': None, 'fee24': None, 'fee7d': None, 'lp_share': None, 'created': gt.iso_ts(x['created_iso']),
                     'age_days': age(gt.iso_ts(x['created_iso']), now), 'tokens': x['tokens'], 'front_url': front_url(x['dex'], 'Base', x['pool'], chain_id),
                     'notes': DYNFEE_NOTE + '（GeckoTerminal 池名里的费率和合约对不上，11-11、11-16 两次核实）；质押 LP 拿 AERO 不拿手续费'
                              + ('；%s：旧工厂池，24h 成交不到 TVL 的 0.1%%，旧前端常给不出一侧价格' % DORMANT_TAG if dormant else '')
                              + ('；按地址复查补回（前一天 ≥$50 万，今天掉出成交榜前 10 页）' if x.get('rechecked') else '')})
        if dormant:  # 11-17 July 批：照常进榜、照常算采全比，只打标
            rows[-1]['tag'] = DORMANT_TAG
        if x.get('rechecked'):
            rows[-1]['rechecked'] = True
            rows[-1]['cover_priced_share'] = x.get('cover_priced_share')  # 只影响采全比分子，不影响榜单
    split = {k: sum(1 for r in rows if r['protocol'] == k) for k in (AERO_NEW, AERO_LEGACY)}
    return [rules.finish(r, stocks, R) for r in rows], {'errors': errs, 'n_raw': len(raw), 'tail_tvl': tail, 'tail_status': 'partial', 'recheck': rstat,
                                                        'n_by_protocol': split, 'n_dormant_legacy': sum(1 for r in rows if r.get('tag') == DORMANT_TAG)}


def coverage(ctx, rows, meta):
    cfg = ctx.config()
    cov = cov_lib.evaluate(cfg['coverage'], ctx.date, ctx.now, rows, defillama.protocol,
                           load_previous=lambda n, d: defillama.previous_ratio(ctx.out_root, n, d), tail_tvl=meta.get('tail_tvl'))
    cov['legacy'] = defillama.legacy_block(cfg['legacy_coverage'], sum(r['tvl'] for r in rows))
    return cov


def status(meta):
    return 'partial' if meta.get('errors') or (meta.get('recheck') or {}).get('errors') or (meta.get('recheck') or {}).get('priced_error') else 'ok'
