"""run_module / orchestrate：故障隔离、状态文件、契约。全部离线。"""
import json
import os
import shutil
import tempfile
import unittest


def load(p):
    with open(p) as fh:
        return json.load(fh)

from lp3 import orchestrate, run_module
from lp3.common import contract

FX = 'lp3.tests.fixtures.'
DATE = '2026-11-17'


class RunOneTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_ok_writes_contract_output_and_meme_archive(self):
        st, path = run_module.run_one('dummy', DATE, now=1794890000, out_root=self.tmp, module_path=FX + 'dummy_ok', quiet=True)
        self.assertEqual(st, 'ok')
        doc = load((path))
        self.assertEqual(contract.validate(doc, 'dummy', DATE), [])
        s = doc['summary']
        self.assertEqual((s['n_ge_500k'], s['n_pass'], s['n_apy_board']), (2, 1, 1))
        self.assertEqual(s['by_class'], {'代币': 1, '股票和商品': 0})
        self.assertEqual(s['meta']['n_meme_archived'], 1)
        self.assertEqual(doc['module']['version'], '9.9.9')
        self.assertTrue(os.path.exists(os.path.join(self.tmp, 'dummy', 'meme-dummy-%s.json' % DATE)))

    def test_partial(self):
        st, path = run_module.run_one('dummy', DATE, now=1794890000, out_root=self.tmp, module_path=FX + 'dummy_partial', quiet=True)
        self.assertEqual(st, 'partial')
        self.assertEqual(load((path))['module']['status'], 'partial')

    def test_any_exception_becomes_failed_file(self):
        for fx, etype in (('dummy_crash', 'KeyError'), ('dummy_exit', 'SystemExit'), ('dummy_badrow', 'KeyError')):
            st, path = run_module.run_one('dummy', DATE, now=1794890000, out_root=self.tmp, module_path=FX + fx, quiet=True)
            self.assertEqual(st, 'failed', fx)
            self.assertTrue(path.endswith('-FAILED.json'))
            doc = load((path))
            self.assertEqual(doc['module']['error_type'], etype, fx)
            for k in ('date', 'source', 'error', 'at'):  # mvp3 原 FAILED 文件的四个键保留
                self.assertIn(k, doc)

    def test_rerun_success_keeps_old_failure_renamed(self):
        run_module.run_one('dummy', DATE, now=1, out_root=self.tmp, module_path=FX + 'dummy_crash', quiet=True)
        run_module.run_one('dummy', DATE, now=2, out_root=self.tmp, module_path=FX + 'dummy_ok', quiet=True)
        files = os.listdir(os.path.join(self.tmp, 'dummy'))
        self.assertNotIn('dummy-%s-FAILED.json' % DATE, files)
        self.assertTrue(any('FAILED-superseded' in f for f in files))


class OrchestrateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.out, self.state = os.path.join(self.tmp, 'out'), os.path.join(self.tmp, 'state')

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_one_crash_and_one_hang_do_not_stop_others(self):
        sched = {'stage1': [['a', 30], ['b', 30], ['c', 3], ['d', 30]]}
        paths = {'a': FX + 'dummy_ok', 'b': FX + 'dummy_crash', 'c': FX + 'dummy_hang', 'd': FX + 'dummy_partial'}
        res, rc = orchestrate.run_stage('stage1', DATE, out_root=self.out, state_dir=self.state, schedule=sched, module_paths=paths)
        self.assertEqual(res, {'a': 'ok', 'b': 'failed', 'c': 'timeout', 'd': 'partial'})
        self.assertEqual(rc, 1)
        self.assertTrue(os.path.exists(os.path.join(self.out, 'a', 'a-%s.json' % DATE)))
        self.assertTrue(os.path.exists(os.path.join(self.out, 'd', 'd-%s.json' % DATE)))
        self.assertTrue(os.path.exists(os.path.join(self.out, 'b', 'b-%s-FAILED.json' % DATE)))
        hang = load((os.path.join(self.out, 'c', 'c-%s-FAILED.json' % DATE)))
        self.assertEqual(hang['module']['error_type'], 'Timeout')
        sa = load((os.path.join(self.state, 'lp3-a.json')))
        sb = load((os.path.join(self.state, 'lp3-b.json')))
        self.assertEqual((sa['last_status'], sa['consecutive_error_count']), ('ok', 0))
        self.assertEqual((sb['last_status'], sb['consecutive_error_count']), ('error', 1))

    def test_all_ok_exit_zero_and_error_count_resets(self):
        sched = {'stage2': [['a', 30]]}
        orchestrate.run_stage('stage2', DATE, out_root=self.out, state_dir=self.state, schedule=sched, module_paths={'a': FX + 'dummy_crash'})
        res, rc = orchestrate.run_stage('stage2', DATE, out_root=self.out, state_dir=self.state, schedule=sched, module_paths={'a': FX + 'dummy_ok'})
        self.assertEqual(rc, 0)
        st = load((os.path.join(self.state, 'lp3-a.json')))
        self.assertEqual(st['consecutive_error_count'], 0)
        self.assertIn('last_error_at', st)

    def test_refuses_production_state_dir(self):
        with self.assertRaises(SystemExit):
            orchestrate.check_state_dir('~/.local/state/automation')
        orchestrate.check_state_dir('~/.local/state/automation-lab')


if __name__ == '__main__':
    unittest.main()
