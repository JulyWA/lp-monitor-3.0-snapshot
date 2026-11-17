#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""【lp3 · M1 原样复制自 mvp3/llama_cover.py，逻辑未改】3.0 采全比（11-16 July 批准的统一口径）。纯函数，网络读取由调用方注入（collect.py 传 get_curl/get，测试与离线回放传本地函数）。

口径：
  分母 = 该协议在目标链上「DEX 子协议」的 DefiLlama TVL 之和（/protocol/<slug> 的 chainTvls[<链>].tvl，取离采集时刻最近的点）。
         非 DEX（收益聚合/借贷/CDP/Launchpad/质押）和「DEX 但无官方接口、采不到」的子协议不进分母，逐项列在 excluded 里。
  分子 = 采到的全部池 TVL（含被门槛/规则筛掉的）+ 已采到的 <$50 万长尾 − 假 TVL 池。
         长尾没采到时 tail_status = 'not_collected'，比值是下限，并在 warn 里说明，不猜。
         Raydium 改为「只算 DefiLlama 能定价的一侧」（priced_side）：每个池 TVL × priced_share。
         Aerodrome 按地址复查补回的池（rechecked）同理只计能定价一侧：TVL × cover_priced_share（两侧都有价 1，否则 0，缺省 0）。
  假 TVL（11-16 批，扩展 11-12 规则）：代币标签 ∈ {unlisted, unknown, error}（未收录或新币/待分类）且 周手续费 / TVL < 0.01%；
         若有能定价一侧数据且 priced_share ≥ 50%，不算假 TVL（真实但闲置的池）。
         周手续费：fee7d；Meteora 没有 7 天字段时用 fee24 × 7（estimated=True）。
         TODO(2026-11-18 之后)：Meteora 攒满 7 个连续日快照后改用快照内 fee24 的 7 日合计（collect.meteora_fee7d_from_history 已实现，按日期自动切换）。
  判定 = 3 日滚动均值 ≥ 80%（单日值照报）；不足 3 天写「数据不足」，不当通过。单日 < 50% 另外直接告警。
  豁免：Raydium 结构上以小池为主，$50 万门槛下约 30%，11-16 July 批准不卡 80% 线（照算照报，verdict = 豁免）。
