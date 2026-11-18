"""Robinhood 主流交易对模块（按链：Aero、Ramses、Uniswap 等多家）。股票池归 2.0，不在这里；非股票、非主流币一律按 meme 存档。
数据源：GeckoTerminal（🔴 第三方聚合，非官方）。Robinhood 链上暂未找到覆盖多家 DEX 的官方接口（任务书 §3.3，待确认）。
动态费率池（dex 以 aero-、aerodrome-、ramses- 开头）不用 GT 池名费率，fee/APY 留空，注「动态费率，未取」（11-17 July 批，提交 872cf6d）。
逻辑原样搬自 mvp3/collect.py 的 rh()。"""
import json
import re
import subprocess

from lp3.common import defillama, geckoterminal as gt, http
from . import rules

DYNFEE_NOTE = '动态费率，未取'


def age(ts, now):
    return None if ts is None else (now - ts) / 86400


def strip_fee_suffix(name):
    return re.sub(r'\s+[\d.]+%$', '', name or '')


def front_url(dex, chain, pool, chain_id):
    """Aero 池 -> app.aero.xyz；Aerodrome 旧版 -> aerodrome.finance；其他（含 Ramses）None。仅作跳转链接，程序不访问。"""
    d = dex or ''
    if d.startswith('aero-') and chain in chain_id:
        return 'https://app.aero.xyz/deposit/%d-%s' % (chain_id[chain], pool)
    if d.startswith('aerodrome-'):
        return 'https://aerodrome.finance/liquidity?query=%s' % pool
    return None


def run(ctx):
    cfg = ctx.config()
    R, major, dyn_prefixes = cfg['rules'], set(cfg['major']), tuple(cfg['dynamic_fee_dex_prefixes'])
    stocks, now = ctx.stocks, ctx.now
    raw, errs = gt.pools('robinhood', None, pages=10)
    rows, archive = [], []
    for x in raw:
        syms = [(s or '').upper() for s, _ in x['tokens']]
        is_stock = any((a or '').lower() in stocks for _, a in x['tokens'])
        if not is_stock and not all(s in major for s in syms):
            # 11-11 July 定：meme 不上卡，但照样采下来单独存档（不设 TVL 门槛，meme 池常常 TVL 很小、成交很大）
            archive.append({'chain': 'Robinhood', 'pool': x['pool'], 'name': x['name'], 'dex': x['dex'], 'tvl': x['tvl'], 'vol24': x['vol24'],
                            'created': gt.iso_ts(x['created_iso']), 'age_days': age(gt.iso_ts(x['created_iso']), now), 'tokens': x['tokens'],
                            'label': '非股票、非主流币（按 meme 处理）'})
            continue
        if x['tvl'] < R['min_tvl'] or is_stock:  # 股票池由 2.0 负责
            continue
        dyn = (x['dex'] or '').startswith(dyn_prefixes)
        m = re.search(r'([\d.]+)%$', x['name'])
        fp = float(m.group(1)) if m and not dyn else None  # 11-17 July 批：动态费率池不用 GT 池名费率，fee/APY 留空
        r = {'protocol': x['dex'], 'chain': 'Robinhood', 'pool': x['pool'], 'name': strip_fee_suffix(x['name']) if dyn else x['name'], 'fee_pct': fp,
             'tvl': x['tvl'], 'vol24': x['vol24'],
             'vol7d': None, 'fee24': x['vol24'] * fp / 100 if fp else None, 'fee7d': None, 'lp_share': None, 'created': gt.iso_ts(x['created_iso']),
             'age_days': age(gt.iso_ts(x['created_iso']), now), 'tokens': x['tokens'],
             'notes': DYNFEE_NOTE + '（GeckoTerminal 池名费率 %s 不可信）' % (m.group(0) if m else '无') if dyn else '' if fp else '池名里没有费率，手续费暂缺'}
        if dyn:
            r['name_gt'] = x['name']
            url = front_url(x['dex'], 'Robinhood', x['pool'], cfg['chain_id'])
            if url:
                r['front_url'] = url
        rows.append(r)
    meta_extra = {}
    if cfg.get('deduct_v3_protocol_fee'):  # 1.1.0：开关打开后 Uniswap V3 池按链上 slot0.feeProtocol 扣成 LP 实收（默认关）
        meta_extra = apply_v3_protocol_fee(rows, cfg)
    rows = [rules.finish(r, stocks, R) for r in rows]
    for r in rows:
        if r.pop('_apy_unreadable', False):
            r['apy_now'] = r['apy_7d'] = None
    meta = {'errors': errs, 'n_raw': len(raw), 'archive': archive, 'n_dynamic_fee': sum(1 for r in rows if (r.get('notes') or '').startswith(DYNFEE_NOTE))}
    meta.update(meta_extra)
    return rows, meta


def apply_v3_protocol_fee(rows, cfg):
    """与 2.0 rwa.py apply_protocol_fee 同口径：V3 池读 slot0().feeProtocol，LP 分成 = 1 − 抽成；V4 不扣（协议费由交易者另付）。
    读不到的 V3 池 APY 留空（不进 APY 榜）。11-18 实测进榜 5 个 V3 池全部开启：0.01%/0.05% 档 1/4，0.3% 档 1/6。"""
    v3 = [r for r in rows if r['protocol'].startswith('uniswap-v3') and r.get('fee_pct')]
    got, rpc_used = {}, None
    body = json.dumps([{'jsonrpc': '2.0', 'id': k, 'method': 'eth_call', 'params': [{'to': r['pool'], 'data': '0x3850c7bd'}, 'latest']} for k, r in enumerate(v3)])
    for rpc in cfg.get('rpcs') or []:
        if not v3:
            break
        p = subprocess.run(['curl', '-sS', '--max-time', '30', '-H', 'content-type: application/json', '-d', body, rpc], capture_output=True, text=True)
        try:
            res = {x['id']: x.get('result') for x in json.loads(p.stdout)}
        except (ValueError, TypeError, KeyError):
            http.record(rpc, False)
            continue
        http.record(rpc, True)
        rpc_used = rpc
        for k, r in enumerate(v3):
            v = res.get(k)
            if v and len(v) >= 2 + 64 * 7:
                got[r['pool']] = int(v[2 + 64 * 5: 2 + 64 * 6], 16) & 0xFF
        break
    ok = fail = 0
    for r in v3:
        fp = got.get(r['pool'])
        if fp is None:
            r['_apy_unreadable'] = True
            r['notes'] = (r['notes'] + '；' if r['notes'] else '') + 'V3 协议抽成读取失败，APY 留空'
            fail += 1
            continue
        a, b = fp & 0xF, fp >> 4
        sh = ((1.0 / a if a else 0.0) + (1.0 / b if b else 0.0)) / 2
        r['lp_share'] = 1 - sh
        r['notes'] = (r['notes'] + '；' if r['notes'] else '') + ('LP 实收：扣 V3 协议抽成 1/%d·1/%d' % (a, b) if fp else 'V3 协议费未开')
        ok += 1
    return {'v3_protocol_fee': {'ok': ok, 'fail': fail, 'rpc': rpc_used}}


def coverage(ctx, rows, meta):
    cfg = ctx.config()
    cov = {'status': '不适用', 'reason': cfg['coverage']['not_applicable']}
    cov['legacy'] = defillama.legacy_block(cfg['legacy_coverage'], sum(r['tvl'] for r in rows))
    return cov
