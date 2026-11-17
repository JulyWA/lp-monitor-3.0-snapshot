"""录制/回放与对比工具的单元测试。全部离线：「真实」网络用假函数代替。"""
import io
import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from unittest import mock

from lp3.replay import cassette as cas_mod
from lp3.replay import compare
from lp3.replay.cassette import Cassette, ReplayMiss


class FakeResp(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


class CassetteTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def _record(self):
        calls = iter([urllib.error.HTTPError('u', 429, 'slow', {}, io.BytesIO(b'')), FakeResp(b'{"a": 1}'), FakeResp(b'{"b": 2}')])

        def real(req, *a, **kw):
            x = next(calls)
            if isinstance(x, BaseException):
                raise x
            return x
        curl = subprocess.CompletedProcess(['curl'], 0, b'[1,2]', b'')
        c = Cassette(self.tmp, 'record')
        with mock.patch.object(cas_mod, '_REAL_URLOPEN', real), mock.patch.object(cas_mod, '_REAL_RUN', return_value=curl):
            with c.patched(now=1794890000) as now:
                self.assertEqual(time.time(), 1794890000)
                with self.assertRaises(urllib.error.HTTPError):
                    urllib.request.urlopen(urllib.request.Request('https://x.test/p?1'))
                self.assertEqual(urllib.request.urlopen(urllib.request.Request('https://x.test/p?1')).read(), b'{"a": 1}')
                self.assertEqual(urllib.request.urlopen(urllib.request.Request('https://x.test/q')).read(), b'{"b": 2}')
                self.assertEqual(subprocess.run(['curl', '-sS', 'https://y.test/big'], capture_output=True).stdout, b'[1,2]')
        return now

    def test_record_then_replay_same_sequence_and_time(self):
        self._record()
        r = Cassette(self.tmp, 'replay')
        real_time = time.time
        with r.patched():
            self.assertEqual(time.time(), 1794890000)
            t0 = real_time()
            time.sleep(100)  # 回放不等待
            self.assertLess(real_time() - t0, 1)
            with self.assertRaises(urllib.error.HTTPError) as e:
                urllib.request.urlopen(urllib.request.Request('https://x.test/p?1'))
            self.assertEqual(e.exception.code, 429)
            self.assertEqual(json.loads(urllib.request.urlopen(urllib.request.Request('https://x.test/p?1')).read()), {'a': 1})
            self.assertEqual(subprocess.run(['curl', '-sS', 'https://y.test/big'], capture_output=True).stdout, b'[1,2]')
            self.assertEqual(subprocess.run(['echo', 'hi'], capture_output=True, text=True).stdout.strip(), 'hi')  # 非 curl 放行
            with self.assertRaises(ReplayMiss):
                urllib.request.urlopen(urllib.request.Request('https://x.test/never'))
        self.assertEqual(r.unused(), {'GET https://x.test/q ' + cas_mod._sha(b''): 1})
        self.assertIs(urllib.request.urlopen, cas_mod._REAL_URLOPEN)  # 退出后恢复

    def test_curl_body_is_part_of_key(self):
        a = cas_mod._curl_key(['curl', 'https://rpc', '-d', '[1]'])
        b = cas_mod._curl_key(['curl', 'https://rpc', '-d', '[2]'])
        self.assertNotEqual(a, b)


class CompareTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.a, self.b = os.path.join(self.tmp, 'a'), os.path.join(self.tmp, 'b')
        os.makedirs(self.a)
        os.makedirs(os.path.join(self.b, 'orca'))

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def write(self, rows_a, rows_b, elapsed_b=9):
        json.dump({'summary': {'n': 1, 'elapsed_s': 1}, 'rows': rows_a}, open(os.path.join(self.a, 'orca-D.json'), 'w'))
        json.dump({'summary': {'n': 1, 'elapsed_s': elapsed_b}, 'rows': rows_b, 'module': {'x': 1}},
                  open(os.path.join(self.b, 'orca', 'orca-D.json'), 'w'))

    def test_identical_flat_vs_module_layout(self):
        self.write([{'pool': 'p', 'tvl': 1.5}], [{'pool': 'p', 'tvl': 1.5}])
        r = compare.compare_source(self.a, self.b, 'orca', 'D')
        self.assertEqual((r['diffs'], r['missing']), ([], []))

    def test_float_must_be_exact(self):
        self.write([{'pool': 'p', 'tvl': 1.5}], [{'pool': 'p', 'tvl': 1.5000000001}])
        self.assertEqual(len(compare.compare_source(self.a, self.b, 'orca', 'D')['diffs']), 1)

    def test_order_and_missing_field(self):
        self.write([{'pool': 'p'}, {'pool': 'q'}], [{'pool': 'q'}, {'pool': 'p', 'x': 1}])
        d = compare.compare_source(self.a, self.b, 'orca', 'D')['diffs']
        self.assertTrue(any('只在 B 里有' in x for x in d))
        self.assertTrue(any("'p' vs 'q'" in x for x in d))


if __name__ == '__main__':
    unittest.main()
