"""1.1.0 开关（默认关）打开后的逻辑：Raydium LP 实收、Robinhood V3 协议抽成、Curve 链上费率。离线。"""
import json
import subprocess
import unittest
from unittest import mock

from lp3.modules.curve import module as curve
from lp3.modules.raydium import module as raydium
from lp3.modules.rh import module as rh


class RaydiumLpShareTest(unittest.TestCase):
    def test_types(self):
        clmm = {'type': 'Concentrated', 'feeRate': 0.0004, 'config': {'protocolFeeRate': 120000, 'fundFeeRate': 40000}}
        self.assertAlmostEqual(raydium.lp_share(clmm)[0], 0.84)
        cpmm = {'type': 'Standard', 'feeRate': 0.01, 'config': {'protocolFeeRate': 120000, 'fundFeeRate': 40000, 'tradeFeeRate': 300, 'creatorFeeRate': 9700}}
        self.assertAlmostEqual(raydium.lp_share(cpmm)[0], 0.0003 * 0.84 / 0.01)
        amm = {'type': 'Standard', 'feeRate': 0.0025, 'config': None, 'programId': raydium.AMM_V4_PROGRAM}
        self.assertAlmostEqual(raydium.lp_share(amm)[0], 0.88)
        self.assertIsNone(raydium.lp_share({'type': 'Standard', 'feeRate': 0.003, 'programId': 'X'})[0])


def curl_result(payload_results):
    def run(args, *a, **kw):
        body = json.loads(args[args.index('-d') + 1])
        return subprocess.CompletedProcess(args, 0, json.dumps([{'id': x['id'], 'result': payload_results(x)} for x in body]), '')
    return run


class RhV3Test(unittest.TestCase):
    def test_deduct_and_unreadable(self):
        slot0 = lambda fp: '0x' + '0' * 64 * 5 + '%064x' % fp + '0' * 64
        rows = [{'protocol': 'uniswap-v3-robinhood', 'pool': '0xa', 'fee_pct': 0.05, 'notes': ''},
                {'protocol': 'uniswap-v3-robinhood', 'pool': '0xb', 'fee_pct': 0.3, 'notes': ''},
                {'protocol': 'uniswap-v4-robinhood', 'pool': '0xc', 'fee_pct': 0.05, 'notes': ''}]
        res = lambda x: slot0(0x44) if x['params'][0]['to'] == '0xa' else '0x'
        with mock.patch('subprocess.run', curl_result(res)):
            meta = rh.apply_v3_protocol_fee(rows, {'rpcs': ['https://rpc.test']})
        self.assertEqual(meta['v3_protocol_fee']['ok'], 1)
        self.assertAlmostEqual(rows[0]['lp_share'], 0.75)
        self.assertTrue(rows[1]['_apy_unreadable'])
        self.assertNotIn('lp_share', rows[2])  # V4 不扣


class CurveFeeTest(unittest.TestCase):
    def test_fee_rates(self):
        res = lambda x: {'0xa': '0x%064x' % 1500000, '0xb': '0x' + 'f' * 64, '0xc': '0x'}[x['params'][0]['to']]
        with mock.patch('subprocess.run', curl_result(res)):
            out = curve.fee_rates(['0xa', '0xb', '0xc'], 'https://rpc.test')
        self.assertEqual(out, {'0xa': 0.015})


if __name__ == '__main__':
    unittest.main()
