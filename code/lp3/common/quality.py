"""lp3 共享数据质量检查（无业务规则）。原样搬自 mvp3/collect.py。"""


def sanity(name, rows, prev):
    """跨日冻结检测：大池（前 10）的 TVL 和 24h 成交与前一天完全相同 → 疑似上游冻结。"""
    if not prev:
        return None
    pv = {r['pool']: r for r in prev}
    top = sorted(rows, key=lambda r: -(r['tvl'] or 0))[:10]
    same = [r for r in top if r['pool'] in pv and pv[r['pool']].get('tvl') == r.get('tvl') and pv[r['pool']].get('vol24') == r.get('vol24')]
    return '疑似冻结：前 10 大池里 %d 个 TVL 和成交与前一天完全相同' % len(same) if len(same) >= 5 else None
