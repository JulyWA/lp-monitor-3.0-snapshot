#!/usr/bin/env python3
"""lp3 编排：按时段依次启动模块。每个模块一个子进程、一个超时；一个失败或超时不影响下一个。

用法（在仓库根目录）：
  /usr/bin/python3 -m lp3.orchestrate stage1|stage2 [--date=YYYY-MM-DD] [--only=a,b] [--out-root=目录] [--state-dir=目录]

每个模块写一个状态文件 <state-dir>/lp3-<模块>.json，字段与 run_task.sh 的状态文件一致（task、last_attempt_at、last_status、
last_duration_seconds、last_success_at、consecutive_error_count、last_output_summary），另加 module_status（ok/partial/failed/timeout）。
退出码：全部 ok/partial 为 0；任一失败或超时为 1（交给外层 run_task 走失败告警）。

安全护栏：状态目录不能是正式生产的 ~/.local/state/automation（研究机只用 automation-lab）。
"""
import datetime
import json
import os
import signal
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SGT = datetime.timezone(datetime.timedelta(hours=8))
DEFAULT_STATE_DIR = os.environ.get('LP3_STATE_DIR', os.path.expanduser('~/.local/state/automation-lab'))
FORBIDDEN_STATE_DIR = os.path.realpath(os.path.expanduser('~/.local/state/automation'))
DEFAULT_OUT_ROOT = os.environ.get('LP3_OUT_ROOT', os.path.join(ROOT, 'out', 'lab', 'lp3'))


def now_iso():
    return datetime.datetime.now(SGT).isoformat(timespec='seconds')


def load_schedule(path=None):
    with open(path or os.path.join(HERE, 'schedule.json')) as fh:
        return json.load(fh)


def check_state_dir(state_dir):
    if os.path.realpath(os.path.expanduser(state_dir)) == FORBIDDEN_STATE_DIR:
        raise SystemExit('拒绝运行：状态目录是正式生产目录 %s；研究机只能用 automation-lab' % FORBIDDEN_STATE_DIR)


def write_state(state_dir, name, started, duration, module_status, summary_line):
    os.makedirs(state_dir, exist_ok=True)
    p = os.path.join(state_dir, 'lp3-%s.json' % name)
    old = {}
    if os.path.exists(p):
        with open(p) as fh:
            old = json.load(fh)
    ok = module_status in ('ok', 'partial')
    st = {'task': 'lp3-%s' % name, 'last_attempt_at': started, 'last_status': 'ok' if ok else 'error',
          'module_status': module_status, 'last_duration_seconds': int(duration),
          'last_success_at': now_iso() if ok else old.get('last_success_at'),
          'consecutive_error_count': 0 if ok else int(old.get('consecutive_error_count') or 0) + 1,
          'last_output_summary': summary_line[-400:]}
    if not ok:
        st['last_error_at'] = now_iso()
    elif old.get('last_error_at'):
        st['last_error_at'] = old['last_error_at']
    tmp = p + '.tmp'
    with open(tmp, 'w') as fh:
        json.dump(st, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, p)
    return st


def run_module_process(name, date, timeout, out_root, module_path=None, python=None):
    """子进程跑一个模块。返回 (module_status, 耗时秒, 输出末行)。"""
    cmd = [python or sys.executable, '-m', 'lp3.run_module', name, '--date=' + date, '--out-root=' + out_root]
    if module_path:
        cmd.append('--module-path=' + module_path)
    t0 = time.time()
    p = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)
    try:
        out, _ = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(p.pid, sig)
            except ProcessLookupError:
                break
            try:
                p.wait(timeout=10)
                break
            except subprocess.TimeoutExpired:
                continue
        out = (p.stdout.read() if p.stdout else b'') or b''
        dur = time.time() - t0
        msg = '%s 超时：超过 %d 秒被终止' % (name, timeout)
        write_timeout_failure(name, date, out_root, msg, int(t0))
        text = out.decode(errors='replace')
        sys.stdout.write(text)
        print(msg)
        return 'timeout', dur, msg
    dur = time.time() - t0
    text = out.decode(errors='replace')
    sys.stdout.write(text)
    last = [l for l in text.strip().splitlines() if l.strip()]
    line = last[-1] if last else ''
    if p.returncode == 0:
        status = 'partial' if line.rstrip().endswith(' partial') else 'ok'
    else:
        status = 'failed'
        if not line:
            line = '%s 退出码 %d，无输出' % (name, p.returncode)
    return status, dur, line


def write_timeout_failure(name, date, out_root, msg, started):
    from lp3.common import contract  # 延迟导入：编排进程本身不依赖模块代码
    d = os.path.join(out_root, name)
    os.makedirs(d, exist_ok=True)
    doc = contract.failure(name, 'unknown', 'unknown', date, started, msg, 'Timeout',
                           datetime.datetime.fromtimestamp(started, SGT).isoformat(timespec='seconds'), now_iso())
    with open(os.path.join(d, '%s-%s-FAILED.json' % (name, date)), 'w') as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1)


def run_stage(stage, date, only=None, out_root=None, state_dir=None, schedule=None, module_paths=None):
    out_root = out_root or DEFAULT_OUT_ROOT
    state_dir = state_dir or DEFAULT_STATE_DIR
    check_state_dir(state_dir)
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    plan = (schedule or load_schedule())[stage]
    results = {}
    for name, timeout in plan:
        if only and name not in only:
            continue
        started = now_iso()
        print('=== %s %s 开始 %s（超时 %ds）' % (stage, name, started, timeout), flush=True)
        status, dur, line = run_module_process(name, date, timeout, out_root, (module_paths or {}).get(name))
        write_state(state_dir, name, started, dur, status, line)
        results[name] = status
        print('=== %s %s 结束：%s，%ds' % (stage, name, status, dur), flush=True)
    bad = [n for n, s in results.items() if s in ('failed', 'timeout')]
    print('=== %s 汇总：%s' % (stage, '，'.join('%s=%s' % kv for kv in results.items())))
    return results, (1 if bad else 0)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    stages = [a for a in argv if not a.startswith('--')]
    opts = dict(a[2:].split('=', 1) for a in argv if a.startswith('--') and '=' in a)
    if len(stages) != 1 or stages[0] not in ('stage1', 'stage2'):
        raise SystemExit('用法：python3 -m lp3.orchestrate stage1|stage2 [--date=] [--only=a,b] [--out-root=] [--state-dir=]')
    date = opts.get('date') or datetime.datetime.now(SGT).strftime('%Y-%m-%d')
    only = set(opts['only'].split(',')) if opts.get('only') else None
    _, rc = run_stage(stages[0], date, only, opts.get('out-root'), opts.get('state-dir'))
    return rc


if __name__ == '__main__':
    sys.exit(main())
