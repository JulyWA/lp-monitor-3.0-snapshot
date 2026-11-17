"""GeckoTerminal 客户端（🔴 第三方聚合，非官方；免费档限速，aero 与 rh 必须串行）。逻辑原样搬自 mvp3/collect.py。
只负责取数和把上游结构整理成统一条目，不含任何筛选规则。"""
import datetime
import re
import time

from lp3.common.http import SourceError, get


def iso_ts(s):
    return int(datetime.datetime.fromisoformat(s.replace('Z', '+00:00')).timestamp()) if s else None


def pools(network, dex_ids=None, pages=10, pause=6.5, sort='h24_volume_usd_desc'):
    """按成交排序拉列表。返回 (条目列表, 错误列表)；单个分页失败只记错误，不中断其他交易所编号。"""
    out, seen, errs = [], set(), []
    paths = ['networks/%s/dexes/%s/pools' % (network, d) for d in dex_ids] if dex_ids else ['networks/%s/pools' % network]
    for path in paths:
        for pg in range(1, pages + 1):
            try:
                d = get('https://api.geckoterminal.com/api/v2/%s?page=%d&sort=%s' % (path, pg, sort), tries=5, wait=8)
            except SourceError as e:
                errs.append(str(e)); break
            time.sleep(pause)
            data = d.get('data') or []
            for x in data:
                if x['attributes']['address'] in seen:
                    continue
                seen.add(x['attributes']['address'])
                out.append(item(x))
            if len(data) < 20:
                break
    return out, errs


def item(x):
    a, rel = x['attributes'], x['relationships']
    tok = lambda k: rel[k]['data']['id'].split('_', 1)[1]
    syms = [s.strip() for s in re.sub(r'\s+[\d.]+%$', '', a['name']).split(' / ')]
    return {'pool': a['address'].lower(), 'name': a['name'], 'dex': rel['dex']['data']['id'], 'tvl': float(a.get('reserve_in_usd') or 0),
            'vol24': float((a.get('volume_usd') or {}).get('h24') or 0), 'created_iso': a.get('pool_created_at'),
            'tokens': [[syms[0] if syms else None, tok('base_token')], [syms[1] if len(syms) > 1 else None, tok('quote_token')]]}


def multi(network, addrs, pause=6.5):
    """按地址批量复查（pools/multi，每次 ≤30 个）。返回 {地址小写: 条目}。"""
    out = {}
    for i in range(0, len(addrs), 30):
        d = get('https://api.geckoterminal.com/api/v2/networks/%s/pools/multi/%s' % (network, ','.join(addrs[i:i + 30])), tries=5, wait=8)
        for x in d.get('data') or []:
            it = item(x)
            out[it['pool']] = it
        time.sleep(pause)
    return out
