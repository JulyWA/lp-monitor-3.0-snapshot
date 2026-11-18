"""Curve · Ethereum 模块。
数据源：成交、手续费、7 天、池列表用 Curve 官方 Prices API（🟢 prices.curve.finance）；
TVL 用 Curve 官方 API getPools（🟡 api.curve.finance，curve.fi 前端同源，非网页抓取；失败时退回 Prices API 并告警）；
LP 分成读链上 admin_fee()（🟡 免费公共节点 publicnode，读不到按默认 50%）。
逻辑原样搬自 mvp3/collect.py 的 curve() / curve_frontend_tvl() / curve_pick_tvl() / curve_admin_fees()。"""
import json
import subprocess
import time

from lp3.common import coverage as cov_lib
from lp3.common import defillama, http
from . import rules

PRICES_URL = 'https://prices.curve.finance/v1/chains/ethereum'
FRONT_URL = 'https://api.curve.finance/v1/getPools/all/ethereum'  # curve.fi 前端用的池列表（公开、只读）
VOLUME_URL = 'https://prices.curve.finance/v1/volume/usd/ethereum/%s?interval=day&start=%d&end=%d'


def age(ts, now):
    return None if ts is None else (now - ts) / 86400


def admin_fees(pools, eth_rpc, chunk=50):
    """批量读 Curve 池的 admin_fee()（1e10 = 100%）。返回 {pool: 比例}；读不到的池不放进结果。"""
    out = {}
    for i in range(0, len(pools), chunk):
        part = pools[i:i + chunk]
        body = json.dumps([{'jsonrpc': '2.0', 'id': k, 'method': 'eth_call', 'params': [{'to': p, 'data': '0xfee3f7f9'}, 'latest']} for k, p in enumerate(part)])
        for attempt in range(3):
            pr = subprocess.run(['curl', '-sS', '--max-time', '60', eth_rpc, '-H', 'content-type: application/json', '-d', body], capture_output=True, text=True)
            try:
                res = json.loads(pr.stdout)
                http.record(eth_rpc, True, retry=attempt > 0)  # 1.0.1：计入 source_health
                break
            except ValueError:
                res = None
                http.record(eth_rpc, False, retry=attempt > 0)
                time.sleep(3 * (attempt + 1))
        if not isinstance(res, list):
            continue  # 整批读不到：这批池走默认 50%，notes 里会写明
        for x in res:
            v = x.get('result')
            if v and v != '0x' and 'error' not in x:
                n = int(v, 16)
                f = n / 1e10 if n <= 10**10 else -1  # 超过 100% 说明不是这个函数的语义（个别池返回别的东西），当读不到
                if 0 <= f <= 1:
                    out[part[x['id']]] = f
    return out


def fee_rates(pools, eth_rpc, chunk=50):
    """1.1.0：批量读 Curve 池的 fee()（1e10 = 100%）。返回 {pool: 百分比}；读不到或超过 100% 的不放进结果。默认关（read_fee_rate）。"""
    out = {}
    for i in range(0, len(pools), chunk):
        part = pools[i:i + chunk]
        body = json.dumps([{'jsonrpc': '2.0', 'id': k, 'method': 'eth_call', 'params': [{'to': p, 'data': '0xddca3f43'}, 'latest']} for k, p in enumerate(part)])
        pr = subprocess.run(['curl', '-sS', '--max-time', '60', eth_rpc, '-H', 'content-type: application/json', '-d', body], capture_output=True, text=True)
        try:
            res = json.loads(pr.stdout)
            http.record(eth_rpc, True)
        except ValueError:
            http.record(eth_rpc, False)
            continue
        for x in res if isinstance(res, list) else []:
            v = x.get('result')
            if v and v != '0x' and 'error' not in x:
                n = int(v, 16)
                if 0 < n <= 10**10:
                    out[part[x['id']]] = n / 1e10 * 100
    return out


