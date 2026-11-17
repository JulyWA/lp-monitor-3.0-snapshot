"""common/http、contract、quality、refdata 的单元测试。全部离线。"""
import io
import json
import os
import unittest
import urllib.error
from unittest import mock

from lp3.common import contract, http, quality, refdata


class Resp(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def seq(*items):
    it = iter(items)

    def fake(req, timeout=None):
        x = next(it)
        if isinstance(x, BaseException):
            raise x
        return Resp(json.dumps(x).encode())
    return fake


def herr(code):
    return urllib.error.HTTPError('https://x.test/a', code, 'err', {}, io.BytesIO(b''))


class HttpTest(unittest.TestCase):
    def setUp(self):
        http.reset_stats()
        self.sleeps = []
        p = mock.patch('time.sleep', side_effect=self.sleeps.append)
        p.start()
        self.addCleanup(p.stop)

    def test_retry_transient_then_ok(self):
        with mock.patch('urllib.request.urlopen', seq(TimeoutError('t'), {'ok': 1})):
            self.assertEqual(http.get('https://x.test/a'), {'ok': 1})
        s = http.stats()['x.test']
        self.assertEqual((s['requests'], s['ok'], s['retries'], s['exceptions']), (2, 1, 1, 1))

    def test_404_no_retry(self):
        with mock.patch('urllib.request.urlopen', seq(herr(404), {'never': 1})):
            with self.assertRaises(http.SourceError):
                http.get('https://x.test/a')
        self.assertEqual(http.stats()['x.test']['requests'], 1)
        self.assertEqual(http.stats()['x.test']['http_errors'], {'404': 1})

    def test_429_backoff_is_4x(self):
        with mock.patch('urllib.request.urlopen', seq(herr(429), {'ok': 1})):
            http.get('https://x.test/a', wait=4)
        self.assertEqual(self.sleeps, [16])

    def test_gives_up_after_tries(self):
        with mock.patch('urllib.request.urlopen', seq(*[herr(500)] * 4)):
            with self.assertRaises(http.SourceError):
                http.get('https://x.test/a', tries=4)
        self.assertEqual(http.stats()['x.test']['http_errors'], {'500': 4})

    def test_get_curl_404_no_retry(self):
        cp = mock.Mock(returncode=22, stdout=b'', stderr=b'curl: (22) The requested URL returned error: 404')
        with mock.patch('subprocess.run', return_value=cp) as run:
            with self.assertRaises(http.SourceError):
                http.get_curl('https://y.test/b')
        self.assertEqual(run.call_count, 1)


class ContractTest(unittest.TestCase):
    def good(self):
        row = {k: '' for k in contract.ROW_REQUIRED}
        row.update(tvl=1.0, tokens=[])
        summ = {k: None for k in contract.SUMMARY_REQUIRED}
        summ.update(date='2026-11-17', n_ge_500k=1)
        mod = contract.module_block('orca', '1.0.0', 'abc', 'ok', 's', 'f', {})
        return {'summary': summ, 'rows': [row], 'module': mod}

    def test_valid(self):
        self.assertEqual(contract.validate(self.good(), 'orca', '2026-11-17'), [])

    def test_detects_problems(self):
        d = self.good()
        d['module']['schema_version'] = 'old'
        d['rows'][0].pop('why_out')
        d['summary']['n_ge_500k'] = 5
        errs = contract.validate(d, 'raydium', '2026-11-18')
        joined = '\n'.join(errs)
        for word in ('schema_version', 'why_out', 'n_ge_500k', 'module.name', 'summary.date'):
            self.assertIn(word, joined)

    def test_legacy_file_without_module_block_fails(self):
        d = self.good()
        d.pop('module')
        self.assertIn('缺 module 块', contract.validate(d))

    def test_bad_status_rejected(self):
        with self.assertRaises(ValueError):
            contract.module_block('x', '1', 'c', 'great', 's', 'f', {})


class QualityRefdataTest(unittest.TestCase):
    def test_sanity_freeze(self):
        rows = [{'pool': str(i), 'tvl': 10 - i, 'vol24': i} for i in range(10)]
        self.assertIn('疑似冻结', quality.sanity('x', rows, rows))
        self.assertIsNone(quality.sanity('x', rows, None))

    def test_refdata_same_as_mvp3(self):
        import sys
        sys.path.insert(0, os.path.join(refdata.ROOT, 'mvp3'))
        import collect
        self.assertEqual(refdata.stock_index(), collect.stock_index())
        self.assertEqual(refdata.sol_labels(), collect.sol_labels())
        fp = refdata.fingerprint(refdata.STOCKLIST)
        self.assertTrue(fp['exists'])
        self.assertEqual(len(fp['sha256_12']), 12)


if __name__ == '__main__':
    unittest.main()
