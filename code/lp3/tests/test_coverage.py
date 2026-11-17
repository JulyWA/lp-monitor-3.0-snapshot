#!/usr/bin/env python3
"""11-16 统一采全比口径的单元测试。全部离线：DefiLlama 返回、前几天比值、价格都用本地假数据。"""
import unittest

import json
import os

from lp3.common import coverage  # M2：参数表已移到各模块 config.json 的 coverage 段，这里按模块名读出来传给函数

_MOD = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'modules')
S = {n: json.load(open(os.path.join(_MOD, n, 'config.json')))['coverage'] for n in ('curve', 'aero', 'rh', 'orca', 'raydium', 'meteora')}

DAY = 86400
T0 = 1794787200  # 2026-11-16 00:00 UTC


def proto(chain_values):
    """chain_values: {chainKey: [(ts, value), ...]}"""
    return {'chainTvls': {c: {'tvl': [{'date': t, 'totalLiquidityUSD': v} for t, v in pts]} for c, pts in chain_values.items()}}


def row(pool, tvl, label=None, fee7d=None, fee24=None):
    r = {'pool': pool, 'name': pool, 'tvl': tvl, 'fee7d': fee7d, 'fee24': fee24}
    if label:
        r['meme_label'] = label
    return r


class DenominatorTest(unittest.TestCase):
    def setUp(self):
        self.db = {
            'meteora-dlmm': proto({'Solana': [(T0 - DAY, 130e6), (T0, 126e6)]}),
            'meteora-damm-v2': proto({'Solana': [(T0, 17e6)]}),
            'meteora-damm-v1': proto({'Solana': [(T0, 37e6)]}),
            'meteora-vaults': proto({'Solana': [(T0, 36e6)]}),
            'meteora-dynamic-bonding-curve': {},
        }

    def test_meteora_only_dex_subprotocols_and_excluded_listed(self):
        d = coverage.denominator(S['meteora'], T0 + 600, self.db.get)
        self.assertAlmostEqual(d['total'], 143e6)
        ex = {(e['slug'], e['category']): e['tvl'] for e in d['excluded']}
        self.assertEqual(ex[('meteora-vaults', 'Yield Aggregator')], 36e6)
        self.assertEqual(ex[('meteora-damm-v1', 'Dexs·无接口')], 37e6)
        self.assertIsNone(ex[('meteora-dynamic-bonding-curve', 'Launchpad')])

    def test_nearest_point_is_used(self):
        v, t = coverage.series_point(self.db['meteora-dlmm'], 'Solana', T0 - DAY + 3600)
        self.assertEqual((v, t), (130e6, T0 - DAY))

    def test_falls_back_to_current_chain_tvls(self):
        v, t = coverage.series_point({'currentChainTvls': {'Solana': 5.0}}, 'Solana', T0)
        self.assertEqual((v, t), (5.0, None))

    def test_missing_included_subprotocol_is_not_a_pass(self):
        db = dict(self.db); db['meteora-damm-v2'] = {}
        out = coverage.evaluate(S['meteora'], '2026-11-16', T0, [row('a', 1e6)], db.get)
        self.assertEqual(out['status'], '未能对比')
        self.assertIn('meteora-damm-v2', out['warn'])


class FakeTvlTest(unittest.TestCase):
    def test_unlisted_and_unknown_low_fee_are_fake(self):
        self.assertTrue(coverage.is_fake_tvl(row('a', 1e7, 'unlisted', fee7d=1), S['raydium'])[0])
        self.assertTrue(coverage.is_fake_tvl(row('b', 1e7, 'unknown', fee7d=1), S['raydium'])[0])
        self.assertTrue(coverage.is_fake_tvl(row('c', 1e7, 'error', fee7d=1), S['raydium'])[0])

    def test_real_labels_or_normal_fee_are_kept(self):
        self.assertFalse(coverage.is_fake_tvl(row('a', 1e7, 'ok', fee7d=1), S['raydium'])[0])
        self.assertFalse(coverage.is_fake_tvl(row('a', 1e7, 'meme', fee7d=1), S['raydium'])[0])
        self.assertFalse(coverage.is_fake_tvl(row('a', 1e7, 'unlisted', fee7d=5000), S['raydium'])[0])
        self.assertFalse(coverage.is_fake_tvl(row('a', 1e7), S['curve'])[0])  # Curve/Aero 没有标签

    def test_priced_side_guard_keeps_real_idle_pool(self):
        bad, why = coverage.is_fake_tvl(row('a', 1e7, 'unlisted', fee7d=1), S['raydium'], priced_share=0.9)
        self.assertFalse(bad); self.assertIn('能定价', why)
        self.assertTrue(coverage.is_fake_tvl(row('a', 1e7, 'unlisted', fee7d=1), S['raydium'], priced_share=0.01)[0])

    def test_meteora_uses_fee24_times_7(self):
        fee, est = coverage.weekly_fee(row('a', 1e7, 'unlisted', fee24=10), S['meteora'])
        self.assertEqual((fee, est), (70, True))
        self.assertEqual(coverage.weekly_fee(row('a', 1e7, fee24=10), S['orca']), (None, False))
        bad, why = coverage.is_fake_tvl(row('a', 1e7, 'unlisted', fee24=10), S['meteora'])
        self.assertTrue(bad); self.assertIn('fee24×7', why)


