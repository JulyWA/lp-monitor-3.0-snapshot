"""DefiLlama 客户端（第三方，只作采全比分母和能定价一侧，不参与排序）。逻辑原样搬自 mvp3/collect.py。

- protocol(slug)：一次拉 /protocols 全表，按 slug 取（每个进程缓存一次）。
- priced_set(chain, addrs)：coins.llama.fi 现价，返回能定价的地址集合（Aero 复查池用）。
- legacy_coverage(spec, tvl_sum)：11-16 之前的旧口径，只作对照写进 llama_coverage.legacy，不告警。
- previous_ratio(out_root, name, date)：采全比 3 日均值要用的前几天单日值。
"""
import json
import os

from lp3.common.http import SourceError, get, get_curl

_ALL = {}
BACKFILL_NAME = 'coverage-backfill-2026-11-16.json'  # 离线回放出的 11-12..11-16 新口径单日值，供 3 日均值起步


def protocol(slug):
    """伪装成 /protocol 的 currentChainTvls 结构。子协议逐个拉单个就有几十 MB，所以只拉一次全表。"""
    if not _ALL:
        for p in get_curl('https://api.llama.fi/protocols'):
            _ALL[p.get('slug')] = p
    p = _ALL.get(slug)
    if p is None:
        return {}
    return {'currentChainTvls': p.get('chainTvls') or {}}


def reset_cache():
    _ALL.clear()


def priced_set(chain, addrs):
    """coins.llama.fi 现价（公开、只读）：返回 DefiLlama 能定价的地址集合（小写）。"""
    addrs = sorted({a.lower() for a in addrs if a})
    ok = set()
    for i in range(0, len(addrs), 60):
        d = get('https://coins.llama.fi/prices/current/' + ','.join('%s:%s' % (chain, a) for a in addrs[i:i + 60]), tries=3)
        ok |= {k.split(':', 1)[1].lower() for k, v in (d.get('coins') or {}).items() if v.get('price')}
    return ok


def legacy_coverage(spec, tvl_sum):
    """旧口径：池合计 ÷ DefiLlama 协议在该链的 TVL。spec = 模块配置的 legacy_coverage 段（slug、chain），null 表示不适用。"""
    if not spec:
        return {'status': '不适用'}
    slug, chain = spec['slug'], spec['chain']
    try:
        total = (get_curl('https://api.llama.fi/protocol/%s' % slug).get('currentChainTvls') or {}).get(chain)
    except SourceError as e:
        return {'status': '未能对比', 'warn': 'DefiLlama 协议总量取数失败，采全检查没做：%s' % str(e)[-80:]}
    if not total:  # 取到了但没有这条链的数：不能当作通过
        return {'status': '未能对比', 'warn': 'DefiLlama %s 没有 %s 链的 TVL，采全检查没做' % (slug, chain)}
    ratio = tvl_sum / total
    return {'status': '已对比', 'llama_slug': slug, 'chain': chain, 'llama_tvl': total, 'ratio': round(ratio, 3)}


def legacy_block(spec, tvl_sum):
    legacy = legacy_coverage(spec, tvl_sum)
    return {k: legacy.get(k) for k in ('status', 'llama_slug', 'llama_tvl', 'ratio')}


def previous_ratio(out_root, name, date):
    """先读本模块前一天输出里的新口径单日值；没有再查回填文件（放在 out_root 下）。"""
    p = os.path.join(out_root, name, '%s-%s.json' % (name, date))
    if os.path.exists(p):
        with open(p) as fh:
            c = (json.load(fh).get('summary') or {}).get('llama_coverage') or {}
        if c.get('definition') == '2026-11-16' and c.get('ratio') is not None:
            return c['ratio']
    bf = os.path.join(out_root, BACKFILL_NAME)
    if os.path.exists(bf):
        with open(bf) as fh:
            return ((json.load(fh).get('ratios') or {}).get(name) or {}).get(date)
    return None
