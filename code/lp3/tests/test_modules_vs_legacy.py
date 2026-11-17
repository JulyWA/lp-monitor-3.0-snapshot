"""差分测试：同一份构造的上游数据分别喂给 mvp3/collect.py 的源函数和 lp3 新模块，rows 与 meta 必须完全相同。
覆盖 11-17 实录回放没走到的分支：Meteora 7 天历史（11-19 起）、Curve getPools 失败退回、admin_fee 读不到、
Aero 复查与 GeckoTerminal 全部失败、Robinhood 动态费率与 meme 分流。另含真实模块的故障注入。全部离线。"""
import copy
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import urllib.error
from unittest import mock

from lp3 import run_module
from lp3.common import defillama

ROOT = run_module.ROOT
sys.path.insert(0, os.path.join(ROOT, 'mvp3'))
import collect  # noqa: E402

NOW = 1795400000  # 2026-11-23 前后，具体值无所谓
DAY = 86400


class Resp(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


class FakeNet:
    """按 URL 子串路由的假网络。value 可以是 JSON 对象、可调用（url -> 对象）或 HTTP 状态码（int，抛 HTTPError）。"""

    def __init__(self, routes, curl=None):
        self.routes, self.curl, self.calls = routes, curl, []

    def urlopen(self, req, timeout=None):
        url = req.full_url if hasattr(req, 'full_url') else req
        self.calls.append(url)
        for k, v in self.routes:
            if k in url:
                v = v(url) if callable(v) else v
                if isinstance(v, int):
                    raise urllib.error.HTTPError(url, v, 'err', {}, io.BytesIO(b''))
                return Resp(json.dumps(v).encode())
        raise urllib.error.HTTPError(url, 404, 'no route', {}, io.BytesIO(b''))

    def run(self, args, *a, **kw):
        out = self.curl(args) if self.curl else ''
        if not kw.get('text'):
            out = out.encode()
        return subprocess.CompletedProcess(args, 0, out, b'' if not kw.get('text') else '')

    def __enter__(self):
        self._p = [mock.patch('urllib.request.urlopen', self.urlopen), mock.patch('subprocess.run', self.run), mock.patch('time.sleep', lambda s: None)]
        for p in self._p:
            p.start()
        return self

    def __exit__(self, *a):
        for p in self._p:
            p.stop()


def llama_curl(args):
    """DefiLlama 走 curl：/protocols 全表给空列表，/protocol/<slug> 给空对象。"""
    url = [a for a in args if isinstance(a, str) and a.startswith('http')][0]
    return '[]' if url.endswith('/protocols') else '{}'


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.legacy_out = os.path.join(self.tmp, 'legacy')
        self.new_root = os.path.join(self.tmp, 'new')
        os.makedirs(self.legacy_out)
        self._old = (collect.OUT, collect.RUN_DATE)
        collect.OUT = self.legacy_out
        defillama.reset_cache()

    def tearDown(self):
        collect.OUT, collect.RUN_DATE = self._old
        shutil.rmtree(self.tmp)

    def history(self, name, date, rows):
        """同一份历史文件同时放进旧沙箱（平铺）和新模块目录。"""
        d = os.path.join(self.new_root, name)
        os.makedirs(d, exist_ok=True)
        doc = {'summary': {}, 'rows': rows}
        for p in (os.path.join(self.legacy_out, '%s-%s.json' % (name, date)), os.path.join(d, '%s-%s.json' % (name, date))):
            with open(p, 'w') as fh:
                json.dump(doc, fh)

    def both(self, name, date, net, labels=None):
        """返回 ((旧 rows, 旧 meta), (新 rows, 新 meta))；任一侧抛异常就把异常类型当结果。"""
        stocks = collect.stock_index()
        collect.RUN_DATE = date

        def legacy():
            with mock.patch.object(collect, 'sol_labels', lambda: copy.deepcopy(labels or {})):
                return collect.SOURCES[name](stocks, NOW)

        def new():
            mod, mdir, _ = run_module.load_module(name)
            ctx = run_module.Context(name, date, NOW, os.path.join(self.new_root, name), mdir)
            ctx._stocks, ctx._labels = stocks, copy.deepcopy(labels or {})
            return mod.run(ctx)
        out = []
        for fn in (legacy, new):
            defillama.reset_cache()
            with net:
                try:
                    out.append(fn())
                except Exception as e:
                    out.append(('raised', type(e).__name__, str(e)[:200]))
        return out

    def assertSame(self, a, b):
        self.assertEqual(json.dumps(a, sort_keys=True, default=str), json.dumps(b, sort_keys=True, default=str))


# ---------- 构造上游数据 ----------
def met_pool(i, tvl, fee24, sym='ABC', addr=None, created_ms=None, black=False):
    return {'address': 'MET%d' % i, 'tvl': tvl, 'fees': {'24h': fee24}, 'protocol_fees': {'24h': fee24 * 0.05 if fee24 else 0},
            'created_at': created_ms if created_ms is not None else (NOW - 40 * DAY) * 1000, 'name': '%s-USDC' % sym,
            'pool_config': {'base_fee_pct': 0.25}, 'volume': {'24h': (fee24 or 0) * 400},
            'token_x': {'symbol': sym, 'address': addr or 'ADDR%d' % i, 'is_verified': True},
            'token_y': {'symbol': 'USDC', 'address': 'USDCmint', 'is_verified': True}, 'is_blacklisted': black}


LABELS = {'ADDR1': {'id': 'abc-token', 'cats': ['DeFi']}, 'ADDR2': {'id': None}, 'ADDR3': {'id': 'dog', 'cats': ['Meme']},
          'ADDR4': {'id': 'ERROR'}, 'ADDR6': {'id': None}}


class MeteoraTest(Base):
    def meteora_net(self):
        dlmm = [met_pool(1, 9e6, 5000), met_pool(2, 5e6, 1.0), met_pool(3, 3e6, 900, 'DOG'), met_pool(4, 2e6, 100),
                met_pool(5, 1e6, 50, created_ms=(NOW - 2 * DAY) * 1000), met_pool(9, 4e5, 1)]
        damm = [met_pool(6, 8e5, 300), met_pool(7, 7e5, 20, black=True)]
        return FakeNet([('dlmm.datapi', {'data': dlmm, 'pages': 1}), ('damm-v2.datapi', {'data': damm, 'pages': 1})])

    def test_history_7d_switches_on_from_1119_when_7_days_present(self):
        for k in range(1, 8):
            day = '2026-11-%02d' % (19 - k)
            self.history('meteora', day, [{'pool': 'MET1', 'fee24': 4000 + k}, {'pool': 'MET2', 'fee24': 0.5}, {'pool': 'MET6', 'fee24': None if k == 3 else 10}])
        a, b = self.both('meteora', '2026-11-19', self.meteora_net(), LABELS)
        self.assertNotEqual(a[0], 'raised')
        self.assertSame(a, b)
        met1 = [r for r in b[0] if r['pool'] == 'MET1'][0]
        self.assertEqual(met1['fee7d'], sum(4000 + k for k in range(1, 8)))
        self.assertIsNone([r for r in b[0] if r['pool'] == 'MET6'][0]['fee7d'])  # 有一天缺 fee24，不算实际 7 天

    def test_history_incomplete_falls_back_to_estimate(self):
        for k in range(1, 7):  # 只有 6 天
            self.history('meteora', '2026-11-%02d' % (19 - k), [{'pool': 'MET2', 'fee24': 0.5}])
        a, b = self.both('meteora', '2026-11-19', self.meteora_net(), LABELS)
        self.assertSame(a, b)
        self.assertTrue(all(r['fee7d'] is None for r in b[0]))
        self.assertTrue(any(r.get('low_fee_unlisted') for r in b[0]))

    def test_before_1119_no_history(self):
        a, b = self.both('meteora', '2026-11-18', self.meteora_net(), LABELS)
        self.assertSame(a, b)

    def test_unsorted_upstream_raises_same(self):
        net = FakeNet([('dlmm.datapi', {'data': [met_pool(1, 1e6, 1), met_pool(2, 9e6, 1)], 'pages': 1}), ('damm-v2.datapi', {'data': [], 'pages': 1})])
        a, b = self.both('meteora', '2026-11-18', net, LABELS)
        self.assertEqual(a[:2], ('raised', 'SourceError'))
        self.assertEqual(a, b)


class CurveTest(Base):
    def prices(self, n=4):
        return {'cached_at': NOW - 600, 'count': n, 'data': [
            {'address': '0xPOOL%d' % i, 'name': ['3pool', 'Yield Basis WBTC', 'tricrypto', 'tiny'][i], 'tvl_usd': [5e7, 2e7, 9e6, 3e5][i],
             'trading_volume_24h': 1e6 * (i + 1), 'trading_fee_24h': 300.0 * (i + 1), 'creation_ts': NOW - 400 * DAY,
             'coins': [{'symbol': 'USDC', 'address': '0xa0b8'}, {'symbol': 'DAI', 'address': '0x6b17'}]} for i in range(n)]}

    def volume(self, url):
        return {'data': [{'timestamp': NOW - (9 - k) * DAY, 'volume': 1e6 + k, 'fees': 300.0 + k} for k in range(9)]}

    def curl(self, args):
        body = json.loads(args[args.index('-d') + 1])
        return json.dumps([{'id': x['id'], 'result': '0x%064x' % (5 * 10**9)} if x['id'] != 1 else {'id': 1, 'result': '0x'} for x in body])

    def test_front_failure_falls_back_and_admin_fee_default(self):
        net = FakeNet([('prices.curve.finance/v1/chains', self.prices()), ('getPools', 500), ('volume/usd', self.volume)], curl=self.curl)
        a, b = self.both('curve', '2026-11-18', net)
        self.assertSame(a, b)
        self.assertIn('front_error', b[1])
        self.assertTrue(all(r['tvl_source'] == 'prices_fallback' for r in b[0]))
        yb = [r for r in b[0] if r['name'].startswith('Yield Basis')][0]
        self.assertEqual(yb['lp_share'], 0.5)  # admin_fee 读不到按默认
        self.assertIn('apy_out', yb)

    def test_front_ok_with_broken_and_zero(self):
        front = {'generatedTimeMs': (NOW - 60) * 1000, 'data': {'poolData': [
            {'address': '0xpool0', 'usdTotal': 4.8e7}, {'address': '0xpool1', 'usdTotal': 0}, {'address': '0xpool2', 'usdTotal': 1e7, 'isBroken': True}]}}
        net = FakeNet([('prices.curve.finance/v1/chains', self.prices()), ('getPools', front), ('volume/usd', self.volume)], curl=self.curl)
        a, b = self.both('curve', '2026-11-18', net)
        self.assertSame(a, b)
        self.assertEqual(len(b[1]['excluded_front']), 2)

    def test_stale_prices_raise_same(self):
        p = self.prices()
        p['cached_at'] = NOW - 7 * 3600
        a, b = self.both('curve', '2026-11-18', FakeNet([('prices.curve.finance/v1/chains', p)]))
        self.assertEqual(a[:2], ('raised', 'SourceError'))
        self.assertEqual(a, b)


def gt_pool(addr, name, dex, tvl, vol, created='2026-09-01T00:00:00Z', base='0xbase', quote='0xquote'):
    return {'attributes': {'address': addr, 'name': name, 'reserve_in_usd': str(tvl), 'volume_usd': {'h24': str(vol)}, 'pool_created_at': created},
            'relationships': {'dex': {'data': {'id': dex}}, 'base_token': {'data': {'id': 'base_' + base}}, 'quote_token': {'data': {'id': 'base_' + quote}}}}


class AeroRhTest(Base):
    def test_aero_recheck_dormant_and_partial_errors(self):
        page = [gt_pool('0xA1', 'WETH / USDC 0.04%', 'aero-slipstream-base', 3e6, 2e6),
                gt_pool('0xA2', 'O / USDC 0.3%', 'aerodrome-slipstream', 1.7e6, 100),
                gt_pool('0xA3', 'NEW / WETH 1%', 'aero-volatile-base', 9e5, 5e4, created='2026-11-20T00:00:00Z'),
                gt_pool('0xA4', 'X / Y', 'aerodrome-base', 1e5, 10)]
        self.history('aero', '2026-11-22', [{'pool': '0xa9', 'tvl': 2e6}, {'pool': '0xa1', 'tvl': 3e6}, {'pool': '0xa8', 'tvl': 9e5}])

        def route_dex(url):
            if 'aerodrome-slipstream-2' in url:
                return 500  # 一个交易所编号失败：只记错误
            return {'data': page if 'page=1' in url and 'aerodrome-slipstream/' in url else []}
        multi = {'data': [gt_pool('0xA9', 'BIG / USDC', 'aerodrome-slipstream', 1.5e6, 0), gt_pool('0xA8', 'S / USDC', 'aero-slipstream-base', 2e5, 0)]}
        prices = {'coins': {'base:0xbase': {'price': 1}}}
        net = FakeNet([('pools/multi', multi), ('networks/base/dexes/', route_dex), ('coins.llama.fi', prices)])
        a, b = self.both('aero', '2026-11-23', net)
        self.assertNotEqual(a[0], 'raised')
        self.assertSame(a, b)
        self.assertEqual(b[1]['recheck']['n_added'], 1)
        self.assertTrue(b[1]['errors'])
        self.assertEqual(b[1]['n_dormant_legacy'], 2)  # O/USDC 和复查补回的 BIG/USDC 都是旧版、几乎零成交

    def test_aero_all_fail_raises_same(self):
        a, b = self.both('aero', '2026-11-23', FakeNet([('geckoterminal', 503)]))
        self.assertEqual(a[:2], ('raised', 'SourceError'))
        self.assertEqual(a, b)

    def test_rh_dynamic_fee_major_and_meme(self):
        stock = next(iter(collect.stock_index()))
        page = [gt_pool('0xR1', 'WETH / USDG 0.067%', 'aero-slipstream-robinhood', 1.4e6, 9e5),
                gt_pool('0xR2', 'WETH / USDG 0.01%', 'ramses-v3-robinhood', 5.5e5, 4e5),
                gt_pool('0xR3', 'WETH / USDC 0.05%', 'uniswap-v3-robinhood', 2e6, 1e6),
                gt_pool('0xR4', 'PEPE / WETH 1%', 'uniswap-v3-robinhood', 3e4, 9e5),
                gt_pool('0xR5', 'TSLA / USDG 0.3%', 'uniswap-v3-robinhood', 9e6, 1e5, base=stock),
                gt_pool('0xR6', 'WETH / USDT', 'uniswap-v4-robinhood', 7e5, 1e5)]
        net = FakeNet([('networks/robinhood/pools', lambda u: {'data': page if 'page=1&' in u else []})])
        a, b = self.both('rh', '2026-11-23', net)
        self.assertSame(a, b)
        self.assertEqual([r['pool'] for r in b[0]], ['0xr1', '0xr2', '0xr3', '0xr6'])
        self.assertEqual(b[1]['n_dynamic_fee'], 2)
        self.assertEqual([x['pool'] for x in b[1]['archive']], ['0xr4'])


class OrcaRaydiumTest(Base):
    def test_orca_pages(self):
        def pool(i, tvl, sym='ABC'):
            return {'address': 'ORCA%d' % i, 'tvlUsdc': str(tvl), 'feeRate': 3000, 'protocolFeeRate': 1300,
                    'stats': {'24h': {'volume': 1e6, 'fees': 300}, '7d': {'volume': 7e6, 'fees': 2100}},
                    'tokenA': {'symbol': sym, 'address': 'ADDR%d' % i}, 'tokenB': {'symbol': 'SOL', 'address': 'So111'}, 'updatedAt': 'x'}

        def route(url):
            if 'next=CUR2' in url:
                return {'data': [pool(3, 6e5), pool(4, 4e5)], 'meta': {'cursor': {'next': 'CUR3'}}}
            return {'data': [pool(1, 9e6), pool(2, 2e6, 'DOG')], 'meta': {'cursor': {'next': 'CUR2'}}}
        a, b = self.both('orca', '2026-11-23', FakeNet([('api.orca.so', route)]), LABELS)
        self.assertSame(a, b)
        self.assertEqual(b[1]['pages'], 2)

    def test_raydium_priced_side_error_is_partial(self):
        mod, mdir, _ = run_module.load_module('raydium')
        ctx = run_module.Context('raydium', '2026-11-23', NOW, os.path.join(self.new_root, 'raydium'), mdir)
        meta = {}
        rows = [{'pool': 'R1', 'tvl': 1e6, 'tokens': [['A', 'm1'], ['B', 'm2']], 'amounts': [1, 2], 'meme_label': 'ok'}]
        with FakeNet([('coins.llama.fi', 500)], curl=llama_curl):
            cov = mod.coverage(ctx, rows, meta)
        self.assertIn('priced_side_error', meta)
        self.assertEqual(mod.status(meta), 'partial')
        self.assertEqual(cov['status'], '未能对比')


class RealModuleFaultInjectionTest(Base):
    def test_orca_schema_change_fails_only_orca(self):
        """Orca 改了字段（tokenA 没了）→ KeyError。mvp3 主循环只拦 SourceError，会连带后面的源；lp3 只让 orca 失败。"""
        bad = {'data': [{'address': 'O1', 'tvlUsdc': '9e6', 'stats': {}}], 'meta': {'cursor': {}}}
        ray = {'data': {'data': [], 'hasNextPage': False}}
        net = FakeNet([('api.orca.so', bad), ('api-v3.raydium.io', ray), ('coins.llama.fi', {'coins': {}})], curl=llama_curl)
        with net:
            s1, p1 = run_module.run_one('orca', '2026-11-23', now=NOW, out_root=self.new_root, quiet=True)
            s2, p2 = run_module.run_one('raydium', '2026-11-23', now=NOW, out_root=self.new_root, quiet=True)
        self.assertEqual((s1, s2), ('failed', 'ok'))
        with open(p1) as fh:
            self.assertEqual(json.load(fh)['module']['error_type'], 'KeyError')


if __name__ == '__main__':
    unittest.main()