def frontend_tvl(now, stale_hours, fetch=None, urls=None):
    """getPools 的 usdTotal。返回 {池地址小写: (usdTotal, isBroken)}。同一池出现在多个 registry 时取较大 TVL，任一处 isBroken 就算 broken。"""
    d = (fetch or http.get)(FRONT_URL)
    pools = ((d or {}).get('data') or {}).get('poolData') if isinstance(d, dict) else None
    if not isinstance(pools, list) or not pools:
        raise http.SourceError('Curve 前端 getPools 返回结构异常：%s' % str(d)[:200])
    gen = (d.get('generatedTimeMs') or 0) / 1000
    if gen and now - gen > stale_hours * 3600:
        raise http.SourceError('Curve 前端 getPools 数据陈旧：距今 %.1f 小时' % ((now - gen) / 3600))
    out = {}
    for p in pools:
        a = (p.get('address') or '').lower()
        if not a:
            continue
        u, b = float(p.get('usdTotal') or 0), bool(p.get('isBroken'))
        if urls is not None and ((p.get('poolUrls') or {}).get('swap') or []):
            urls.setdefault(a, p['poolUrls']['swap'][0])  # 官方 curve.fi 池页（1.1.0，默认不写进输出）
        if a in out:
            u, b = max(u, out[a][0]), b or out[a][1]
        out[a] = (u, b)
    return out


def pick_tvl(p, front):
    """返回 (tvl, 来源, 排除原因或 None)。前端接口整体取不到（front is None）或前端没有这个池时退回 Prices API 的 tvl_usd。"""
    if front is None:
        return p.get('tvl_usd') or 0, 'prices_fallback', None
    a = (p.get('address') or '').lower()
    if a not in front:
        return p.get('tvl_usd') or 0, 'prices_not_in_front', None
    u, broken = front[a]
    if broken:
        return 0.0, 'front', 'curve.fi 前端标记 isBroken'
    if u <= 0:
        return 0.0, 'front', 'curve.fi 前端 TVL 为 0'
    return u, 'front', None