"""
import datetime

COVER_MIN = 0.8
HARD_MIN = 0.5
ROLL_DAYS = 3
FAKE_FEE_TVL_7D = 0.0001
PRICED_SHARE_REAL = 0.5
FAKE_LABELS = ('unlisted', 'unknown', 'error')

# M2：原来按源名查的参数表（LLAMA_DEX / NOT_APPLICABLE / EXEMPT / PRICED_SIDE / TAIL_STATUS）已移到各模块的
# lp3/modules/<模块>/config.json 的 "coverage" 段。函数改为接收这段配置（spec），计算逻辑不变：
#   name、chain、include、exclude[[slug, chainTvls 键, 类别, 原因]…]、not_applicable（原因或 null）、exempt（原因或 null）、
#   priced_side（布尔）、tail_status（full / partial / not_collected）、fee24x7_estimate（布尔，Meteora 为 true）


def weekly_fee(row, spec=None):
    """返回 (周手续费, 是否估算)。spec.fee24x7_estimate 为真（Meteora）且没 fee7d 时用 fee24×7。"""
    if row.get('fee7d') is not None:
        return row['fee7d'], bool(row.get('fee7d_estimated'))
    if (spec or {}).get('fee24x7_estimate') and row.get('fee24') is not None:
        return row['fee24'] * 7, True
    return None, False


def is_fake_tvl(row, spec=None, priced_share=None):
    """返回 (是否假 TVL, 原因)。"""
    if row.get('meme_label') not in FAKE_LABELS:
        return False, ''
    fee, est = weekly_fee(row, spec)
    tvl = row.get('tvl') or 0
    if fee is None or not tvl:
        return False, '无周手续费，判不了'
    if fee / tvl >= FAKE_FEE_TVL_7D:
        return False, ''
    if priced_share is not None and priced_share >= PRICED_SHARE_REAL:
        return False, '低费但能定价一侧占 %.0f%%，按真实闲置池保留' % (priced_share * 100)
    return True, '%s 且周手续费/TVL %.6f%% < 0.01%%%s' % (
        {'unlisted': 'CoinGecko 未收录', 'unknown': '代币分类待更新（新币）', 'error': '代币分类读取失败'}[row['meme_label']],
        fee / tvl * 100, '（fee24×7 估算）' if est else '')


def series_point(proto, chain, ts):
    """从 /protocol/<slug> 的返回里取 chainTvls[chain].tvl 离 ts 最近的点；没有历史时退回 currentChainTvls。返回 (值, 点时刻)。"""
    s = (((proto or {}).get('chainTvls') or {}).get(chain) or {}).get('tvl') or []
    if s:
        best = min(s, key=lambda x: abs(x['date'] - ts))
        return best['totalLiquidityUSD'], best['date']
    v = ((proto or {}).get('currentChainTvls') or {}).get(chain)
    return (v, None) if v is not None else (None, None)


def denominator(spec, ts, fetch_protocol):
    cache, inc, exc, total, missing = {}, [], [], 0.0, []

    def proto(slug):
        if slug not in cache:
            cache[slug] = fetch_protocol(slug)
        return cache[slug]
    for slug in spec['include']:
        v, t = series_point(proto(slug), spec['chain'], ts)
        if v is None:
            missing.append(slug)
        inc.append({'slug': slug, 'chain': spec['chain'], 'tvl': v, 'point_ts': t})
        total += v or 0
    for slug, ck, cat, why in spec['exclude']:
        try:
            v, t = series_point(proto(slug), ck, ts)
        except Exception as e:  # 扣除项取不到不影响分母，只记下来
            v, t, why = None, None, why + '（取数失败：%s）' % str(e)[-60:]
        exc.append({'slug': slug, 'chain_key': ck, 'category': cat, 'reason': why, 'tvl': v, 'point_ts': t})
    return {'total': total, 'included': inc, 'excluded': exc, 'missing': missing}


def numerator(spec, rows, tail_tvl=None, priced=None):
    """priced: {pool: priced_share}；只对 spec.priced_side 为真的源用。返回明细。"""
    use_priced = bool(spec.get('priced_side')) and priced is not None
    raw = sum(r.get('tvl') or 0 for r in rows)
    fake, kept, priced_value, no_share = [], 0.0, 0.0, []
    rechecked_tvl, rechecked_counted = 0.0, 0.0
    for r in rows:
        if r.get('rechecked') and not use_priced:  # Aerodrome 按地址复查补回的池：只计能定价一侧（cover_priced_share，缺省 0）
            t = r.get('tvl') or 0
            c = t * (r.get('cover_priced_share') or 0)
            rechecked_tvl += t; rechecked_counted += c; kept += c
            continue
        share = priced.get(r['pool']) if use_priced else None
        bad, why = is_fake_tvl(r, spec, share)
        if use_priced:
            if share is None:
                no_share.append(r['pool'])
                share = 0.0 if r.get('meme_label') in FAKE_LABELS else 1.0  # 拿不到两侧数量：可疑标签按 0，其他按 1，并计数
            priced_value += (r.get('tvl') or 0) * share
        if bad:
            fake.append({'pool': r['pool'], 'name': r.get('name'), 'tvl': r.get('tvl'), 'reason': why})
        else:
            kept += r.get('tvl') or 0
    status = spec.get('tail_status') or 'not_collected'
    if status == 'not_collected' or tail_tvl is None:  # 配置说能落长尾但这次没给数，也按没采到算
        status, tail = 'not_collected', None
    else:
        tail = tail_tvl
    value = (priced_value if use_priced else kept) + (tail or 0)
    return {'value': value, 'raw_tvl': raw, 'fake_tvl': sum(x['tvl'] or 0 for x in fake), 'fake_pools': fake,
            'method': 'priced_side' if use_priced else 'tvl_minus_fake', 'priced_value': priced_value if use_priced else None,
            'n_no_priced_share': len(no_share), 'tail_status': status, 'tail_tvl': tail,
            'rechecked_tvl': rechecked_tvl, 'rechecked_counted': rechecked_counted}


def rolling(today_ratio, previous_ratios, days=ROLL_DAYS):
    """previous_ratios: 之前各日的单日比值（按日期从近到远，可含 None）。返回 (均值或 None, 用到的天数)。"""
    xs = [today_ratio] + [x for x in previous_ratios[:days - 1] if x is not None]
    if today_ratio is None or len(xs) < days:
        return None, len([x for x in xs if x is not None])
    return sum(xs) / len(xs), len(xs)


def evaluate(spec, date, ts, rows, fetch_protocol, load_previous=None, tail_tvl=None, priced=None):
    """返回写进 summary['llama_coverage'] 的字典（键名沿用，analyze_stage2 读 status / ratio）。spec 是模块配置的 coverage 段。"""
    src = spec.get('name')
    exempt = spec.get('exempt')
    if spec.get('not_applicable'):
        return {'status': '不适用', 'reason': spec['not_applicable']}
    if not spec.get('chain'):
        return {'status': '不适用', 'reason': '未配置'}
    try:
        den = denominator(spec, ts, fetch_protocol)
    except Exception as e:
        return {'status': '未能对比', 'warn': 'DefiLlama 子协议 TVL 取数失败，采全检查没做：%s' % str(e)[-80:]}
    if den['missing'] or not den['total']:
        return {'status': '未能对比', 'warn': 'DefiLlama 缺 %s 的 %s 链 TVL，采全检查没做' % ('、'.join(den['missing']) or '全部子协议', spec['chain']),
                'denominator': den}
    num = numerator(spec, rows, tail_tvl, priced)
    ratio = num['value'] / den['total']
    prev = []
    if load_previous:
        d = datetime.date.fromisoformat(date)
        for k in range(1, ROLL_DAYS):
            prev.append(load_previous(src, (d - datetime.timedelta(days=k)).isoformat()))
    mean, n = rolling(ratio, prev)
    warns = []
    if num['tail_status'] == 'not_collected':
        warns.append('长尾（<$50 万）采集时未落下，比值是下限')
    if exempt:
        verdict = '豁免'
    elif mean is None:
        verdict = '数据不足（%d/%d 天）' % (n, ROLL_DAYS)
    elif mean < COVER_MIN:
        verdict = '未达标'
        warns.append('采全比 3 日均值 %.0f%%（低于 %.0f%%；今天 %.0f%%）' % (mean * 100, COVER_MIN * 100, ratio * 100))
    else:
        verdict = '达标'
    if ratio < HARD_MIN and not exempt:
        warns.append('采全比单日只有 %.0f%%（低于 %.0f%%）' % (ratio * 100, HARD_MIN * 100))
    alert = [w for w in warns if not w.startswith('长尾')]
    return {'status': '已对比', 'definition': '2026-11-16', 'chain': spec['chain'],
            'llama_tvl': den['total'], 'ratio': round(ratio, 4), 'ratio_3d': round(mean, 4) if mean is not None else None,
            'days_in_mean': n, 'verdict': verdict, 'exempt': exempt,
            'numerator': {k: v for k, v in num.items() if k != 'fake_pools'}, 'fake_pools': num['fake_pools'],
            'denominator': den, 'notes': warns, 'warn': '；'.join(alert) or None}