class NumeratorTest(unittest.TestCase):
    def test_minus_fake_and_tail_status(self):
        rows = [row('a', 10e6, 'ok', fee7d=1e4), row('b', 5e6, 'unlisted', fee7d=1)]
        n = coverage.numerator(S['orca'], rows)
        self.assertEqual(n['value'], 10e6); self.assertEqual(n['fake_tvl'], 5e6); self.assertEqual(n['tail_status'], 'not_collected')
        n = coverage.numerator(S['curve'], [row('c', 10e6)], tail_tvl=2e6)
        self.assertEqual((n['value'], n['tail_status']), (12e6, 'full'))
        n = coverage.numerator(S['curve'], [row('c', 10e6)])  # 该落长尾但没给数 → 当没采到
        self.assertEqual(n['tail_status'], 'not_collected')
        n = coverage.numerator(S['orca'], [row('c', 10e6)], tail_tvl=2e6)  # 配置为没采长尾时忽略传入值
        self.assertEqual(n['value'], 10e6)

    def test_raydium_priced_side(self):
        rows = [row('real', 10e6, 'ok', fee7d=1e4), row('fake', 50e6, 'unknown', fee7d=1), row('nodata', 4e6, 'unlisted', fee7d=1)]
        n = coverage.numerator(S['raydium'], rows, priced={'real': 1.0, 'fake': 0.001})
        self.assertAlmostEqual(n['value'], 10e6 + 50e3)  # nodata 按 0
        self.assertEqual(n['method'], 'priced_side'); self.assertEqual(n['n_no_priced_share'], 1)


class RollingAndVerdictTest(unittest.TestCase):
    def setUp(self):
        self.db = {'orca-dex': proto({'Solana': [(T0, 100e6)]}), 'orca-wavebreak': {},
                   'raydium-amm': proto({'Solana': [(T0, 100e6)]}), 'launchlab': {},
                   'curve-dex': proto({'Ethereum': [(T0, 100e6)]}), 'curve-llamalend': {}, 'curve-llamalend-v2': {}, 'crvusd': {}}

    def test_rolling_mean_needs_three_days(self):
        self.assertEqual(coverage.rolling(0.7, [0.9, None]), (None, 2))
        m, n = coverage.rolling(0.7, [0.9, 0.86])
        self.assertAlmostEqual(m, 0.82); self.assertEqual(n, 3)

    def test_single_low_day_passes_when_3d_mean_ok(self):
        prev = {'2026-11-15': 0.9, '2026-11-14': 0.9}
        out = coverage.evaluate(S['orca'], '2026-11-16', T0, [row('a', 78e6, 'ok')], self.db.get,
                                load_previous=lambda s, d: prev.get(d))
        self.assertEqual(out['verdict'], '达标'); self.assertIsNone(out['warn'])
        self.assertIn('长尾', out['notes'][0])

    def test_stage1_alerts_below_80_not_50(self):
        prev = {'2026-11-15': 0.79, '2026-11-14': 0.79}
        out = coverage.evaluate(S['curve'], '2026-11-16', T0, [row('a', 70e6)], self.db.get,
                                load_previous=lambda s, d: prev.get(d), tail_tvl=0)
        self.assertEqual(out['verdict'], '未达标'); self.assertIn('3 日均值', out['warn'])

    def test_insufficient_days(self):
        out = coverage.evaluate(S['orca'], '2026-11-16', T0, [row('a', 90e6, 'ok')], self.db.get, load_previous=lambda s, d: None)
        self.assertTrue(out['verdict'].startswith('数据不足'))

    def test_raydium_exempt(self):
        prev = {'2026-11-15': 0.3, '2026-11-14': 0.3}
        out = coverage.evaluate(S['raydium'], '2026-11-16', T0, [row('a', 30e6, 'ok')], self.db.get,
                                load_previous=lambda s, d: prev.get(d), priced={'a': 1.0})
        self.assertEqual(out['verdict'], '豁免'); self.assertIsNone(out['warn']); self.assertAlmostEqual(out['ratio'], 0.3)

    def test_rh_not_applicable(self):
        self.assertEqual(coverage.evaluate(S['rh'], '2026-11-16', T0, [], self.db.get)['status'], '不适用')


class RecheckedPricedSideTest(unittest.TestCase):
    def test_rechecked_pools_count_only_priced_share(self):
        rows = [row('a', 100e6), dict(row('zbtc', 62e6), rechecked=True, cover_priced_share=0.0),
                dict(row('ok', 3e6), rechecked=True, cover_priced_share=1.0), dict(row('noinfo', 5e6), rechecked=True)]
        n = coverage.numerator(S['aero'], rows, tail_tvl=None)
        self.assertEqual(n['value'], 103e6)
        self.assertEqual((n['rechecked_tvl'], n['rechecked_counted']), (70e6, 3e6))


if __name__ == '__main__':
    unittest.main()