def run(ctx, with_7d=True):
    cfg = ctx.config()
    R, stale = cfg['rules'], cfg['stale_hours']
    stocks, now = ctx.stocks, ctx.now
    d = http.get(PRICES_URL, timeout=120)
    if not isinstance(d, dict) or not isinstance(d.get('data'), list) or not d['data']:
        raise http.SourceError('Curve Prices API 返回结构异常：%s' % str(d)[:200])
    cached = d.get('cached_at')
    if cached and now - cached > stale * 3600:
        raise http.SourceError('Curve Prices API 数据陈旧：cached_at 距今 %.1f 小时' % ((now - cached) / 3600))
    front_err = None
    try:
        urls = {} if cfg.get('use_pool_urls') else None
        front = frontend_tvl(now, stale, fetch=lambda u: http.get(u, tries=3, timeout=120), urls=urls)
    except http.SourceError as e:  # 前端接口失败不让任务失败：退回 Prices API 的 TVL，summary.meta 和 warn 里写明
        front, front_err, urls = None, str(e)[-160:], None
    rows, excluded, dropped, tail, n_fallback = [], [], [], 0.0, 0
    for p in d['data']:
        tvl, src, why = pick_tvl(p, front)
        if why:
            if (p.get('tvl_usd') or 0) >= R['min_tvl']:
                excluded.append({'pool': p['address'].lower(), 'name': p.get('name'), 'tvl_prices': p.get('tvl_usd'), 'reason': why})
            continue
        if tvl < R['min_tvl']:
            tail += tvl  # 11-16：长尾计入采全比分子（全量）
            if src == 'front' and (p.get('tvl_usd') or 0) >= R['min_tvl']:  # Prices 说 ≥$50 万、前端不到：记下来便于核对
                dropped.append({'pool': p['address'].lower(), 'name': p.get('name'), 'tvl_prices': p.get('tvl_usd'), 'tvl_front': tvl})
            continue
        coins = p.get('coins') or []
        note = {'front': '', 'prices_not_in_front': 'curve.fi 前端接口没有这个池，TVL 用 Prices API；',
                'prices_fallback': 'curve.fi 前端接口取数失败，TVL 用 Prices API；'}[src]
        n_fallback += src != 'front'
        rows.append({'protocol': 'Curve', 'chain': 'Ethereum', 'pool': p['address'].lower(), 'name': p.get('name'), 'fee_pct': None,
                     'tvl': tvl, 'tvl_prices': p.get('tvl_usd'), 'tvl_source': src,
                     'vol24': p.get('trading_volume_24h'), 'fee24': p.get('trading_fee_24h'), 'vol7d': None, 'fee7d': None,
                     'lp_share': None, 'created': p.get('creation_ts'), 'age_days': age(p.get('creation_ts'), now),
                     'tokens': [[c.get('symbol'), c.get('address')] for c in coins], 'notes': note})
    # LP 拿多少：11-11 链上实测各池不同（多数 50%，Yield Basis 池 0% 归协议，3pool 100% 归协议）。
    # 读每个池的 admin_fee()；读不到（tricrypto-ng 等没有这个函数）按 Curve 文档默认 50%，并在 notes 里写明。
    adm = admin_fees([r['pool'] for r in rows], cfg['eth_rpc'])
    for r in rows:
        a = adm.get(r['pool'])
        if a is None:
            r['lp_share'] = cfg['default_lp_share']
            r['notes'] += 'admin_fee() 读不到，按 Curve 文档默认 LP 拿 50%'
        else:
            r['lp_share'] = 1 - a
            r['notes'] += '链上 admin_fee %.0f%%，LP 拿 %.0f%%' % (a * 100, (1 - a) * 100)
        if (r['name'] or '').lower().startswith(tuple(cfg['yb_prefixes'])):
            r['yb'] = True
            r['apy_out'] = 'Yield Basis 杠杆池：11-11 July 定不进 APY 榜，只上 TVL 榜'
            r['notes'] += '；Yield Basis 杠杆池：池子的 LP 是 Yield Basis 合约，个人经 YB 进入，还要扣 YB 分成和借款成本，APY 不能和普通池直接比'
    if cfg.get('read_fee_rate'):
        fees = fee_rates([r['pool'] for r in rows], cfg['eth_rpc'])
        for r in rows:
            r['fee_pct'] = fees.get(r['pool'])
    if cfg.get('use_pool_urls') and urls:
        for r in rows:
            if urls.get(r['pool']):
                r['front_url'] = urls[r['pool']]
    if with_7d:
        for r in rows:
            u = VOLUME_URL % (r['pool'], now - 9 * 86400, now)
            try:
                days = http.get(u, tries=3).get('data') or []
            except http.SourceError as e:
                r['notes'] += '；7 天取数失败：%s' % str(e)[-80:]
                continue
            full = [x for x in days if x['timestamp'] + 86400 <= now][-7:]  # 只用完整的 UTC 日
            if len(full) >= 6:
                k = 7 / len(full)
                r['vol7d'] = sum(x['volume'] for x in full) * k
                r['fee7d'] = sum(x['fees'] for x in full) * k
            time.sleep(0.3)
    meta = {'cached_at': cached, 'n_api': len(d['data']), 'count_field': d.get('count'), 'tail_tvl': tail, 'tail_status': 'full',
            'tvl_source': 'curve.fi getPools usdTotal' if front is not None else 'Prices API tvl_usd（前端接口失败，退回）',
            'n_front': len(front) if front is not None else None, 'n_tvl_fallback': n_fallback,
            'excluded_front': excluded, 'below_threshold_by_front': dropped, 'tvl_prices_sum': sum(r['tvl_prices'] or 0 for r in rows)}
    if front_err:
        meta['front_error'] = front_err
    return [rules.finish(r, stocks, R) for r in rows], meta


def coverage(ctx, rows, meta):
    cfg = ctx.config()
    cov = cov_lib.evaluate(cfg['coverage'], ctx.date, ctx.now, rows, defillama.protocol,
                           load_previous=lambda n, d: defillama.previous_ratio(ctx.out_root, n, d), tail_tvl=meta.get('tail_tvl'))
    cov['legacy'] = defillama.legacy_block(cfg['legacy_coverage'], sum(r['tvl'] for r in rows))
    return cov


def extra_warn(ctx, meta):
    return ('Curve TVL 退回 Prices API（前端 getPools 取数失败：%s）' % meta['front_error'][-80:]) if meta.get('front_error') else None


def status(meta):
    return 'partial' if meta.get('front_error') else 'ok'
