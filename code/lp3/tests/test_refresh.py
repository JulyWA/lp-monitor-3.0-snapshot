"""阶段 3 刷新工具：标签与股票名单。全部离线（假网络）。"""
import datetime
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from lp3.refresh import sol_labels, stocklist

D = datetime.date(2026, 11, 19)


class LabelsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cache = os.path.join(self.tmp, 'refdata', 'sol-token-labels.json')
        os.makedirs(os.path.dirname(self.cache))
        with open(self.cache, 'w') as fh:
            json.dump({'OLD_OK': {'id': 'a', 'cats': ['DeFi'], 'mcap': 1, 'symbol': 'A'},
                       'OLD_ERR': {'id': 'ERROR', 'cats': [], 'mcap': None, 'symbol': 'E'},
                       'OLD_FLIP': {'id': 'f', 'cats': ['DeFi'], 'mcap': 1, 'symbol': 'F'}}, fh)
        p = mock.patch('time.sleep', lambda s: None)
        p.start()
        self.addCleanup(p.stop)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def fake(self, table):
        def fetch(url):
            mint = url.rsplit('/', 1)[1]
            v = table[mint]
            return (v, None) if isinstance(v, int) else (200, v)
        return fetch

    def test_incremental_queries_new_and_error_only_and_keeps_old_on_failure(self):
        seen = {'NEW_MEME': 'M', 'NEW_404': 'N', 'OLD_ERR': 'E', 'OLD_OK': 'A', 'NEW_FAIL': 'X'}
        table = {'NEW_MEME': {'id': 'm', 'categories': ['Meme'], 'symbol': 'm'}, 'NEW_404': 404,
                 'OLD_ERR': {'id': 'e', 'categories': ['DeFi'], 'symbol': 'e'}, 'NEW_FAIL': 503}
        with mock.patch.object(sol_labels, 'recent_tokens', return_value=seen):
            res, old, new = sol_labels.refresh('incremental', pause=0, cache_path=self.cache, fetch=self.fake(table), today=D)
        self.assertEqual(res['queried'], 4)  # OLD_OK 不查
        self.assertEqual(new['NEW_404']['id'], None)
        self.assertEqual(sol_labels.label_of(new['NEW_MEME']), 'meme')
        self.assertEqual(new['OLD_ERR']['id'], 'e')
        self.assertEqual(new['NEW_FAIL']['id'], 'ERROR')  # 新代币查不到：与旧脚本一致记 ERROR
        self.assertEqual([x['symbol'] for x in res['failed']], ['X'])
        self.assertTrue(os.listdir(os.path.join(os.path.dirname(self.cache), 'backup')))

    def test_full_failure_keeps_previous_value_with_stale_since(self):
        table = {'OLD_OK': 503, 'OLD_ERR': 404, 'OLD_FLIP': {'id': 'f', 'categories': ['Meme'], 'symbol': 'f'}}
        with mock.patch.object(sol_labels, 'recent_tokens', return_value={}):
            res, old, new = sol_labels.refresh('full', pause=0, cache_path=self.cache, fetch=self.fake(table), today=D)
        self.assertEqual(new['OLD_OK']['id'], 'a')
        self.assertEqual(new['OLD_OK']['stale_since'], '2026-11-19')
        flips = {x['mint']: (x['from'], x['to']) for x in res['changed']}
        self.assertEqual(flips['OLD_FLIP'], ('ok', 'meme'))
        self.assertEqual(flips['OLD_ERR'], ('error', 'unlisted'))

    def test_backup_rotation_keeps_8(self):
        bdir = os.path.join(os.path.dirname(self.cache), 'backup')
        os.makedirs(bdir)
        for i in range(10):
            open(os.path.join(bdir, 'sol-token-labels-20261101-0000%02d.json' % i), 'w').close()
        sol_labels.backup(self.cache)
        self.assertEqual(len(os.listdir(bdir)), 8)


class StocklistTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.prev = os.path.join(self.tmp, 'base.json')
        with open(self.prev, 'w') as fh:
            json.dump({'categories': ['c1', 'c2'], 'members': {'c1': [['s1', 'S1', 1], ['s2', 'S2', 1]], 'c2': [['g1', 'G1', 1]]},
                       'platforms': {'s1': {'solana': 'MINT1'}, 's2': {'ethereum': '0xabc'}, 'g1': {}}}, fh)
        self.patches = [mock.patch.object(stocklist, 'REFDATA', os.path.join(self.tmp, 'refdata')),
                        mock.patch.object(stocklist, 'BASELINE', self.prev), mock.patch('time.sleep', lambda s: None)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        shutil.rmtree(self.tmp)

    def test_union_adds_new_keeps_missing(self):
        def fetch(url):
            if 'category=c1' in url:
                return 200, [{'id': 's1', 'symbol': 'S1'}, {'id': 's3', 'symbol': 'S3'}]
            if 'category=c2' in url:
                return 200, [{'id': 'g1', 'symbol': 'G1'}]
            if '/coins/s3' in url:
                return 200, {'platforms': {'solana': 'MINT3', '': ''}}
            return 404, None
        res = stocklist.refresh(pause=0, fetch=fetch, today=D)
        self.assertEqual((res['added'], res['gone'], res['errors']), (['s3'], ['s2'], []))
        with open(os.path.join(stocklist.REFDATA, 'stocklist-raw-2026-11-19.json')) as fh:
            out = json.load(fh)
        ids = {i for v in out['members'].values() for i, _, _ in v}
        self.assertEqual(ids, {'s1', 's2', 's3', 'g1'})
        self.assertEqual(out['missing_since'], {'s2': '2026-11-19'})
        self.assertEqual(out['platforms']['s3'], {'solana': 'MINT3'})

    def test_category_failure_writes_nothing(self):
        def fetch(url):
            return (503, None) if 'category=c2' in url else (200, [])
        res = stocklist.refresh(pause=0, fetch=fetch, today=D)
        self.assertIsNone(res['written'])
        self.assertTrue(res['errors'])
        self.assertFalse(os.path.exists(os.path.join(stocklist.REFDATA, 'stocklist-raw-2026-11-19.json')))


if __name__ == '__main__':
    unittest.main()
