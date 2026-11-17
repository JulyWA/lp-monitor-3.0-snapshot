"""整合层：每种模块状态都能正确标注，一个模块出问题不影响其他行；不含任何发送代码。全部离线。"""
import datetime
import json
import os
import shutil
import tempfile
import unittest

from lp3 import aggregate, run_module
from lp3.common import contract

DATE = '2026-11-18'
SGT = datetime.timezone(datetime.timedelta(hours=8))
FX = 'lp3.tests.fixtures.'


def ts(hhmm):
    h, m = map(int, hhmm.split(':'))
    return int(datetime.datetime(2026, 11, 18, h, m, tzinfo=SGT).timestamp())


class AggregateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def good(self, name, fixture='dummy_ok'):
        st, p = run_module.run_one(name, DATE, now=ts('08:21'), out_root=self.tmp, module_path=FX + fixture, quiet=True)
        self.assertIn(st, ('ok', 'partial'))
        return p

    def write(self, name, suffix, obj=None, raw=None):
        d = os.path.join(self.tmp, name)
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, '%s-%s%s.json' % (name, DATE, suffix))
        with open(p, 'w') as fh:
            fh.write(raw if raw is not None else json.dumps(obj))
        return p

    def states(self, now):
        dg = aggregate.build(DATE, self.tmp, now=now)
        return dg, {e['name']: e for e in dg['modules']}

    def test_every_state_is_labelled_and_isolated(self):
        self.good('curve')
        self.good('aero', 'dummy_partial')
        run_module.run_one('rh', DATE, now=ts('08:30'), out_root=self.tmp, module_path=FX + 'dummy_crash', quiet=True)
        legacy = {'summary': {'date': DATE, 'n_ge_500k': 0}, 'rows': []}  # mvp3 旧格式：没有 module 块
        self.write('orca', '', legacy)
        self.write('raydium', '', raw='{"summary": ')  # 半个文件
        dg, s = self.states(ts('12:00'))
        self.assertEqual({k: v['state'] for k, v in s.items()},
                         {'curve': '正常', 'aero': '部分失败', 'rh': '失败', 'orca': '契约不符', 'raydium': '契约不符', 'meteora': '暂缺'})
        self.assertEqual((dg['n_usable'], dg['all_usable']), (2, False))
        self.assertEqual(s['rh']['error_type'], 'KeyError')
        self.assertIn('缺 module 块', s['orca']['issues'])
        self.assertTrue(s['raydium']['issues'][0].startswith('文件读不出'))
        self.assertEqual(s['curve']['n_pass'], 1)
        self.assertEqual(s['curve']['health']['requests'], 0)

    def test_not_due_and_running(self):
        self.good('curve')
        _, s = self.states(ts('09:00'))
        self.assertEqual(s['orca']['state'], '未到点')
        self.assertEqual(s['aero']['state'], '运行中')  # 08:20 开始，stage1 合计超时 45 分钟内
        _, s = self.states(ts('10:25'))
        self.assertEqual(s['meteora']['state'], '运行中')
        self.assertEqual(s['aero']['state'], '暂缺')

    def test_wrong_date_inside_file_is_contract_violation(self):
        p = self.good('curve')
        with open(p) as fh:
            doc = json.load(fh)
        doc['summary']['date'] = '2026-11-17'
        with open(p, 'w') as fh:
            json.dump(doc, fh)
        _, s = self.states(ts('12:00'))
        self.assertEqual(s['curve']['state'], '契约不符')

    def test_outputs_and_card_are_dry_run(self):
        self.good('curve')
        dg = aggregate.build(DATE, self.tmp, now=ts('12:00'))
        paths = aggregate.write_all(dg, self.tmp)
        for p in paths.values():
            self.assertTrue(os.path.exists(p))
        with open(paths['card']) as fh:
            card = json.load(fh)
        title = card['card']['header']['title']['content']
        self.assertIn('影子/测试', title)
        self.assertEqual(card['card']['header']['template'], 'grey')
        with open(paths['md']) as fh:
            md = fh.read()
        self.assertIn('| Curve · Ethereum | 🟡 | 正常 |', md)
        with open(aggregate.__file__) as fh:
            src = fh.read()
        imports = [l.strip() for l in src.splitlines() if l.strip().startswith(('import ', 'from '))]
        self.assertEqual(sorted(imports), sorted(['import datetime', 'import json', 'import os', 'import sys',
                                                  'from lp3.common import contract  # noqa: E402']))  # 整合层不得有任何网络或发送能力
        self.assertNotIn('webhook', src.lower())

    def test_module_output_contract_is_what_aggregate_reads(self):
        p = self.good('curve')
        with open(p) as fh:
            self.assertEqual(contract.validate(json.load(fh), 'curve', DATE), [])


if __name__ == '__main__':
    unittest.main()
