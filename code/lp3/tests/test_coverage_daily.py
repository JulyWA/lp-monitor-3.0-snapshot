"""覆盖率每天重算：公式与原脚本一致的小样本、历史告警。离线。"""
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from lp3.refresh import coverage_daily as cd


def proto(name, parent, chain, fee=None, vol=None, tvl=None):
    p = {'name': name, 'parentProtocol': parent, 'category': 'Dexs'}
    if fee is not None:
        p['breakdown30d'] = {chain: {'x': fee * 30}}
    if vol is not None:
        p['breakdown30d'] = {chain: {'x': vol * 30}}
    if tvl is not None:
        p['chainTvls'] = {chain: tvl, chain + '-staking': 999}
    return p


class CoverageDailyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        F = {'protocols': [proto('Uniswap V3', 'parent#uniswap', 'Ethereum', fee=30), proto('Orca', 'parent#orca', 'Solana', fee=10),
                           proto('Pump', 'parent#pump', 'Solana', fee=60)]}
        V = {'protocols': [proto('Uniswap V3', 'parent#uniswap', 'Ethereum', vol=300), proto('Pump', 'parent#pump', 'Solana', vol=700)]}
        P = [proto('Uniswap V3', 'parent#uniswap', 'Ethereum', tvl=50), proto('Pump', 'parent#pump', 'Solana', tvl=50)]
        for n, d in (('fees.json', F), ('dexs.json', V), ('protocols.json', P)):
            with open(os.path.join(self.tmp, n), 'w') as fh:
                json.dump(d, fh)
        self.split = {b[1]: (None, 't') for b in cd.SCOPE}

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_levels(self):
        with mock.patch.object(cd, 'pass_split', return_value=self.split):
            res = cd.compute(self.tmp, '2026-11-18')
        lv = {x['level']: round(x['fee_pct'], 1) for x in res['levels']}
        self.assertEqual(lv, {'现在': 30.0, '第一步': 30.0, '第二步': 40.0})
        self.assertEqual(res['outside_top5'][0]['protocol'], 'pump')
        self.assertEqual(round(res['market']['tvl']), 100)  # staking 不计

    def test_history_alert(self):
        out = os.path.join(self.tmp, 'out')
        os.makedirs(out)
        for d in ('2026-11-16', '2026-11-17'):
            with open(os.path.join(out, 'scope-%s.json' % d), 'w') as fh:
                json.dump({'levels': [{'level': '现在', 'fee_pct': 20.0}]}, fh)
        with mock.patch.object(cd, 'OUTD', out):
            hist = cd.history('2026-11-18')
        self.assertEqual(len(hist), 2)


if __name__ == '__main__':
    unittest.main()
