#!/usr/bin/env python3
"""打发布包（交接书 §11 的结构）。只从已提交的代码打包：lp3/ 有未提交改动就拒绝。

用法（仓库根目录）：/usr/bin/python3 -m lp3.release.build_release --version=1.0.0 [--replay=out/lab/replay/2026-11-17-s2:orca,raydium,meteora ...] [--out=out/lab/release]
产物：<out>/lp-release-lp3-<版本>-<日期>/ 和同名 .zip。
不进包：研究机专用的 lab 定时任务文件、automation-lab 状态、研究日志、任何密钥。
"""
import datetime
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import io

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BASELINE = 'fe9f8e2'
BASELINE_FILES = ('mvp3/collect.py', 'mvp3/llama_cover.py')
LAB_ONLY = ('lp3/lab/launchd/', 'lp3/lab/install_lab.sh', 'lp3/lab/uninstall_lab.sh', 'lp3/lab/run_lab.sh', 'lp3/release/')
SGT = datetime.timezone(datetime.timedelta(hours=8))


def git(*a, binary=False):
    p = subprocess.run(['git', '-C', ROOT] + list(a), capture_output=True, check=True)
    return p.stdout if binary else p.stdout.decode().strip()


def sha(b):
    return hashlib.sha256(b).hexdigest()


def write(p, text):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, 'w') as fh:
        fh.write(text)


def main():
    o = {}
    replays = []
    for a in sys.argv[1:]:
        k, v = a[2:].split('=', 1)
        if k == 'replay':
            replays.append(v)
        else:
            o[k] = v
    ver = o['version']
    if git('status', '--porcelain', '--', 'lp3'):
        raise SystemExit('lp3/ 有未提交的改动，先提交再打包')
    commit = git('rev-parse', '--short', 'HEAD')
    today = datetime.datetime.now(SGT).strftime('%Y%m%d')
    name = 'lp-release-lp3-%s-%s' % (ver, today)
    out = os.path.join(o.get('out') or os.path.join(ROOT, 'out', 'lab', 'release'), name)
    if os.path.exists(out):
        shutil.rmtree(out)
    # src：从 HEAD 导出，去掉研究机专用文件
    tar = tarfile.open(fileobj=io.BytesIO(git('archive', 'HEAD', 'lp3', binary=True)))
    members = [m for m in tar.getmembers() if not (m.name + '/').startswith(LAB_ONLY) and not m.name.startswith(LAB_ONLY)]
    tar.extractall(os.path.join(out, 'src'), members=members)
    write(os.path.join(out, 'src', 'lp3', 'RELEASE_VERSION'), '%s+%s\n' % (ver, commit))
    rel = os.path.join(ROOT, 'lp3', 'release')
    shutil.copytree(os.path.join(rel, 'templates'), os.path.join(out, 'launchd', 'templates'))
    shutil.copytree(os.path.join(rel, 'install'), os.path.join(out, 'install'))
    # 回放证据：cassette + 旧代码实跑输出 + 当时的历史种子
    rep_summary = []
    for spec in replays:
        d, srcs = spec.split(':')
        d = os.path.join(ROOT, d) if not os.path.isabs(d) else d
        live = os.path.join(d, 'legacy-live')
        with open(os.path.join(live, 'SEED.json')) as fh:
            seed = json.load(fh)
        date = seed['date']
        tgt = os.path.join(out, 'evidence', 'replay', os.path.basename(d))
        shutil.copytree(os.path.join(d, 'cassette'), os.path.join(tgt, 'cassette'))
        os.makedirs(os.path.join(tgt, 'legacy-live'))
        os.makedirs(os.path.join(tgt, 'seed'))
        for s in srcs.split(','):
            for fn in ('%s-%s.json' % (s, date), 'meme-%s-%s.json' % (s, date)):
                if os.path.exists(os.path.join(live, fn)):
                    shutil.copy2(os.path.join(live, fn), os.path.join(tgt, 'legacy-live', fn))
        for fn in seed['files']:
            shutil.copy2(os.path.join(live, fn), os.path.join(tgt, 'seed', fn))
        write(os.path.join(tgt, 'SOURCES'), srcs)
        write(os.path.join(tgt, 'DATE'), date)
        rep_summary.append({'name': os.path.basename(d), 'date': date, 'sources': srcs.split(','), 'recorded_now': json.load(open(os.path.join(live, 'RUN.json'))).get('now')})
    # 测试数
    p = subprocess.run(['/usr/bin/python3', '-m', 'unittest', 'discover', '-s', 'lp3/tests', '-t', '.'], cwd=ROOT, capture_output=True, text=True)
    tests_line = [l for l in p.stderr.splitlines() if l.startswith('Ran ')]
    tests_ok = p.returncode == 0
    if not tests_ok:
        raise SystemExit('单元测试没过，不打包')
    nat = o.get('natural-runs', '待填（研究机自然运行天数，见 evidence/scheduled-runs.md）')
    manifest = {
        'name': name, 'version': ver, 'lab_commit': commit, 'built_at': datetime.datetime.now(SGT).isoformat(timespec='seconds'),
        'baseline': {'commit': BASELINE, 'branch_on_machine1': 'mvp2-stage3-4',
                     'files': {f: sha(git('show', '%s:%s' % (BASELINE, f), binary=True)) for f in BASELINE_FILES}},
        'changes': '3.0 采集拆成 6 个独立模块（curve、aero、rh、orca、raydium、meteora）+ 只读整合层；规则、数据源、输出字段与 mvp3 相同（录制回放 0 差异）',
        'entry_points': {'stage': 'lp3/run_stage.sh stage1|stage2', 'module': 'python3 -m lp3.run_module <模块>', 'digest': 'python3 -m lp3.aggregate'},
        'schedules': {'shadow': {'com.july.lp3m-shadow-stage2': '10:35', 'com.july.lp3m-shadow-stage1': '11:00'},
                      'production_after_activate': {'com.july.lp3m-stage1': '08:20（替代 com.july.lp3-collect）', 'com.july.lp3m-stage2': '10:20（替代 com.july.lp3-stage2-collect）'}},
        'external_writes': {'feishu_cards': '无', 'bitable': '无', 'alerts': '正式启用后仅失败时经 run_task.sh 通用告警；影子阶段无'},
        'network': '只读公开接口：Curve Prices/getPools、publicnode、GeckoTerminal、Orca/Raydium/Meteora 官方 API、DefiLlama、coins.llama.fi',
        'keychain_items': [],
        'state_layout': {'shadow': {'out': 'out/lp3-shadow/<模块>/', 'state': '~/.local/state/automation-lp3m-shadow/'},
                         'production': {'out': 'out/lp3/<模块>/', 'state': '~/.local/state/automation/lp3m-stage{1,2}.json（run_task）+ automation/lp3m-modules/lp3-<模块>.json'}},
        'tests': {'unit': tests_line[-1] if tests_line else '?', 'replay': rep_summary},
        'natural_runs_on_lab': nat,
        'conflicts': ['aero、rh 与 com.july.lp3-collect 共用 GeckoTerminal 限速：影子 stage1 放在 11:00 错开；正式启用后旧任务停用，不再冲突',
                      '2.0 的 RWA 也用 GeckoTerminal（08:50）：正式 stage1 08:20 约 08:45 前结束，和旧任务时段相同'],
        'rollback': 'install/rollback.sh：停用 lp3m 任务、恢复 .disabled-* 的旧 plist 并加载；不删代码和输出',
    }
    write(os.path.join(out, 'MANIFEST.json'), json.dumps(manifest, ensure_ascii=False, indent=1))
    write(os.path.join(out, 'CHANGELOG.md'), '# lp3 %s（%s）\n\n- %s\n- 模块版本：%s\n' % (
        ver, commit, manifest['changes'],
        '、'.join('%s %s' % (m, open(os.path.join(out, 'src', 'lp3', 'modules', m, 'VERSION')).read().strip())
                 for m in ('curve', 'aero', 'rh', 'orca', 'raydium', 'meteora'))))
    write(os.path.join(out, 'README-INSTALL.md'), README % {'name': name, 'ver': ver, 'commit': commit})
    os.makedirs(os.path.join(out, 'evidence'), exist_ok=True)
    for src, dst in ((o.get('acceptance'), 'acceptance.md'), (o.get('scheduled-runs'), 'scheduled-runs.md')):
        if src and os.path.exists(src):
            shutil.copy2(src, os.path.join(out, 'evidence', dst))
        else:
            write(os.path.join(out, 'evidence', dst), '# %s\n\n待填。\n' % dst)
    # 校验和
    lines = []
    for dp, _, fns in os.walk(out):
        for fn in sorted(fns):
            p = os.path.join(dp, fn)
            r = os.path.relpath(p, out)
            if r == 'SHA256SUMS.txt':
                continue
            with open(p, 'rb') as fh:
                lines.append('%s  %s' % (sha(fh.read()), r))
    write(os.path.join(out, 'SHA256SUMS.txt'), '\n'.join(sorted(lines, key=lambda l: l.split('  ', 1)[1])) + '\n')
    z = shutil.make_archive(out, 'zip', os.path.dirname(out), name)
    print(json.dumps({'package': out, 'zip': z, 'files': len(lines), 'lab_commit': commit}, ensure_ascii=False))
    return 0


README = """# %(name)s 安装说明（1 号机）

版本 %(ver)s，研究机提交 %(commit)s，基线 fe9f8e2（分支 mvp2-stage3-4）。默认不发送任何飞书消息。

## 顺序（交接书 §12）

1. 校验和预检（只读）：`bash install/preflight.sh`
2. 安装影子：`bash install/install.sh`（加 `--commit` 会把 lp3/ 提交进仓库）。现有 com.july.lp3-collect / lp3-stage2-collect 照常运行。
3. 本机验证：`bash install/verify.sh`。会跑单元测试和录制回放；新模块和本机旧代码都必须 0 差异。
4. 影子自然运行 1–3 天：stage2 每天 10:35，stage1 每天 11:00，产出在 `out/lp3-shadow/`。
   对比：`/usr/bin/python3 -m lp3.lab.compare_prod --prod=out/mvp3 --lab-root=out/lp3-shadow --date=<日期>`
5. July 明确批准后才启用：`bash install/activate.sh --confirm="July 批准 <日期> <原话>"`
6. 出问题回退：`bash install/rollback.sh`（旧 plist 留档至少 7 天）。

## 会改什么

- 仓库新增 `lp3/`（已有的先备份成 `lp3.bak-<时间>`）；新增输出目录 `out/lp3-shadow/`，启用后还有 `out/lp3/`。
- LaunchAgents：影子 2 个；启用时停用旧 2 个（plist 改名 `.disabled-<时间>`，不删），新增正式 2 个。
- 不改 `mvp3/`、`mvp/`、`mvp2/`、钥匙串、飞书。
"""

if __name__ == '__main__':
    sys.exit(main())
